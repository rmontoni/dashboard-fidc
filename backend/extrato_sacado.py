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


def _normalizar_tipo_recebivel(tipo: object) -> str:
    import unicodedata

    texto = str(tipo or "")
    return (
        unicodedata.normalize("NFKD", texto)
        .encode("ascii", "ignore")
        .decode("ascii")
        .upper()
        .strip()
    )


def _eh_confissao_divida(pos: dict[str, Any]) -> bool:
    tipo = _normalizar_tipo_recebivel(pos.get("tipo_recebivel"))
    return "CONFISSAO DE DIVIDA" in tipo


def _sacado_so_confissao(marcado: dict[str, dict[str, Any]]) -> bool:
    if not marcado:
        return False
    return all(_eh_confissao_divida(pos) for pos in marcado.values())


def _sacado_em_atraso(
    marcado: dict[str, dict[str, Any]],
    data_alvo: date,
) -> bool:
    for pos in marcado.values():
        venc = _parse_data_simples(pos.get("data_vencimento"))
        if venc is not None and data_alvo > venc:
            return True
    return False


def _totais_sacado_marcado(
    marcado: dict[str, dict[str, Any]],
    data_alvo: date | None = None,
    *,
    acumular: bool = False,
) -> dict[str, float]:
    face = vp = pdd = vencido = 0.0
    n = len(marcado)
    em_atraso = False
    so_confissao = False
    if data_alvo is not None:
        em_atraso = _sacado_em_atraso(marcado, data_alvo)
        so_confissao = _sacado_so_confissao(marcado)
    contagion = em_atraso and so_confissao
    for pos in marcado.values():
        face += float(pos.get("valor_face") or 0)
        vp += float(pos.get("vl_presente_adm") or 0)
        pdd += float(pos.get("vl_pdd") or 0)
        if data_alvo is not None:
            vencido += _vencido_posicao(
                pos,
                data_alvo,
                acumular=acumular,
                confissao_contagion=contagion,
            )
    return {
        "face": round(face, 2),
        "vp": round(vp, 2),
        "vencido": round(vencido, 2),
        "pdd": round(pdd, 2),
        "n_titulos": n,
    }


def _vencido_posicao(
    pos: dict[str, Any],
    data_alvo: date,
    *,
    acumular: bool,
    confissao_contagion: bool = False,
) -> float:
    """Parcela vencida: face (sem juros pós-venc) ou VP (com juros pós-venc).

    Confissão de dívida (sacado 100% confissão): se há qualquer parcela em atraso,
    todo o saldo aberto entra como vencido (aceleração do saldo renegociado).
    """
    venc = _parse_data_simples(pos.get("data_vencimento"))
    if confissao_contagion and _eh_confissao_divida(pos):
        if acumular:
            return money_half_up(float(pos.get("vl_presente_adm") or 0))
        return money_half_up(float(pos.get("valor_face") or 0))
    if venc is None or data_alvo <= venc:
        return 0.0
    if acumular:
        return money_half_up(float(pos.get("vl_presente_adm") or 0))
    return money_half_up(float(pos.get("valor_face") or 0))


def _estoque_inicial_sacado(alvo: str) -> dict[str, dict[str, Any]]:
    from carteira_movimentacoes import carregar_estoque_base

    return {
        k: dict(v)
        for k, v in carregar_estoque_base().items()
        if _match_sacado(v, alvo)
    }


