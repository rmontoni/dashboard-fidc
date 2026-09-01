"""Conciliação de datas base do FIDC (multi-fundo).

Datas disponíveis = calendário desde o início do fundo (dias úteis),
limitado a D-2 (dois dias úteis antes de hoje) — BDR/IDSF ainda
consolida o estoque com atraso; não baixar nem liberar o mesmo dia.
Cobertura das bases: ver ``politica_atualizacao`` (BDR/série → D-2;
IDSF liquidez/classes → idealmente D-2).
O motor de risco só roda em datas com status `ok` (estoque de direitos
creditórios conferido). Caixa/outras aplicações (IDSF) entram depois no PL.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

from db import (
    PAGE_SIZE,
    _br_para_float,
    get_supabase,
    nome_tabela,
)
from fundos import fundo_padrao, obter_fundo

STATUS_OK = "ok"
STATUS_PENDENTE = "pendente"
TABELA_CONC = "fidc_conciliacao_data_base"

# Atraso operacional: dashboard só libera até D-N (dias úteis).
# D-2 enquanto a gestão do estoque não estiver 100% interna (orientação BDR).
ATRASO_DIAS_UTEIS = 2

# Dashboard e motor: sem datas anteriores a esta (estoque-base BDR).
DATA_MINIMA_DASHBOARD = date(2024, 5, 31)


def data_base_minima() -> date:
    return DATA_MINIMA_DASHBOARD


def data_base_maxima(
    referencia: date | None = None,
    *,
    atraso_uteis: int = ATRASO_DIAS_UTEIS,
) -> date:
    """Última data base liberada no sistema (D-N em dias úteis bancários)."""
    from calendario import e_dia_util

    cursor = referencia or date.today()
    restantes = max(0, int(atraso_uteis))
    while restantes > 0:
        cursor -= timedelta(days=1)
        if e_dia_util(cursor):
            restantes -= 1
    return cursor


def _parse_date(valor: str | date | datetime | None) -> date | None:
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = str(valor).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(texto[:10] if fmt == "%Y-%m-%d" else texto, fmt).date()
        except ValueError:
            continue
    dt = pd.to_datetime(texto, dayfirst=True, errors="coerce")
    if pd.isna(dt):
        return None
    return pd.Timestamp(dt).date()


def dias_uteis(inicio: date, fim: date) -> list[date]:
    """Dias úteis bancários entre inicio e fim (inclusive): seg–sex sem feriado."""
    from calendario import e_dia_util

    if fim < inicio:
        return []
    out: list[date] = []
    cursor = inicio
    while cursor <= fim:
        if e_dia_util(cursor):
            out.append(cursor)
        cursor += timedelta(days=1)
    return out


def _resolver_fundo(
    *,
    id_fundo: int | None = None,
    codigo: str | None = None,
) -> dict[str, Any]:
    if id_fundo is not None:
        fundo = obter_fundo(id_fundo=id_fundo)
    elif codigo:
        fundo = obter_fundo(codigo=codigo)
    else:
        fundo = fundo_padrao()
    if not fundo:
        raise RuntimeError("Nenhum fundo encontrado. Cadastre em fidc_fundos.")
    return fundo


def carregar_conciliacoes(cnpj_fundo: str) -> dict[date, dict[str, Any]]:
    sb = get_supabase()
    rows: list[dict] = []
    offset = 0
    while True:
        response = (
            sb.table(TABELA_CONC)
            .select("*")
            .eq("cnpj_fundo", cnpj_fundo)
            .order("data_base")
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
        )
        batch = response.data or []
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    mapa: dict[date, dict[str, Any]] = {}
    for row in rows:
        d = _parse_date(row.get("data_base"))
        if d:
            mapa[d] = row
    return mapa


def listar_datas_detalhe(
    *,
    id_fundo: int | None = None,
    codigo: str | None = None,
    ate: date | None = None,
) -> list[dict[str, Any]]:
    """
    Calendário de datas base desde o início do fundo, com flag de conciliação
    e indicadores de liquidez IDSF (PL dia a dia mesmo sem conciliação).

    Por padrão, `fim` = D-2 (dois dias úteis antes de hoje).
    """
    from db import mapa_liquidez_diario
    from carteira_movimentacoes import dc_bdr_conciliado

    fundo = _resolver_fundo(id_fundo=id_fundo, codigo=codigo)
    inicio_fundo = _parse_date(fundo.get("data_inicio")) or date(2021, 3, 1)
    inicio = max(inicio_fundo, data_base_minima())
    fim = ate if ate is not None else data_base_maxima()
    if fim < inicio:
        return []
    liq = mapa_liquidez_diario()

    detalhe: list[dict[str, Any]] = []
    for d in dias_uteis(inicio, fim):
        liq_row = liq.get(d.isoformat())
        tem_liquidez = bool(liq_row)
        dc_idsf = float((liq_row or {}).get("dc_idsf") or 0) if tem_liquidez else 0.0
        conc_dc = (
            dc_bdr_conciliado(d, dc_idsf)
            if tem_liquidez
            else {
                "dc_bdr": 0.0,
                "dc_idsf": 0.0,
                "delta_dc": 0.0,
                "conciliada_idsf": False,
                "sem_snapshot": True,
            }
        )
        conciliada = bool(
            tem_liquidez
            and not conc_dc.get("sem_snapshot")
            and conc_dc.get("conciliada_idsf")
        )
        status = STATUS_OK if conciliada else STATUS_PENDENTE
        detalhe.append(
            {
                "data": d.strftime("%d/%m/%Y"),
                "data_iso": d.isoformat(),
                "status": status,
                "conciliada": conciliada,
                "estoque_linhas": int(conc_dc.get("n_titulos") or 0) or None,
                "observacao": (
                    f"ΔDC={conc_dc.get('delta_dc')}"
                    if tem_liquidez
                    else None
                ),
                "escopo": "movimentacoes_bdr+idsf",
                "tem_liquidez": tem_liquidez,
                "caixa": float((liq_row or {}).get("caixa") or 0) if tem_liquidez else None,
                "aplicacoes": float((liq_row or {}).get("aplicacoes") or 0)
                if tem_liquidez
                else None,
                "pl_estimado": float((liq_row or {}).get("pl_estimado") or 0)
                if tem_liquidez
                else None,
                "dc_bdr": conc_dc.get("dc_bdr") if tem_liquidez else None,
                "dc_idsf": conc_dc.get("dc_idsf") if tem_liquidez else None,
                "delta_dc": conc_dc.get("delta_dc") if tem_liquidez else None,
            }
        )
    return detalhe


def listar_datas_conciliadas(
    *,
    id_fundo: int | None = None,
    codigo: str | None = None,
) -> list[str]:
    """Datas em dd/mm/yyyy com conciliação ok (usáveis no motor)."""
    return [d["data"] for d in listar_datas_detalhe(id_fundo=id_fundo, codigo=codigo) if d["conciliada"]]


def esta_conciliada(
    data_base: str | date,
    *,
    id_fundo: int | None = None,
    codigo: str | None = None,
) -> bool:
    """True se DC BDR ≈ DC IDSF na data (conciliação operacional)."""
    d = _parse_date(data_base)
    if d is None:
        return False
    for item in listar_datas_detalhe(id_fundo=id_fundo, codigo=codigo, ate=d):
        if item.get("data_iso") == d.isoformat():
            return bool(item.get("conciliada"))
    return False


def registrar_conciliacao(
    data_base: date,
    *,
    cnpj_fundo: str,
    status: str,
    ticket_estoque: str | None = None,
    estoque_linhas: int | None = None,
    estoque_vl_face: float | None = None,
    estoque_vl_aquisicao: float | None = None,
    estoque_vl_pdd: float | None = None,
    observacao: str | None = None,
    id_fundo: int | None = None,
) -> dict[str, Any]:
    sb = get_supabase()
    agora = datetime.utcnow().isoformat() + "Z"
    row: dict[str, Any] = {
        "data_base": data_base.isoformat(),
        "cnpj_fundo": cnpj_fundo,
        "status": status,
        "ticket_estoque": ticket_estoque,
        "estoque_linhas": estoque_linhas,
        "estoque_vl_face": estoque_vl_face,
        "estoque_vl_aquisicao": estoque_vl_aquisicao,
        "estoque_vl_pdd": estoque_vl_pdd,
        "observacao": observacao,
        "atualizado_em": agora,
    }
    if status == STATUS_OK:
        row["conferido_em"] = agora
    # id_fundo é opcional (coluna pode não existir em schemas antigos)
    row_com_fundo = {**row, "id_fundo": id_fundo} if id_fundo else row

    # Preferência: upsert por (cnpj_fundo, data_base) se existir unique;
    # fallback: delete+insert. Tenta com id_fundo e sem, conforme schema.
    ultimo_erro: Exception | None = None
    for payload in (row_com_fundo, row):
        try:
            sb.table(TABELA_CONC).upsert(payload, on_conflict="data_base").execute()
            return payload
        except Exception as exc:  # noqa: BLE001
            ultimo_erro = exc
            try:
                sb.table(TABELA_CONC).delete().eq("data_base", data_base.isoformat()).eq(
                    "cnpj_fundo", cnpj_fundo
                ).execute()
                sb.table(TABELA_CONC).insert(payload).execute()
                return payload
            except Exception as exc2:  # noqa: BLE001
                ultimo_erro = exc2
                continue
    raise RuntimeError(f"Falha ao registrar conciliação: {ultimo_erro}")

def totais_estoque_local(data_base: date, tabela: str | None = None) -> dict[str, Any]:
    """Soma totais do estoque já gravado (direitos creditórios) para a data."""
    sb = get_supabase()
    tabela = tabela or nome_tabela()
    dt_ref = data_base.isoformat()
    rows: list[dict] = []
    offset = 0
    while True:
        response = (
            sb.table(tabela)
            .select("vl_face,vl_aquisicao,vl_pdd")
            .eq("dt_ref", dt_ref)
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
        )
        batch = response.data or []
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    if not rows:
        return {
            "estoque_linhas": 0,
            "estoque_vl_face": 0.0,
            "estoque_vl_aquisicao": 0.0,
            "estoque_vl_pdd": 0.0,
        }

    df = pd.DataFrame(rows)
    for col in ("vl_face", "vl_aquisicao", "vl_pdd"):
        if col in df.columns:
            df[col] = _br_para_float(df[col]).fillna(0.0)
        else:
            df[col] = 0.0

    return {
        "estoque_linhas": int(len(df)),
        "estoque_vl_face": float(df["vl_face"].sum()),
        "estoque_vl_aquisicao": float(df["vl_aquisicao"].sum()),
        "estoque_vl_pdd": float(df["vl_pdd"].sum()),
    }


def conciliar_estoque_existente(
    data_base: str | date,
    *,
    codigo_fundo: str | None = None,
    observacao: str | None = None,
) -> dict[str, Any]:
    """
    Marca data como conciliada usando o estoque já presente no BD
    (sem baixar de novo na BDR). Escopo atual: direitos creditórios.
    """
    fundo = _resolver_fundo(codigo=codigo_fundo)
    d = _parse_date(data_base)
    if not d:
        raise ValueError(f"Data inválida: {data_base}")

    totais = totais_estoque_local(d, tabela=str(fundo.get("tabela_estoque") or nome_tabela()))
    if totais["estoque_linhas"] <= 0:
        raise RuntimeError(
            f"Nenhum título em {fundo.get('tabela_estoque')} para {d.isoformat()}. "
            "Baixe o estoque antes de conciliar."
        )

    obs = observacao or (
        "Conciliação de direitos creditórios a partir do estoque local "
        "(PL caixa/aplicações IDSF pendente)."
    )
    row = registrar_conciliacao(
        d,
        cnpj_fundo=str(fundo["cnpj"]),
        status=STATUS_OK,
        estoque_linhas=totais["estoque_linhas"],
        estoque_vl_face=totais["estoque_vl_face"],
        estoque_vl_aquisicao=totais["estoque_vl_aquisicao"],
        estoque_vl_pdd=totais["estoque_vl_pdd"],
        observacao=obs,
        id_fundo=int(fundo["id"]) if fundo.get("id") else None,
    )
    return {
        "data_base": d.isoformat(),
        "fundo": fundo["codigo"],
        "status": STATUS_OK,
        "escopo": "direitos_creditorios",
        **totais,
        "registro": row,
    }
