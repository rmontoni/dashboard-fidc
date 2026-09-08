"""Listagem de aquisições e liquidações BDR (fidc_aquisicoes / fidc_liquidacoes)."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any, Literal

from bdr_arquivos import cnpj_fundo, extrair_data_movimento
from calendario import dias_uteis_entre

PAGE_SIZE = 1000
TipoMov = Literal["aquisicoes", "liquidacoes"]
TABELA = {
    "aquisicoes": "fidc_aquisicoes",
    "liquidacoes": "fidc_liquidacoes",
}


def _parse_data(texto: str | None) -> date | None:
    if not texto or not str(texto).strip():
        return None
    t = str(texto).strip()[:10]
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    return None


def _br(d: date | None) -> str | None:
    return d.strftime("%d/%m/%Y") if d else None


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def _parse_valor(valor: Any) -> float:
    if valor is None:
        return 0.0
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        return float(valor)
    texto = str(valor).strip()
    if not texto or texto.lower() in {"nan", "none", "null"}:
        return 0.0
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return 0.0


def _dados_dict(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _match_texto(valor: str, filtro: str | None) -> bool:
    if not filtro or not str(filtro).strip():
        return True
    return str(valor or "").strip().upper() == str(filtro).strip().upper()


def _taxa_am_du(compra: float, face: float, entrada: date | None, venc: date | None) -> float | None:
    """Taxa a.m. em dias úteis: (face/compra)^(21/du) − 1."""
    if compra <= 0 or face <= 0 or entrada is None or venc is None or venc <= entrada:
        return None
    du = dias_uteis_entre(entrada, venc)
    if du <= 0:
        return None
    try:
        taxa = (face / compra) ** (21.0 / float(du)) - 1.0
    except (OverflowError, ValueError, ZeroDivisionError):
        return None
    if taxa < -0.99 or taxa > 50:
        return None
    return round(taxa * 100.0, 4)  # % a.m.


def _data_linha(row: dict[str, Any], dados: dict[str, Any], *, tipo: TipoMov) -> date | None:
    dm = _parse_data(str(row.get("data_movimento") or "") or None)
    if dm:
        return dm
    if tipo == "aquisicoes":
        return (
            extrair_data_movimento(dados)
            or _parse_data(str(dados.get("ENTRADA") or ""))
        )
    return (
        extrair_data_movimento(dados)
        or _parse_data(str(dados.get("DATA MOVIMENTO") or ""))
    )


def _paginar_periodo(
    tipo: TipoMov,
    *,
    cnpj: str,
    inicio: date,
    fim: date,
) -> list[dict[str, Any]]:
    from db import get_supabase

    sb = get_supabase()
    tabela = TABELA[tipo]
    rows: list[dict[str, Any]] = []
    offset = 0
    # data_movimento no intervalo OU período de carga sobrepõe o intervalo pedido
    filtro = (
        f"and(data_movimento.gte.{inicio.isoformat()},data_movimento.lte.{fim.isoformat()}),"
        f"and(periodo_inicio.lte.{fim.isoformat()},periodo_fim.gte.{inicio.isoformat()})"
    )
    while True:
        resp = (
            sb.table(tabela)
            .select("id,data_movimento,periodo_inicio,periodo_fim,dados")
            .eq("cnpj_fundo", cnpj)
            .or_(filtro)
            .order("id")
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
        )
        batch = resp.data or []
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return rows


def _linha_aquisicao(row: dict[str, Any], dados: dict[str, Any], data_ref: date) -> dict[str, Any]:
    entrada = _parse_data(str(dados.get("ENTRADA") or "")) or data_ref
    venc = _parse_data(str(dados.get("DATA VENCIMENTO") or ""))
    compra = _parse_valor(dados.get("VALOR DE COMPRA"))
    face = _parse_valor(dados.get("VALOR DE VENCIMENTO"))
    du = dias_uteis_entre(entrada, venc) if entrada and venc and venc > entrada else 0
    return {
        "data": _br(entrada),
        "data_iso": _iso(entrada),
        "vencimento": _br(venc),
        "vencimento_iso": _iso(venc),
        "cedente": str(dados.get("CEDENTE") or "").strip(),
        "sacado": str(dados.get("NOME SACADO") or dados.get("SACADO") or "").strip(),
        "valor": round(compra, 2),
        "valor_face": round(face, 2),
        "taxa_am": _taxa_am_du(compra, face, entrada, venc),
        "du": du,
        "seu_numero": str(dados.get("SEU NUMERO") or "").strip(),
        "documento": str(dados.get("NUMERO DOCUMENTO") or "").strip(),
        "tipo_recebivel": str(dados.get("TIPO RECEBIVEL") or "").strip(),
    }


def _linha_liquidacao(row: dict[str, Any], dados: dict[str, Any], data_ref: date) -> dict[str, Any]:
    pago = _parse_valor(dados.get("VALOR DE PAGO"))
    face = _parse_valor(dados.get("VALOR DE VENCIMENTO"))
    ajuste_raw = dados.get("AJUSTE")
    if ajuste_raw is None or str(ajuste_raw).strip() == "":
        ajuste = round(pago - face, 2)
    else:
        ajuste = round(_parse_valor(ajuste_raw), 2)
    venc = _parse_data(
        str(dados.get("DATA DE VENCIMENTO") or dados.get("DATA VENCIMENTO") or "")
    )
    du = (
        dias_uteis_entre(data_ref, venc)
        if venc and venc > data_ref
        else 0
    )
    return {
        "data": _br(data_ref),
        "data_iso": _iso(data_ref),
        "cedente": str(dados.get("CEDENTE") or "").strip(),
        "sacado": str(dados.get("SACADO") or dados.get("NOME SACADO") or "").strip(),
        "ocorrencia": str(dados.get("OCORRENCIA") or "").strip(),
        "situacao": str(
            dados.get("SITUACAO DO RECEBIVEL") or dados.get("SITUACAO") or ""
        ).strip(),
        "vencimento": _br(venc),
        "vencimento_iso": _iso(venc),
        "valor_pago": round(pago, 2),
        "ajuste": ajuste,
        "tipo_recebivel": str(dados.get("TIPO RECEBIVEL") or "").strip(),
        "seu_numero": str(dados.get("SEU NUMERO") or "").strip(),
        "documento": str(dados.get("DOCUMENTO") or "").strip(),
        "du": du,
    }


def listar_movimentacoes(
    tipo: TipoMov,
    *,
    inicio: str,
    fim: str,
    cedente: str | None = None,
    sacado: str | None = None,
) -> dict[str, Any]:
    d_ini = _parse_data(inicio)
    d_fim = _parse_data(fim)
    if d_ini is None or d_fim is None:
        raise ValueError("Informe início e fim no formato dd/mm/yyyy ou YYYY-MM-DD.")
    if d_ini > d_fim:
        d_ini, d_fim = d_fim, d_ini
    if (d_fim - d_ini).days > 366:
        raise ValueError("Intervalo máximo de 366 dias.")

    cnpj = cnpj_fundo()
    brutos = _paginar_periodo(tipo, cnpj=cnpj, inicio=d_ini, fim=d_fim)

    linhas: list[dict[str, Any]] = []
    cedentes: set[str] = set()
    sacados: set[str] = set()
    filtradas: list[dict[str, Any]] = []

    for row in brutos:
        dados = _dados_dict(row.get("dados"))
        data_ref = _data_linha(row, dados, tipo=tipo)
        if data_ref is None or data_ref < d_ini or data_ref > d_fim:
            continue
        if tipo == "aquisicoes":
            item = _linha_aquisicao(row, dados, data_ref)
        else:
            item = _linha_liquidacao(row, dados, data_ref)
        if item.get("cedente"):
            cedentes.add(str(item["cedente"]))
        if item.get("sacado"):
            sacados.add(str(item["sacado"]))
        linhas.append(item)

    for item in linhas:
        if not _match_texto(str(item.get("cedente") or ""), cedente):
            continue
        if not _match_texto(str(item.get("sacado") or ""), sacado):
            continue
        filtradas.append(item)

    filtradas.sort(
        key=lambda r: (
            str(r.get("data_iso") or ""),
            str(r.get("sacado") or "").upper(),
            str(r.get("seu_numero") or ""),
        )
    )

    def _prazo_medio(itens: list[dict[str, Any]], peso_chave: str) -> float | None:
        peso = 0.0
        soma = 0.0
        for x in itens:
            w = float(x.get(peso_chave) or 0)
            du = float(x.get("du") or 0)
            if w <= 0 or du <= 0:
                continue
            peso += w
            soma += du * w
        if peso <= 0:
            return None
        return round(soma / peso, 1)

    if tipo == "aquisicoes":
        soma_valor = sum(float(x.get("valor") or 0) for x in filtradas)
        soma_face = sum(float(x.get("valor_face") or 0) for x in filtradas)
        peso_taxa = 0.0
        soma_taxa_pond = 0.0
        for x in filtradas:
            taxa = x.get("taxa_am")
            valor = float(x.get("valor") or 0)
            if taxa is None or valor <= 0:
                continue
            peso_taxa += valor
            soma_taxa_pond += float(taxa) * valor
        totais = {
            "n": len(filtradas),
            "valor": round(soma_valor, 2),
            "valor_face": round(soma_face, 2),
            "taxa_am_media": (
                round(soma_taxa_pond / peso_taxa, 4) if peso_taxa > 0 else None
            ),
            "prazo_medio_du": _prazo_medio(filtradas, "valor"),
        }
    else:
        totais = {
            "n": len(filtradas),
            "valor_pago": round(
                sum(float(x.get("valor_pago") or 0) for x in filtradas), 2
            ),
            "ajuste": round(sum(float(x.get("ajuste") or 0) for x in filtradas), 2),
            "prazo_medio_du": _prazo_medio(filtradas, "valor_pago"),
        }

    return {
        "tipo": tipo,
        "inicio": _br(d_ini),
        "inicio_iso": _iso(d_ini),
        "fim": _br(d_fim),
        "fim_iso": _iso(d_fim),
        "cedente": cedente or None,
        "sacado": sacado or None,
        "cedentes": sorted(cedentes, key=lambda s: s.casefold()),
        "sacados": sorted(sacados, key=lambda s: s.casefold()),
        "totais": totais,
        "linhas": filtradas,
    }