def _eventos_do_sacado(
    eventos: list[dict[str, Any]],
    alvo: str,
    *,
    chaves_iniciais: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Replay só de aquisições/liquidações dos títulos do sacado."""
    chaves = set(chaves_iniciais or ())
    out: list[dict[str, Any]] = []
    for ev in eventos:
        chave = str(ev.get("chave") or "")
        if not chave:
            continue
        tipo = str(ev.get("tipo") or "").lower()
        if tipo == "aquisicao":
            if _match_sacado(ev, alvo):
                chaves.add(chave)
                out.append(ev)
        elif tipo == "liquidacao" and chave in chaves:
            out.append(ev)
    return out


def _primeira_data_sacado_filtrado(
    eventos_sacado: list[dict[str, Any]],
    estoque: dict[str, dict[str, Any]],
    alvo: str,
) -> date | None:
    from carteira_movimentacoes import DATA_MINIMA, _parse_data_campo

    datas: list[date] = []
    for pos in estoque.values():
        aq = _parse_data_campo(pos.get("data_aquisicao"))
        if aq and aq >= DATA_MINIMA:
            datas.append(aq)
    alvo_u = alvo.strip().upper()
    for ev in eventos_sacado:
        if str(ev.get("tipo") or "").lower() != "aquisicao":
            continue
        if str(ev.get("sacado") or "").strip().upper() != alvo_u:
            continue
        d = _parse_data_campo(ev.get("data"))
        if d:
            datas.append(d)
    return min(datas) if datas else None


def _juros_dia_subset(
    subset: dict[str, dict[str, Any]],
    d: date,
    d_prev: date | None,
    *,
    acumular: bool,
) -> float:
    """Juros contratuais (VP D − VP D−1) sobre posições já filtradas do sacado."""
    if d_prev is None or not subset:
        return 0.0
    vp_d = _totais_sacado_marcado(_marcar_subset_sacado(subset, d, acumular=acumular))["vp"]
    vp_prev = _totais_sacado_marcado(
        _marcar_subset_sacado(subset, d_prev, acumular=acumular)
    )["vp"]
    return round(vp_d - vp_prev, 2)


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
    alvo = sacado.strip()

    from carteira_movimentacoes import (
        DATA_MINIMA,
        _aplicar_eventos_ate,
        _aplicar_repactuacoes,
        _carregar_eventos,
    )

    estado = _estoque_inicial_sacado(alvo)
    chaves_iniciais = set(estado)
    todos_eventos = _carregar_eventos(desde=DATA_MINIMA)
    eventos = _eventos_do_sacado(todos_eventos, alvo, chaves_iniciais=chaves_iniciais)

    inicio = _primeira_data_sacado_filtrado(eventos, estado, alvo) or DATA_MINIMA
    if inicio > fim:
        inicio = fim

    ev_idx = 0
    serie: list[dict[str, Any]] = []
    d_prev_util: date | None = None

    # Aplica movimentos anteriores ao primeiro dia útil da série.
    d_loop = inicio
    while d_loop <= fim and not e_dia_util(d_loop):
        d_loop += timedelta(days=1)
    if d_loop <= fim and d_loop > inicio:
        limite_pre = d_loop - timedelta(days=1)
        while ev_idx < len(eventos) and str(eventos[ev_idx].get("data") or "") <= limite_pre.isoformat():
            ev_idx += 1
        if ev_idx > 0:
            estado = _aplicar_eventos_ate(eventos[:ev_idx], limite_pre, base=estado)
            _aplicar_repactuacoes(estado, limite_pre)

    d = d_loop if d_loop <= fim else inicio
    while d <= fim:
        if not e_dia_util(d):
            d += timedelta(days=1)
            continue
        d_iso = d.isoformat()
        inicio_ev = ev_idx
        while ev_idx < len(eventos) and str(eventos[ev_idx].get("data") or "") <= d_iso:
            ev_idx += 1

        aquisicao, liquidacao = _movimentos_dia_sacado(
            eventos, inicio_ev, ev_idx, alvo, estado
        )
        juros = _juros_dia_subset(estado, d, d_prev_util, acumular=acumular)

        if ev_idx > inicio_ev:
            estado = _aplicar_eventos_ate(eventos[inicio_ev:ev_idx], d, base=estado)
        _aplicar_repactuacoes(estado, d)

        marcado = _marcar_subset_sacado(estado, d, acumular=acumular)
        tot = _totais_sacado_marcado(marcado, d, acumular=acumular)
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
                    "vencido": tot["vencido"],
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
            "vencido": 0.0,
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
            "vencido": ultimo.get("vencido", 0.0),
            "pdd": ultimo["pdd"],
            "aquisicao": ultimo.get("aquisicao", 0.0),
            "juros": ultimo.get("juros", 0.0),
            "liquidacao": ultimo.get("liquidacao", 0.0),
        },
    }
