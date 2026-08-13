"""Cliente IDSF GetPortfolioComposition — PL/PDD e liquidez (caixa/aplicações).

API (PDF Composição por Período):
  GET .../GetPortfolioComposition/{IdCarteira}/{dataInicio}/{dataFim}/JSON
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import date, datetime, timedelta
from typing import Any

import requests

# Ex.: "COTA MEZANINO ALPHA -  Vcto: 31-12-2049 -> 170,00% CDI"
_RE_PCT_CDI = re.compile(r"(\d+[.,]\d+)\s*%\s*CDI", re.IGNORECASE)
_RE_VCTO_ATIVO = re.compile(r"Vcto:\s*(\d{2}-\d{2}-\d{4})", re.IGNORECASE)

IDSF_BASE = "https://prod.idsf.com.br/api/report/GetPortfolioComposition"
ATIVO_PDD = "ALPHA PDD"
ID_ATIVO_PDD = "258"
ATIVO_VALID = "ALPHA VALID"  # aporte em cotas ainda fora do passivo (vira Mezanino IV)
ID_CONSOLIDADO = 0
APELIDO_CONSOLIDADO = "CONSOLIDADO"

CATEGORIA_CAIXA = "caixa"
CATEGORIA_CPR = "caixa_cpr"
CATEGORIA_PROVISAO = "provisao"  # taxas gestão/admin/custódia (entram no PL)
CATEGORIA_APLICACAO = "aplicacao"
CATEGORIA_DC = "dc_idsf"
# Aporte pendente de emissão de cotas (não é PDD; ajuste de passivo)
CATEGORIA_PASSIVO_APORTE = "passivo_aporte"

DESC_PROVISOES = {
    "Taxa de gestão",
    "Taxa de administração",
    "Taxa de custódia",
}

_CACHE_POSICOES: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_TTL_S = 30 * 60


def token_idsf() -> str:
    token = (os.getenv("IDSF_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("Defina IDSF_TOKEN no arquivo .env")
    return token


def carteiras_idsf() -> list[int]:
    # Inclui Mezanino IV (34691304) — aparece a partir de ~23/06/2026
    raw = os.getenv(
        "IDSF_CARTEIRAS",
        "34691,34691302,34691303,34691304,566391",
    )
    ids: list[int] = []
    for parte in raw.split(","):
        parte = parte.strip()
        if not parte:
            continue
        ids.append(int(parte))
    if not ids:
        raise RuntimeError("IDSF_CARTEIRAS vazio")
    return ids


def carteira_composicao_idsf() -> int | None:
    """Carteira com ativos do fundo (caixa/aplicações). Default: última de IDSF_CARTEIRAS."""
    raw = (os.getenv("IDSF_CARTEIRA_COMPOSICAO") or "").strip()
    if raw:
        return int(raw)
    carteiras = carteiras_idsf()
    return carteiras[-1] if carteiras else None


def buscar_composicao(
    id_carteira: int,
    data_inicio: date,
    data_fim: date,
    token: str | None = None,
    timeout: int = 180,
) -> list[dict[str, Any]]:
    """Retorna lista de snapshots diários da composição da carteira."""
    tok = token or token_idsf()
    url = (
        f"{IDSF_BASE}/{id_carteira}/"
        f"{data_inicio.isoformat()}/{data_fim.isoformat()}/JSON"
    )
    response = requests.get(url, headers={"token": tok}, timeout=timeout)
    response.raise_for_status()
    payload = response.json()

    if not payload.get("Success", True):
        erros = payload.get("Errors") or ["erro desconhecido"]
        raise RuntimeError(f"IDSF {id_carteira}: {erros}")

    model = payload.get("Model")
    if model is None:
        return []
    if isinstance(model, str):
        model = json.loads(model) if model.strip() else []
    if isinstance(model, dict):
        return [model]
    if isinstance(model, list):
        return [m for m in model if isinstance(m, dict)]
    return []


def _pdd_do_snapshot(snapshot: dict[str, Any]) -> float:
    total = 0.0
    for pos in snapshot.get("Posicoes") or []:
        ativo = str(pos.get("Ativo") or "").strip().upper()
        id_ativo = str(pos.get("IdAtivo") or "").strip()
        if ativo != ATIVO_PDD and id_ativo != ID_ATIVO_PDD:
            continue
        valor = pos.get("ValorLiquido")
        if valor is None:
            valor = pos.get("ValorBruto")
        try:
            total += abs(float(valor))
        except (TypeError, ValueError):
            continue
    return float(total)


def _pl_cota_campos(snapshot: dict[str, Any]) -> tuple[float, float | None, float | None]:
    """Retorna (PL, qtde_cotas, valor_cota) a partir de PlCota."""
    pl_cota = snapshot.get("PlCota") or {}
    try:
        pl = float(pl_cota.get("PL") or 0.0)
    except (TypeError, ValueError):
        pl = 0.0
    qtde: float | None
    valor: float | None
    try:
        raw_q = pl_cota.get("Qtde")
        qtde = float(raw_q) if raw_q is not None and str(raw_q).strip() != "" else None
    except (TypeError, ValueError):
        qtde = None
    try:
        raw_c = pl_cota.get("Cota")
        valor = float(raw_c) if raw_c is not None and str(raw_c).strip() != "" else None
    except (TypeError, ValueError):
        valor = None
    return pl, qtde, valor


def _pl_do_snapshot(snapshot: dict[str, Any]) -> float:
    pl, _q, _c = _pl_cota_campos(snapshot)
    return pl


def extrair_pct_cdi_vencimento_snapshot(
    snapshot: dict[str, Any],
) -> tuple[float | None, date | None]:
    """Extrai (%CDI, vencimento) do texto Posicoes[].Ativo da Composition."""
    pct: float | None = None
    venc: date | None = None
    for pos in snapshot.get("Posicoes") or []:
        ativo = str(pos.get("Ativo") or "")
        if "CDI" not in ativo.upper():
            continue
        if pct is None:
            m_pct = _RE_PCT_CDI.search(ativo)
            if m_pct:
                try:
                    pct = float(str(m_pct.group(1)).replace(",", "."))
                except ValueError:
                    pct = None
        if venc is None:
            m_v = _RE_VCTO_ATIVO.search(ativo)
            if m_v:
                try:
                    venc = datetime.strptime(m_v.group(1), "%d-%m-%Y").date()
                except ValueError:
                    venc = None
        if pct is not None and venc is not None:
            break
    return pct, venc


def extrair_pct_cdi_da_composicao(
    id_carteira: int,
    *,
    token: str | None = None,
    ref: date | None = None,
) -> tuple[float | None, date | None]:
    """Busca um dia recente de Composition e extrai %CDI/vencimento."""
    fim = ref or date.today()
    # janela curta para achar um dia útil com posições
    inicio = fim - timedelta(days=14)
    try:
        snaps = buscar_composicao(id_carteira, inicio, fim, token=token)
    except Exception:  # noqa: BLE001
        return None, None
    # preferir o snapshot mais recente com CDI no Ativo
    for snap in reversed(snaps):
        pct, venc = extrair_pct_cdi_vencimento_snapshot(snap)
        if pct is not None:
            return pct, venc
    return None, None


def _data_posicao(snapshot: dict[str, Any]) -> date | None:
    raw = snapshot.get("DataPosicao")
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def extrair_pl_pdd(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    """Normaliza um snapshot IDSF em registro para fidc_pl_pdd_diario."""
    data_pos = _data_posicao(snapshot)
    if data_pos is None:
        return None
    id_carteira = int(snapshot.get("IdCarteira") or 0)
    if id_carteira <= 0:
        return None
    apelido = str(snapshot.get("Apelido") or f"Carteira {id_carteira}").strip()
    pl, qtde, valor_cota = _pl_cota_campos(snapshot)
    return {
        "data_posicao": data_pos.isoformat(),
        "id_carteira": id_carteira,
        "apelido": apelido,
        "pl": round(pl, 2),
        "pdd": round(_pdd_do_snapshot(snapshot), 2),
        "qtde_cotas": round(qtde, 8) if qtde is not None else None,
        "valor_cota": round(valor_cota, 8) if valor_cota is not None else None,
        "fonte": "idsf_json",
    }


def consolidar_registros(registros: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Soma PL/PDD de várias carteiras no mesmo dia."""
    if not registros:
        return None
    data_pos = registros[0]["data_posicao"]
    return {
        "data_posicao": data_pos,
        "id_carteira": ID_CONSOLIDADO,
        "apelido": APELIDO_CONSOLIDADO,
        "pl": round(sum(float(r["pl"]) for r in registros), 2),
        "pdd": round(sum(float(r["pdd"]) for r in registros), 2),
        "qtde_cotas": None,
        "valor_cota": None,
        "fonte": "idsf_json",
    }


