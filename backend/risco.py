from datetime import date
from decimal import ROUND_HALF_UP, Decimal

import pandas as pd

from credit_var import calcular_credit_var
from carteira_movimentacoes import carregar_carteira_movimentacoes
from db import carregar_liquidez_dia
from idsf_pl_pdd import buscar_posicoes_caixa_aplicacoes
from liquidacoes_taxas import calcular_taxas_baixa_recompra

TOLERANCIA_DC_ABS = 500.0  # R$ — resíduo de marcação aceito vs IDSF/BDR
TOLERANCIA_DC_PCT = 0.0001  # 0,01% do DC IDSF

CASAS_DINHEIRO = Decimal("0.01")
CASAS_TAXA_AA = 8
CASAS_TAXA_AM = 10


def _money(valor: float | int | Decimal | None) -> Decimal:
    """Arredonda dinheiro com HALF_UP (padrão comercial BR)."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return Decimal("0.00")
    return Decimal(str(valor)).quantize(CASAS_DINHEIRO, rounding=ROUND_HALF_UP)


def _money_float(valor: float | int | Decimal | None) -> float:
    return float(_money(valor))


def _sum_money(valores) -> float:
    total = sum((_money(v) for v in valores), start=Decimal("0.00"))
    return float(total.quantize(CASAS_DINHEIRO, rounding=ROUND_HALF_UP))


def _subordinacao_kpi(data_ref: date) -> float | None:
    try:
        from passivo import calcular_subordinacao_para_data

        return calcular_subordinacao_para_data(data_ref)
    except Exception:  # noqa: BLE001
        return None


def _posicoes_from_row(row: dict) -> dict:
    detalhes = row.get("detalhes") or {}
    if isinstance(detalhes, str):
        import json

        try:
            detalhes = json.loads(detalhes)
        except Exception:  # noqa: BLE001
            detalhes = {}
    caixa = list(detalhes.get("caixa") or [])
    aplicacoes = list(detalhes.get("aplicacoes") or [])
    passivo_aporte = list(detalhes.get("passivo_aporte") or [])
    total_caixa = float(row.get("caixa") or 0)
    total_cpr = float(row.get("caixa_cpr") or 0)
    total_aplicacoes = float(row.get("aplicacoes") or 0)
    total_dc = float(row.get("dc_idsf") or 0)
    total_provisoes = float(detalhes.get("total_provisoes") or 0)
    total_passivo_aporte = float(detalhes.get("total_passivo_aporte") or 0)
    if total_provisoes == 0 and total_cpr != 0:
        # Cache antigo: usa CPR como proxy até recarregar liquidez
        total_provisoes = total_cpr
    # Cache antigo: dc_idsf podia incluir VALID — se não houver campo dedicado, 0
    return {
        "data_posicao": str(row.get("data_posicao") or "")[:10],
        "id_carteira": row.get("id_carteira"),
        "carteira": row.get("carteira"),
        "caixa": caixa,
        "aplicacoes": aplicacoes,
        "passivo_aporte": passivo_aporte,
        "total_caixa": total_caixa,
        "total_caixa_cpr": total_cpr,
        "total_provisoes": total_provisoes,
        "total_aplicacoes": total_aplicacoes,
        "total_dc_idsf": total_dc,
        "total_passivo_aporte": total_passivo_aporte,
        "total_liquidez": round(total_caixa + total_aplicacoes + total_provisoes, 2),
        "pl_estimado": float(
            row.get("pl_estimado")
            or (
                total_caixa
                + total_aplicacoes
                + total_provisoes
                + total_dc
                + total_passivo_aporte
            )
        ),
        "pl_carteira_idsf": float(row.get("pl_carteira") or 0),
        "fonte": row.get("fonte") or "fidc_liquidez_diaria",
    }


def carregar_liquidez_data(data_pos: date) -> dict:
    """Prefere histórico no BD; se faltar, consulta a IDSF ao vivo."""
    row = carregar_liquidez_dia(data_pos)
    if row:
        return _posicoes_from_row(row)
    return buscar_posicoes_caixa_aplicacoes(data_pos)


def pl_motor_do_dia(data_pos: date) -> dict:
    """PL do motor: DC (VP−PDD da série) + CC + aplicações + provisões + VALID.

    Não usa o PL consolidado da IDSF.
    """
    from carteira_movimentacoes import mapa_dc_bdr_diario

    serie = mapa_dc_bdr_diario().get(data_pos.isoformat()) or {}
    if not serie:
        return {"pl": None, "sem_serie": True}

    pos = carregar_liquidez_data(data_pos)
    dc = _money_float(float(serie.get("vp") or 0) - float(serie.get("pdd") or 0))
    caixa = _money_float(pos.get("total_caixa") or 0)
    aplicacoes = _money_float(pos.get("total_aplicacoes") or 0)
    provisoes = _money_float(pos.get("total_provisoes") or 0)
    aporte = _money_float(pos.get("total_passivo_aporte") or 0)
    return {
        "pl": _money_float(dc + caixa + aplicacoes + provisoes + aporte),
        "dc_bdr": dc,
        "caixa": caixa,
        "aplicacoes": aplicacoes,
        "provisoes": provisoes,
        "passivo_aporte": aporte,
        "sem_serie": False,
    }


def calcular_pl_liquidez(data_base_filtro: str) -> dict:
    """
    PL dia a dia sem conciliação de estoque:
    DC (proxy IDSF Outros Ativos) + Conta Corrente Saldo + Aplicações.
    """
    data_alvo = pd.to_datetime(data_base_filtro, format="%d/%m/%Y", errors="coerce")
    if pd.isna(data_alvo):
        return {"erro": f"Data inválida: {data_base_filtro}"}
    data_pos = pd.Timestamp(data_alvo).date()
    aviso_idsf: str | None = None
    try:
        pos = carregar_liquidez_data(data_pos)
        aviso_idsf = pos.get("aviso")
    except Exception as exc:  # noqa: BLE001
        return {
            "erro": f"Sem liquidez IDSF para {data_base_filtro}: {exc}",
            "modo": "parcial",
        }

    total_caixa = float(pos.get("total_caixa") or 0)
    total_aplicacoes = float(pos.get("total_aplicacoes") or 0)
    total_provisoes = float(pos.get("total_provisoes") or 0)
    total_passivo_aporte = float(pos.get("total_passivo_aporte") or 0)
    dc_idsf = float(pos.get("total_dc_idsf") or 0)
    pl_fundo = float(
        pos.get("pl_estimado")
        or (
            total_caixa
            + total_aplicacoes
            + total_provisoes
            + dc_idsf
            + total_passivo_aporte
        )
    )

    taxas_mov = calcular_taxas_baixa_recompra(data_pos)

    return {
        "modo": "parcial",
        "aviso_idsf": aviso_idsf
        or "Data sem conciliação de estoque — PL via composição IDSF (DC proxy).",
        "kpis": {
            "pl_fundo": round(pl_fundo, 2),
            "pl_direitos_creditorios": round(dc_idsf, 2),
            "caixa": round(total_caixa, 2),
            "provisoes": round(total_provisoes, 2),
            "aplicacoes": round(total_aplicacoes, 2),
            "passivo_aporte": round(total_passivo_aporte, 2),
            "provisao_pdd": 0.0,
            "operacoes_ativas": 0,
            "volume_cedido": 0.0,
            "valor_presente": round(dc_idsf, 2),
            "prazo_medio": 0.0,
            "hhi": 0,
            "inadimplencia": 0.0,
            "volume_aquisicoes_historico": 0.0,
            "receita_projetada": 0.0,
            "taxa_media": 0.0,
            "taxa_recompra": float(taxas_mov.get("taxa_recompra") or 0.0),
            "taxa_baixa": float(taxas_mov.get("taxa_baixa") or 0.0),
            "taxa_baixa_recompra": float(taxas_mov.get("taxa_baixa_recompra") or 0.0),
            "tem_recompra": bool(taxas_mov.get("tem_recompra")),
            "credit_var_historico_95": 0.0,
            "credit_var_parametrico_95": 0.0,
            "n_obs": 0,
            "subordinacao_pct": _subordinacao_kpi(data_pos),
        },
        "posicoes_liquidez": pos,
        "top_cedentes": [],
        "top_sacados": [],
        "distribuicao_cedentes": [],
        "distribuicao_sacados": [],
        "distribuicao_tipos": [],
        "aging_inadimplencia": [],
        "top_sacados_inadimplentes": [],
        "top_cedentes_inadimplentes": [],
        "grafico_fluxo_caixa": [],
        "grafico_evolucao": [],
    }


def _taxa_aa_para_am_pct(taxa_aa: float) -> float:
    """tx_cessao (decimal a.a., base 252) -> equivalente composto em % a.m."""
    if pd.isna(taxa_aa):
        return 0.0
    taxa = float(taxa_aa)
    if taxa <= -1.0:
        return 0.0
    taxa = float(round(taxa, CASAS_TAXA_AA))
    am = ((1.0 + taxa) ** (1.0 / 12.0) - 1.0) * 100.0
    return float(round(am, CASAS_TAXA_AM))


def _valor_presente_titulo(valor_face: float, taxa_operacao: float, dias_restantes: float) -> float:
    """Desconta o face pela taxa a.a. (decimal) em equivalente mensal composto."""
    if pd.isna(valor_face) or pd.isna(taxa_operacao):
        return 0.0
    face = _money_float(valor_face)
    if pd.isna(dias_restantes) or dias_restantes <= 0:
        return face
    taxa_am = _taxa_aa_para_am_pct(taxa_operacao) / 100.0
    vp = face / ((1.0 + taxa_am) ** (float(dias_restantes) / 30.0))
    return _money_float(vp)


def _desconto_pdd(dias_atraso: float) -> float:
    """Percentual de desconto PDD conforme faixas de atraso (0 a 1)."""
    if pd.isna(dias_atraso) or dias_atraso <= 0:
        return 0.0  # AA
    if dias_atraso <= 14:
        return 0.0  # A
    if dias_atraso <= 30:
        return 0.01  # B
    if dias_atraso <= 60:
        return 0.03  # C
    if dias_atraso <= 90:
        return 0.10  # D
    if dias_atraso <= 120:
        return 0.30  # E
    if dias_atraso <= 150:
        return 0.50  # F
    if dias_atraso <= 180:
        return 0.70  # G
    return 1.0  # H


_PDD_POR_FAIXA = {
    "AA": 0.0,
    "A": 0.0,
    "B": 0.01,
    "C": 0.03,
    "D": 0.10,
    "E": 0.30,
    "F": 0.50,
    "G": 0.70,
    "H": 1.0,
}


def _desconto_pdd_faixa(fx_pdd: object) -> float:
    """Converte rating fx_pdd (AA..H) no fator de desconto."""
    if fx_pdd is None or (isinstance(fx_pdd, float) and pd.isna(fx_pdd)):
        return 0.0
    chave = str(fx_pdd).strip().upper()
    return float(_PDD_POR_FAIXA.get(chave, 0.0))


def _provisao_pdd_titulo(valor_face: float, vl_pdd: float, fx_pdd: object) -> float:
    """PDD do título: usa vl_pdd da base (com sinal); senão face × rating fx_pdd."""
    if pd.notna(vl_pdd):
        try:
            return float(vl_pdd)
        except (TypeError, ValueError):
            pass
    if pd.isna(valor_face):
        return 0.0
    return float(valor_face) * _desconto_pdd_faixa(fx_pdd)


def calcular_risco_fidc(data_base_filtro: str) -> dict:
    # 1. Carteira aberta a partir do histórico BDR (aq − liq), sem BD_Estoque
    df_atual = carregar_carteira_movimentacoes(data_base_filtro)

    # Converte a data do filtro para o formato datetime
    data_alvo = pd.to_datetime(data_base_filtro, format="%d/%m/%Y")

    if df_atual.empty:
        return {"erro": "Nenhum título aberto nas movimentações BDR para esta data base."}

    # 2. Indicadores de carteira (definições do produto)
    status_atraso = ["VENCIDO", "ATRASO"]
    status_fora_atraso = ["LIQUIDADO", "BAIXADO", "RECOMPRADO", "CEDIDO"]

    df_atual["dias_restantes"] = (df_atual["data_vencimento"] - data_alvo).dt.days
    df_atual["valor_presente_calc"] = [
        _valor_presente_titulo(vf, tx, dias)
        for vf, tx, dias in zip(
            df_atual["valor_face"],
            df_atual["taxa_operacao"],
            df_atual["dias_restantes"],
            strict=False,
        )
    ]
    # Preferir VP administrativo do estoque-base quando ainda válido
    if "vl_presente_adm" in df_atual.columns:
        mask_vp = df_atual["vl_presente_adm"].notna()
        df_atual.loc[mask_vp, "valor_presente_calc"] = df_atual.loc[
            mask_vp, "vl_presente_adm"
        ].astype(float)
    # Centavos por título (HALF_UP) antes de agregar
    df_atual["valor_presente_calc"] = [
        _money_float(v) for v in df_atual["valor_presente_calc"]
    ]

    # Operações Ativas: quantidade com status A VENCER ou VENCIDO
    condicao_ativas = df_atual["status"].isin(["A VENCER", "VENCIDO"])
    operacoes_ativas = int(condicao_ativas.sum())

    # Volume Cedido: valor face com status CEDIDO (ainda inexistente na base)
    volume_cedido = float(
        df_atual.loc[df_atual["status"] == "CEDIDO", "valor_face"].sum()
    )

    # Valor Presente: desconto do valor face pela taxa, nas operações ativas
    valor_presente = _sum_money(df_atual.loc[condicao_ativas, "valor_presente_calc"])

    # Prazo médio: média ponderada (dias a partir da data base) dos A VENCER pelo VP
    df_a_vencer = df_atual.loc[df_atual["status"] == "A VENCER"].copy()
    soma_vp_a_vencer = float(df_a_vencer["valor_presente_calc"].sum())
    prazo_medio = (
        float(
            (df_a_vencer["dias_restantes"] * df_a_vencer["valor_presente_calc"]).sum()
            / soma_vp_a_vencer
        )
        if soma_vp_a_vencer > 0
        else 0.0
    )

    # Totais da carteira na data base (inclui resolvidos do snapshot)
    vol_face_total = df_atual["valor_face"].sum()

    # Taxas de baixa/recompra: histórico BDR (fidc_liquidacoes) até a data base.
    # (baixa + recompra) / (liquidações + baixas + recompras), volume = aquisição.
    taxas_mov = calcular_taxas_baixa_recompra(data_alvo.date())
    taxa_recompra = float(taxas_mov.get("taxa_recompra") or 0.0)
    taxa_baixa = float(taxas_mov.get("taxa_baixa") or 0.0)
    taxa_baixa_recompra = float(taxas_mov.get("taxa_baixa_recompra") or 0.0)
    tem_recompra = bool(taxas_mov.get("tem_recompra"))

    # Lógica de Inadimplência (CEDIDO não entra no atraso)
    condicao_atraso = (df_atual["status"].isin(status_atraso)) | (
        (df_atual["data_vencimento"] < data_alvo)
        & (~df_atual["status"].isin(status_fora_atraso))
    )

    vol_atraso = df_atual.loc[condicao_atraso, "valor_face"].sum()

    # Inadimplência = face vencida / aquisições históricas até a data base.
    from aquisicoes_volume import total_aquisicoes_ate

    aq_hist = total_aquisicoes_ate(data_alvo.date())
    vol_aquisicoes_hist = float(aq_hist.get("total") or 0.0)
    if vol_aquisicoes_hist > 0:
        inadimplencia_pct = float(vol_atraso / vol_aquisicoes_hist) * 100
    elif vol_face_total > 0:
        # Fallback se o cache/BD de aquisições ainda não estiver disponível.
        inadimplencia_pct = float(vol_atraso / vol_face_total) * 100
    else:
        inadimplencia_pct = 0.0

    # PDD: preferir vl_pdd calculado na marcação (VP × faixa); senão aging por face
    df_atual["dias_atraso_calc"] = (data_alvo - df_atual["data_vencimento"]).dt.days
    pior_atraso_sacado = (
        df_atual.loc[df_atual["dias_atraso_calc"] > 0]
        .groupby("sacado")["dias_atraso_calc"]
        .max()
    )

    def _letra_por_dias(dias: float) -> str:
        if pd.isna(dias) or dias <= 0:
            return "AA"
        if dias <= 14:
            return "A"
        if dias <= 30:
            return "B"
        if dias <= 60:
            return "C"
        if dias <= 90:
            return "D"
        if dias <= 120:
            return "E"
        if dias <= 150:
            return "F"
        if dias <= 179:
            return "G"
        return "H"

    mapa_fx = pior_atraso_sacado.map(_letra_por_dias)
    fx_aging = df_atual["sacado"].map(mapa_fx).fillna("AA")
    if "fx_pdd" in df_atual.columns:
        fx_marca = df_atual["fx_pdd"]
        df_atual["fx_pdd_efetivo"] = fx_marca.where(fx_marca.notna(), fx_aging)
    else:
        df_atual["fx_pdd_efetivo"] = fx_aging

    df_atual["desconto_pdd"] = df_atual["fx_pdd_efetivo"].map(_desconto_pdd_faixa)
    pdd_aging = [
        _money_float(float(vf) * float(fat) if pd.notna(vf) else 0.0)
        for vf, fat in zip(
            df_atual["valor_face"],
            df_atual["desconto_pdd"],
            strict=False,
        )
    ]
    if "vl_pdd" in df_atual.columns:
        df_atual["provisao_pdd"] = [
            _money_float(float(v)) if pd.notna(v) else a
            for v, a in zip(df_atual["vl_pdd"], pdd_aging, strict=False)
        ]
    else:
        df_atual["provisao_pdd"] = pdd_aging
    df_atual["valor_com_pdd"] = (
        df_atual["valor_face"] - df_atual["provisao_pdd"]
    ).clip(lower=0.0)
    provisao_pdd_total = _sum_money(df_atual["provisao_pdd"])

    # PL direitos creditórios: VP das ativas líquido da PDD (movimentações BDR)
    pl_direitos_creditorios = _money_float(valor_presente - provisao_pdd_total)

    # Caixa (CC Saldo) + aplicações + provisões (CPR + taxas) fecham o PL
    data_pos_idsf: date | None = None
    try:
        data_pos_idsf = pd.Timestamp(data_alvo).date()
    except Exception:  # noqa: BLE001
        data_pos_idsf = None

    posicoes_liquidez: dict = {
        "caixa": [],
        "aplicacoes": [],
        "total_caixa": 0.0,
        "total_provisoes": 0.0,
        "total_aplicacoes": 0.0,
        "total_liquidez": 0.0,
        "total_dc_idsf": 0.0,
        "total_dc_bruto_idsf": 0.0,
        "total_pdd_idsf": 0.0,
        "fonte": None,
    }
    aviso_idsf: str | None = None
    if data_pos_idsf is not None:
        try:
            posicoes_liquidez = buscar_posicoes_caixa_aplicacoes(data_pos_idsf)
            aviso_idsf = posicoes_liquidez.get("aviso")
        except Exception as exc:  # noqa: BLE001
            try:
                posicoes_liquidez = carregar_liquidez_data(data_pos_idsf)
                aviso_idsf = posicoes_liquidez.get("aviso")
            except Exception:  # noqa: BLE001
                aviso_idsf = f"IDSF indisponível: {exc}"

    total_caixa = _money_float(posicoes_liquidez.get("total_caixa") or 0.0)
    total_aplicacoes = _money_float(posicoes_liquidez.get("total_aplicacoes") or 0.0)
    total_provisoes = _money_float(posicoes_liquidez.get("total_provisoes") or 0.0)
    total_passivo_aporte = _money_float(
        posicoes_liquidez.get("total_passivo_aporte") or 0.0
    )
    dc_idsf = _money_float(
        posicoes_liquidez.get("total_dc_idsf")
        or posicoes_liquidez.get("total_dc")
        or 0.0
    )
    dc_bruto_idsf = _money_float(
        posicoes_liquidez.get("total_dc_bruto_idsf") or 0.0
    )
    pdd_idsf = _money_float(posicoes_liquidez.get("total_pdd_idsf") or 0.0)
    # Se IDSF não desmembrou linhas ALPHA, estima bruto a partir do líquido + PDD
    if dc_bruto_idsf == 0.0 and pdd_idsf > 0 and dc_idsf != 0.0:
        dc_bruto_idsf = _money_float(dc_idsf + pdd_idsf)
    elif dc_bruto_idsf == 0.0 and dc_idsf != 0.0:
        dc_bruto_idsf = dc_idsf

    # PL = DC(BDR) + CC + Aplicações + Provisões + VALID (ajuste de passivo)
    pl_fundo = _money_float(
        pl_direitos_creditorios
        + total_caixa
        + total_aplicacoes
        + total_provisoes
        + total_passivo_aporte
    )

    # Conciliação: VP e PDD do motor × IDSF (ALPHA DC A VENCER+VENCIDO e ALPHA PDD).
    # Aceita resíduo pequeno de arredondamento (centavos × títulos); sem overlay BDR.
    from marcacao_carteira import parte_inteira_sem_centavos

    ivp = parte_inteira_sem_centavos(valor_presente)
    idc = parte_inteira_sem_centavos(dc_bruto_idsf) if dc_bruto_idsf else 0
    ipdd = parte_inteira_sem_centavos(provisao_pdd_total)
    ipdd_i = parte_inteira_sem_centavos(pdd_idsf) if pdd_idsf else 0
    delta_dc = _money_float(valor_presente - dc_bruto_idsf)
    delta_pdd = _money_float(provisao_pdd_total - pdd_idsf)
    delta_liq = _money_float(pl_direitos_creditorios - dc_idsf)
    tol = float(TOLERANCIA_DC_ABS)

    # Desconsidera resíduos VP≤0 conhecidos da BDR (e contágio de faixa) na tolerância.
    efeito_res: dict | None = None
    delta_dc_tol = delta_dc
    delta_pdd_tol = delta_pdd
    try:
        from datetime import datetime as _dt

        from excecoes_bdr import (
            calcular_efeito_residuos,
            calcular_efeito_salto_prazo,
            caminho_estoque_bdr,
            combinar_efeitos,
            dentro_tolerancia,
            registrar_ajuste_tolerancia,
        )

        data_ref = _dt.strptime(str(data_base_filtro).strip()[:10], "%d/%m/%Y").date()
        bdr_csv = caminho_estoque_bdr(data_ref)
        if bdr_csv is not None:
            abertos_ctx: dict[str, dict] = {}
            col_doc = "documento" if "documento" in df_atual.columns else None
            for _, row in df_atual.iterrows():
                chave = str(row[col_doc] if col_doc else row.get("seu_numero", "")).strip()
                if not chave:
                    continue
                abertos_ctx[chave] = {
                    "documento": chave,
                    "sacado": str(row.get("sacado") or ""),
                    "doc_sacado": str(row.get("doc_sacado") or ""),
                    "fx_pdd": str(row.get("fx_pdd") or ""),
                    "vl_pdd": float(row.get("provisao_pdd") or row.get("vl_pdd") or 0),
                    "vl_presente_adm": float(
                        row.get("valor_presente_calc") or row.get("vl_presente_adm") or 0
                    ),
                    "valor_face": float(row.get("valor_face") or 0),
                    "valor_descontado": float(row.get("valor_descontado") or 0),
                    "prazo": row.get("prazo"),
                    "prazo_atual": row.get("prazo_atual"),
                    "data_vencimento": row.get("data_vencimento"),
                }
            efeito_res = calcular_efeito_residuos(bdr_csv, abertos_ctx)
            efeito_salto = calcular_efeito_salto_prazo(
                abertos_ctx,
                data_ref=data_ref,
                delta_vp_bruto=delta_dc,
                tol=tol,
            )
            efeito_res_comb = combinar_efeitos(efeito_res, efeito_salto)
            ok_tol, delta_dc_tol, delta_pdd_tol = dentro_tolerancia(
                delta_dc, delta_pdd, tol=tol, efeito=efeito_res_comb
            )
            if efeito_res_comb.get("ativo"):
                registrar_ajuste_tolerancia(
                    data_ref.isoformat(),
                    efeito_res_comb,
                    delta_vp_bruto=delta_dc,
                    delta_pdd_bruto=delta_pdd,
                    delta_vp_limpo=delta_dc_tol,
                    delta_pdd_limpo=delta_pdd_tol,
                    ok_bruto=abs(delta_dc) <= tol and abs(delta_pdd) <= tol,
                    ok_limpo=ok_tol,
                    fonte="risco_api",
                )
                efeito_res = efeito_res_comb
    except Exception:  # noqa: BLE001
        efeito_res = None
        delta_dc_tol, delta_pdd_tol = delta_dc, delta_pdd

    vp_bate = bool(dc_bruto_idsf) and abs(delta_dc_tol) <= tol
    pdd_bate = (not pdd_idsf and abs(provisao_pdd_total) <= tol) or (
        bool(pdd_idsf) and abs(delta_pdd_tol) <= tol
    )
    conciliada_idsf = (
        bool(vp_bate and pdd_bate) if dc_bruto_idsf else abs(delta_liq) <= tol
    )
    # Resíduo dentro da tolerância: conciliado, mas o dashboard ainda alerta
    tem_divergencia_residual = bool(
        conciliada_idsf
        and (abs(delta_dc) >= 0.01 or abs(delta_pdd) >= 0.01)
    )
    conciliacao_dc = {
        "dc_bdr": round(float(valor_presente), 2),
        "dc_idsf": round(float(dc_bruto_idsf), 2),
        "dc_idsf_liquido": round(float(dc_idsf), 2),
        "pdd_bdr": round(float(provisao_pdd_total), 2),
        "pdd_idsf": round(float(pdd_idsf), 2),
        "delta_dc": round(float(delta_dc), 2),
        "delta_pdd": round(float(delta_pdd), 2),
        "delta_dc_limpo": round(float(delta_dc_tol), 2),
        "delta_pdd_limpo": round(float(delta_pdd_tol), 2),
        "excecao_residuos_ativa": bool(efeito_res and efeito_res.get("ativo")),
        "delta_dc_liquido": round(float(delta_liq), 2),
        "vp_int": ivp,
        "dc_int": idc,
        "pdd_int": ipdd,
        "pdd_idsf_int": ipdd_i,
        "vp_bate": vp_bate,
        "pdd_bate": pdd_bate,
        "tolerancia": round(tol, 2),
        "conciliada_idsf": conciliada_idsf,
        "tem_divergencia_residual": tem_divergencia_residual,
        "passivo_aporte": round(float(total_passivo_aporte), 2),
    }

    # Aging de inadimplência e tops inadimplentes (somente status VENCIDO)
    df_inad = df_atual.loc[df_atual["status"] == "VENCIDO"].copy()
    df_inad["dias_atraso"] = df_inad["dias_atraso_calc"].clip(lower=0)

    def faixa_aging(dias: float) -> str:
        if pd.isna(dias) or dias <= 30:
            return "1-30 dias"
        if dias <= 60:
            return "31-60 dias"
        if dias <= 90:
            return "61-90 dias"
        if dias <= 180:
            return "91-180 dias"
        return ">180 dias"

    ordem_aging = [
        "1-30 dias",
        "31-60 dias",
        "61-90 dias",
        "91-180 dias",
        ">180 dias",
    ]
    if df_inad.empty:
        aging_inadimplencia = [
            {
                "faixa": faixa,
                "valor": 0.0,
                "valor_com_pdd": 0.0,
                "qtd": 0,
                "peso": 0.0,
                "titulos": [],
            }
            for faixa in ordem_aging
        ]
        top_sacados_inad = []
        top_cedentes_inad = []
    else:
        df_inad["faixa_aging"] = df_inad["dias_atraso"].map(faixa_aging)
        aging_grp = (
            df_inad.groupby("faixa_aging", as_index=False)
            .agg(
                valor=("valor_face", "sum"),
                valor_com_pdd=("valor_com_pdd", "sum"),
                qtd=("valor_face", "count"),
            )
        )
        aging_map = aging_grp.set_index("faixa_aging")
        total_inad = float(df_inad["valor_face"].sum())
        aging_inadimplencia = []
        for faixa in ordem_aging:
            df_faixa = df_inad.loc[df_inad["faixa_aging"] == faixa].sort_values(
                by=["dias_atraso", "valor_face"], ascending=[False, False]
            )
            if faixa in aging_map.index:
                valor = float(aging_map.loc[faixa, "valor"])
                valor_com_pdd = float(aging_map.loc[faixa, "valor_com_pdd"])
                qtd = int(aging_map.loc[faixa, "qtd"])
            else:
                valor, valor_com_pdd, qtd = 0.0, 0.0, 0
            titulos = [
                {
                    "documento": str(row.get("documento", "")),
                    "cedente": str(row.get("cedente", "")),
                    "sacado": str(row.get("sacado", "")),
                    "status": str(row.get("status", "")),
                    "data_vencimento": (
                        pd.Timestamp(row["data_vencimento"]).strftime("%d/%m/%Y")
                        if pd.notna(row["data_vencimento"])
                        else ""
                    ),
                    "dias_atraso": int(row["dias_atraso"]),
                    "valor_face": round(float(row["valor_face"]), 2),
                    "valor_com_pdd": round(float(row["valor_com_pdd"]), 2),
                }
                for _, row in df_faixa.iterrows()
            ]
            aging_inadimplencia.append(
                {
                    "faixa": faixa,
                    "valor": round(valor, 2),
                    "valor_com_pdd": round(valor_com_pdd, 2),
                    "qtd": qtd,
                    "peso": round((valor / total_inad * 100), 1) if total_inad > 0 else 0.0,
                    "titulos": titulos,
                }
            )

        sacados_inad = (
            df_inad.groupby("sacado")["valor_face"]
            .sum()
            .reset_index()
            .sort_values(by="valor_face", ascending=False)
            .head(5)
        )
        cedentes_inad = (
            df_inad.groupby("cedente")["valor_face"]
            .sum()
            .reset_index()
            .sort_values(by="valor_face", ascending=False)
            .head(5)
        )
        top_sacados_inad = [
            {
                "nome": row["sacado"],
                "valor": round(float(row["valor_face"]), 2),
                "peso": f"{(row['valor_face'] / total_inad * 100):.1f}%",
            }
            for _, row in sacados_inad.iterrows()
        ]
        top_cedentes_inad = [
            {
                "nome": row["cedente"],
                "valor": round(float(row["valor_face"]), 2),
                "peso": f"{(row['valor_face'] / total_inad * 100):.1f}%",
            }
            for _, row in cedentes_inad.iterrows()
        ]

    # 3. Taxa média a.m.: ponderada pelo descontado das ativas (tx_cessao é decimal a.a.)
    df_ativas = df_atual.loc[condicao_ativas].copy()
    vol_desc_ativas = float(df_ativas["valor_descontado"].sum())
    df_ativas["taxa_am_pct"] = df_ativas["taxa_operacao"].map(_taxa_aa_para_am_pct)
    taxa_media = (
        float(
            (df_ativas["taxa_am_pct"] * df_ativas["valor_descontado"]).sum() / vol_desc_ativas
        )
        if vol_desc_ativas > 0
        else 0.0
    )

    # 4. Cálculos de Concentração (Top 10, HHI e distribuição para pizza)
    def pct_status_descontado(df: pd.DataFrame, entidade: str, status: str) -> pd.Series:
        total = df.groupby(entidade)["valor_descontado"].sum()
        parte = (
            df.loc[df["status"] == status]
            .groupby(entidade)["valor_descontado"]
            .sum()
            .reindex(total.index)
            .fillna(0.0)
        )
        return (parte / total.replace(0, pd.NA) * 100).fillna(0.0)

    cedentes_all = (
        df_atual.groupby("cedente")["valor_face"]
        .sum()
        .reset_index()
        .sort_values(by="valor_face", ascending=False)
    )
    cedentes_all["perc_recompra"] = cedentes_all["cedente"].map(
        pct_status_descontado(df_atual, "cedente", "RECOMPRADO")
    )
    cedentes_all["perc_baixa"] = cedentes_all["cedente"].map(
        pct_status_descontado(df_atual, "cedente", "BAIXADO")
    )
    cedentes_grp = cedentes_all.head(10)

    sacados_all = (
        df_atual.groupby("sacado")["valor_face"]
        .sum()
        .reset_index()
        .sort_values(by="valor_face", ascending=False)
    )
    sacados_all["peso_pct"] = (sacados_all["valor_face"] / vol_face_total) * 100
    atraso_por_sacado = (
        df_atual.loc[condicao_atraso]
        .groupby("sacado")["valor_face"]
        .sum()
    )
    sacados_all["vol_atraso"] = sacados_all["sacado"].map(atraso_por_sacado).fillna(0.0)
    from pd_estimada import pd_por_sacado as _pd_sacado_map

    pd_map_sac = _pd_sacado_map(df_atual, data_alvo.date())
    sacados_all["pd_estimada"] = sacados_all["sacado"].map(pd_map_sac).fillna(0.0)
    sacados_all["perc_recompra"] = sacados_all["sacado"].map(
        pct_status_descontado(df_atual, "sacado", "RECOMPRADO")
    )
    sacados_all["perc_baixa"] = sacados_all["sacado"].map(
        pct_status_descontado(df_atual, "sacado", "BAIXADO")
    )
    hhi_calc = (sacados_all["peso_pct"] ** 2).sum()
    top_sacados = sacados_all.head(10)

    # Pizza: distribuição pelo Valor Presente das operações ativas
    df_pizza = df_atual.loc[condicao_ativas].copy()
    vp_total_pizza = float(df_pizza["valor_presente_calc"].sum())

    cedentes_pizza = (
        df_pizza.groupby("cedente")["valor_presente_calc"]
        .sum()
        .reset_index()
        .sort_values(by="valor_presente_calc", ascending=False)
    )
    sacados_pizza = (
        df_pizza.groupby("sacado")["valor_presente_calc"]
        .sum()
        .reset_index()
        .sort_values(by="valor_presente_calc", ascending=False)
    )
    tipos_pizza = (
        df_pizza.groupby("tipo_recebivel")["valor_presente_calc"]
        .sum()
        .reset_index()
        .sort_values(by="valor_presente_calc", ascending=False)
    )

    def fatias_pizza(grp: pd.DataFrame, col_nome: str, top_n: int = 7) -> list[dict]:
        """Top N + Outros por Valor Presente (operações ativas)."""
        if grp.empty or vp_total_pizza <= 0:
            return []
        top = grp.head(top_n)
        resto_valor = (
            float(grp.iloc[top_n:]["valor_presente_calc"].sum())
            if len(grp) > top_n
            else 0.0
        )
        fatias = [
            {
                "nome": row[col_nome],
                "valor": round(float(row["valor_presente_calc"]), 2),
                "peso": round(float(row["valor_presente_calc"] / vp_total_pizza * 100), 1),
            }
            for _, row in top.iterrows()
        ]
        if resto_valor > 0:
            fatias.append(
                {
                    "nome": "Outros",
                    "valor": round(resto_valor, 2),
                    "peso": round(float(resto_valor / vp_total_pizza * 100), 1),
                }
            )
        return fatias

    distribuicao_cedentes = fatias_pizza(cedentes_pizza, "cedente")
    distribuicao_sacados = fatias_pizza(sacados_pizza, "sacado")
    # Tipos costumam ser poucos: lista completa (sem agregação em Outros)
    distribuicao_tipos = fatias_pizza(
        tipos_pizza, "tipo_recebivel", top_n=max(len(tipos_pizza), 1)
    )

    # 5. Fluxo de caixa projetado (mensal) com PD por título — só A VENCER
    from pd_estimada import pd_por_titulo

    df_fluxo = df_atual.loc[df_atual["status"] == "A VENCER"].copy()
    pd_full = pd_por_titulo(df_atual, data_alvo.date())
    df_fluxo["pd"] = pd_full.loc[df_fluxo.index].values
    df_fluxo["fator_esperanca"] = (1 - df_fluxo["pd"] / 100.0).clip(lower=0.0)
    df_fluxo["fluxo_caixa"] = df_fluxo["valor_face"] * df_fluxo["fator_esperanca"]
    df_fluxo["receita_esperada"] = (
        df_fluxo["valor_face"] - df_fluxo["valor_presente_calc"]
    ) * df_fluxo["fator_esperanca"]

    df_fluxo["mes_ano"] = df_fluxo["data_vencimento"].dt.strftime("%m/%Y")

    fluxo_mensal = df_fluxo.groupby("mes_ano", as_index=False).agg(
        fluxo_caixa=("fluxo_caixa", "sum"),
    )
    fluxo_mensal["sort_date"] = pd.to_datetime(fluxo_mensal["mes_ano"], format="%m/%Y")
    fluxo_mensal = fluxo_mensal.sort_values("sort_date").drop(columns=["sort_date"])

    receita_projetada_total = float(df_fluxo["receita_esperada"].sum())

    grafico_fluxo = [
        {
            "mes_ano": row["mes_ano"],
            "fluxo_caixa": round(float(row["fluxo_caixa"]), 2),
        }
        for _, row in fluxo_mensal.iterrows()
    ]

    # 6. Gráfico de Evolução (originação) — últimos 60 dias até a data base
    inicio_originacao = data_alvo - pd.Timedelta(days=60)
    tipo_norm = (
        df_atual["tipo_recebivel"]
        .astype(str)
        .str.normalize("NFKD")
        .str.encode("ascii", errors="ignore")
        .str.decode("ascii")
        .str.upper()
        .str.strip()
    )
    df_originacao = df_atual.loc[
        (df_atual["data_emissao"] > inicio_originacao)
        & (df_atual["data_emissao"] <= data_alvo)
        & (tipo_norm != "CONFISSAO DE DIVIDA")
    ].copy()
    df_originacao["mes_ano_emissao"] = df_originacao["data_emissao"].dt.strftime("%d/%m")
    df_originacao["receita_operacao"] = (
        df_originacao["valor_face"] - df_originacao["valor_descontado"]
    )
    df_originacao["taxa_am_pct"] = df_originacao["taxa_operacao"].map(_taxa_aa_para_am_pct)
    df_originacao["taxa_x_vol"] = (
        df_originacao["taxa_am_pct"] * df_originacao["valor_descontado"]
    )

    grafico_originacao = df_originacao.groupby("mes_ano_emissao", as_index=False).agg(
        volume_originado=("valor_descontado", "sum"),
        receita_projetada=("receita_operacao", "sum"),
        taxa_x_vol=("taxa_x_vol", "sum"),
        sort_date=("data_emissao", "min"),
    )
    grafico_originacao["taxa_media"] = grafico_originacao.apply(
        lambda r: float(r["taxa_x_vol"] / r["volume_originado"])
        if float(r["volume_originado"]) > 0
        else 0.0,
        axis=1,
    )
    grafico_originacao = grafico_originacao.sort_values("sort_date").drop(
        columns=["sort_date", "taxa_x_vol"]
    )

    grafico_records = [
        {
            "mes_ano_emissao": row["mes_ano_emissao"],
            "volume_originado": round(float(row["volume_originado"]), 2),
            "receita_projetada": round(float(row["receita_projetada"]), 2),
            "taxa_media": round(float(row["taxa_media"]), 2),
        }
        for _, row in grafico_originacao.iterrows()
    ]

    resposta = {
        "kpis": {
            "pl_fundo": round(float(pl_fundo), 2),
            "pl_direitos_creditorios": round(float(pl_direitos_creditorios), 2),
            "caixa": round(total_caixa, 2),
            "provisoes": round(total_provisoes, 2),
            "aplicacoes": round(total_aplicacoes, 2),
            "passivo_aporte": round(float(total_passivo_aporte), 2),
            "provisao_pdd": round(float(provisao_pdd_total), 2),
            "operacoes_ativas": operacoes_ativas,
            "volume_cedido": round(volume_cedido, 2),
            "valor_presente": round(valor_presente, 2),
            "prazo_medio": round(prazo_medio, 1),
            "hhi": int(round(float(hhi_calc), 0)),
            "inadimplencia": round(float(inadimplencia_pct), 2),
            "volume_aquisicoes_historico": round(float(vol_aquisicoes_hist), 2),
            "receita_projetada": round(float(receita_projetada_total), 2),
            "taxa_media": round(float(taxa_media), 2),
            "taxa_recompra": round(float(taxa_recompra), 2),
            "taxa_baixa": round(float(taxa_baixa), 2),
            "taxa_baixa_recompra": round(float(taxa_baixa_recompra), 2),
            "tem_recompra": bool(tem_recompra),
            "subordinacao_pct": _subordinacao_kpi(data_alvo.date()),
            **calcular_credit_var(
                id_carteira=0,
                confianca=0.95,
                data_base=data_base_filtro,
            ),
        },
        "posicoes_liquidez": posicoes_liquidez,
        "aviso_idsf": aviso_idsf,
        "modo": "completo",
        "fonte_carteira": "movimentacoes_bdr",
        "conciliacao_dc": conciliacao_dc,
        "top_cedentes": [
            {
                "nome": row["cedente"],
                "valor": round(float(row["valor_face"]), 2),
                "peso": f"{(row['valor_face'] / vol_face_total * 100):.1f}%",
                "perc_recompra": round(float(row["perc_recompra"]), 2),
                "perc_baixa": round(float(row["perc_baixa"]), 2),
            }
            for _, row in cedentes_grp.iterrows()
        ],
        "top_sacados": [
            {
                "nome": row["sacado"],
                "valor": round(float(row["valor_face"]), 2),
                "peso": f"{row['peso_pct']:.1f}%",
                "pd_estimada": round(float(row["pd_estimada"]), 2),
                "perc_recompra": round(float(row["perc_recompra"]), 2),
                "perc_baixa": round(float(row["perc_baixa"]), 2),
            }
            for _, row in top_sacados.iterrows()
        ],
        "distribuicao_cedentes": distribuicao_cedentes,
        "distribuicao_sacados": distribuicao_sacados,
        "distribuicao_tipos": distribuicao_tipos,
        "aging_inadimplencia": aging_inadimplencia,
        "top_sacados_inadimplentes": top_sacados_inad,
        "top_cedentes_inadimplentes": top_cedentes_inad,
        "grafico_fluxo_caixa": grafico_fluxo,
        "grafico_evolucao": grafico_records,
    }

    return resposta
