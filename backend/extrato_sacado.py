"""Extrato diário de sacado — evolução VP/face/PDD pelo motor de carteira."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from calendario import e_dia_util
from marcacao_carteira import (
    fator_pdd,
    letra_pdd_por_dias,
    money_half_up,
    vp_por_prazo,
    _parse_data_simples,
)


def _parse_data_base(texto: str) -> date:
    t = texto.strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(t[:10], fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Data base inválida: {texto}")


def _br(d: date | None) -> str | None:
    return d.strftime("%d/%m/%Y") if d else None


def _label_dia(d: date, ref: date) -> str:
    fmt = "%d/%m" if d.year == ref.year else "%d/%m/%y"
    return d.strftime(fmt)


def _chave_sacado(pos: dict[str, Any]) -> str:
    return str(pos.get("sacado") or "").strip().upper()


def _match_sacado(pos: dict[str, Any], alvo: str) -> bool:
    nome = str(pos.get("sacado") or "").strip().upper()
    doc = str(pos.get("doc_sacado") or "").strip()
    alvo_u = alvo.strip().upper()
    alvo_doc = alvo.strip()
    return nome == alvo_u or (doc and doc == alvo_doc)


def _listar_sacados_live(data_base: str) -> dict[str, Any]:
    """Sacados com posição aberta na data base (recalcula pelo motor)."""
    from carteira_movimentacoes import carregar_carteira_movimentacoes

    ref = _parse_data_base(data_base)
    df = carregar_carteira_movimentacoes(ref)
    if df is None or df.empty:
        return {"data_ref": _br(ref), "data_ref_iso": ref.isoformat(), "sacados": []}

    agg: dict[str, dict[str, Any]] = {}
    for _, row in df.iterrows():
        nome = str(row.get("sacado") or "").strip()
        if not nome:
            continue
        chave = nome.upper()
        if chave not in agg:
            agg[chave] = {
                "sacado": nome,
                "doc_sacado": None,
                "face": 0.0,
                "vp": 0.0,
                "pdd": 0.0,
                "n_titulos": 0,
            }
        agg[chave]["face"] += float(row.get("valor_face") or 0)
        vp = row.get("vl_presente_adm")
        agg[chave]["vp"] += float(vp) if vp == vp else 0.0  # noqa: PLR0124
        pdd = row.get("vl_pdd")
        agg[chave]["pdd"] += float(pdd) if pdd == pdd else 0.0
        agg[chave]["n_titulos"] += 1

    sacados = []
    for item in agg.values():
        sacados.append(
            {
                "sacado": item["sacado"],
                "doc_sacado": item["doc_sacado"],
                "face": round(item["face"], 2),
                "vp": round(item["vp"], 2),
                "pdd": round(item["pdd"], 2),
                "n_titulos": item["n_titulos"],
            }
        )
    sacados.sort(key=lambda s: (-s["vp"], s["sacado"]))
    return {
        "data_ref": _br(ref),
        "data_ref_iso": ref.isoformat(),
        "sacados": sacados,
    }


def listar_sacados(data_base: str) -> dict[str, Any]:
    """Sacados com posição aberta na data base (motor)."""
    return _listar_sacados_live(data_base)


def _vp_posicao(
    pos: dict[str, Any],
    data_alvo: date,
    *,
    acumular: bool,
) -> float:
    face = float(pos.get("valor_face") or 0)
    compra = float(pos.get("valor_descontado") or 0)
    venc = _parse_data_simples(pos.get("data_vencimento"))
    data_aq = _parse_data_simples(pos.get("data_aquisicao"))
    if face <= 0:
        return 0.0
    if data_aq is not None and data_alvo <= data_aq:
        return money_half_up(compra if compra > 0 else face)
    prazo_raw = pos.get("prazo")
    try:
        prazo = float(prazo_raw) if prazo_raw not in (None, "", 0, 0.0) else None
    except (TypeError, ValueError):
        prazo = None
    if prazo is not None and prazo > 0 and compra > 0:
        return vp_por_prazo(
            face,
            compra,
            venc,
            data_alvo,
            prazo,
            acumular_juros_pos_venc=acumular,
        )
    vp_ref = pos.get("vl_presente_adm")
    if vp_ref not in (None, 0, 0.0):
        return money_half_up(float(vp_ref))
    return money_half_up(compra if compra > 0 else face)


def _marcar_subset_sacado(
    subset: dict[str, dict[str, Any]],
    data_alvo: date,
    *,
    acumular: bool,
) -> dict[str, dict[str, Any]]:
    if not subset:
        return {}
    max_atraso = 0
    for pos in subset.values():
        venc = _parse_data_simples(pos.get("data_vencimento"))
        if venc is not None:
            max_atraso = max(max_atraso, (data_alvo - venc).days)
    faixa = letra_pdd_por_dias(max_atraso)
    fat = fator_pdd(faixa)
    out: dict[str, dict[str, Any]] = {}
    for chave, pos in subset.items():
        p = dict(pos)
        vp = _vp_posicao(p, data_alvo, acumular=acumular)
        p["vl_presente_adm"] = vp
        p["fx_pdd"] = faixa
        p["vl_pdd"] = money_half_up(vp * fat)
        out[chave] = p
    return out


def _totais_sacado_marcado(marcado: dict[str, dict[str, Any]]) -> dict[str, float]:
    face = vp = pdd = 0.0
    n = len(marcado)
    for pos in marcado.values():
        face += float(pos.get("valor_face") or 0)
        vp += float(pos.get("vl_presente_adm") or 0)
        pdd += float(pos.get("vl_pdd") or 0)
    return {
        "face": round(face, 2),
        "vp": round(vp, 2),
        "pdd": round(pdd, 2),
        "n_titulos": n,
    }


def _filtrar_sacado(estado: dict[str, dict[str, Any]], alvo: str) -> dict[str, dict[str, Any]]:
    return {k: dict(v) for k, v in estado.items() if _match_sacado(v, alvo)}


def _primeira_data_sacado(eventos: list[dict[str, Any]], alvo: str) -> date | None:
    from carteira_movimentacoes import DATA_MINIMA, _parse_data_campo, carregar_estoque_base

    alvo_u = alvo.strip().upper()
    for pos in carregar_estoque_base().values():
        if _chave_sacado(pos) == alvo_u:
            aq = _parse_data_campo(pos.get("data_aquisicao"))
            if aq and aq >= DATA_MINIMA:
                return aq
    for ev in eventos:
        if str(ev.get("tipo") or "").upper() != "AQUISICAO":
            continue
        sac = str(ev.get("sacado") or "").strip().upper()
        if sac != alvo_u:
            continue
        d = _parse_data_campo(ev.get("data"))
        if d:
            return d
    return None


def _match_sacado_evento(
    ev: dict[str, Any],
    sacado: str,
    estado_ref: dict[str, dict[str, Any]],
) -> bool:
    if _match_sacado(ev, sacado):
        return True
    chave = str(ev.get("chave") or "")
    pos = estado_ref.get(chave)
    return bool(pos and _match_sacado(pos, sacado))


def _movimentos_dia_sacado(
    eventos: list[dict[str, Any]],
    inicio: int,
    fim: int,
    sacado: str,
    estado_ref: dict[str, dict[str, Any]],
) -> tuple[float, float]:
    """Valor de aquisição (compra) e valor pago (liquidações) do sacado no dia."""
    aquisicao = liquidacao = 0.0
    for ev in eventos[inicio:fim]:
        tipo = str(ev.get("tipo") or "").lower()
        if tipo == "aquisicao":
            if _match_sacado(ev, sacado):
                compra = float(ev.get("valor_descontado") or 0)
                aquisicao += compra if compra > 0 else float(ev.get("valor_face") or 0)
        elif tipo == "liquidacao":
            if _match_sacado_evento(ev, sacado, estado_ref):
                liquidacao += float(ev.get("valor_pago") or 0)
    return round(aquisicao, 2), round(liquidacao, 2)


def _juros_dia_sacado(
    estado_inicio: dict[str, dict[str, Any]],
    sacado: str,
    d: date,
    d_prev: date | None,
    *,
    acumular: bool,
) -> float:
    """Juros contratuais do dia (VP D − VP D−1) sobre a carteira do sacado."""
    if d_prev is None:
        return 0.0
    subset = _filtrar_sacado(estado_inicio, sacado)
    if not subset:
        return 0.0
    vp_d = _totais_sacado_marcado(
        _marcar_subset_sacado(subset, d, acumular=acumular)
    )["vp"]
    vp_prev = _totais_sacado_marcado(
        _marcar_subset_sacado(subset, d_prev, acumular=acumular)
    )["vp"]
    return round(vp_d - vp_prev, 2)


def montar_extrato_sacado(
    sacado: str,
    data_base: str,
    *,
    modo: str = "motor",
) -> dict[str, Any]:
    """
    Evolução diária da posição do sacado até a data base.

    modo:
      - motor: sem acúmulo de juros após vencimento (padrão do motor)
      - juros_pos_venc: continua juros contratuais após vencimento
    """
    if not sacado.strip():
        raise ValueError("Sacado não informado")

    from extrato_sacado_cache import extrato_do_cache

    em_cache = extrato_do_cache(sacado, data_base, modo=modo)
    if em_cache is not None:
        return em_cache

    resultado = _montar_extrato_sacado_live(sacado, data_base, modo=modo)
    try:
        from extrato_sacado_cache import gravar_extrato_modo

        gravar_extrato_modo(sacado, data_base, modo, resultado)
    except OSError:
        pass
    return resultado


def _montar_extrato_sacado_live(
    sacado: str,
    data_base: str,
    *,
    modo: str = "motor",
) -> dict[str, Any]:
    acumular = modo in ("juros_pos_venc", "juros-pos-venc", "2")
    fim = _parse_data_base(data_base)

    from carteira_movimentacoes import (
        DATA_MINIMA,
        _aplicar_eventos_ate,
        _aplicar_repactuacoes,
        _carregar_eventos,
        carregar_estoque_base,
    )

    eventos = _carregar_eventos(desde=DATA_MINIMA)
    inicio = _primeira_data_sacado(eventos, sacado) or DATA_MINIMA
    if inicio > fim:
        inicio = fim

    estado = carregar_estoque_base()
    ev_idx = 0
    serie: list[dict[str, Any]] = []
    d_prev_util: date | None = None

    d = inicio
    while d <= fim:
        if not e_dia_util(d):
            d += timedelta(days=1)
            continue
        d_iso = d.isoformat()
        estado_inicio = {k: dict(v) for k, v in estado.items()}
        inicio_ev = ev_idx
        while ev_idx < len(eventos) and str(eventos[ev_idx].get("data") or "") <= d_iso:
            ev_idx += 1

        aquisicao, liquidacao = _movimentos_dia_sacado(
            eventos, inicio_ev, ev_idx, sacado, estado_inicio
        )
        juros = _juros_dia_sacado(
            estado_inicio, sacado, d, d_prev_util, acumular=acumular
        )

        if ev_idx > inicio_ev:
            estado = _aplicar_eventos_ate(eventos[inicio_ev:ev_idx], d, base=estado)
        _aplicar_repactuacoes(estado, d)

        subset = _filtrar_sacado(estado, sacado)
        marcado = _marcar_subset_sacado(subset, d, acumular=acumular)
        tot = _totais_sacado_marcado(marcado)
        if tot["n_titulos"] > 0 or serie:
            serie.append(
                {
                    "data": d_iso,
                    "label": _label_dia(d, fim),
                    "aquisicao": aquisicao,
                    "face": tot["face"],
                    "juros": juros,
                    "liquidacao": liquidacao,
                    "vp": tot["vp"],
                    "pdd": tot["pdd"],
                }
            )
        d_prev_util = d
        d += timedelta(days=1)

    ultimo = (
        serie[-1]
        if serie
        else {
            "face": 0.0,
            "vp": 0.0,
            "pdd": 0.0,
            "aquisicao": 0.0,
            "juros": 0.0,
            "liquidacao": 0.0,
        }
    )
    return {
        "data_ref": _br(fim),
        "data_ref_iso": fim.isoformat(),
        "sacado": sacado.strip(),
        "modo": "juros_pos_venc" if acumular else "motor",
        "modo_label": (
            "Juros após vencimento"
            if acumular
            else "Sem juros após vencimento"
        ),
        "inicio": _br(inicio),
        "inicio_iso": inicio.isoformat(),
        "serie": serie,
        "kpis": {
            "face": ultimo["face"],
            "vp": ultimo["vp"],
            "pdd": ultimo["pdd"],
            "aquisicao": ultimo.get("aquisicao", 0.0),
            "juros": ultimo.get("juros", 0.0),
            "liquidacao": ultimo.get("liquidacao", 0.0),
        },
    }
