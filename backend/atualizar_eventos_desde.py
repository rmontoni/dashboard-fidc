"""Atualiza o cache de eventos só a partir de uma data (sem rebuild total)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone

from dotenv import load_dotenv

from bdr_arquivos import cnpj_fundo, extrair_data_movimento
from carteira_movimentacoes import (
    CACHE_PATH,
    META_PATH,
    PAGE_SIZE,
    _dados_dict,
    _evento_aquisicao,
    _evento_liquidacao,
    _parse_data_campo,
)
from db import get_supabase

load_dotenv()


def _log(*args: object) -> None:
    try:
        print(*args, file=sys.stderr)
    except OSError:
        pass


def _paginar_desde(tabela: str, cnpj: str, desde_iso: str) -> list[dict]:
    sb = get_supabase()
    rows: list[dict] = []
    offset = 0
    while True:
        resp = (
            sb.table(tabela)
            .select("dados,data_movimento")
            .eq("cnpj_fundo", cnpj)
            .gte("data_movimento", desde_iso)
            .order("id")
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
        )
        batch = resp.data or []
        if not batch:
            break
        rows.extend(batch)
        _log(f"  {tabela} +{len(batch)} (total {len(rows)})")
        if len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return rows


def atualizar_eventos(desde: date) -> dict:
    """Reescreve o JSONL mantendo eventos < desde e reimportando >= desde do BD."""
    corte = desde.isoformat()
    cnpj_n = cnpj_fundo()

    _log("Lendo cache existente...")
    antigos: list[dict] = []
    if CACHE_PATH.exists():
        with CACHE_PATH.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                ev = json.loads(line)
                if str(ev.get("data") or "") < corte:
                    antigos.append(ev)
    _log(f"mantidos (< {corte}): {len(antigos)}")

    novos: list[dict] = []
    sem_data = 0
    sem_chave = 0

    _log("Aquisicoes desde", corte)
    for row in _paginar_desde("fidc_aquisicoes", cnpj_n, corte):
        dados = _dados_dict(row.get("dados"))
        dm = (
            _parse_data_campo(row.get("data_movimento"))
            or extrair_data_movimento(dados)
            or _parse_data_campo(dados.get("ENTRADA"))
        )
        if dm is None:
            sem_data += 1
            continue
        if dm < desde:
            continue
        ev = _evento_aquisicao(dados, dm)
        if ev is None:
            sem_chave += 1
            continue
        novos.append(ev)
    _log(f"aq novas={sum(1 for e in novos if e.get('tipo')=='aquisicao')}")

    _log("Liquidacoes desde", corte)
    n_antes = len(novos)
    for row in _paginar_desde("fidc_liquidacoes", cnpj_n, corte):
        dados = _dados_dict(row.get("dados"))
        dm = _parse_data_campo(row.get("data_movimento")) or extrair_data_movimento(dados)
        if dm is None:
            sem_data += 1
            continue
        if dm < desde:
            continue
        ev = _evento_liquidacao(dados, dm)
        if ev is None:
            sem_chave += 1
            continue
        novos.append(ev)
    _log(f"liq novas={len(novos) - n_antes}")

    ordem_tipo = {"aquisicao": 0, "liquidacao": 1}
    eventos = antigos + novos
    eventos.sort(
        key=lambda e: (
            str(e.get("data") or ""),
            ordem_tipo.get(str(e.get("tipo") or ""), 9),
            str(e.get("chave") or ""),
        )
    )

    with CACHE_PATH.open("w", encoding="utf-8") as fh:
        for ev in eventos:
            fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
    meta = {
        "cnpj_fundo": cnpj_n,
        "atualizado_em": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "eventos": len(eventos),
        "sem_data": sem_data,
        "sem_chave": sem_chave,
        "cache": CACHE_PATH.name,
        "incremental_desde": corte,
    }
    META_PATH.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    _log(json.dumps(meta, ensure_ascii=False, indent=2))
    return meta


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", required=True, help="YYYY-MM-DD")
    args = ap.parse_args()
    desde = datetime.strptime(args.desde[:10], "%Y-%m-%d").date()
    atualizar_eventos(desde)


if __name__ == "__main__":
    main()
