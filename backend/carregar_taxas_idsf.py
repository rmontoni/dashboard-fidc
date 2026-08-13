"""Carga incremental de taxas por classe (GetSettledFeeHistory)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from typing import Any

import requests
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv

from db import get_supabase
from idsf_pl_pdd import carteiras_idsf, token_idsf
from passivo import CLASSES_ORDEM, ID_SUB

TABELA = "fidc_taxas_classe"
SQL_HINT = "backend/sql/fidc_taxas_classe.sql"
URL = "https://prod.idsf.com.br/api/Fundo/GetSettledFeeHistory"

# Na prática as taxas do fundo vêm em IdCliente = SUB; mezaninos sozinhos retornam vazio.
IDS_TAXAS = [cid for cid, _, _ in CLASSES_ORDEM]


def tabela_disponivel() -> bool:
    try:
        get_supabase().table(TABELA).select("data_historico").limit(1).execute()
        return True
    except Exception:  # noqa: BLE001
        return False


def _parse_date(texto: object) -> date | None:
    s = str(texto or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _float(v: object) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _ultima_data(id_carteira: int) -> date | None:
    rows = (
        get_supabase()
        .table(TABELA)
        .select("data_historico")
        .eq("id_carteira", id_carteira)
        .order("data_historico", desc=True)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        return None
    return _parse_date(rows[0].get("data_historico"))


def buscar_taxas(
    ids_carteira: list[int],
    data_inicio: date,
    data_fim: date,
    *,
    tipo_agrupamento: int = 1,
    token: str | None = None,
    timeout: int = 180,
) -> list[dict[str, Any]]:
    """A API real aceita GET com body JSON (POST retorna 405). Campo fim = datFim."""
    tok = token or token_idsf()
    body = {
        "idCarteira": [str(i) for i in ids_carteira],
        "dataInicio": data_inicio.isoformat(),
        "datFim": data_fim.isoformat(),  # typo oficial da API (dataFim falha)
        "tipoAgrupamento": tipo_agrupamento,
    }
    resp = requests.get(
        URL,
        headers={"token": tok, "Token": tok, "Content-Type": "application/json"},
        json=body,
        timeout=timeout,
    )
    if resp.status_code == 400:
        # lista vazia / sem dados no período
        try:
            msg = str((resp.json() or {}).get("Message") or "")
        except Exception:  # noqa: BLE001
            msg = resp.text or ""
        if "vazia" in msg.lower() or "não há" in msg.lower() or "nao ha" in msg.lower():
            return []
        resp.raise_for_status()
    resp.raise_for_status()
    payload = resp.json()
    model = payload.get("Model") if isinstance(payload, dict) else payload
    if isinstance(model, str):
        model = json.loads(model) if model.strip() else []
    if isinstance(model, dict):
        for key in ("Historico", "Itens", "Items", "Taxas", "Dados"):
            if isinstance(model.get(key), list):
                model = model[key]
                break
        else:
            model = [model]
    if not isinstance(model, list):
        return []
    return [m for m in model if isinstance(m, dict)]


def _normalizar(row: dict[str, Any], id_carteira_fallback: int | None = None) -> dict[str, Any] | None:
    dh = _parse_date(
        row.get("DataHistorico")
        or row.get("dataHistorico")
        or row.get("Data")
        or row.get("data")
    )
    if dh is None:
        return None
    try:
        cid = int(
            row.get("IdCarteira")
            or row.get("idCarteira")
            or row.get("IdCarteiraFundo")
            or row.get("IdCliente")  # GetSettledFeeHistory usa IdCliente
            or id_carteira_fallback
            or 0
        )
    except (TypeError, ValueError):
        cid = int(id_carteira_fallback or 0)
    if cid <= 0:
        return None
    try:
        id_tipo = int(row.get("IdTipoTaxa") or row.get("idTipoTaxa") or 0)
    except (TypeError, ValueError):
        id_tipo = 0
    tipo = str(row.get("TipoTaxa") or row.get("tipoTaxa") or "").strip()
    return {
        "data_historico": dh.isoformat(),
        "id_carteira": cid,
        "id_tipo_taxa": id_tipo,
        "tipo_taxa": tipo or f"tipo_{id_tipo}",
        "valor_dia": _float(row.get("ValorDia") or row.get("valorDia")),
        "valor_acumulado": _float(
            row.get("ValorAcumulado") or row.get("valorAcumulado")
        ),
        "pl_base": _float(row.get("PlBase") or row.get("plBase")) or None,
        "data_fim_apropriacao": (
            d.isoformat()
            if (
                d := _parse_date(
                    row.get("DataFimApropriacao") or row.get("dataFimApropriacao")
                )
            )
            else None
        ),
        "data_pagamento": (
            d.isoformat()
            if (d := _parse_date(row.get("DataPagamento") or row.get("dataPagamento")))
            else None
        ),
        "fonte": "idsf_fee_history",
    }


def upsert_registros(regs: list[dict[str, Any]], *, batch_size: int = 200) -> int:
    if not regs:
        return 0
    sb = get_supabase()
    total = 0
    for i in range(0, len(regs), batch_size):
        batch = regs[i : i + batch_size]
        sb.table(TABELA).upsert(
            batch, on_conflict="data_historico,id_carteira,id_tipo_taxa,tipo_taxa"
        ).execute()
        total += len(batch)
    return total


def carregar(
    *,
    inicio: date | None = None,
    fim: date | None = None,
    incluir_sub: bool = True,
) -> dict[str, Any]:
    if not tabela_disponivel():
        raise RuntimeError(f"Tabela {TABELA} ausente. Execute {SQL_HINT}.")

    fim = fim or date.today()
    ids = list(IDS_TAXAS)
    if not incluir_sub:
        ids = [i for i in ids if i != ID_SUB]
    # restringe ao que está no .env
    permitidos = set(carteiras_idsf())
    ids = [i for i in ids if i in permitidos]
    # Garante SUB (fonte real das taxas do fundo) quando disponível no env
    if incluir_sub and ID_SUB in permitidos and ID_SUB not in ids:
        ids.append(ID_SUB)
    if not ids:
        return {"registros": 0, "aviso": "nenhuma carteira em IDSF_CARTEIRAS"}

    if inicio is None:
        ultimas = [_ultima_data(i) for i in ids]
        ultimas_ok = [u for u in ultimas if u is not None]
        if ultimas_ok:
            inicio = min(ultimas_ok) + timedelta(days=1)
        else:
            inicio = fim - relativedelta(months=2)

    if inicio > fim:
        return {
            "registros": 0,
            "inicio": str(inicio),
            "fim": str(fim),
            "mensagem": "já atualizado",
        }

    brutos = buscar_taxas(ids, inicio, fim)
    regs: list[dict[str, Any]] = []
    for row in brutos:
        norm = _normalizar(row)
        if norm and (norm["id_carteira"] in ids or norm["id_carteira"] == ID_SUB):
            regs.append(norm)

    # dedup por PK
    mapa: dict[tuple, dict[str, Any]] = {}
    for r in regs:
        chave = (
            r["data_historico"],
            r["id_carteira"],
            r["id_tipo_taxa"],
            r["tipo_taxa"],
        )
        mapa[chave] = r
    gravados = upsert_registros(list(mapa.values()))
    return {
        "registros": gravados,
        "brutos": len(brutos),
        "inicio": str(inicio),
        "fim": str(fim),
        "carteiras": ids,
    }


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Carga taxas IDSF → Supabase")
    parser.add_argument("--inicio", help="YYYY-MM-DD")
    parser.add_argument("--fim", help="YYYY-MM-DD")
    parser.add_argument(
        "--sem-sub",
        action="store_true",
        help="Não inclui carteira SUB (taxas do fundo normalmente vêm nela)",
    )
    args = parser.parse_args()
    try:
        ini = date.fromisoformat(args.inicio) if args.inicio else None
        fim = date.fromisoformat(args.fim) if args.fim else None
        print(
            json.dumps(
                carregar(inicio=ini, fim=fim, incluir_sub=not args.sem_sub),
                indent=2,
            )
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Falha: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
