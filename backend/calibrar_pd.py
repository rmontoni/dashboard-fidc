"""
Calibração do redutor PD e comparação com realizado.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

import pandas as pd

import pd_estimada as pe
from carteira_movimentacoes import (
    DATA_MINIMA,
    _aplicar_eventos_ate,
    _carregar_eventos,
    carregar_carteira_movimentacoes,
    carregar_estoque_base,
    reconstruir_eventos,
)

T0 = date(2026, 1, 2)
T1 = date(2026, 8, 25)


def _abertos_na_data(data_limite: date) -> dict[str, dict]:
    reconstruir_eventos()
    base = carregar_estoque_base()
    if data_limite == DATA_MINIMA:
        return dict(base)
    eventos = _carregar_eventos(desde=DATA_MINIMA, ate=data_limite)
    return _aplicar_eventos_ate(eventos, data_limite, base=base)


def _parse_venc(v) -> date | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if hasattr(v, "date"):
        return v.date()
    return pd.to_datetime(v, errors="coerce").date()


def _pagamentos(chaves: set[str]) -> dict[str, float]:
    eventos = _carregar_eventos(desde=T0 + timedelta(days=1), ate=T1)
    pagos: dict[str, float] = defaultdict(float)
    for ev in eventos:
        if ev.get("tipo") != "liquidacao":
            continue
        ch = str(ev.get("chave") or "")
        if ch in chaves:
            pagos[ch] += float(ev.get("valor_pago") or 0.0)
    return dict(pagos)


class _Ctx:
    cohort: pd.DataFrame
    pd_lookup: dict[tuple, float]


_CTX: _Ctx | None = None


def _carregar_ctx() -> _Ctx:
    global _CTX
    if _CTX is not None:
        return _CTX

    print("Carregando carteira T0/T1…", flush=True)
    df0 = carregar_carteira_movimentacoes(T0)
    ab0 = _abertos_na_data(T0)
    ab1 = _abertos_na_data(T1)

    consig, sacados, sac_venc, bruta = pe.preparar_base_pd(df0, T0)
    pd_full = pe.pd_por_titulo_com_base(df0, consig, sacados, sac_venc, bruta, pe.REDUTOR_PD)
    df0 = df0.copy()
    df0["_pd_ref"] = pd_full.values

    pd_lookup: dict[tuple, float] = {}
    for _, row in df0.iterrows():
        venc = _parse_venc(row.get("data_vencimento"))
        if venc is None:
            continue
        pd_lookup[(str(row.get("documento") or ""), str(row.get("sacado") or ""), venc)] = float(
            row["_pd_ref"]
        )

    docs_consig = pe._docs_cadastro_consignado()  # noqa: SLF001
    rows = []
    for chave, pos in ab0.items():
        venc = _parse_venc(pos.get("data_vencimento"))
        face = float(pos.get("valor_face") or 0.0)
        if face <= 0 or venc is None or venc <= T0:
            continue
        doc = str(pos.get("documento") or "")
        sac = str(pos.get("sacado") or "")
        ced = str(pos.get("cedente") or "")
        rows.append(
            {
                "chave": str(chave),
                "documento": doc,
                "sacado": sac,
                "cedente": ced,
                "data_vencimento": venc,
                "valor_face": face,
                "consig": doc in docs_consig or pe.e_consignado_cedente(ced),
                "sac_venc": sac in sac_venc,
                "pd_bruta": bruta.get(sac, 0.0),
            }
        )

    cohort = pd.DataFrame(rows)
    pagos = _pagamentos(set(cohort["chave"]))
    cohort["pago"] = cohort["chave"].map(pagos).fillna(0.0)
    cohort["face_t1"] = cohort["chave"].map(lambda c: float(ab1.get(c, {}).get("valor_face") or 0.0))
    cohort["venceu"] = cohort["data_vencimento"] <= T1
    cohort["liquidado"] = cohort["venceu"] & (cohort["face_t1"] < 0.01)

    _CTX = _Ctx()
    _CTX.cohort = cohort
    _CTX.pd_lookup = pd_lookup
    _CTX.consig = cohort["consig"].values  # type: ignore[attr-defined]
    _CTX.sac_venc = cohort["sac_venc"].values  # type: ignore[attr-defined]
    _CTX.pd_bruta = cohort["pd_bruta"].values  # type: ignore[attr-defined]
    return _CTX


def _pd_cohort(redutor: float) -> pd.Series:
    ctx = _carregar_ctx()
    c = ctx.cohort
    base = pd.Series(c["pd_bruta"].values * redutor).clip(upper=100.0)
    out = base.copy()
    consig = c["consig"].values
    sac_venc = c["sac_venc"].values
    for i in range(len(out)):
        if consig[i] and sac_venc[i]:
            out.iloc[i] = pe.PD_CONSIGNADO_VENCIDO
        elif consig[i]:
            out.iloc[i] = max(base.iloc[i], pe.PD_MIN_CONSIGNADO)
    return out.clip(lower=0.0, upper=100.0)


def metricas(redutor: float) -> dict:
    ctx = _carregar_ctx()
    c = ctx.cohort.copy()
    c["pd_pct"] = _pd_cohort(redutor).values
    c["esperado"] = c["valor_face"] * (1.0 - c["pd_pct"] / 100.0)

    def _res(sub: pd.DataFrame) -> dict:
        f = float(sub["valor_face"].sum())
        if f <= 0:
            return {"face": 0.0, "recovery_esperado_pct": 0.0, "recovery_caixa_pct": 0.0, "erro_abs_pct": 0.0}
        esp = float(sub["esperado"].sum())
        pg = float(sub["pago"].sum())
        return {
            "face": round(f, 2),
            "recovery_esperado_pct": round(esp / f * 100, 2),
            "recovery_caixa_pct": round(pg / f * 100, 2),
            "erro_abs_pct": round(abs(esp - pg) / f * 100, 2),
        }

    liq = c.loc[c["liquidado"]]
    venc = c.loc[c["venceu"]]
    return {
        "redutor": redutor,
        "todos_a_vencer": _res(c),
        "vencidos_periodo": _res(venc),
        "liquidados": _res(liq),
    }


def calibrar_redutor(lo: float = 0.5, hi: float = 5.0, step: float = 0.05) -> float:
    _carregar_ctx()
    melhor = lo
    menor_erro = float("inf")
    x = lo
    while x <= hi + 1e-9:
        err = metricas(x)["liquidados"]["erro_abs_pct"]
        if err < menor_erro:
            menor_erro = err
            melhor = round(x, 2)
        x = round(x + step, 4)
    return melhor


def main() -> None:
    print("=" * 72)
    print(f"Calibração PD — base {T0:%d/%m/%Y} vs real até {T1:%d/%m/%Y}")
    print(f"Regras: consignado min {pe.PD_MIN_CONSIGNADO}% | vencido {pe.PD_CONSIGNADO_VENCIDO}%")
    print("=" * 72, flush=True)

    opt = calibrar_redutor()
    print(f"\nRedutor ótimo (cohort liquidado): {opt}")

    for red in sorted({0.8, 1.0, 1.5, 2.0, opt, pe.REDUTOR_PD}):
        m = metricas(red)
        liq = m["liquidados"]
        venc = m["vencidos_periodo"]
        tag = " (otimo)" if red == opt else (" (modulo)" if red == pe.REDUTOR_PD else "")
        print(
            f"\nredutor={red:.2f}{tag}"
            f"\n  Liquidados: face R$ {liq['face']:,.0f} | "
            f"esperado {liq['recovery_esperado_pct']:.1f}% | caixa {liq['recovery_caixa_pct']:.1f}% | "
            f"erro {liq['erro_abs_pct']:.1f}pp"
            f"\n  Vencidos: esperado {venc['recovery_esperado_pct']:.1f}% | caixa {venc['recovery_caixa_pct']:.1f}%"
        )

    print(f"\n>>> Atualizar REDUTOR_PD em pd_estimada.py para {opt}")


if __name__ == "__main__":
    main()
