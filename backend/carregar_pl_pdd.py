"""Carga dos últimos 12 meses de PL/PDD (IDSF -> Supabase).

Uso:
  cd backend
  python carregar_pl_pdd.py
  python carregar_pl_pdd.py --from-cache   # só grava cache local (sem chamar IDSF)

Requer:
  - Tabela public.fidc_pl_pdd_diario (ver sql/fidc_pl_pdd_diario.sql)
  - SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, IDSF_TOKEN no .env
"""

from __future__ import annotations

import argparse
import calendar
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv

from db import get_supabase
from idsf_pl_pdd import (
    buscar_composicao,
    carteiras_idsf,
    consolidar_registros,
    extrair_pl_pdd,
    token_idsf,
)

TABELA = "fidc_pl_pdd_diario"
MESES = 12
CACHE_PATH = Path(__file__).resolve().parent / "data" / "pl_pdd_cache.json"
SQL_PATH = Path(__file__).resolve().parent / "sql" / "fidc_pl_pdd_diario.sql"


def _meses_entre(inicio: date, fim: date) -> list[tuple[date, date]]:
    periodos: list[tuple[date, date]] = []
    cursor = inicio.replace(day=1)
    while cursor <= fim:
        ultimo = calendar.monthrange(cursor.year, cursor.month)[1]
        mes_fim = date(cursor.year, cursor.month, ultimo)
        if mes_fim > fim:
            mes_fim = fim
        mes_ini = max(cursor, inicio)
        if mes_ini <= mes_fim:
            periodos.append((mes_ini, mes_fim))
        cursor = (cursor + relativedelta(months=1)).replace(day=1)
    return periodos


def _meses_janela(fim: date | None = None, n_meses: int = MESES) -> list[tuple[date, date]]:
    fim = fim or date.today()
    inicio_janela = fim - relativedelta(months=n_meses - 1)
    inicio_janela = inicio_janela.replace(day=1)
    return _meses_entre(inicio_janela, fim)


def ultima_data_cache() -> date | None:
    if not CACHE_PATH.exists():
        return None
    try:
        regs = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    datas: list[date] = []
    for reg in regs if isinstance(regs, list) else []:
        raw = str(reg.get("data_posicao") or "")[:10]
        if len(raw) == 10 and raw[4] == "-":
            try:
                datas.append(date.fromisoformat(raw))
            except ValueError:
                continue
    return max(datas) if datas else None


def ids_carteira_no_cache() -> set[int]:
    if not CACHE_PATH.exists():
        return set()
    try:
        regs = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return set()
    out: set[int] = set()
    for reg in regs if isinstance(regs, list) else []:
        try:
            cid = int(reg.get("id_carteira"))
        except (TypeError, ValueError):
            continue
        if cid > 0:
            out.add(cid)
    return out


def garantir_tabela() -> None:
    sb = get_supabase()
    try:
        sb.table(TABELA).select("data_posicao").limit(1).execute()
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        if "PGRST205" in msg or "Could not find the table" in msg or TABELA in msg:
            raise RuntimeError(
                f"Tabela '{TABELA}' não existe no Supabase.\n"
                "1) Abra o SQL Editor do projeto\n"
                f"2) Execute o arquivo: {SQL_PATH}\n"
                "3) Rode de novo: python carregar_pl_pdd.py --from-cache\n"
                "(ou sem --from-cache para buscar de novo na IDSF)"
            ) from exc
        raise


def upsert_registros(registros: list[dict]) -> int:
    if not registros:
        return 0
    sb = get_supabase()
    batch_size = 200
    total = 0
    for i in range(0, len(registros), batch_size):
        batch = registros[i : i + batch_size]
        sb.table(TABELA).upsert(batch, on_conflict="data_posicao,id_carteira").execute()
        total += len(batch)
    return total


