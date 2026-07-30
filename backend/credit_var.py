"""Credit VaR histórico e paramétrico a partir da série diária PL/PDD."""

from __future__ import annotations

import numpy as np
import pandas as pd

from db import carregar_pl_pdd_diario

# Quantil normal padrão N^{-1}(0.95) para cauda esquerda (perda)
Z_95 = 1.6448536269514722


def calcular_credit_var(
    id_carteira: int = 0,
    confianca: float = 0.95,
    data_base: str | pd.Timestamp | None = None,
) -> dict:
    """
    Impacto no PL (retorno de crédito):
      R_t = -(PDD_t - PDD_{t-1}) / PL_{t-1}

    Aumento de PDD => R_t negativo.

    Janela: últimos 12 meses até a data base do relatório (inclusive).
    Posições posteriores à data base são ignoradas.

    - Histórico 95%: percentil (1 - confianca) de R_t (cauda esquerda), em %
    - Paramétrico 95%: μ - z_95 * σ, em %
    """
    vazio = {
        "credit_var_historico_95": 0.0,
        "credit_var_parametrico_95": 0.0,
        "n_obs": 0,
        "media_perda_pct": 0.0,
        "volatilidade_pct": 0.0,
        "pl_ref": 0.0,
        "pdd_ref": 0.0,
    }
    try:
        df = carregar_pl_pdd_diario(id_carteira=id_carteira)
    except Exception:  # noqa: BLE001
        return vazio
    if df.empty or len(df) < 2:
        return vazio

    df = df.copy()
    df["data_posicao"] = pd.to_datetime(df["data_posicao"], errors="coerce")
    df = df.dropna(subset=["data_posicao"]).sort_values("data_posicao")

    if data_base is not None:
        fim = pd.to_datetime(data_base, dayfirst=True, errors="coerce")
        if pd.isna(fim):
            return vazio
        inicio = fim - pd.DateOffset(months=12)
        df = df[(df["data_posicao"] > inicio) & (df["data_posicao"] <= fim)]
    if df.empty or len(df) < 2:
        return vazio

    df["pl_ant"] = df["pl"].shift(1)
    df["delta_pdd"] = df["pdd"] - df["pdd"].shift(1)
    # Impacto no PL: provisão sobe => retorno negativo
    df["retorno"] = np.where(
        df["pl_ant"] > 0,
        -df["delta_pdd"] / df["pl_ant"],
        np.nan,
    )
    retornos = df["retorno"].dropna()
    if retornos.empty:
        return vazio

    ret_arr = retornos.to_numpy(dtype=float)
    media = float(np.mean(ret_arr))
    desvio = float(np.std(ret_arr, ddof=1)) if len(ret_arr) > 1 else 0.0

    alpha = 1.0 - confianca
    hist = float(np.quantile(ret_arr, alpha))
    param = media - Z_95 * desvio

    ultimo = df.iloc[-1]
    return {
        "credit_var_historico_95": round(hist * 100.0, 4),
        "credit_var_parametrico_95": round(param * 100.0, 4),
        "n_obs": int(len(ret_arr)),
        "media_perda_pct": round(media * 100.0, 4),
        "volatilidade_pct": round(desvio * 100.0, 4),
        "pl_ref": round(float(ultimo["pl"]), 2),
        "pdd_ref": round(float(ultimo["pdd"]), 2),
    }
