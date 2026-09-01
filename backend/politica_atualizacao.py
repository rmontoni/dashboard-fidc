"""Política de cobertura das bases do dashboard.

Regras:
- **Sem caixa** (BDR movimentações, eventos, estoque): sempre até **D-2**
  (``conciliacao.data_base_maxima``).
- **Carteira própria (série)**: sempre até **D-2** (dias úteis), independente
  de BDR ou IDSF; conciliação IDSF por dia é opcional.
- **IDSF / caixa** (liquidez, classes, taxas, passivo): no mínimo até a
  **última data de liquidez IDSF** disponível; a carga tenta estender até D-2.
"""

from __future__ import annotations

from datetime import date
from typing import Any


def alvo_d2(referencia: date | None = None) -> date:
    """Última data operacional liberada (D-2 em dias úteis)."""
    from conciliacao import data_base_maxima

    return data_base_maxima(referencia)


def alvo_sem_caixa(referencia: date | None = None) -> date:
    """Alvo para fontes que não dependem de caixa IDSF."""
    return alvo_d2(referencia)


def referencia_idsf() -> date | None:
    """Última data com liquidez IDSF carregada (referência para PL/classes)."""
    from atualizacoes import _ultima_data_liquidez

    return _ultima_data_liquidez()


def alvo_com_caixa() -> date:
    """Alvo mínimo para fontes IDSF: última liquidez ou D-2 se ainda vazia."""
    return referencia_idsf() or alvo_d2()


def _ultima_data_serie() -> date | None:
    from atualizacoes import _ultima_data_serie as serie

    return serie()


def _lacuna(
    id_: str,
    label: str,
    atual: date | None,
    alvo: date,
    *,
    politica: str,
) -> dict[str, Any]:
    return {
        "id": id_,
        "label": label,
        "atual": atual.isoformat() if atual else None,
        "alvo": alvo.isoformat(),
        "politica": politica,
        "dias_atraso": (alvo - atual).days if atual and atual < alvo else None,
    }


def verificar_cobertura(referencia: date | None = None) -> dict[str, Any]:
    """Compara bases carregadas com a política; retorna lacunas."""
    from atualizacoes import (
        _ultima_data_classes,
        _ultima_data_estoque_bdr,
        _ultima_data_eventos,
        _ultima_data_liquidez,
    )

    d2 = alvo_d2(referencia)
    liq = _ultima_data_liquidez()
    ref_idsf = liq or d2
    lacunas: list[dict[str, Any]] = []

    def _registrar(
        id_: str,
        label: str,
        atual: date | None,
        alvo: date,
        *,
        politica: str,
    ) -> None:
        if atual is None or atual < alvo:
            lacunas.append(_lacuna(id_, label, atual, alvo, politica=politica))

    # Sem caixa + série → D-2
    _registrar(
        "bdr_estoque",
        "BDR - Estoque",
        _ultima_data_estoque_bdr(),
        d2,
        politica="d2",
    )
    _registrar(
        "bdr_movimentacoes",
        "BDR - Movimentações",
        _ultima_data_eventos(),
        d2,
        politica="d2",
    )
    _registrar(
        "carteira_propria",
        "Carteira Própria (série)",
        _ultima_data_serie(),
        d2,
        politica="d2",
    )

    # Liquidez IDSF → idealmente D-2
    _registrar("idsf", "IDSF - Liquidez", liq, d2, politica="d2")

    # Demais IDSF → última liquidez disponível
    _registrar(
        "idsf_classes",
        "IDSF - Classes",
        _ultima_data_classes(),
        ref_idsf,
        politica="idsf",
    )

    return {
        "ok": len(lacunas) == 0,
        "alvo_d2": d2.isoformat(),
        "referencia_idsf": liq.isoformat() if liq else None,
        "lacunas": lacunas,
    }


def item_atualizacao(
    id_: str,
    label: str,
    data: date | None,
    *,
    referencia: date | None = None,
) -> dict[str, Any]:
    """Monta item de status com alvo e flag ``atualizado``."""
    from atualizacoes import _br

    d2 = alvo_d2(referencia)
    ref_idsf = referencia_idsf() or d2

    alvo_d2_ids = id_ in (
        "bdr_estoque",
        "bdr_movimentacoes",
        "carteira_propria",
        "idsf",
    )
    alvo = d2 if alvo_d2_ids else ref_idsf
    politica = "d2" if alvo_d2_ids else "idsf"
    atualizado = data is not None and data >= alvo

    return {
        "id": id_,
        "label": label,
        "data": _br(data),
        "data_iso": data.isoformat() if data else None,
        "alvo": _br(alvo),
        "alvo_iso": alvo.isoformat(),
        "politica": politica,
        "atualizado": atualizado,
    }
