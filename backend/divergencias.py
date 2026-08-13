"""Divergências motor × BDR × IDSF acima da tolerância."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

from carteira_movimentacoes import (
    DATA_MINIMA,
    DIARIO_PATH,
    TOLERANCIA_DC_ABS,
    _aplicar_eventos_ate,
    _carregar_eventos,
    anexar_prazo_atual_do_dia,
    carregar_estoque_base,
    mapa_dc_bdr_diario,
)
from conciliar_junho_2024 import (
    _normalizar_colunas_bdr,
    cent,
    parse_valor,
    totais_bdr,
    totais_sistema,
)
from excecoes_bdr import caminho_estoque_bdr
from marcacao_carteira import atualizar_marcacao
from risco import TOLERANCIA_DC_ABS as TOL_RISCO

import pandas as pd


def _parse_data(texto: str | date) -> date:
    if isinstance(texto, date):
        return texto
    t = str(texto).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(t[:10], fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Data inválida: {texto}")


def _tol() -> float:
    return float(TOL_RISCO or TOLERANCIA_DC_ABS or 500.0)


def listar_divergencias(
    *,
    desde: date | None = None,
    ate: date | None = None,
) -> dict[str, Any]:
    """Dias da série em que |ΔVP| ou |ΔPDD| limpo supera a tolerância."""
    tol = _tol()
    serie = mapa_dc_bdr_diario()
    dias: list[dict[str, Any]] = []
    for iso in sorted(serie):
        d = _parse_data(iso)
        if desde and d < desde:
            continue
        if ate and d > ate:
            continue
        row = serie[iso]
        bruto = float(row.get("dc_bruto_idsf") or 0)
        if not bruto:
            continue
        vp = float(row.get("vp") or 0)
        pdd = float(row.get("pdd") or 0)
        pdd_i = float(row.get("pdd_idsf") or 0)
        delta_vp = float(row.get("delta_vp") if "delta_vp" in row else round(vp - bruto, 2))
        delta_pdd = float(
            row.get("delta_pdd") if "delta_pdd" in row else round(pdd - pdd_i, 2)
        )
        if "delta_vp_limpo" in row and "delta_pdd_limpo" in row:
            dv = float(row["delta_vp_limpo"])
            dp = float(row["delta_pdd_limpo"])
        else:
            dv, dp = delta_vp, delta_pdd
        if abs(dv) <= tol and abs(dp) <= tol:
            continue
        bdr_path = caminho_estoque_bdr(d)
        dias.append(
            {
                "data": d.strftime("%d/%m/%Y"),
                "data_iso": iso,
                "n_titulos": int(row.get("n") or 0),
                "vp_motor": round(vp, 2),
                "pdd_motor": round(pdd, 2),
                "vp_idsf": round(bruto, 2),
                "pdd_idsf": round(pdd_i, 2),
                "delta_vp": round(delta_vp, 2),
                "delta_pdd": round(delta_pdd, 2),
                "delta_vp_limpo": round(dv, 2),
                "delta_pdd_limpo": round(dp, 2),
                "tem_estoque_bdr": bdr_path is not None and Path(bdr_path).exists(),
                "excecao_residuos": bool(row.get("excecao_residuos")),
            }
        )
    return {
        "tolerancia": tol,
        "fonte_serie": str(DIARIO_PATH),
        "n_dias": len(dias),
        "dias": dias,
    }


def _carteira_motor(d: date) -> dict[str, dict[str, Any]]:
    base = carregar_estoque_base()
    ev = _carregar_eventos(desde=DATA_MINIMA, ate=d)
    ab = _aplicar_eventos_ate(ev, d, base=base)
    anexar_prazo_atual_do_dia(ab, d)
    if d == DATA_MINIMA:
        return ab
    return atualizar_marcacao(ab, data_ref=DATA_MINIMA, data_alvo=d)


def _idsf_totais(d: date) -> dict[str, Any]:
    serie = mapa_dc_bdr_diario().get(d.isoformat()) or {}
    if float(serie.get("dc_bruto_idsf") or 0):
        return {
            "vp": round(float(serie["dc_bruto_idsf"]), 2),
            "pdd": round(float(serie.get("pdd_idsf") or 0), 2),
            "fonte": "serie_diaria",
        }
    try:
        from carteira_movimentacoes import _idsf_do_dia

        idsf = _idsf_do_dia(d)
        return {
            "vp": round(float(idsf.get("dc_bruto_idsf") or 0), 2),
            "pdd": round(float(idsf.get("pdd_idsf") or 0), 2),
            "fonte": "idsf_api_cache",
        }
    except Exception as exc:  # noqa: BLE001
        return {"vp": 0.0, "pdd": 0.0, "fonte": None, "aviso": str(exc)}


def detalhe_divergencia(data_base: str | date) -> dict[str, Any]:
    """Resumo triplo + títulos com diferença material vs EstoqueBDR."""
    d = _parse_data(data_base)
    if d < DATA_MINIMA:
        raise ValueError(
            f"Data anterior ao estoque-base ({DATA_MINIMA.isoformat()})"
        )
    tol = _tol()
    abertos = _carteira_motor(d)
    sis = totais_sistema(abertos)
    idsf = _idsf_totais(d)

    bdr_path = caminho_estoque_bdr(d)
    bdr_tot: dict[str, Any] | None = None
    titulos: list[dict[str, Any]] = []
    so_motor: list[dict[str, Any]] = []
    so_bdr: list[dict[str, Any]] = []

    if bdr_path is not None and Path(bdr_path).exists():
        bdr_tot = totais_bdr(Path(bdr_path))
        bdr = _normalizar_colunas_bdr(
            pd.read_csv(bdr_path, sep=";", dtype=str, encoding="utf-8-sig")
        )
        bdr["doc"] = bdr["SEU_NUMERO"].astype(str).str.strip()
        bdr["vp_bdr"] = [cent(parse_valor(x)) for x in bdr["VALOR_PRESENTE"]]
        bdr["pdd_bdr"] = [cent(parse_valor(x)) for x in bdr["VALOR_PDD"]]
        bdr["face_bdr"] = [cent(parse_valor(x)) for x in bdr["VALOR_NOMINAL"]]
        bdr["fx_bdr"] = bdr["FAIXA_PDD"].astype(str).str.strip().str.upper()

        linhas = []
        for chave, pos in abertos.items():
            linhas.append(
                {
                    "doc": str(pos.get("documento") or chave).strip(),
                    "sacado": str(pos.get("sacado") or ""),
                    "vp_motor": cent(float(pos.get("vl_presente_adm") or 0)),
                    "pdd_motor": cent(float(pos.get("vl_pdd") or 0)),
                    "face_motor": cent(float(pos.get("valor_face") or 0)),
                    "fx_motor": str(pos.get("fx_pdd") or "").strip().upper(),
                    "venc": str(pos.get("data_vencimento") or ""),
                }
            )
        sis_df = pd.DataFrame(linhas)
        m = sis_df.merge(
            bdr[["doc", "vp_bdr", "pdd_bdr", "face_bdr", "fx_bdr"]],
            on="doc",
            how="outer",
            indicator=True,
        )
        for _, r in m[m["_merge"] == "left_only"].iterrows():
            so_motor.append(
                {
                    "documento": r["doc"],
                    "sacado": r.get("sacado") or "",
                    "vp_motor": float(r["vp_motor"] or 0),
                    "pdd_motor": float(r["pdd_motor"] or 0),
                }
            )
        for _, r in m[m["_merge"] == "right_only"].iterrows():
            so_bdr.append(
                {
                    "documento": r["doc"],
                    "vp_bdr": float(r["vp_bdr"] or 0),
                    "pdd_bdr": float(r["pdd_bdr"] or 0),
                }
            )
        ambos = m[m["_merge"] == "both"].copy()
        ambos["delta_vp"] = (ambos["vp_motor"].astype(float) - ambos["vp_bdr"]).round(2)
        ambos["delta_pdd"] = (ambos["pdd_motor"].astype(float) - ambos["pdd_bdr"]).round(2)
        # Material: ≥ R$ 0,01; prioriza os que somam a divergência
        div = ambos[
            (ambos["delta_vp"].abs() >= 0.01) | (ambos["delta_pdd"].abs() >= 0.01)
        ].copy()
        div = div.reindex(div["delta_vp"].abs().sort_values(ascending=False).index)
        for _, r in div.head(200).iterrows():
            titulos.append(
                {
                    "documento": r["doc"],
                    "sacado": r.get("sacado") or "",
                    "vencimento": r.get("venc") or "",
                    "vp_motor": float(r["vp_motor"] or 0),
                    "vp_bdr": float(r["vp_bdr"] or 0),
                    "delta_vp": float(r["delta_vp"] or 0),
                    "pdd_motor": float(r["pdd_motor"] or 0),
                    "pdd_bdr": float(r["pdd_bdr"] or 0),
                    "delta_pdd": float(r["delta_pdd"] or 0),
                    "fx_motor": r.get("fx_motor") or "",
                    "fx_bdr": r.get("fx_bdr") or "",
                    "face_motor": float(r.get("face_motor") or 0),
                    "face_bdr": float(r.get("face_bdr") or 0),
                }
            )

    delta_mi_vp = round(float(sis["vp"]) - float(idsf["vp"]), 2)
    delta_mi_pdd = round(float(sis["pdd"]) - float(idsf["pdd"]), 2)
    delta_mb_vp = (
        round(float(sis["vp"]) - float(bdr_tot["vp"]), 2) if bdr_tot else None
    )
    delta_mb_pdd = (
        round(float(sis["pdd"]) - float(bdr_tot["pdd"]), 2) if bdr_tot else None
    )
    delta_bi_vp = (
        round(float(bdr_tot["vp"]) - float(idsf["vp"]), 2) if bdr_tot else None
    )
    delta_bi_pdd = (
        round(float(bdr_tot["pdd"]) - float(idsf["pdd"]), 2) if bdr_tot else None
    )

    acima = abs(delta_mi_vp) > tol or abs(delta_mi_pdd) > tol
    if delta_mb_vp is not None and delta_mb_pdd is not None:
        acima = acima or abs(delta_mb_vp) > tol or abs(delta_mb_pdd) > tol

    return {
        "data": d.strftime("%d/%m/%Y"),
        "data_iso": d.isoformat(),
        "tolerancia": tol,
        "acima_tolerancia": acima,
        "resumo": {
            "motor": {
                "n": int(sis["n"]),
                "vp": float(sis["vp"]),
                "pdd": float(sis["pdd"]),
                "face": float(sis["face"]),
            },
            "idsf": idsf,
            "bdr": (
                {
                    "n": int(bdr_tot["n"]),
                    "vp": float(bdr_tot["vp"]),
                    "pdd": float(bdr_tot["pdd"]),
                    "face": float(bdr_tot["face"]),
                    "disponivel": True,
                    "arquivo": Path(bdr_path).name if bdr_path else None,
                }
                if bdr_tot
                else {"disponivel": False}
            ),
            "delta_motor_idsf": {"vp": delta_mi_vp, "pdd": delta_mi_pdd},
            "delta_motor_bdr": (
                {"vp": delta_mb_vp, "pdd": delta_mb_pdd}
                if bdr_tot
                else None
            ),
            "delta_bdr_idsf": (
                {"vp": delta_bi_vp, "pdd": delta_bi_pdd} if bdr_tot else None
            ),
        },
        "titulos": titulos,
        "so_motor": so_motor[:50],
        "so_bdr": so_bdr[:50],
        "n_titulos_divergentes": len(titulos),
        "n_so_motor": len(so_motor),
        "n_so_bdr": len(so_bdr),
    }
