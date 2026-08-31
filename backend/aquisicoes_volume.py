"""Volume histórico de aquisições (fidc_aquisicoes) até a data base.

Agregação histórica de aquisições (face = VALOR DE VENCIMENTO).
O KPI de inadimplência do dashboard usa VNP/vencimentos totais (ver inadimplencia.py).

Agrega por dia e grava cache em data/aquisicoes_agg_cache.json.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from bdr_arquivos import cnpj_fundo, extrair_data_movimento

CACHE_PATH = Path(__file__).resolve().parent / "data" / "aquisicoes_agg_cache.json"
PAGE_SIZE = 1000


def _parse_valor(valor: Any) -> float:
    if valor is None:
        return 0.0
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        return float(valor)
    texto = str(valor).strip()
    if not texto or texto.lower() in {"nan", "none", "null"}:
        return 0.0
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return 0.0


def _dados_dict(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _volume_aquisicao(dados: dict[str, Any]) -> float:
    """Face adquirida; fallback valor de compra."""
    for chave in ("VALOR DE VENCIMENTO", "VALOR DE COMPRA", "VALOR DE AQUISICAO"):
        vol = _parse_valor(dados.get(chave))
        if vol > 0:
            return vol
    return 0.0


def _parse_data_campo(valor: Any) -> date | None:
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = str(valor).strip()
    if not texto:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(texto[:10], fmt).date()
        except ValueError:
            continue
    return None


def _data_aquisicao(row: dict[str, Any], dados: dict[str, Any]) -> date | None:
    return (
        _parse_data_campo(row.get("data_movimento"))
        or extrair_data_movimento(dados)
        or _parse_data_campo(dados.get("ENTRADA"))
        or _parse_data_campo(row.get("periodo_fim"))
    )


def reconstruir_cache(*, forcar: bool = False) -> dict[str, float]:
    """Soma face adquirida por dia (ISO → volume)."""
    if CACHE_PATH.exists() and not forcar:
        try:
            raw = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            por_dia = raw.get("por_dia") or {}
            if isinstance(por_dia, dict) and por_dia:
                return {str(k)[:10]: float(v) for k, v in por_dia.items()}
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass

    from db import get_supabase

    sb = get_supabase()
    cnpj = cnpj_fundo()
    por_dia: dict[str, float] = {}
    offset = 0
    while True:
        resp = (
            sb.table("fidc_aquisicoes")
            .select("dados,data_movimento,periodo_fim")
            .eq("cnpj_fundo", cnpj)
            .order("id")
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
        )
        batch = resp.data or []
        if not batch:
            break
        for row in batch:
            dados = _dados_dict(row.get("dados"))
            dm = _data_aquisicao(row, dados)
            if dm is None:
                continue
            vol = _volume_aquisicao(dados)
            if vol <= 0:
                continue
            chave = dm.isoformat()
            por_dia[chave] = por_dia.get(chave, 0.0) + vol
        if len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    payload = {
        "atualizado_em": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "cnpj_fundo": cnpj,
        "dias": len(por_dia),
        "total": round(sum(por_dia.values()), 2),
        "por_dia": {k: round(v, 2) for k, v in sorted(por_dia.items())},
    }
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {str(k)[:10]: float(v) for k, v in por_dia.items()}


def total_aquisicoes_ate(data_base: date, *, forcar: bool = False) -> dict[str, Any]:
    """Total de face adquirida com data de aquisição ≤ data_base."""
    por_dia = reconstruir_cache(forcar=forcar)
    corte = data_base.isoformat()
    total = 0.0
    n_dias = 0
    primeira: str | None = None
    ultima: str | None = None
    for dia, vol in sorted(por_dia.items()):
        if dia > corte:
            continue
        total += float(vol)
        n_dias += 1
        if primeira is None:
            primeira = dia
        ultima = dia
    return {
        "total": round(total, 2),
        "n_dias": n_dias,
        "desde": primeira,
        "ate": ultima,
        "data_base": corte,
    }
