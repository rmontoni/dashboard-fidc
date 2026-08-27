"""Agregações de vencimentos / posição / fluxo de caixa do passivo mezanino."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Any

from passivo_cadastro import listar_chamadas, listar_classes, listar_cotistas, obter_cotista
from passivo_calc import montar_todas_posicoes, posicao_to_dict


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


def _pd_por_sacado(df) -> dict[str, float]:
    """PD estimada = (face em atraso / face total do sacado) × 80%, como no Dashboard."""
    if df is None or df.empty or "sacado" not in df.columns:
        return {}
    status = df["status"].astype(str).str.upper()
    atrasado = status.isin(["VENCIDO", "ATRASO"])
    if "dias_atraso_calc" in df.columns:
        atrasado = atrasado | (df["dias_atraso_calc"].fillna(0) > 0)
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
            out[str(sac)] = float(atr.get(sac, 0.0)) / ft * 100.0 * 0.8
    return out


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


def montar_fluxo_passivo_caixa(data_base: str | None = None) -> dict[str, Any]:
    """Caixa mês a mês a partir da data base: real até a última liquidez, depois projetado.

    - Histórico: CC + aplicações observados (último dia de cada mês ≥ data base).
    - Projeção: a partir do dia seguinte à última liquidez — liquidações a vencer
      com haircut de PD − amortizações de cotas mezanino.
    """
    hoje = _parse_data_base(data_base) if data_base else date.today()
    ref, posicoes = _carregar_posicoes(hoje)

    liq_mapa = _mapa_liquidez_valores()
    dias_liq = sorted(liq_mapa)
    ultima_liq: date | None = date.fromisoformat(dias_liq[-1]) if dias_liq else None

    # --- trecho real (mês a mês da data base até a última liquidez) ---
    serie: list[dict[str, Any]] = []
    reais_por_mes: dict[str, tuple[str, float]] = {}
    for d_iso in dias_liq:
        d = date.fromisoformat(d_iso)
        if d < ref:
            continue
        if ultima_liq and d > ultima_liq:
            continue
        mes = d.strftime("%Y-%m")
        prev = reais_por_mes.get(mes)
        if prev is None or d_iso >= prev[0]:
            reais_por_mes[mes] = (d_iso, liq_mapa[d_iso])

    # ponto inicial na data base (último dia com liquidez ≤ ref; se a base
    # for anterior a qualquer liquidez, usa a primeira ≥ ref)
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

    mes_ref = ref.strftime("%Y-%m")
    # Fim do histórico real: última liquidez, mas não antes da data base
    if ultima_liq and ultima_liq >= ref:
        mes_ultima = ultima_liq.strftime("%Y-%m")
    else:
        mes_ultima = mes_ref

    def _label_ponto(mes: str, data_iso: str | None, tipo: str, ponto: str) -> str:
        if ponto == "inicial" and data_iso:
            d = date.fromisoformat(data_iso)
            return d.strftime("%d/%m")
        base = _label_mes(mes)
        if tipo == "projetado":
            return f"{base}*"
        return base

    # Garante o mês da data base com o valor na data base (não só o fim do mês)
    serie.append(
        {
            "mes": mes_ref,
            "mes_ano": ref.strftime("%d/%m"),
            "data": data_inicial_iso,
            "entradas_ativos": 0.0,
            "entradas_brutas": 0.0,
            "saidas_passivo": 0.0,
            "liquido": 0.0,
            "caixa": round(caixa_inicial, 2),
            "tipo": "real",
            "ponto": "inicial",
        }
    )

    for mes in _meses_entre(mes_ref, mes_ultima):
        if mes == mes_ref:
            item = reais_por_mes.get(mes)
            if (
                item
                and item[0] > data_inicial_iso
                and round(item[1], 2) != round(caixa_inicial, 2)
            ):
                serie.append(
                    {
                        "mes": mes,
                        "mes_ano": _label_ponto(mes, item[0], "real", "mes"),
                        "data": item[0],
                        "entradas_ativos": 0.0,
                        "entradas_brutas": 0.0,
                        "saidas_passivo": 0.0,
                        "liquido": 0.0,
                        "caixa": round(item[1], 2),
                        "tipo": "real",
                        "ponto": "mes",
                    }
                )
            continue
        item = reais_por_mes.get(mes)
        if not item:
            continue
        serie.append(
            {
                "mes": mes,
                "mes_ano": _label_ponto(mes, item[0], "real", "mes"),
                "data": item[0],
                "entradas_ativos": 0.0,
                "entradas_brutas": 0.0,
                "saidas_passivo": 0.0,
                "liquido": 0.0,
                "caixa": round(item[1], 2),
                "tipo": "real",
                "ponto": "mes",
            }
        )

    # --- projeção após o fim do histórico real ---
    # Projeta fluxos com vencimento depois da última liquidez (≥ data base).
    # Se não houver liquidez ≥ data base, corta na própria data base.
    if ultima_liq and ultima_liq >= ref:
        corte = ultima_liq
    else:
        corte = ref
    saidas: dict[str, float] = defaultdict(float)
    for p in posicoes:
        for parc in p.parcelas:
            if parc.liquidada:
                continue
            if parc.data_vencimento <= corte:
                continue
            mes = parc.data_vencimento.strftime("%Y-%m")
            saidas[mes] += parc.valor_na_liquidacao

    entradas: dict[str, float] = defaultdict(float)
    entradas_brutas: dict[str, float] = defaultdict(float)
    try:
        from carteira_movimentacoes import carregar_carteira_movimentacoes

        df = carregar_carteira_movimentacoes(ref.strftime("%d/%m/%Y"))
        if df is not None and not df.empty:
            pd_map = _pd_por_sacado(df)
            ativos = df[df["status"].astype(str).str.upper() == "A VENCER"].copy()
            for _, row in ativos.iterrows():
                d = _to_date(row.get("data_vencimento"))
                if d is None or d <= corte:
                    continue
                mes = d.strftime("%Y-%m")
                face = float(row.get("valor_face") or 0)
                if face <= 0:
                    continue
                pd_pct = float(pd_map.get(str(row.get("sacado") or ""), 0.0))
                fator = max(0.0, 1.0 - pd_pct / 100.0)
                entradas_brutas[mes] += face
                entradas[mes] += face * fator
    except Exception:  # noqa: BLE001
        pass

    meses_proj = sorted(set(saidas) | set(entradas))
    caixa = float(serie[-1]["caixa"]) if serie else caixa_inicial
    if meses_proj:
        for mes in _meses_entre(meses_proj[0], meses_proj[-1]):
            # não projetar meses que já têm ponto real (exceto se for o mês do corte
            # e ainda há fluxos após o corte — aí o ponto projetado é o fim do mês)
            ent = round(entradas.get(mes, 0.0), 2)
            ent_b = round(entradas_brutas.get(mes, 0.0), 2)
            sai = round(saidas.get(mes, 0.0), 2)
            if ent == 0 and sai == 0:
                continue
            liq = round(ent - sai, 2)
            caixa = round(caixa + liq, 2)
            serie.append(
                {
                    "mes": mes,
                    "mes_ano": _label_ponto(mes, None, "projetado", "mes"),
                    "data": None,
                    "entradas_ativos": ent,
                    "entradas_brutas": ent_b,
                    "saidas_passivo": sai,
                    "liquido": liq,
                    "caixa": caixa,
                    "tipo": "projetado",
                    "ponto": "mes",
                }
            )

    tot_ent = round(sum(p["entradas_ativos"] for p in serie if p["tipo"] == "projetado"), 2)
    tot_ent_b = round(sum(p.get("entradas_brutas") or 0 for p in serie if p["tipo"] == "projetado"), 2)
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
