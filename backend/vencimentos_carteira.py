"""Vencimentos da carteira aberta na data base."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd


def _parse_data(texto: str | None) -> date | None:
    if not texto or not str(texto).strip():
        return None
    t = str(texto).strip()[:10]
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    return None


def _br(d: date | None) -> str | None:
    return d.strftime("%d/%m/%Y") if d else None


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def _to_date(valor: object) -> date | None:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    ts = pd.to_datetime(valor, errors="coerce")
    if pd.isna(ts):
        return None
    return ts.date()


def _money(valor: object) -> float:
    try:
        if valor is None or (isinstance(valor, float) and pd.isna(valor)):
            return 0.0
        return round(float(valor), 2)
    except (TypeError, ValueError):
        return 0.0


def montar_vencimentos(
    data_base: str,
    *,
    inicio: str | None = None,
    fim: str | None = None,
) -> dict[str, Any]:
    from carteira_movimentacoes import carregar_carteira_movimentacoes

    ref = _parse_data(data_base)
    if ref is None:
        raise ValueError(f"Data base inválida: {data_base}")

    d_ini = _parse_data(inicio) or ref
    d_fim = _parse_data(fim) or (ref + timedelta(days=90))
    if d_ini > d_fim:
        d_ini, d_fim = d_fim, d_ini

    df = carregar_carteira_movimentacoes(ref)
    if df is None or df.empty:
        return {
            "data_base": _br(ref),
            "data_base_iso": _iso(ref),
            "inicio": _br(d_ini),
            "inicio_iso": _iso(d_ini),
            "fim": _br(d_fim),
            "fim_iso": _iso(d_fim),
            "totais": {"n": 0, "face": 0.0, "vp": 0.0, "pdd": 0.0},
            "por_data": [],
            "titulos": [],
        }

    linhas: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        venc = _to_date(row.get("data_vencimento"))
        if venc is None or venc < d_ini or venc > d_fim:
            continue
        face = _money(row.get("valor_face"))
        vp = _money(row.get("vl_presente_adm"))
        if vp <= 0:
            vp = _money(row.get("valor_descontado")) or face
        pdd = _money(row.get("vl_pdd"))
        linhas.append(
            {
                "documento": str(row.get("documento") or "").strip(),
                "cedente": str(row.get("cedente") or "").strip(),
                "sacado": str(row.get("sacado") or "").strip(),
                "tipo": str(row.get("tipo_recebivel") or "").strip(),
                "status": str(row.get("status") or "").strip(),
                "data_vencimento": _br(venc),
                "data_vencimento_iso": _iso(venc),
                "face": face,
                "vp": vp,
                "pdd": pdd,
            }
        )

    linhas.sort(
        key=lambda r: (
            str(r.get("data_vencimento_iso") or ""),
            str(r.get("sacado") or ""),
            str(r.get("documento") or ""),
        )
    )

    buckets: dict[str, dict[str, Any]] = {}
    for item in linhas:
        iso = str(item["data_vencimento_iso"])
        b = buckets.get(iso)
        if b is None:
            b = {
                "data": item["data_vencimento"],
                "data_iso": iso,
                "n": 0,
                "face": 0.0,
                "vp": 0.0,
                "pdd": 0.0,
            }
            buckets[iso] = b
        b["n"] += 1
        b["face"] = round(b["face"] + item["face"], 2)
        b["vp"] = round(b["vp"] + item["vp"], 2)
        b["pdd"] = round(b["pdd"] + item["pdd"], 2)

    por_data = [buckets[k] for k in sorted(buckets)]
    totais = {
        "n": len(linhas),
        "face": round(sum(x["face"] for x in linhas), 2),
        "vp": round(sum(x["vp"] for x in linhas), 2),
        "pdd": round(sum(x["pdd"] for x in linhas), 2),
    }
    return {
        "data_base": _br(ref),
        "data_base_iso": _iso(ref),
        "inicio": _br(d_ini),
        "inicio_iso": _iso(d_ini),
        "fim": _br(d_fim),
        "fim_iso": _iso(d_fim),
        "totais": totais,
        "por_data": por_data,
        "titulos": linhas,
    }
