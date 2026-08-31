"""
Backtest da PD estimada (redutor 0,8) na data base 02/01/2026.

Compara recebimento esperado (face × (1 − PD/100)) com liquidações reais
posteriores até a data final do estudo.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from carteira_movimentacoes import (
    DATA_MINIMA,
    _aplicar_eventos_ate,
    _carregar_eventos,
    carregar_carteira_movimentacoes,
    carregar_estoque_base,
    reconstruir_eventos,
)
from passivo_vencimentos import _pd_por_sacado

T0 = date(2026, 1, 2)
T1 = date(2026, 8, 25)
REDUTOR_ATUAL = 0.8


def _abertos_na_data(data_limite: date) -> dict[str, dict]:
    reconstruir_eventos()
    base = carregar_estoque_base()
    if data_limite == DATA_MINIMA:
        return dict(base)
    eventos = _carregar_eventos(desde=DATA_MINIMA, ate=data_limite)
    return _aplicar_eventos_ate(eventos, data_limite, base=base)


def _pd_map(df: pd.DataFrame, redutor: float = REDUTOR_ATUAL) -> dict[str, float]:
    raw = _pd_por_sacado(df)
    if redutor == REDUTOR_ATUAL:
        return raw
    fator = redutor / REDUTOR_ATUAL if REDUTOR_ATUAL else 1.0
    return {k: min(100.0, v * fator) for k, v in raw.items()}


def _pagamentos_pos_t0(chaves: set[str]) -> dict[str, float]:
    """Soma valor_pago de liquidações estritamente após T0 até T1 inclusive."""
    eventos = _carregar_eventos(desde=T0 + timedelta(days=1), ate=T1)
    pagos: dict[str, float] = defaultdict(float)
    for ev in eventos:
        if ev.get("tipo") != "liquidacao":
            continue
        ch = str(ev.get("chave") or "")
        if ch not in chaves:
            continue
        pagos[ch] += float(ev.get("valor_pago") or 0.0)
    return dict(pagos)


def _parse_venc(v) -> date | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if hasattr(v, "date"):
        return v.date()
    return pd.to_datetime(v, errors="coerce").date()


def montar_cohort(abertos_t0: dict[str, dict]) -> pd.DataFrame:
    rows = []
    for chave, pos in abertos_t0.items():
        venc = _parse_venc(pos.get("data_vencimento"))
        face = float(pos.get("valor_face") or 0.0)
        if face <= 0 or venc is None:
            continue
        if venc <= T0:
            continue  # já vencido na data base — não entra no fluxo A VENCER
        rows.append(
            {
                "chave": chave,
                "documento": pos.get("documento"),
                "sacado": str(pos.get("sacado") or ""),
                "cedente": str(pos.get("cedente") or ""),
                "data_vencimento": venc,
                "face_t0": face,
            }
        )
    return pd.DataFrame(rows)


def analisar(
    *,
    t0: date = T0,
    t1: date = T1,
    redutor: float = REDUTOR_ATUAL,
) -> dict:
    global T0, T1
    T0, T1 = t0, t1

    df0 = carregar_carteira_movimentacoes(t0)
    abertos_t0 = _abertos_na_data(t0)
    abertos_t1 = _abertos_na_data(t1)
    pd_map = _pd_map(df0, redutor)

    cohort = montar_cohort(abertos_t0)
    if cohort.empty:
        return {"erro": "cohort vazio"}

    chaves = set(cohort["chave"])
    pagos = _pagamentos_pos_t0(chaves)

    cohort["pd_pct"] = cohort["sacado"].map(pd_map).fillna(0.0)
    cohort["esperado"] = cohort["face_t0"] * (1.0 - cohort["pd_pct"] / 100.0)
    cohort["pago"] = cohort["chave"].map(pagos).fillna(0.0)
    cohort["face_t1"] = cohort["chave"].map(
        lambda c: float(abertos_t1.get(c, {}).get("valor_face") or 0.0)
    )
    cohort["ainda_aberto"] = cohort["face_t1"] > 0.01
    cohort["venceu_no_periodo"] = cohort["data_vencimento"] <= t1

    # Caixa recebido = liquidações; títulos ainda abertos não contam como recebido
    cohort["realizado_caixa"] = cohort["pago"]

    # Para títulos que já venceram no período: perda implícita = face - pago - saldo remanescente
    cohort["perda_face"] = 0.0
    mask_venc = cohort["venceu_no_periodo"]
    cohort.loc[mask_venc, "perda_face"] = (
        cohort.loc[mask_venc, "face_t0"]
        - cohort.loc[mask_venc, "pago"]
        - cohort.loc[mask_venc, "face_t1"]
    ).clip(lower=0.0)

    # PD implícita observada (só títulos com vencimento no período — desfecho parcial)
    obs = cohort.loc[mask_venc].copy()
    obs["pd_implicita_pct"] = (
        (obs["face_t0"] - obs["pago"] - obs["face_t1"]) / obs["face_t0"] * 100.0
    ).clip(lower=0.0, upper=100.0)

    # Agregados
    total_face = float(cohort["face_t0"].sum())
    total_esperado = float(cohort["esperado"].sum())
    total_pago = float(cohort["pago"].sum())

    vencidos_periodo = cohort.loc[mask_venc]
    face_vencida = float(vencidos_periodo["face_t0"].sum())
    esperado_vencida = float(vencidos_periodo["esperado"].sum())
    pago_vencida = float(vencidos_periodo["pago"].sum())
    perda_vencida = float(vencidos_periodo["perda_face"].sum())

    # Por faixa de PD
    bins = [0, 1, 5, 10, 20, 50, 100.001]
    labels = ["0%", "0-5%", "5-10%", "10-20%", "20-50%", "50%+"]
    obs["faixa_pd"] = pd.cut(obs["pd_pct"], bins=bins, labels=labels, right=False)

    por_faixa = []
    for faixa in labels:
        sub = obs.loc[obs["faixa_pd"] == faixa]
        if sub.empty:
            continue
        f = float(sub["face_t0"].sum())
        por_faixa.append(
            {
                "faixa_pd_modelo": faixa,
                "face": round(f, 2),
                "pd_media_modelo_pct": round(float(sub["pd_pct"].mean()), 2),
                "pd_implicita_media_pct": round(
                    float((sub["face_t0"] * sub["pd_implicita_pct"]).sum() / f) if f else 0, 2
                ),
                "recovery_caixa_pct": round(float(sub["pago"].sum() / f * 100) if f else 0, 2),
                "titulos": len(sub),
            }
        )

    # Sacados: PD modelo vs perda observada (ponderado por face vencida no período)
    sac_agg = (
        obs.groupby("sacado")
        .agg(
            face=("face_t0", "sum"),
            pd_modelo=("pd_pct", "first"),
            pago=("pago", "sum"),
            face_restante=("face_t1", "sum"),
        )
        .reset_index()
    )
    sac_agg["pd_implicita"] = (
        (sac_agg["face"] - sac_agg["pago"] - sac_agg["face_restante"])
        / sac_agg["face"]
        * 100.0
    ).clip(lower=0.0)
    sac_agg = sac_agg.sort_values("face", ascending=False)

    # Calibrar redutor: qual multiplicador sobre taxa bruta (sem 0.8) minimiza erro?
    pd_bruta = _pd_map(df0, redutor=1.0)  # sem redutor 0.8 => _pd_por_sacado usa 0.8 internamente
    # Recalcular PD bruta manualmente
    status = df0["status"].astype(str).str.upper()
    atrasado = status.isin(["VENCIDO", "ATRASO"])
    if "dias_atraso_calc" not in df0.columns:
        df0 = df0.copy()
        df0["dias_atraso_calc"] = (pd.to_datetime(t0) - df0["data_vencimento"]).dt.days
    atrasado = atrasado | (df0["dias_atraso_calc"].fillna(0) > 0)
    tot = df0.groupby("sacado")["valor_face"].sum()
    atr = (
        df0.loc[atrasado].groupby("sacado")["valor_face"].sum().reindex(tot.index).fillna(0.0)
    )
    pd_bruta_map = {
        str(s): float(atr.get(s, 0) / ft * 100) if ft > 0 else 0.0
        for s, ft in tot.items()
    }

    obs2 = obs.copy()
    obs2["pd_bruta"] = obs2["sacado"].map(pd_bruta_map).fillna(0.0)
    obs2["pd_implicita_pct"] = (
        (obs2["face_t0"] - obs2["pago"] - obs2["face_t1"]) / obs2["face_t0"] * 100.0
    ).clip(lower=0.0, upper=100.0)

    # Regressão simples: pd_implicita ~ k * pd_bruta (por sacado agregado)
    sac_cal = (
        obs2.groupby("sacado")
        .apply(
            lambda g: pd.Series(
                {
                    "face": g["face_t0"].sum(),
                    "pd_bruta": g["pd_bruta"].iloc[0],
                    "pd_implicita": (
                        (g["face_t0"].sum() - g["pago"].sum() - g["face_t1"].sum())
                        / g["face_t0"].sum()
                        * 100
                    ),
                }
            ),
            include_groups=False,
        )
        .reset_index()
    )
    sac_cal = sac_cal[sac_cal["face"] > 1000]
    if len(sac_cal) >= 5:
        # k = sum(w * y * x) / sum(w * x^2) com peso face
        w = sac_cal["face"].values
        x = sac_cal["pd_bruta"].values
        y = sac_cal["pd_implicita"].values
        mask = x > 0.01
        if mask.sum() >= 3:
            k_opt = float((w[mask] * x[mask] * y[mask]).sum() / (w[mask] * x[mask] ** 2).sum())
        else:
            k_opt = None
    else:
        k_opt = None

    return {
        "periodo": {"t0": t0.isoformat(), "t1": t1.isoformat()},
        "redutor_testado": redutor,
        "cohort_a_vencer_t0": {
            "titulos": len(cohort),
            "face_total": round(total_face, 2),
            "receita_esperada_pd": round(total_esperado, 2),
            "caixa_liquidacoes": round(total_pago, 2),
            "gap_esperado_menos_caixa": round(total_esperado - total_pago, 2),
            "pct_gap_sobre_esperado": round(
                (total_esperado - total_pago) / total_esperado * 100 if total_esperado else 0, 2
            ),
        },
        "desfecho_vencimento_ate_t1": {
            "titulos": len(vencidos_periodo),
            "face": round(face_vencida, 2),
            "esperado_pd": round(esperado_vencida, 2),
            "caixa_recebido": round(pago_vencida, 2),
            "perda_face_remanescente": round(perda_vencida, 2),
            "recovery_caixa_pct": round(pago_vencida / face_vencida * 100 if face_vencida else 0, 2),
            "recovery_esperado_pct": round(
                esperado_vencida / face_vencida * 100 if face_vencida else 0, 2
            ),
            "pd_implicita_agregada_pct": round(
                (face_vencida - pago_vencida - float(vencidos_periodo["face_t1"].sum()))
                / face_vencida
                * 100
                if face_vencida
                else 0,
                2,
            ),
        },
        "por_faixa_pd": por_faixa,
        "top_sacados_gap": [
            {
                "sacado": r["sacado"][:60],
                "face_vencida": round(float(r["face"]), 2),
                "pd_modelo_pct": round(float(r["pd_modelo"]), 2),
                "pd_implicita_pct": round(float(r["pd_implicita"]), 2),
                "gap_pd": round(float(r["pd_implicita"] - r["pd_modelo"]), 2),
            }
            for _, r in sac_agg.head(15).iterrows()
        ],
        "calibracao_redutor": {
            "k_otimo_sobre_pd_bruta": round(k_opt, 3) if k_opt is not None else None,
            "interpretacao": (
                f"PD_modelo = pd_bruta × {REDUTOR_ATUAL}; "
                f"se k_otimo > {REDUTOR_ATUAL}, o redutor atual subestima a perda."
            ),
        },
        "sensibilidade_redutor": {},
    }


def main() -> None:
    print("=" * 72)
    print(f"ESTUDO PD — base {T0.strftime('%d/%m/%Y')} vs real até {T1.strftime('%d/%m/%Y')}")
    print("=" * 72)

    for red in (0.8, 1.0, 1.2, 1.5):
        r = analisar(redutor=red)
        des = r["desfecho_vencimento_ate_t1"]
        coh = r["cohort_a_vencer_t0"]
        print(f"\n--- Redutor {red} ---")
        print(
            f"  Cohort A VENCER (face {coh['face_total']:,.0f}): "
            f"esperado {coh['receita_esperada_pd']:,.0f} | "
            f"caixa {coh['caixa_liquidacoes']:,.0f} | "
            f"gap {coh['gap_esperado_menos_caixa']:+,.0f} "
            f"({coh['pct_gap_sobre_esperado']:+.1f}% sobre esperado)"
        )
        print(
            f"  Vencidos no período (face {des['face']:,.0f}): "
            f"recovery caixa {des['recovery_caixa_pct']:.1f}% | "
            f"esperado modelo {des['recovery_esperado_pct']:.1f}% | "
            f"PD implícita {des['pd_implicita_agregada_pct']:.1f}%"
        )

    base = analisar(redutor=REDUTOR_ATUAL)
    cal = base["calibracao_redutor"]
    print(f"\n--- Calibração ---")
    print(f"  k ótimo sobre PD bruta (sem redutor): {cal['k_otimo_sobre_pd_bruta']}")
    print(f"  {cal['interpretacao']}")

    print("\n--- Por faixa de PD (modelo 0,8) — títulos vencidos no período ---")
    for row in base["por_faixa_pd"]:
        print(
            f"  {row['faixa_pd_modelo']:>6} face={row['face']:>14,.0f} "
            f"PD modelo={row['pd_media_modelo_pct']:5.1f}% "
            f"PD implícita={row['pd_implicita_media_pct']:5.1f}% "
            f"recovery={row['recovery_caixa_pct']:5.1f}% "
            f"({row['titulos']} títulos)"
        )

    print("\n--- Top sacados: PD modelo vs implícita ---")
    for row in base["top_sacados_gap"]:
        print(
            f"  {row['sacado'][:50]:50} face={row['face_vencida']:>12,.0f} "
            f"PD mod={row['pd_modelo_pct']:5.1f}% impl={row['pd_implicita_pct']:5.1f}% "
            f"gap={row['gap_pd']:+5.1f}pp"
        )

    out = Path(__file__).with_name("estudo_pd_20260102_resultado.json")
    import json

    out.write_text(json.dumps(base, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nResultado salvo em {out}")


if __name__ == "__main__":
    main()
