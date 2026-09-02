"""Atualiza carteira_mov_diario.json de forma incremental.

Política: dias conciliados são imutáveis; o motor só avança a partir do
primeiro dia útil após a última data conciliada, usando snapshot de posição
e eventos novos (sem replay diário desde DATA_MINIMA).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import date, datetime, timezone

from dotenv import load_dotenv

from calendario import dia_util_seguinte
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
    carregar_estado_conciliado,
    carregar_estoque_base,
    datas_util_serie_ate,
    gravar_estado_conciliado,
    mapa_dc_bdr_diario,
    reconstruir_estado_ate,
    saltos_prazo_atual_do_dia,
    ultima_data_conciliada_serie,
)
from marcacao_carteira import atualizar_marcacao

load_dotenv()

TOLERANCIA_DC_ABS = 500.0


def _linha_com_conciliacao(
    d: date,
    d_iso: str,
    marcado: dict,
    *,
    serie: dict[str, dict],
) -> dict[str, float]:
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
        except Exception:  # noqa: BLE001
            idsf = None
        if idsf and not idsf["dc_bruto_idsf"]:
            idsf = None
    if not idsf:
        return row

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
        registrar_saltos_prazo_atual(d_iso, list(salto_meta.get("titulos") or []))
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
    return row


def atualizar_desde(
    *,
    progresso: Callable[[str, dict[str, float]], None] | None = None,
) -> dict:
    """Estende a série após a última data conciliada (dias conciliados intactos)."""
    t0 = time.perf_counter()
    serie = dict(mapa_dc_bdr_diario())
    ultima_conc = ultima_data_conciliada_serie()

    if ultima_conc is not None:
        inicio_escrita = dia_util_seguinte(ultima_conc)
        par = carregar_estado_conciliado()
        if par is not None and par[0] == ultima_conc:
            estado = {k: dict(v) for k, v in par[1].items()}
        else:
            print(
                f"Snapshot ausente — bootstrap pontual até {ultima_conc.isoformat()}…",
                flush=True,
            )
            estado = reconstruir_estado_ate(ultima_conc)
            gravar_estado_conciliado(ultima_conc, estado)
        eventos = _carregar_eventos(desde=ultima_conc)
        modo = "incremental_pos_conciliada"
    elif serie:
        inicio_escrita = DATA_MINIMA
        estado = carregar_estoque_base()
        eventos = _carregar_eventos(desde=DATA_MINIMA)
        modo = "serie_sem_conciliada"
    else:
        raise RuntimeError(
            "Série vazia — rode reconstruir_serie_diaria antes do incremental."
        )

    datas_processar = [
        d_iso
        for d_iso in datas_util_serie_ate()
        if (_parse_data_campo(d_iso) or DATA_MINIMA) >= inicio_escrita
    ]
    ev_idx = 0
    dias_novos = 0

    for d_iso in datas_processar:
        d = _parse_data_campo(d_iso)
        assert d is not None

        if ultima_conc is not None and d <= ultima_conc:
            continue

        inicio = ev_idx
        while ev_idx < len(eventos) and str(eventos[ev_idx].get("data") or "") <= d_iso:
            ev_idx += 1
        if ev_idx > inicio:
            estado = _aplicar_eventos_ate(eventos[inicio:ev_idx], d, base=estado)
        _aplicar_repactuacoes(estado, d)

        if d == DATA_MINIMA:
            marcado = estado
        else:
            snapshot = {k: dict(v) for k, v in estado.items()}
            anexar_prazo_atual_do_dia(snapshot, d)
            marcado = atualizar_marcacao(
                snapshot, data_ref=DATA_MINIMA, data_alvo=d
            )

        row = _linha_com_conciliacao(d, d_iso, marcado, serie=serie)
        serie[d_iso] = row
        dias_novos += 1

        if bool(row.get("conciliada")):
            gravar_estado_conciliado(d, marcado)

        if progresso is not None:
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
        "dias_novos": dias_novos,
        "modo": modo,
        "ultima_conciliada": ultima_conc.isoformat() if ultima_conc else None,
        "inicio_escrita": inicio_escrita.isoformat(),
        "por_dia": serie,
    }
    DIARIO_PATH.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload


if __name__ == "__main__":
    out = atualizar_desde()
    print(
        f"ok modo={out.get('modo')} dias={out['dias']} "
        f"novos={out.get('dias_novos')} → {DIARIO_PATH}"
    )
