"""Marcação de carteira: VP em dias úteis + PDD = VP × fator da faixa.

Não usa estoque BDR do dia como atalho. Parte do estoque-base (DATA_MINIMA)
e dos movimentos, rolando o VP e atualizando faixas/PDD.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import Any

from calendario import dias_uteis_prazo

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

_ORDEM_FAIXA = ["AA", "A", "B", "C", "D", "E", "F", "G", "H"]
_RANK_FAIXA = {f: i for i, f in enumerate(_ORDEM_FAIXA)}


def money_trunc(valor: float | int | None) -> float:
    """Trunca para centavos (aproximação da marcação BDR no salto diário)."""
    if valor is None:
        return 0.0
    return float(Decimal(str(float(valor))).quantize(Decimal("0.01"), rounding=ROUND_DOWN))


def money_half_up(valor: float | int | None) -> float:
    if valor is None:
        return 0.0
    return float(
        Decimal(str(float(valor))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    )


def parte_inteira_sem_centavos(valor: float) -> int:
    """Compara totais sem centavos (arredonda para o real mais próximo)."""
    return int(
        Decimal(str(float(valor))).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )


def letra_pdd_por_dias(dias_atraso: float | int | None) -> str:
    if dias_atraso is None:
        return "AA"
    try:
        dias = float(dias_atraso)
    except (TypeError, ValueError):
        return "AA"
    if dias <= 0:
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
    # BDR/IDSF: 180 dias já entra em H (100%); 151–179 = G.
    if dias <= 179:
        return "G"
    return "H"


def fator_pdd(fx: str | None) -> float:
    if not fx:
        return 0.0
    return float(_PDD_POR_FAIXA.get(str(fx).strip().upper(), 0.0))


def pior_faixa(*faixas: str | None) -> str:
    melhor = "AA"
    melhor_rank = -1
    for fx in faixas:
        if not fx:
            continue
        chave = str(fx).strip().upper()
        rank = _RANK_FAIXA.get(chave, -1)
        if rank > melhor_rank:
            melhor, melhor_rank = chave, rank
    return melhor


def _parse_data_simples(valor: object) -> date | None:
    if valor is None:
        return None
    if isinstance(valor, date) and not hasattr(valor, "hour"):
        return valor
    texto = str(valor).strip()
    if not texto or texto.lower() in {"nan", "none", "null"}:
        return None
    if len(texto) >= 10 and texto[4] == "-" and texto[7] == "-":
        try:
            y, m, d = int(texto[0:4]), int(texto[5:7]), int(texto[8:10])
            return date(y, m, d)
        except ValueError:
            return None
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            from datetime import datetime

            return datetime.strptime(texto[:10], fmt).date()
        except ValueError:
            continue
    return None


def _du_atual_com_prazo(
    data_alvo: date,
    venc: date,
    prazo_atual: float | int | None = None,
) -> int:
    """
    Dias úteis remanescentes para a fórmula do registrador.

    Preferência: PRAZO_ATUAL do EstoqueBDR do dia (quando informado).
    Senão: calendário próprio do motor. Não se propaga o offset embutido no
    PRAZO congelado na aquisição: ele carrega o calendário vigente naquela data
    (sem 20/11, feriado nacional só a partir de 2024) e, projetado para o
    presente, conta um dia útil a mais em títulos longos.
    """
    if prazo_atual is not None:
        try:
            atual = int(prazo_atual)
        except (TypeError, ValueError):
            atual = 0
        if atual > 0:
            return atual
    return dias_uteis_prazo(data_alvo, venc)


def vp_por_prazo(
    face: float,
    compra: float,
    venc: date | None,
    data_alvo: date,
    prazo: float | int,
    *,
    prazo_atual: float | int | None = None,
    acumular_juros_pos_venc: bool = False,
) -> float:
    """
    Marcação do registrador: VP = face / (face/compra) ** (DU_atual / PRAZO).

    PRAZO é o prazo contratual congelado na aquisição (coluna PRAZO do EstoqueBDR).
    DU_atual vem do PRAZO_ATUAL do dia (se houver) ou do calendário do motor.
    Com acumular_juros_pos_venc, DU negativo após o vencimento continua a taxa contratual.
    """
    face_f = float(face or 0)
    compra_f = float(compra or 0)
    prazo_f = float(prazo or 0)
    if face_f <= 0:
        return 0.0
    if compra_f <= 0:
        return money_half_up(face_f)
    if venc is None or prazo_f <= 0:
        return money_half_up(compra_f)
    du_atual = _du_atual_com_prazo(data_alvo, venc, prazo_atual)
    if du_atual <= 0 and acumular_juros_pos_venc and data_alvo > venc:
        du_atual = -dias_uteis_prazo(venc, data_alvo)
    if du_atual <= 0 and not acumular_juros_pos_venc:
        return money_half_up(face_f)
    try:
        vp = face_f / ((face_f / compra_f) ** (float(du_atual) / prazo_f))
    except (OverflowError, ZeroDivisionError, ValueError):
        return money_half_up(compra_f)
    return money_half_up(vp)


def rolar_vp(
    face: float,
    vp_ref: float,
    venc: date | None,
    data_ref: date,
    data_alvo: date,
    *,
    ajuste_du_ref: int = 0,
) -> float:
    """
    Rola VP de data_ref → data_alvo em dias úteis (feriados nacionais incluídos).

    A taxa é a implícita do próprio título em data_ref: (face/vp_ref) elevado à
    razão dos prazos em DU. Preferir `vp_por_prazo` quando o PRAZO do registrador
    estiver disponível.
    """
    face_f = float(face or 0)
    vp0 = float(vp_ref or 0)
    if face_f <= 0:
        return 0.0
    if venc is None:
        return money_half_up(vp0 if vp0 > 0 else face_f)
    du0 = dias_uteis_prazo(data_ref, venc) + int(ajuste_du_ref)
    du1 = dias_uteis_prazo(data_alvo, venc)
    if du0 <= 0 or du1 <= 0 or vp0 <= 0:
        return money_half_up(face_f)
    try:
        vp1 = face_f / ((face_f / vp0) ** (float(du1) / float(du0)))
    except (OverflowError, ZeroDivisionError, ValueError):
        return money_half_up(vp0)
    return money_half_up(vp1)


def atualizar_marcacao(
    abertos: dict[str, dict[str, Any]],
    *,
    data_ref: date,
    data_alvo: date,
    acumular_juros_pos_venc: bool = False,
) -> dict[str, dict[str, Any]]:
    """
    Atualiza VP/PDD/faixa das posições abertas para data_alvo.

    - Preferência: PRAZO do registrador (EstoqueBDR) + preço de compra →
      VP = face / (face/compra) ** (DU_atual / PRAZO).
    - Fallback: rola VP de referência do estoque-base em dias úteis.
    - Faixa: uniforme por DOC_SACADO (pior aging na data_alvo).
    - PDD = HALF_UP(VP × fator da faixa).
    """
    if not abertos:
        return abertos

    # 1) VP
    for pos in abertos.values():
        face = float(pos.get("valor_face") or 0)
        venc = _parse_data_simples(pos.get("data_vencimento"))
        data_aq = _parse_data_simples(pos.get("data_aquisicao"))
        compra = float(pos.get("valor_descontado") or 0)
        vp0_compra = money_half_up(compra if compra > 0 else face)
        prazo_raw = pos.get("prazo")
        try:
            prazo = float(prazo_raw) if prazo_raw not in (None, "", 0, 0.0) else None
        except (TypeError, ValueError):
            prazo = None
        if prazo is not None and prazo <= 0:
            prazo = None

        vp_ref = pos.get("vl_presente_adm")
        if data_aq is not None and data_alvo <= data_aq:
            pos["vl_presente_adm"] = vp0_compra
        elif prazo is not None and compra > 0:
            # PRAZO do registrador: mesma fórmula do EstoqueBDR/IDSF.
            pos["vl_presente_adm"] = vp_por_prazo(
                face,
                compra,
                venc,
                data_alvo,
                prazo,
                prazo_atual=pos.get("prazo_atual"),
                acumular_juros_pos_venc=acumular_juros_pos_venc,
            )
        elif data_aq is not None:
            pos["vl_presente_adm"] = rolar_vp(
                face, vp0_compra, venc, data_aq, data_alvo
            )
        elif vp_ref not in (None, 0, 0.0):
            pos["vl_presente_adm"] = rolar_vp(
                face, float(vp_ref), venc, data_ref, data_alvo
            )
        else:
            pos["vl_presente_adm"] = vp0_compra

        pos["data_vencimento"] = venc.isoformat() if venc else pos.get("data_vencimento")

    # 2) Faixa por pior atraso atual do sacado (DOC_SACADO; nome só como fallback).
    # Homônimos sem documento distinto não podem contaminar a faixa.
    # Não herda faixa do estoque-base: quando as parcelas piores saem (liquidação),
    # a faixa melhora — alinhado ao BDR/IDSF.
    def _chave_sacado(pos: dict[str, Any]) -> str:
        doc = str(pos.get("doc_sacado") or "").strip()
        if doc and doc.lower() not in {"nan", "none", "null"}:
            return f"doc:{doc}"
        return f"nome:{str(pos.get('sacado') or '').strip()}"

    atraso_sacado: dict[str, int] = {}

    for pos in abertos.values():
        chave_sac = _chave_sacado(pos)
        venc = _parse_data_simples(pos.get("data_vencimento"))
        if venc is not None:
            dias = (data_alvo - venc).days
            if dias > atraso_sacado.get(chave_sac, 0):
                atraso_sacado[chave_sac] = dias

    faixa_sacado: dict[str, str] = {
        chave_sac: letra_pdd_por_dias(dias)
        for chave_sac, dias in atraso_sacado.items()
    }

    for pos in abertos.values():
        pos["fx_pdd"] = faixa_sacado.get(_chave_sacado(pos), "AA")

    # 3) PDD = VP × fator (HALF_UP — alinhado à marcação BDR)
    for pos in abertos.values():
        vp = float(pos.get("vl_presente_adm") or 0)
        fat = fator_pdd(pos.get("fx_pdd"))
        pos["vl_pdd"] = money_half_up(vp * fat)

    return abertos
