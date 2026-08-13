"""Marcação da cota mezanino por % do CDI + amortização/juros."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from calendario import dia_util_anterior, e_dia_util
from cdi_bcb import mapa_cdi

TOLERANCIA_COTA_ABS = 0.05
TOLERANCIA_COTA_REL = 5e-3  # 0,5% — residual de CDI/arredondamento em séries longas


def fator_dia(cdi_pct_ad: float, pct_cdi: float) -> float:
    """fator = 1 + (CDI%/100) × (pct_cdi/100)."""
    return 1.0 + (float(cdi_pct_ad) / 100.0) * (float(pct_cdi) / 100.0)


def marcar_cota(
    *,
    cota_inicial: float,
    data_inicio: date,
    data_fim: date,
    pct_cdi: float,
    cdi_por_dia: dict[date, float] | None = None,
    dist_por_dia: dict[date, dict[str, float]] | None = None,
) -> dict[str, Any]:
    """
    Em cada dia útil D após data_inicio:
      1) aplica CDI do dia útil anterior × %CDI
      2) se houver Amortização/Juros em D: cota -= (amort+juros) / qtde
    """
    if cota_inicial <= 0 or pct_cdi <= 0:
        return {
            "valor_cota": None,
            "dias_uteis": 0,
            "n_distribuicoes": 0,
            "aviso": "cota_inicial ou pct_cdi inválidos",
        }

    ini_fetch = data_inicio - timedelta(days=10)
    mapa = cdi_por_dia if cdi_por_dia is not None else mapa_cdi(ini_fetch, data_fim)
    dists = dist_por_dia or {}

    cota = float(cota_inicial)
    dias = 0
    n_dist = 0
    total_dist = 0.0
    faltando_cdi: list[str] = []
    faltando_qtde: list[str] = []

    d = data_inicio + timedelta(days=1)
    while d <= data_fim:
        if e_dia_util(d):
            ref = dia_util_anterior(d)
            cdi = mapa.get(ref)
            if cdi is None:
                cdi = mapa.get(d)
            if cdi is None:
                faltando_cdi.append(d.isoformat())
            else:
                cota *= fator_dia(cdi, pct_cdi)
                dias += 1

            ev = dists.get(d)
            if ev and float(ev.get("dist_bruto") or 0) > 0:
                qtde = float(ev.get("qtde_cotas") or 0)
                if qtde <= 0:
                    faltando_qtde.append(d.isoformat())
                else:
                    cota -= float(ev["dist_bruto"]) / qtde
                    n_dist += 1
                    total_dist += float(ev["dist_bruto"])
        d += timedelta(days=1)

    avisos: list[str] = []
    if faltando_cdi:
        avisos.append(f"CDI ausente em {len(faltando_cdi)} dia(s)")
    if faltando_qtde:
        avisos.append(f"qtde ausente em {len(faltando_qtde)} dist(s)")

    return {
        "valor_cota": round(cota, 8),
        "dias_uteis": dias,
        "n_distribuicoes": n_dist,
        "total_distribuido": round(total_dist, 2),
        "faltando_cdi": faltando_cdi[:5],
        "faltando_qtde": faltando_qtde[:5],
        "aviso": "; ".join(avisos) if avisos else None,
    }


def comparar_com_idsf(
    valor_app: float | None,
    valor_idsf: float | None,
    *,
    tolerancia_abs: float = TOLERANCIA_COTA_ABS,
    tolerancia_rel: float = TOLERANCIA_COTA_REL,
) -> dict[str, Any]:
    if valor_app is None or valor_idsf is None:
        return {
            "delta_cota": None,
            "delta_pct": None,
            "ok_marcacao": None,
        }
    delta = float(valor_app) - float(valor_idsf)
    base = abs(float(valor_idsf)) or 1.0
    delta_pct = delta / base * 100.0
    ok = abs(delta) <= tolerancia_abs or abs(delta) / base <= tolerancia_rel
    return {
        "delta_cota": round(delta, 8),
        "delta_pct": round(delta_pct, 6),
        "ok_marcacao": ok,
    }