def salvar_cache(registros: list[dict], *, mesclar: bool = True) -> Path:
    """Persiste cache local. Com mesclar=True, preserva dias/carteiras fora da coleta."""
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    mapa: dict[tuple[str, int], dict] = {}
    if mesclar and CACHE_PATH.exists():
        try:
            antigos = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            for reg in antigos if isinstance(antigos, list) else []:
                data_pos = str(reg.get("data_posicao") or "")[:10]
                try:
                    cid = int(reg.get("id_carteira"))
                except (TypeError, ValueError):
                    continue
                if data_pos:
                    mapa[(data_pos, cid)] = reg
        except (OSError, json.JSONDecodeError, TypeError):
            pass
    for reg in registros:
        data_pos = str(reg.get("data_posicao") or "")[:10]
        try:
            cid = int(reg.get("id_carteira"))
        except (TypeError, ValueError):
            continue
        if data_pos:
            mapa[(data_pos, cid)] = reg
    ordenados = [
        mapa[k]
        for k in sorted(mapa.keys(), key=lambda t: (t[0], t[1]))
    ]
    CACHE_PATH.write_text(
        json.dumps(ordenados, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return CACHE_PATH


def carregar_cache() -> list[dict]:
    if not CACHE_PATH.exists():
        raise RuntimeError(
            f"Cache não encontrado em {CACHE_PATH}. Rode primeiro sem --from-cache."
        )
    return json.loads(CACHE_PATH.read_text(encoding="utf-8"))


def coletar_da_idsf(
    n_meses: int = MESES,
    *,
    inicio: date | None = None,
    fim: date | None = None,
) -> list[dict]:
    token = token_idsf()
    carteiras = carteiras_idsf()
    fim = fim or date.today()
    if inicio is not None:
        periodos = _meses_entre(inicio, fim)
    else:
        periodos = _meses_janela(fim=fim, n_meses=n_meses)
    if not periodos:
        return []

    por_dia: dict[str, dict[int, dict]] = defaultdict(dict)
    ok = 0
    vazios = 0
    erros: list[str] = []

    print(f"Carteiras: {carteiras}")
    print(f"Períodos: {periodos[0][0]} -> {periodos[-1][1]} ({len(periodos)} meses)")

    for data_ini, data_fim in periodos:
        for id_carteira in carteiras:
            rotulo = f"{id_carteira} {data_ini}..{data_fim}"
            try:
                snapshots = buscar_composicao(id_carteira, data_ini, data_fim, token=token)
                if not snapshots:
                    vazios += 1
                    print(f"  vazio  {rotulo}")
                    continue
                n_dia = 0
                for snap in snapshots:
                    reg = extrair_pl_pdd(snap)
                    if not reg:
                        continue
                    por_dia[reg["data_posicao"]][reg["id_carteira"]] = reg
                    n_dia += 1
                ok += 1
                print(f"  ok     {rotulo} ({n_dia} dias)")
            except Exception as exc:  # noqa: BLE001
                msg = f"{rotulo}: {exc}"
                erros.append(msg)
                print(f"  erro   {msg}")

    registros: list[dict] = []
    consolidados = 0
    for _data_pos, mapa in sorted(por_dia.items()):
        regs = list(mapa.values())
        registros.extend(regs)
        cons = consolidar_registros(regs)
        if cons:
            registros.append(cons)
            consolidados += 1

    print(
        f"Coletado: {len(registros)} registros | dias: {len(por_dia)} | "
        f"consolidados: {consolidados} | ok: {ok} | vazios: {vazios} | erros: {len(erros)}"
    )
    return registros


def carregar(
    *,
    from_cache: bool = False,
    n_meses: int = MESES,
    inicio: date | None = None,
    fim: date | None = None,
    mesclar_cache: bool = True,
) -> dict:
    garantir_tabela()

    if from_cache:
        registros = carregar_cache()
        print(f"Cache: {len(registros)} registros em {CACHE_PATH}")
        mesclar_cache = False
    else:
        registros = coletar_da_idsf(n_meses=n_meses, inicio=inicio, fim=fim)
        path = salvar_cache(registros, mesclar=mesclar_cache)
        print(f"Cache salvo: {path}")

    gravados = upsert_registros(registros)
    print("---")
    print(f"Upsert no Supabase: {gravados} registros em {TABELA}")
    return {
        "registros_upsert": gravados,
        "from_cache": from_cache,
        "inicio": str(inicio) if inicio else None,
        "fim": str(fim) if fim else None,
    }


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Carga PL/PDD diário IDSF → Supabase")
    parser.add_argument(
        "--from-cache",
        action="store_true",
        help="Usa backend/data/pl_pdd_cache.json sem chamar a IDSF",
    )
    args = parser.parse_args()
    try:
        carregar(from_cache=args.from_cache)
    except Exception as exc:  # noqa: BLE001
        print(f"Falha: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