def _float_pos(valor: Any) -> float:
    try:
        from decimal import ROUND_HALF_UP, Decimal

        return float(Decimal(str(float(valor))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    except (TypeError, ValueError):
        return 0.0


def classificar_posicao(pos: dict[str, Any]) -> str | None:
    """
    Classificação para PL e painéis:
    - caixa: Conta Corrente - Saldo
    - caixa_cpr: Conta Corrente - CPR (entra no PL como provisão)
    - provisao: taxas gestão/admin/custódia (entra no PL)
    - aplicacao: Fundo
    - dc_idsf: Outros Ativos DC/PDD (sem ALPHA VALID)
    - passivo_aporte: ALPHA VALID (aporte em cotas ainda não emitido / Mezanino IV)
    """
    desc = str(pos.get("DescricaoTipoPosicao") or "").strip()
    ativo = str(pos.get("Ativo") or "").strip()
    if not ativo or ativo == "0000":
        return None
    if desc == "Conta Corrente - Saldo":
        return CATEGORIA_CAIXA
    if desc == "Conta Corrente - CPR":
        return CATEGORIA_CPR
    if desc in DESC_PROVISOES:
        return CATEGORIA_PROVISAO
    if desc == "Fundo":
        return CATEGORIA_APLICACAO
    if desc == "Outros Ativos":
        # VALID não é PDD: aporte pendente que vira Mezanino IV
        if ativo.upper() == ATIVO_VALID or "VALID" in ativo.upper():
            return CATEGORIA_PASSIVO_APORTE
        return CATEGORIA_DC
    return None


def _agregar_posicoes(
    posicoes: list[dict[str, Any]],
    *,
    id_carteira: int,
    apelido: str,
) -> dict[str, Any]:
    agregados: dict[tuple[str, str], dict[str, Any]] = {}
    for pos in posicoes:
        categoria = classificar_posicao(pos)
        if not categoria:
            continue
        ativo = str(pos.get("Ativo") or "").strip()
        tipo = str(pos.get("DescricaoTipoPosicao") or "").strip()
        chave = (categoria, ativo)
        item = agregados.get(chave)
        vl = _float_pos(pos.get("ValorLiquido"))
        vb = _float_pos(pos.get("ValorBruto"))
        if item is None:
            agregados[chave] = {
                "categoria": categoria,
                "ativo": ativo,
                "tipo": tipo,
                "valor_liquido": vl,
                "valor_bruto": vb,
                "qtd_linhas": 1,
                "id_carteira": id_carteira,
                "carteira": apelido,
                "agente": str(pos.get("Agente") or "").strip() or None,
            }
        else:
            item["valor_liquido"] += vl
            item["valor_bruto"] += vb
            item["qtd_linhas"] += 1

    caixa: list[dict[str, Any]] = []
    caixa_cpr: list[dict[str, Any]] = []
    provisoes: list[dict[str, Any]] = []
    aplicacoes: list[dict[str, Any]] = []
    dc_itens: list[dict[str, Any]] = []
    passivo_aporte: list[dict[str, Any]] = []
    for item in agregados.values():
        item["valor_liquido"] = round(float(item["valor_liquido"]), 2)
        item["valor_bruto"] = round(float(item["valor_bruto"]), 2)
        cat = item["categoria"]
        if cat == CATEGORIA_CAIXA:
            caixa.append(item)
        elif cat == CATEGORIA_CPR:
            caixa_cpr.append(item)
        elif cat == CATEGORIA_PROVISAO:
            provisoes.append(item)
        elif cat == CATEGORIA_APLICACAO:
            aplicacoes.append(item)
        elif cat == CATEGORIA_DC:
            dc_itens.append(item)
        elif cat == CATEGORIA_PASSIVO_APORTE:
            passivo_aporte.append(item)

    for lista in (caixa, caixa_cpr, provisoes, aplicacoes, dc_itens, passivo_aporte):
        lista.sort(key=lambda r: abs(float(r["valor_liquido"])), reverse=True)

    total_caixa = round(sum(float(r["valor_liquido"]) for r in caixa), 2)
    total_cpr = round(sum(float(r["valor_liquido"]) for r in caixa_cpr), 2)
    total_provisoes_taxas = round(sum(float(r["valor_liquido"]) for r in provisoes), 2)
    # Provisões no PL = CPR + taxas (gestão/admin/custódia)
    total_provisoes = round(total_cpr + total_provisoes_taxas, 2)
    total_aplicacoes = round(sum(float(r["valor_liquido"]) for r in aplicacoes), 2)
    # DC líquido de PDD (sem VALID)
    total_dc = round(sum(float(r["valor_liquido"]) for r in dc_itens), 2)

    # Desmembra ALPHA DC bruto × ALPHA PDD (para conciliação com o motor)
    total_dc_bruto = 0.0
    total_pdd_idsf = 0.0
    for item in dc_itens:
        ativo_u = str(item.get("ativo") or "").strip().upper()
        vl = float(item.get("valor_liquido") or 0)
        if "PDD" in ativo_u:
            total_pdd_idsf += abs(vl)
        elif "A VENCER" in ativo_u or "VENCIDO" in ativo_u:
            total_dc_bruto += vl
    if total_dc_bruto == 0.0 and total_pdd_idsf == 0.0 and dc_itens:
        # Fallback: líquido conhecido; bruto/PDD não tipados
        total_dc_bruto = total_dc
    total_dc_bruto = round(total_dc_bruto, 2)
    total_pdd_idsf = round(total_pdd_idsf, 2)

    # VALID: aporte pendente (valor normalmente negativo na SUB)
    total_passivo_aporte = round(
        sum(float(r["valor_liquido"]) for r in passivo_aporte), 2
    )
    return {
        "data_posicao": None,
        "id_carteira": id_carteira,
        "carteira": apelido,
        "caixa": caixa,
        "aplicacoes": aplicacoes,
        "passivo_aporte": passivo_aporte,
        "dc_itens": dc_itens,
        "total_caixa": total_caixa,
        "total_caixa_cpr": total_cpr,
        "total_provisoes": total_provisoes,
        "total_aplicacoes": total_aplicacoes,
        "total_dc_idsf": total_dc,
        "total_dc_bruto_idsf": total_dc_bruto,
        "total_pdd_idsf": total_pdd_idsf,
        "total_passivo_aporte": total_passivo_aporte,
        "total_liquidez": round(total_caixa + total_aplicacoes + total_provisoes, 2),
        "fonte": "idsf_json",
    }



def extrair_posicoes_liquidez(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Extrai caixa (saldo), CPR, aplicações e DC IDSF de um snapshot."""
    id_carteira = int(snapshot.get("IdCarteira") or 0)
    apelido = str(snapshot.get("Apelido") or f"Carteira {id_carteira}").strip()
    resultado = _agregar_posicoes(
        list(snapshot.get("Posicoes") or []),
        id_carteira=id_carteira,
        apelido=apelido,
    )
    data_pos = _data_posicao(snapshot)
    resultado["data_posicao"] = data_pos.isoformat() if data_pos else None
    resultado["pl_carteira_idsf"] = round(_pl_do_snapshot(snapshot), 2)
    # PL estimado: DC (sem VALID) + liquidez + ajuste de passivo (VALID)
    resultado["pl_estimado"] = round(
        float(resultado["total_caixa"])
        + float(resultado["total_aplicacoes"])
        + float(resultado["total_provisoes"])
        + float(resultado["total_dc_idsf"])
        + float(resultado["total_passivo_aporte"]),
        2,
    )
    return resultado


def registro_liquidez_diario(extraido: dict[str, Any]) -> dict[str, Any] | None:
    """Linha para upsert em fidc_liquidez_diaria."""
    data_pos = extraido.get("data_posicao")
    id_carteira = int(extraido.get("id_carteira") or 0)
    if not data_pos or id_carteira <= 0:
        return None
    return {
        "data_posicao": data_pos,
        "id_carteira": id_carteira,
        "carteira": extraido.get("carteira"),
        "caixa": float(extraido.get("total_caixa") or 0),
        "caixa_cpr": float(extraido.get("total_caixa_cpr") or 0),
        "aplicacoes": float(extraido.get("total_aplicacoes") or 0),
        "dc_idsf": float(extraido.get("total_dc_idsf") or 0),
        "pl_carteira": float(extraido.get("pl_carteira_idsf") or 0),
        "pl_estimado": float(extraido.get("pl_estimado") or 0),
        "detalhes": {
            "caixa": extraido.get("caixa") or [],
            "aplicacoes": extraido.get("aplicacoes") or [],
            "passivo_aporte": extraido.get("passivo_aporte") or [],
            "total_provisoes": float(extraido.get("total_provisoes") or 0),
            "total_passivo_aporte": float(extraido.get("total_passivo_aporte") or 0),
        },
        "fonte": "idsf_json",
    }


def buscar_posicoes_caixa_aplicacoes(
    data_posicao: date,
    *,
    id_carteira: int | None = None,
    token: str | None = None,
    usar_cache: bool = True,
) -> dict[str, Any]:
    """
    Busca posições de caixa e aplicações na IDSF para a data.
    Usa IDSF_CARTEIRA_COMPOSICAO (ou última de IDSF_CARTEIRAS), tipicamente a SUB.
    """
    carteira = id_carteira if id_carteira is not None else carteira_composicao_idsf()
    if carteira is None:
        raise RuntimeError("Nenhuma carteira IDSF configurada para composição")

    cache_key = f"{carteira}:{data_posicao.isoformat()}"
    agora = time.time()
    if usar_cache and cache_key in _CACHE_POSICOES:
        expira, payload = _CACHE_POSICOES[cache_key]
        if agora < expira:
            return payload

    snaps = buscar_composicao(carteira, data_posicao, data_posicao, token=token)
    if not snaps:
        for cid in carteiras_idsf():
            if cid == carteira:
                continue
            snaps = buscar_composicao(cid, data_posicao, data_posicao, token=token)
            if not snaps:
                continue
            extraido = extrair_posicoes_liquidez(snaps[0])
            if extraido["total_liquidez"] != 0 or extraido["total_dc_idsf"] != 0:
                if usar_cache:
                    _CACHE_POSICOES[cache_key] = (agora + _CACHE_TTL_S, extraido)
                return extraido
        vazio = {
            "data_posicao": data_posicao.isoformat(),
            "id_carteira": carteira,
            "carteira": None,
            "caixa": [],
            "aplicacoes": [],
            "passivo_aporte": [],
            "total_caixa": 0.0,
            "total_caixa_cpr": 0.0,
            "total_provisoes": 0.0,
            "total_aplicacoes": 0.0,
            "total_dc_idsf": 0.0,
            "total_passivo_aporte": 0.0,
            "total_liquidez": 0.0,
            "pl_estimado": 0.0,
            "fonte": "idsf_json",
            "aviso": "Sem composição IDSF na data",
        }
        if usar_cache:
            _CACHE_POSICOES[cache_key] = (agora + _CACHE_TTL_S, vazio)
        return vazio

    resultado = extrair_posicoes_liquidez(snaps[0])
    if usar_cache:
        _CACHE_POSICOES[cache_key] = (agora + _CACHE_TTL_S, resultado)
    return resultado
