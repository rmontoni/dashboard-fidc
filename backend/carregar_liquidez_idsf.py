"""Carga diária de caixa + aplicações (IDSF GetPortfolioComposition → Supabase/cache).

Usa a mesma API do PDF «Composição de Carteira por Período».

Uso:
  cd backend
  python carregar_liquidez_idsf.py --inicio 2025-01-01
  python carregar_liquidez_idsf.py --pendentes

Requer IDSF_TOKEN. Para gravar no Supabase: sql/fidc_liquidez_diaria.sql
Sem a tabela, grava em data/liquidez_cache.json.
"""

from __future__ import annotations

import argparse
import calendar
import json
import sys
from datetime import date, datetime
from pathlib import Path

from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv

from db import get_supabase
from fundos import fundo_padrao
from idsf_pl_pdd import (
    buscar_composicao,
    carteira_composicao_idsf,
    extrair_posicoes_liquidez,
    registro_liquidez_diario,
    token_idsf,
)

TABELA = "fidc_liquidez_diaria"
SQL_HINT = "backend/sql/fidc_liquidez_diaria.sql"
CACHE_PATH = Path(__file__).resolve().parent / "data" / "liquidez_cache.json"


def _parse_date(texto: str | None) -> date | None:
    if not texto:
        return None
    texto = texto.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(texto[:10] if fmt.startswith("%Y") else texto, fmt).date()
        except ValueError:
            continue
    return None


def _meses(inicio: date, fim: date) -> list[tuple[date, date]]:
    periodos: list[tuple[date, date]] = []
    cursor = inicio.replace(day=1)
    while cursor <= fim:
        ultimo = calendar.monthrange(cursor.year, cursor.month)[1]
        mes_fim = date(cursor.year, cursor.month, ultimo)
        if mes_fim > fim:
            mes_fim = fim
        mes_ini = cursor if cursor >= inicio else inicio
        if mes_ini <= mes_fim:
            periodos.append((mes_ini, mes_fim))
        cursor = (cursor + relativedelta(months=1)).replace(day=1)
    return periodos


def tabela_disponivel() -> bool:
    try:
        get_supabase().table(TABELA).select("data_posicao").limit(1).execute()
        return True
    except Exception:  # noqa: BLE001
        return False


def carregar_cache_local() -> dict[str, dict]:
    if not CACHE_PATH.exists():
        return {}
    try:
        raw = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    if isinstance(raw, list):
        return {str(r.get("data_posicao"))[:10]: r for r in raw if r.get("data_posicao")}
    if isinstance(raw, dict):
        return raw
    return {}


