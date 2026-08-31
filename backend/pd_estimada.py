"""PD estimada por sacado/título — regras de consignado + redutor calibrado."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from consignado import DOCS_CEDENTE_CONSIGNADO, TABELA

# Defaults (sobrescritos por data/pd_config.json quando existir)
_PD_DEFAULTS = {
    "pd_min_consignado": 15.0,
    "pd_consignado_vencido": 80.0,
    "redutor": 0.5,
}

CONFIG_PATH = Path(__file__).resolve().parent / "data" / "pd_config.json"

PD_MIN_CONSIGNADO = _PD_DEFAULTS["pd_min_consignado"]
PD_CONSIGNADO_VENCIDO = _PD_DEFAULTS["pd_consignado_vencido"]
REDUTOR_PD = _PD_DEFAULTS["redutor"]
NOMES_CEDENTE_CONSIGNADO = ("BMP", "VIA CAPITAL", "CARTOS")

_CADASTRO_DOCS: frozenset[str] | None = None


def _parse_data_base(data_base: date | datetime | str | None) -> date | None:
    if data_base is None:
        return None
    if isinstance(data_base, datetime):
        return data_base.date()
    if isinstance(data_base, date):
        return data_base
    texto = str(data_base).strip()[:10]
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(texto, fmt).date()
        except ValueError:
            continue
    parsed = pd.to_datetime(data_base, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def _docs_cadastro_consignado() -> frozenset[str]:
    global _CADASTRO_DOCS
    if _CADASTRO_DOCS is not None:
        return _CADASTRO_DOCS
    docs: set[str] = set()
    try:
        from db import get_supabase

        sb = get_supabase()
        offset = 0
        page = 1000
        while True:
            batch = (
                sb.table(TABELA)
                .select("documento")
                .eq("tp_sacado", "PF")
                .in_("doc_cedente", list(DOCS_CEDENTE_CONSIGNADO))
                .range(offset, offset + page - 1)
                .execute()
                .data
                or []
            )
            if not batch:
                break
            for row in batch:
                doc = str(row.get("documento") or "").strip()
                if doc:
                    docs.add(doc)
            if len(batch) < page:
                break
            offset += page
    except Exception:  # noqa: BLE001
        pass
    _CADASTRO_DOCS = frozenset(docs)
    return _CADASTRO_DOCS


def reset_cadastro_cache() -> None:
    global _CADASTRO_DOCS
    _CADASTRO_DOCS = None


def e_consignado_cedente(cedente: str) -> bool:
    nome = (cedente or "").upper()
    return any(n in nome for n in NOMES_CEDENTE_CONSIGNADO)


def marcar_consignado(df: pd.DataFrame, docs_cadastro: frozenset[str] | None = None) -> pd.Series:
    """True para títulos de consignado privado (cadastro ou cedente)."""
    if df is None or df.empty:
        return pd.Series(dtype=bool)
    docs = docs_cadastro if docs_cadastro is not None else _docs_cadastro_consignado()
    por_doc = (
        df["documento"].astype(str).str.strip().isin(docs)
        if "documento" in df.columns
        else pd.Series(False, index=df.index)
    )
    por_ced = (
        df["cedente"].map(lambda c: e_consignado_cedente(str(c or "")))
        if "cedente" in df.columns
        else pd.Series(False, index=df.index)
    )
    return por_doc | por_ced


def _condicao_atraso(df: pd.DataFrame, data_base: date | None) -> pd.Series:
    status = df["status"].astype(str).str.upper()
    atrasado = status.isin(["VENCIDO", "ATRASO"])
    if data_base is not None and "data_vencimento" in df.columns:
        venc = pd.to_datetime(df["data_vencimento"], errors="coerce")
        atrasado = atrasado | (venc.dt.date < data_base)
    if "dias_atraso_calc" in df.columns:
        atrasado = atrasado | (df["dias_atraso_calc"].fillna(0) > 0)
    return atrasado


def _pd_formula_sacado(
    df: pd.DataFrame,
    data_base: date | None,
    redutor: float,
) -> dict[str, float]:
    """PD bruta por sacado: (face em atraso / face total) × redutor."""
    if df.empty or "sacado" not in df.columns:
        return {}
    atrasado = _condicao_atraso(df, data_base)
    tot = df.groupby("sacado")["valor_face"].sum()
    atr = (
        df.loc[atrasado]
        .groupby("sacado")["valor_face"]
        .sum()
        .reindex(tot.index)
        .fillna(0.0)
    )
    out: dict[str, float] = {}
    for sac, face_tot in tot.items():
        ft = float(face_tot)
        if ft <= 0:
            out[str(sac)] = 0.0
        else:
            out[str(sac)] = min(100.0, float(atr.get(sac, 0.0)) / ft * 100.0 * redutor)
    return out


def sacados_consignado_com_vencido(df: pd.DataFrame, data_base: date | None) -> set[str]:
    """Sacados com ao menos uma parcela consignada vencida na data base."""
    if df.empty:
        return set()
    work = df.copy()
    work["_consig"] = marcar_consignado(work)
    if not work["_consig"].any():
        return set()
    atrasado = _condicao_atraso(work, data_base)
    mask = work["_consig"] & atrasado
    if not mask.any():
        return set()
    return set(work.loc[mask, "sacado"].astype(str))


def _pd_formula_sacado_bruta(df: pd.DataFrame, data_base: date | None) -> dict[str, float]:
    """Taxa de atraso (%) por sacado, sem redutor."""
    if df.empty or "sacado" not in df.columns:
        return {}
    atrasado = _condicao_atraso(df, data_base)
    tot = df.groupby("sacado")["valor_face"].sum()
    atr = (
        df.loc[atrasado]
        .groupby("sacado")["valor_face"]
        .sum()
        .reindex(tot.index)
        .fillna(0.0)
    )
    return {
        str(sac): (float(atr.get(sac, 0.0)) / float(ft) * 100.0 if float(ft) > 0 else 0.0)
        for sac, ft in tot.items()
    }


def preparar_base_pd(
    df: pd.DataFrame,
    data_base: date | datetime | str | None = None,
) -> tuple[pd.Series, pd.Series, set[str], dict[str, float]]:
    """Flags e fórmula bruta para calibrar redutor sem recomputar tudo."""
    ref = _parse_data_base(data_base)
    if ref is None and "data_base" in df.columns:
        ref = _parse_data_base(str(df["data_base"].iloc[0]))
    consig = marcar_consignado(df)
    sac_venc = sacados_consignado_com_vencido(df, ref)
    bruta = _pd_formula_sacado_bruta(df, ref)
    return consig, df["sacado"].astype(str), sac_venc, bruta


def pd_por_titulo_com_base(
    df: pd.DataFrame,
    consig: pd.Series,
    sacados: pd.Series,
    sac_venc: set[str],
    bruta: dict[str, float],
    redutor: float,
) -> pd.Series:
    base_pd = sacados.map(lambda s: min(100.0, bruta.get(str(s), 0.0) * redutor)).fillna(0.0)
    out = base_pd.copy()
    mask_consig = consig
    mask_venc = sacados.isin(sac_venc)
    out.loc[mask_consig & mask_venc] = PD_CONSIGNADO_VENCIDO
    mask_consig_ok = mask_consig & ~mask_venc
    out.loc[mask_consig_ok] = base_pd.loc[mask_consig_ok].clip(lower=PD_MIN_CONSIGNADO)
    return out.clip(lower=0.0, upper=100.0)


def pd_por_titulo(
    df: pd.DataFrame,
    data_base: date | datetime | str | None = None,
    *,
    redutor: float | None = None,
) -> pd.Series:
    """
    PD (%) linha a linha, aplicando:
    - consignado com parcela vencida → PD_CONSIGNADO_VENCIDO
    - consignado sem vencido → max(fórmula sacado, PD_MIN_CONSIGNADO)
    - demais → fórmula sacado
    """
    if df is None or df.empty:
        return pd.Series(dtype=float)
    red = REDUTOR_PD if redutor is None else redutor
    consig, sacados, sac_venc, bruta = preparar_base_pd(df, data_base)
    return pd_por_titulo_com_base(df, consig, sacados, sac_venc, bruta, red)


def pd_por_sacado(
    df: pd.DataFrame,
    data_base: date | datetime | str | None = None,
    *,
    redutor: float | None = None,
) -> dict[str, float]:
    """PD (%) por sacado — média ponderada pela face dos títulos."""
    if df is None or df.empty or "sacado" not in df.columns:
        return {}
    pd_t = pd_por_titulo(df, data_base, redutor=redutor)
    work = df.copy()
    work["_pd"] = pd_t.values
    out: dict[str, float] = {}
    for sac, sub in work.groupby("sacado"):
        face = sub["valor_face"].astype(float).sum()
        if face <= 0:
            out[str(sac)] = 0.0
        else:
            out[str(sac)] = float((sub["valor_face"].astype(float) * sub["_pd"].astype(float)).sum() / face)
    return out


def parametros_pd() -> dict[str, Any]:
    return {
        "pd_min_consignado": PD_MIN_CONSIGNADO,
        "pd_consignado_vencido": PD_CONSIGNADO_VENCIDO,
        "redutor": REDUTOR_PD,
    }


def _aplicar_parametros(data: dict[str, Any]) -> None:
    global PD_MIN_CONSIGNADO, PD_CONSIGNADO_VENCIDO, REDUTOR_PD
    PD_MIN_CONSIGNADO = float(data["pd_min_consignado"])
    PD_CONSIGNADO_VENCIDO = float(data["pd_consignado_vencido"])
    REDUTOR_PD = float(data["redutor"])


def carregar_config_pd() -> dict[str, Any]:
    """Carrega parâmetros do JSON (ou defaults) e aplica em memória."""
    data = dict(_PD_DEFAULTS)
    if CONFIG_PATH.is_file():
        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for chave in _PD_DEFAULTS:
                    if chave in raw:
                        data[chave] = float(raw[chave])
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass
    _aplicar_parametros(data)
    return parametros_pd()


def salvar_parametros_pd(body: dict[str, Any]) -> dict[str, Any]:
    """Valida, persiste e aplica novos parâmetros de PD."""
    try:
        pd_min = float(body.get("pd_min_consignado", PD_MIN_CONSIGNADO))
        pd_venc = float(body.get("pd_consignado_vencido", PD_CONSIGNADO_VENCIDO))
        redutor = float(body.get("redutor", REDUTOR_PD))
    except (TypeError, ValueError) as exc:
        raise ValueError("Parâmetros PD devem ser numéricos.") from exc

    if not 0 <= pd_min <= 100:
        raise ValueError("PD mínima consignado deve estar entre 0 e 100.")
    if not 0 <= pd_venc <= 100:
        raise ValueError("PD consignado vencido deve estar entre 0 e 100.")
    if pd_venc < pd_min:
        raise ValueError("PD consignado vencido deve ser >= PD mínima.")
    if not 0 <= redutor <= 10:
        raise ValueError("Redutor deve estar entre 0 e 10.")

    data = {
        "pd_min_consignado": round(pd_min, 4),
        "pd_consignado_vencido": round(pd_venc, 4),
        "redutor": round(redutor, 4),
    }
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    _aplicar_parametros(data)
    return parametros_pd()


carregar_config_pd()