"""Atualiza carteira_mov_diario.json a partir de uma data (mantém dias anteriores)."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone

from dotenv import load_dotenv

from calendario import e_dia_util
from carteira_movimentacoes import (
    DATA_MINIMA,
    DIARIO_PATH,
    _aplicar_eventos_ate,
    _aplicar_repactuacoes,
    _carregar_eventos,
    _idsf_do_dia,
    _parse_data_campo,
    _totais_motor,
    anexar_prazo_atual_do_dia,
    carregar_estoque_base,
    mapa_dc_bdr_diario,
    saltos_prazo_atual_do_dia,
)
from db import mapa_liquidez_diario
from marcacao_carteira import atualizar_marcacao

load_dotenv()

TOLERANCIA_DC_ABS = 500.0


def atualizar_desde(
    desde: date,
    *,
    progresso: Callable[[str, dict[str, float]], None] | None = None,
) -> dict:
    t0 = time.perf_counter()
    serie = dict(mapa_dc_bdr_diario())
    eventos = _carregar_eventos(desde=DATA_MINIMA)
    datas_alvo = []
    for d_iso in sorted(mapa_liquidez_diario()):
        d = _parse_data_campo(d_iso)
        if d is None or not e_dia_util(d) or d < DATA_MINIMA:
            continue
        datas_alvo.append(d_iso)

    estado = carregar_estoque_base()
    ev_idx = 0
    desde_iso = desde.isoformat()

    for d_iso in datas_alvo:
        d = _parse_data_campo(d_iso)
        assert d is not None
        inicio = ev_idx
        while ev_idx < len(eventos) and str(eventos[ev_idx].get("data") or "") <= d_iso:
            ev_idx += 1
        if ev_idx > inicio:
            estado = _aplicar_eventos_ate(eventos[inicio:ev_idx], d, base=estado)
        _aplicar_repactuacoes(estado, d)

        if d_iso < desde_iso:
            # Só avança o estado; mantém linha antiga da série.
            continue

        if d == DATA_MINIMA:
            marcado = estado
        else:
            snapshot = {k: dict(v) for k, v in estado.items()}
            anexar_prazo_atual_do_dia(snapshot, d)
            marcado = atualizar_marcacao(
                snapshot, data_ref=DATA_MINIMA, data_alvo=d
            )
        row = _totais_motor(marcado)

        prev = serie.get(d_iso) or {}
        idsf = None
        if float(prev.get("dc_bruto_idsf") or 0):
            idsf = {
                k: float(prev.get(k) or 0)
                for k in ("dc_bruto_idsf", "pdd_idsf", "dc_liquido_idsf")
            }
        else:
            try:
                idsf = _idsf_do_dia(d)
            except Exception:
                idsf = None
            if idsf and not idsf["dc_bruto_idsf"]:
                idsf = None
        if idsf:
            delta_vp = round(row["vp"] - idsf["dc_bruto_idsf"], 2)
            delta_pdd = round(row["pdd"] - idsf["pdd_idsf"], 2)
            row.update(idsf)
            row["delta_vp"] = delta_vp
            row["delta_pdd"] = delta_pdd
            from excecoes_bdr import (
                calcular_efeito_residuos,
                calcular_efeito_salto_prazo,
                caminho_estoque_bdr,
                combinar_efeitos,
                dentro_tolerancia,
                registrar_saltos_prazo_atual,
            )

            salto_meta = saltos_prazo_atual_do_dia(marcado)
            if salto_meta:
                registrar_saltos_prazo_atual(
                    d_iso, list(salto_meta.get("titulos") or [])
                )
            bdr_csv = caminho_estoque_bdr(d)
            efeito_res = (
                calcular_efeito_residuos(bdr_csv, marcado)
                if bdr_csv is not None
                else {"ativo": False}
            )
            efeito_salto = calcular_efeito_salto_prazo(
                marcado,
                data_ref=d,
                delta_vp_bruto=delta_vp,
                tol=TOLERANCIA_DC_ABS,
            )
            efeito = combinar_efeitos(efeito_res, efeito_salto)
            ok, dv_l, dp_l = dentro_tolerancia(
                delta_vp, delta_pdd, tol=TOLERANCIA_DC_ABS, efeito=efeito
            )
            row["delta_vp_limpo"] = dv_l
            row["delta_pdd_limpo"] = dp_l
            row["excecao_residuos"] = float(bool(efeito_res.get("ativo")))
            row["excecao_salto_prazo"] = float(bool(efeito_salto.get("ativo")))
            row["conciliada"] = float(ok)
            if salto_meta:
                row["salto_prazo_n"] = float(salto_meta.get("n") or 0)
        serie[d_iso] = row
        if progresso is not None and d_iso >= desde_iso:
            progresso(d_iso, row)
        marca = "ok " if row.get("conciliada") else "DIV"
        print(
            f"[{time.perf_counter() - t0:>5.0f}s] {d_iso} {marca} "
            f"dVP={row.get('delta_vp', 0):>10,.2f}",
            flush=True,
        )

    payload = {
        "atualizado_em": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "dias": len(serie),
        "por_dia": serie,
    }
    DIARIO_PATH.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", default="2026-08-04")
    args = ap.parse_args()
    y, m, d = map(int, args.desde.split("-"))
    out = atualizar_desde(date(y, m, d))
    print(f"ok dias={out['dias']} → {DIARIO_PATH}")
