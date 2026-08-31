"""Agregações de vencimentos / posição / fluxo de caixa do passivo mezanino."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from calendario import e_dia_util
from passivo_cadastro import listar_chamadas, listar_classes, listar_cotistas, obter_cotista
from passivo_calc import (
    _classe_from_row,
    ancoras_por_chamada,
    carregar_fatorador,
    extrato_chamada_dia,
    montar_todas_posicoes,
    posicao_to_dict,
    preparar_ctx_extrato,
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


def _carregar_posicoes(hoje: date | None = None):
    classes = listar_classes(apenas_ativos=True)
    cotistas = listar_cotistas()
    chamadas = listar_chamadas()
    if not classes or not chamadas:
        return hoje or date.today(), []
    return montar_todas_posicoes(classes, cotistas, chamadas, hoje=hoje)


def montar_vencimentos(data_base: str | None = None) -> dict[str, Any]:
    hoje = _parse_data_base(data_base) if data_base else date.today()
    ref, posicoes = _carregar_posicoes(hoje)

    total_aplicado = sum(p.valor_nominal for p in posicoes)
    total_vp = sum(p.valor_presente_remanescente for p in posicoes)
    cotistas_ids = {p.cotista_id for p in posicoes}
    parcelas_abertas = [
        parc
        for p in posicoes
        for parc in p.parcelas
        if not parc.liquidada
    ]
    proximo_data = None
    proximo_valor = None
    if parcelas_abertas:
        proximo_data = min(p.data_vencimento for p in parcelas_abertas)
        proximo_valor = round(
            sum(
                p.valor_na_liquidacao
                for p in parcelas_abertas
                if p.data_vencimento == proximo_data
            ),
            2,
        )

    por_classe: dict[int, dict[str, Any]] = {}
    for p in posicoes:
        cid = p.classe.id
        if cid not in por_classe:
            por_classe[cid] = {
                "classe_id": cid,
                "classe": p.classe.nome,
                "percentual_cdi": p.classe.percentual_cdi,
                "meses_primeira": p.classe.meses_primeira,
                "meses_segunda": p.classe.meses_segunda,
                "aplicado": 0.0,
                "vp": 0.0,
                "n_cotistas": set(),
                "n_chamadas": 0,
                "n_parcelas_abertas": 0,
                "proximo": None,
            }
        row = por_classe[cid]
        row["aplicado"] += p.valor_nominal
        row["vp"] += p.valor_presente_remanescente
        row["n_cotistas"].add(p.cotista_id)
        row["n_chamadas"] += 1
        for parc in p.parcelas:
            if not parc.liquidada:
                row["n_parcelas_abertas"] += 1
                if row["proximo"] is None or parc.data_vencimento < row["proximo"]:
                    row["proximo"] = parc.data_vencimento

    classes_out = []
    for row in sorted(por_classe.values(), key=lambda r: r["classe_id"]):
        classes_out.append(
            {
                "classe_id": row["classe_id"],
                "classe": row["classe"],
                "percentual_cdi": row["percentual_cdi"],
                "meses_primeira": row["meses_primeira"],
                "meses_segunda": row["meses_segunda"],
                "aplicado": round(row["aplicado"], 2),
                "vp": round(row["vp"], 2),
                "n_cotistas": len(row["n_cotistas"]),
                "n_chamadas": row["n_chamadas"],
                "n_parcelas_abertas": row["n_parcelas_abertas"],
                "proximo": _br(row["proximo"]),
                "proximo_iso": row["proximo"].isoformat() if row["proximo"] else None,
            }
        )

    por_data: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "aplicado": 0.0,
            "vp_hoje": 0.0,
            "valor_liquidacao": 0.0,
            "n": 0,
            "n_liq": 0,
        }
    )
    for p in posicoes:
        for parc in p.parcelas:
            key = parc.data_vencimento.isoformat()
            bucket = por_data[key]
            bucket["data_iso"] = key
            bucket["data"] = _br(parc.data_vencimento)
            bucket["aplicado"] += parc.valor_original
            bucket["vp_hoje"] += parc.valor_presente
            bucket["valor_liquidacao"] += parc.valor_na_liquidacao
            bucket["n"] += 1
            if parc.liquidada:
                bucket["n_liq"] += 1

    datas_out = []
    for key in sorted(por_data.keys()):
        b = por_data[key]
        if b["n_liq"] >= b["n"]:
            status = "liquidado"
        elif b["n_liq"] > 0:
            status = "misto"
        else:
            status = "aberto"
        datas_out.append(
            {
                "data": b["data"],
                "data_iso": b["data_iso"],
                "status": status,
                "n": b["n"],
                "aplicado": round(b["aplicado"], 2),
                "vp_hoje": round(b["vp_hoje"], 2),
                "valor_liquidacao": round(b["valor_liquidacao"], 2),
            }
        )

    por_cotista: dict[int, dict[str, Any]] = {}
    for p in posicoes:
        if p.cotista_id not in por_cotista:
            por_cotista[p.cotista_id] = {
                "cotista_id": p.cotista_id,
                "nome": p.cotista_nome,
                "documento": p.cotista_documento,
                "aplicado": 0.0,
                "vp": 0.0,
                "proximo": None,
            }
        row = por_cotista[p.cotista_id]
        row["aplicado"] += p.valor_nominal
        row["vp"] += p.valor_presente_remanescente
        for parc in p.parcelas:
            if not parc.liquidada:
                if row["proximo"] is None or parc.data_vencimento < row["proximo"]:
                    row["proximo"] = parc.data_vencimento

    cotistas_out = []
    for row in sorted(por_cotista.values(), key=lambda r: r["nome"].upper()):
        cotistas_out.append(
            {
                "cotista_id": row["cotista_id"],
                "nome": row["nome"],
                "documento": row["documento"],
                "aplicado": round(row["aplicado"], 2),
                "vp": round(row["vp"], 2),
                "proximo": _br(row["proximo"]),
                "proximo_iso": row["proximo"].isoformat() if row["proximo"] else None,
            }
        )

    return {
        "data_ref": _br(ref),
        "data_ref_iso": ref.isoformat(),
        "kpis": {
            "aplicado": round(total_aplicado, 2),
            "vp": round(total_vp, 2),
            "n_cotistas": len(cotistas_ids),
            "n_parcelas_abertas": len(parcelas_abertas),
            "proximo": _br(proximo_data) if proximo_data else None,
            "proximo_valor": proximo_valor,
            "proximo_iso": proximo_data.isoformat() if proximo_data else None,
        },
        "por_classe": classes_out,
        "por_data": datas_out,
        "por_cotista": cotistas_out,
    }


def montar_posicao_cotista(id_cotista: int, data_base: str | None = None) -> dict[str, Any]:
    cotista = obter_cotista(id_cotista)
    if not cotista:
        raise ValueError(f"Cotista {id_cotista} não encontrado")
    hoje = _parse_data_base(data_base) if data_base else date.today()
    ref, posicoes = _carregar_posicoes(hoje)
    minhas = [p for p in posicoes if p.cotista_id == id_cotista]
    por_classe: dict[str, list[dict[str, Any]]] = defaultdict(list)
    aplicado = 0.0
    vp = 0.0
    for p in minhas:
        aplicado += p.valor_nominal
        vp += p.valor_presente_remanescente
        por_classe[p.classe.nome].append(posicao_to_dict(p))
    return {
        "data_ref": _br(ref),
        "data_ref_iso": ref.isoformat(),
        "cotista": cotista,
        "kpis": {
            "aplicado": round(aplicado, 2),
            "vp": round(vp, 2),
            "n_chamadas": len(minhas),
        },
        "por_classe": [
            {"classe": nome, "chamadas": chs}
            for nome, chs in sorted(por_classe.items())
        ],
    }


def _label_dia_extrato(d: date, ref: date) -> str:
    fmt = "%d/%m" if d.year == ref.year else "%d/%m/%y"
    return d.strftime(fmt)


def montar_extrato_cotista(
    cotista_id: int,
    data_base: str | None = None,
    *,
    classe_ids: list[int] | None = None,
) -> dict[str, Any]:
    """Evolução diária da posição do cotista (motor passivo / CDI)."""
    cotista = obter_cotista(cotista_id)
    if not cotista:
        raise ValueError(f"Cotista {cotista_id} não encontrado")

    fim = _parse_data_base(data_base) if data_base else date.today()
    classes = listar_classes(apenas_ativos=True)
    chamadas = listar_chamadas(cotista_id=cotista_id)

    ids_filtro = set(classe_ids or [])
    if ids_filtro:
        chamadas = [c for c in chamadas if int(c["classe_id"]) in ids_filtro]
        classes = [c for c in classes if int(c["id"]) in ids_filtro]

    if not chamadas:
        return {
            "data_ref": _br(fim),
            "data_ref_iso": fim.isoformat(),
            "cotista": cotista,
            "classes": [
                {"id": int(c["id"]), "nome": c["nome"]} for c in listar_classes(apenas_ativos=True)
            ],
            "classe_ids": sorted(ids_filtro) if ids_filtro else [],
            "inicio": None,
            "inicio_iso": None,
            "serie": [],
            "kpis": {"aplicado": 0.0, "vp": 0.0},
        }

    mapa_cls = {int(r["id"]): _classe_from_row(r) for r in classes}
    ancoras = ancoras_por_chamada(chamadas)
    fatorador = carregar_fatorador(fim)

    ctxs: list[dict[str, Any]] = []
    for ch in chamadas:
        classe = mapa_cls.get(int(ch["classe_id"]))
        if not classe:
            continue
        data_base_ch = ancoras[(int(ch["classe_id"]), int(ch["numero"]))]
        ctxs.append(preparar_ctx_extrato(ch, classe, data_base_ch, fatorador))

    if not ctxs:
        return {
            "data_ref": _br(fim),
            "data_ref_iso": fim.isoformat(),
            "cotista": cotista,
            "classes": [
                {"id": int(c["id"]), "nome": c["nome"]}
                for c in listar_classes(apenas_ativos=True)
            ],
            "classe_ids": sorted(ids_filtro) if ids_filtro else [],
            "inicio": None,
            "inicio_iso": None,
            "serie": [],
            "kpis": {"aplicado": 0.0, "vp": 0.0, "n_chamadas": 0},
        }

    inicio = min(c["data_aporte"] for c in ctxs)

    serie: list[dict[str, Any]] = []
    d = inicio
    while d <= fim:
        saldo = 0.0
        vp = 0.0
        aporte = 0.0
        amortizacao = 0.0
        juros = 0.0
        n_chamadas = 0
        for ctx in ctxs:
            dia = extrato_chamada_dia(ctx, fatorador, d)
            if d < ctx["data_aporte"]:
                continue
            n_chamadas += 1
            saldo += dia["saldo"]
            vp += dia["vp"]
            aporte += dia["aporte"]
            amortizacao += dia["amortizacao"]
            juros += dia["juros"]

        serie.append(
            {
                "data": d.isoformat(),
                "label": _label_dia_extrato(d, fim),
                "saldo": round(saldo, 2),
                "vp": round(vp, 2),
                "aporte": round(aporte, 2),
                "amortizacao": round(amortizacao, 2),
                "juros": round(juros, 2),
                "n_chamadas": n_chamadas,
                # compatibilidade com clientes antigos
                "aplicado": round(saldo, 2),
            }
        )
        d += timedelta(days=1)

    ultimo = serie[-1] if serie else {}
    total_aportado = round(sum(float(c["nominal"]) for c in ctxs), 2)
    return {
        "data_ref": _br(fim),
        "data_ref_iso": fim.isoformat(),
        "cotista": cotista,
        "classes": [
            {"id": int(c["id"]), "nome": c["nome"]}
            for c in listar_classes(apenas_ativos=True)
        ],
        "classe_ids": sorted(ids_filtro) if ids_filtro else [],
        "inicio": _br(inicio),
        "inicio_iso": inicio.isoformat(),
        "serie": serie,
        "kpis": {
            "saldo": ultimo.get("saldo", 0.0),
            "vp": ultimo.get("vp", 0.0),
            "total_aportado": total_aportado,
            "n_chamadas": ultimo.get("n_chamadas", 0),
            "aplicado": ultimo.get("saldo", 0.0),
        },
    }


def vp_por_id_carteira(data_base: str | None = None) -> dict[int, float]:
    """id_carteira IDSF → VP remanescente (motor passivo / Alpha)."""
    hoje = _parse_data_base(data_base) if data_base else date.today()
    _, posicoes = _carregar_posicoes(hoje)
    out: dict[int, float] = {}
    for p in posicoes:
        id_cart = p.classe.id_carteira
        if not id_cart:
            continue
        out[int(id_cart)] = out.get(int(id_cart), 0.0) + p.valor_presente_remanescente
    return {k: round(v, 2) for k, v in out.items()}


def liquidacao_por_id_carteira(data_base: str | None = None) -> dict[int, float]:
    """id_carteira IDSF → soma do valor_na_liquidacao das parcelas abertas."""
    hoje = _parse_data_base(data_base) if data_base else date.today()
    _, posicoes = _carregar_posicoes(hoje)
    out: dict[int, float] = {}
    for p in posicoes:
        id_cart = p.classe.id_carteira
        if not id_cart:
            continue
        for parc in p.parcelas:
            if parc.liquidada:
                continue
            out[int(id_cart)] = out.get(int(id_cart), 0.0) + parc.valor_na_liquidacao
    return {k: round(v, 2) for k, v in out.items()}


def contagem_cotistas_por_classe() -> dict[int, int]:
    """id_carteira IDSF → nº cotistas distintos (via classe)."""
    classes = {int(c["id"]): c for c in listar_classes()}
    chamadas = listar_chamadas()
    por_cls: dict[int, set[int]] = defaultdict(set)
    for ch in chamadas:
        por_cls[int(ch["classe_id"])].add(int(ch["cotista_id"]))
    out: dict[int, int] = {}
    for cid, docs in por_cls.items():
        meta = classes.get(cid) or {}
        id_cart = meta.get("id_carteira")
        if id_cart:
            out[int(id_cart)] = len(docs)
    return out


_MESES_ABREV = (
    "jan",
    "fev",
    "mar",
    "abr",
    "mai",
    "jun",
    "jul",
    "ago",
    "set",
    "out",
    "nov",
    "dez",
)


def _label_mes(ym: str) -> str:
    y, m = ym.split("-")
    return f"{_MESES_ABREV[int(m) - 1]}/{y[2:]}"


def _meses_entre(inicio: str, fim: str) -> list[str]:
    y, m = map(int, inicio.split("-"))
    ye, me = map(int, fim.split("-"))
    out: list[str] = []
    while (y, m) <= (ye, me):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


def _soma_liquidez(row: dict[str, Any] | None) -> float:
    if not row:
        return 0.0
    return round(
        float(row.get("total_caixa") or row.get("caixa") or 0)
        + float(row.get("total_aplicacoes") or row.get("aplicacoes") or 0),
        2,
    )


def _mapa_liquidez_valores() -> dict[str, float]:
    """data_iso → CC + aplicações."""
    try:
        from db import mapa_liquidez_diario

        mapa = mapa_liquidez_diario()
    except Exception:  # noqa: BLE001
        return {}
    out: dict[str, float] = {}
    for d_iso, row in (mapa or {}).items():
        try:
            val = _soma_liquidez(row)
        except Exception:  # noqa: BLE001
            continue
        if d_iso:
            out[str(d_iso)[:10]] = val
    return out


def _pd_por_sacado(df, data_base=None) -> dict[str, float]:
    """PD estimada (consignado + redutor calibrado) — ver pd_estimada.py."""
    from pd_estimada import pd_por_sacado

    if data_base is None and df is not None and not df.empty and "data_base" in df.columns:
        data_base = df["data_base"].iloc[0]
    return pd_por_sacado(df, data_base)


def _to_date(venc: Any) -> date | None:
    if venc is None:
        return None
    if hasattr(venc, "to_pydatetime"):
        venc = venc.to_pydatetime()
    if hasattr(venc, "date") and hasattr(venc, "hour"):
        return venc.date()
    if hasattr(venc, "isoformat") and not isinstance(venc, str):
        return venc  # date
    return None


def _dias_entre(inicio: date, fim: date) -> list[date]:
    out: list[date] = []
    d = inicio
    while d <= fim:
        out.append(d)
        d += timedelta(days=1)
    return out


def _label_dia(d: date, ref: date, projetado: bool = False) -> str:
    fmt = "%d/%m" if d.year == ref.year else "%d/%m/%y"
    base = d.strftime(fmt)
    return f"{base}*" if projetado else base


def montar_fluxo_passivo_caixa(data_base: str | None = None) -> dict[str, Any]:
    """Caixa dia a dia a partir da data base: real até a última liquidez, depois projetado.

    - Histórico: CC + aplicações observados em cada dia com liquidez ≥ data base.
    - Projeção: liquidações a vencer (face × (1−PD)) e amortizações de cotas na data
      de vencimento, acumulando o caixa dia a dia.
    """
    hoje = _parse_data_base(data_base) if data_base else date.today()
    ref, posicoes = _carregar_posicoes(hoje)

    liq_mapa = _mapa_liquidez_valores()
    dias_liq = sorted(liq_mapa)
    ultima_liq: date | None = date.fromisoformat(dias_liq[-1]) if dias_liq else None

    caixa_inicial = 0.0
    data_inicial_iso = ref.isoformat()
    if dias_liq:
        ate = [d for d in dias_liq if d <= ref.isoformat()]
        if ate:
            data_inicial_iso = ate[-1]
        else:
            apos = [d for d in dias_liq if d >= ref.isoformat()]
            data_inicial_iso = apos[0] if apos else dias_liq[-1]
        caixa_inicial = liq_mapa[data_inicial_iso]

    serie: list[dict[str, Any]] = []
    vistos: set[str] = set()

    def _append(
        d: date,
        caixa: float,
        *,
        tipo: str,
        ent: float = 0.0,
        ent_b: float = 0.0,
        sai: float = 0.0,
        ponto: str = "dia",
    ) -> None:
        iso = d.isoformat()
        if iso in vistos:
            return
        vistos.add(iso)
        liq = round(ent - sai, 2)
        serie.append(
            {
                "mes": d.strftime("%Y-%m"),
                "mes_ano": _label_dia(d, ref, projetado=(tipo == "projetado")),
                "data": iso,
                "entradas_ativos": round(ent, 2),
                "entradas_brutas": round(ent_b, 2),
                "saidas_passivo": round(sai, 2),
                "liquido": liq,
                "caixa": round(caixa, 2),
                "tipo": tipo,
                "ponto": ponto,
            }
        )

    # Ponto na data base (caixa observado)
    _append(
        ref,
        caixa_inicial,
        tipo="real",
        ponto="inicial",
    )

    # Histórico real: um ponto por dia com liquidez observada
    if ultima_liq and ultima_liq >= ref:
        fim_real = ultima_liq
    else:
        fim_real = ref
    for d_iso in dias_liq:
        d = date.fromisoformat(d_iso)
        if d < ref or d > fim_real or d_iso == ref.isoformat():
            continue
        _append(d, liq_mapa[d_iso], tipo="real")

    # Projeção a partir do dia seguinte ao fim do histórico real
    if ultima_liq and ultima_liq >= ref:
        corte = ultima_liq
    else:
        corte = ref

    saidas: dict[str, float] = defaultdict(float)
    for p in posicoes:
        for parc in p.parcelas:
            if parc.liquidada or parc.data_vencimento <= corte:
                continue
            saidas[parc.data_vencimento.isoformat()] += parc.valor_na_liquidacao

    entradas: dict[str, float] = defaultdict(float)
    entradas_brutas: dict[str, float] = defaultdict(float)
    try:
        from carteira_movimentacoes import carregar_carteira_movimentacoes

        df = carregar_carteira_movimentacoes(ref.strftime("%d/%m/%Y"))
        if df is not None and not df.empty:
            from pd_estimada import pd_por_titulo

            df = df.copy()
            df["_pd_pct"] = pd_por_titulo(df, ref).values
            ativos = df[df["status"].astype(str).str.upper() == "A VENCER"]
            for _, row in ativos.iterrows():
                d = _to_date(row.get("data_vencimento"))
                if d is None or d <= corte:
                    continue
                iso = d.isoformat()
                face = float(row.get("valor_face") or 0)
                if face <= 0:
                    continue
                pd_pct = float(row.get("_pd_pct") or 0.0)
                fator = max(0.0, 1.0 - pd_pct / 100.0)
                entradas_brutas[iso] += face
                entradas[iso] += face * fator
    except Exception:  # noqa: BLE001
        pass

    dias_fluxo = sorted(set(saidas) | set(entradas))
    if dias_fluxo:
        caixa = float(serie[-1]["caixa"]) if serie else caixa_inicial
        inicio_proj = corte + timedelta(days=1)
        fim_proj = date.fromisoformat(dias_fluxo[-1])
        for d in _dias_entre(inicio_proj, fim_proj):
            iso = d.isoformat()
            ent = float(entradas.get(iso, 0.0))
            ent_b = float(entradas_brutas.get(iso, 0.0))
            sai = float(saidas.get(iso, 0.0))
            caixa = round(caixa + ent - sai, 2)
            _append(
                d,
                caixa,
                tipo="projetado",
                ent=ent,
                ent_b=ent_b,
                sai=sai,
            )

    tot_ent = round(sum(p["entradas_ativos"] for p in serie if p["tipo"] == "projetado"), 2)
    tot_ent_b = round(
        sum(p.get("entradas_brutas") or 0 for p in serie if p["tipo"] == "projetado"), 2
    )
    tot_sai = round(sum(p["saidas_passivo"] for p in serie if p["tipo"] == "projetado"), 2)

    return {
        "data_ref": _br(ref),
        "data_ref_iso": ref.isoformat(),
        "ultima_liquidez": _br(ultima_liq) if ultima_liq else None,
        "ultima_liquidez_iso": ultima_liq.isoformat() if ultima_liq else None,
        "caixa_inicial": round(caixa_inicial, 2),
        "caixa_final": round(float(serie[-1]["caixa"]) if serie else caixa_inicial, 2),
        "serie": serie,
        "totais": {
            "entradas_ativos": tot_ent,
            "entradas_brutas": tot_ent_b,
            "saidas_passivo": tot_sai,
            "liquido": round(tot_ent - tot_sai, 2),
        },
    }