def salvar_cache_local(registros: list[dict]) -> Path:
    atual = carregar_cache_local()
    for reg in registros:
        chave = str(reg.get("data_posicao") or "")[:10]
        if chave:
            atual[chave] = reg
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(
        json.dumps(list(atual.values()), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return CACHE_PATH


def datas_ja_carregadas(id_carteira: int) -> set[date]:
    """
    Datas já persistidas no destino principal.
    Com tabela no Supabase, só o BD conta (cache local sozinho nao pula upsert).
    Sem tabela, usa o cache local.
    """
    out: set[date] = set()
    if tabela_disponivel():
        sb = get_supabase()
        offset = 0
        page = 1000
        while True:
            response = (
                sb.table(TABELA)
                .select("data_posicao")
                .eq("id_carteira", id_carteira)
                .range(offset, offset + page - 1)
                .execute()
            )
            batch = response.data or []
            for row in batch:
                d = _parse_date(str(row.get("data_posicao") or ""))
                if d:
                    out.add(d)
            if len(batch) < page:
                break
            offset += page
        return out

    for chave in carregar_cache_local():
        d = _parse_date(chave)
        if d:
            out.add(d)
    return out


def sync_cache_para_supabase(id_carteira: int | None = None) -> int:
    """Envia registros do cache local que ainda nao estao no Supabase."""
    if not tabela_disponivel():
        print("Tabela ausente no Supabase — nada a sincronizar.")
        return 0
    carteira = id_carteira if id_carteira is not None else carteira_composicao_idsf()
    if carteira is None:
        raise RuntimeError("Carteira IDSF nao configurada")
    no_bd = datas_ja_carregadas(carteira)
    pendentes: list[dict] = []
    for reg in carregar_cache_local().values():
        if int(reg.get("id_carteira") or 0) != int(carteira):
            continue
        d = _parse_date(str(reg.get("data_posicao") or ""))
        if d and d not in no_bd:
            pendentes.append(reg)
    if not pendentes:
        print("Cache ja esta sincronizado com o Supabase.")
        return 0
    n = upsert_registros(pendentes)
    print(f"Sincronizados do cache -> Supabase: {n}")
    return n


def upsert_registros(registros: list[dict]) -> int:
    salvar_cache_local(registros)
    if not registros or not tabela_disponivel():
        return len(registros)
    sb = get_supabase()
    total = 0
    for i in range(0, len(registros), 200):
        batch = registros[i : i + 200]
        sb.table(TABELA).upsert(batch, on_conflict="data_posicao,id_carteira").execute()
        total += len(batch)
    return total


def coletar(
    *,
    inicio: date,
    fim: date,
    id_carteira: int,
    so_pendentes: bool = False,
) -> list[dict]:
    token = token_idsf()
    existentes = datas_ja_carregadas(id_carteira) if so_pendentes else set()
    periodos = _meses(inicio, fim)
    print(f"Carteira {id_carteira} | {inicio} -> {fim} | {len(periodos)} mes(es)")
    if so_pendentes:
        print(f"Ja carregados: {len(existentes)} dias")

    registros: list[dict] = []
    ok = vazios = erros = 0
    for data_ini, data_fim in periodos:
        rotulo = f"{data_ini}..{data_fim}"
        try:
            snaps = buscar_composicao(id_carteira, data_ini, data_fim, token=token)
            if not snaps:
                vazios += 1
                print(f"  vazio  {rotulo}")
                continue
            n = 0
            n_skip = 0
            for snap in snaps:
                extraido = extrair_posicoes_liquidez(snap)
                reg = registro_liquidez_diario(extraido)
                if not reg:
                    continue
                d = _parse_date(reg["data_posicao"])
                if so_pendentes and d in existentes:
                    n_skip += 1
                    continue
                registros.append(reg)
                n += 1
            ok += 1
            if n == 0 and n_skip > 0:
                print(f"  skip   {rotulo} ({n_skip} ja no destino)")
            else:
                print(f"  ok     {rotulo} ({n} dias)")
        except Exception as exc:  # noqa: BLE001
            erros += 1
            print(f"  erro   {rotulo}: {exc}")

    print(f"Coletado: {len(registros)} | ok={ok} vazios={vazios} erros={erros}")
    return registros


def carregar(
    *,
    inicio: date | None = None,
    fim: date | None = None,
    so_pendentes: bool = False,
) -> dict:
    carteira = carteira_composicao_idsf()
    if carteira is None:
        raise RuntimeError("Defina IDSF_CARTEIRA_COMPOSICAO ou IDSF_CARTEIRAS")

    if inicio is None or fim is None:
        fundo = fundo_padrao()
        ini_fundo = None
        if fundo and fundo.get("data_inicio"):
            ini_fundo = _parse_date(str(fundo["data_inicio"]))
        inicio = inicio or ini_fundo or date(2021, 3, 1)
        fim = fim or date.today()

    tem_tabela = tabela_disponivel()
    if not tem_tabela:
        print(f"AVISO: tabela {TABELA} ausente - gravando so em {CACHE_PATH}")
        print(f"Execute {SQL_HINT} no Supabase para persistir no BD.")

    registros = coletar(
        inicio=inicio,
        fim=fim,
        id_carteira=carteira,
        so_pendentes=so_pendentes,
    )
    gravados = upsert_registros(registros)
    print(f"Gravados: {gravados} (supabase={tem_tabela})")
    return {
        "registros": gravados,
        "id_carteira": carteira,
        "inicio": str(inicio),
        "fim": str(fim),
        "supabase": tem_tabela,
        "cache": str(CACHE_PATH),
    }


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Carga liquidez diária IDSF")
    parser.add_argument("--inicio", help="YYYY-MM-DD ou dd/mm/yyyy")
    parser.add_argument("--fim", help="YYYY-MM-DD ou dd/mm/yyyy")
    parser.add_argument(
        "--pendentes",
        action="store_true",
        help="Pula dias ja gravados no destino (Supabase se existir; senao cache)",
    )
    parser.add_argument(
        "--sync-cache",
        action="store_true",
        help="Soh envia o cache local para o Supabase (sem chamar IDSF)",
    )
    args = parser.parse_args()
    try:
        if args.sync_cache:
            sync_cache_para_supabase()
            return 0
        carregar(
            inicio=_parse_date(args.inicio),
            fim=_parse_date(args.fim),
            so_pendentes=args.pendentes,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Falha: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
