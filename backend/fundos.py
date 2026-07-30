"""Cadastro e resolução de fundos FIDC (multi-tenant)."""

from __future__ import annotations

import os
import re
from datetime import date, datetime
from typing import Any

from db import get_supabase

_CNPJ_DIGITS = re.compile(r"\D+")


def normalizar_cnpj(cnpj: str) -> str:
    return _CNPJ_DIGITS.sub("", (cnpj or "").strip())


def formatar_cnpj(cnpj: str) -> str:
    d = normalizar_cnpj(cnpj)
    if len(d) != 14:
        return d
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"


def _row_to_fundo(row: dict[str, Any]) -> dict[str, Any]:
    cnpj = normalizar_cnpj(str(row.get("cnpj") or ""))
    return {
        "id": int(row["id"]),
        "codigo": str(row.get("codigo") or ""),
        "nome": str(row.get("nome") or ""),
        "cnpj": cnpj,
        "cnpj_formatado": formatar_cnpj(cnpj),
        "data_inicio": row.get("data_inicio"),
        "idsf_carteiras": str(row.get("idsf_carteiras") or ""),
        "tabela_estoque": str(row.get("tabela_estoque") or "BD_Estoque"),
        "bdr_tp_contabil_estoque": str(row.get("bdr_tp_contabil_estoque") or "P"),
        "bdr_tp_contabil_mov": str(row.get("bdr_tp_contabil_mov") or "A"),
        "ativo": bool(row.get("ativo", True)),
        "observacao": row.get("observacao"),
    }


def listar_fundos(*, apenas_ativos: bool = False) -> list[dict[str, Any]]:
    sb = get_supabase()
    q = sb.table("fidc_fundos").select("*").order("nome")
    if apenas_ativos:
        q = q.eq("ativo", True)
    rows = q.execute().data or []
    return [_row_to_fundo(r) for r in rows]


def obter_fundo(
    *,
    id_fundo: int | None = None,
    codigo: str | None = None,
    cnpj: str | None = None,
) -> dict[str, Any] | None:
    sb = get_supabase()
    q = sb.table("fidc_fundos").select("*")
    if id_fundo is not None:
        q = q.eq("id", id_fundo)
    elif codigo:
        q = q.eq("codigo", codigo.strip().lower())
    elif cnpj:
        q = q.eq("cnpj", normalizar_cnpj(cnpj))
    else:
        return None
    rows = q.limit(1).execute().data or []
    if not rows:
        return None
    return _row_to_fundo(rows[0])


def fundo_padrao() -> dict[str, Any] | None:
    """Primeiro fundo ativo; fallback env BDR_CNPJ_FUNDO / codigo alpha."""
    ativos = listar_fundos(apenas_ativos=True)
    if ativos:
        codigo_pref = (os.getenv("FIDC_FUNDO_PADRAO") or "alpha").strip().lower()
        for f in ativos:
            if f["codigo"] == codigo_pref:
                return f
        return ativos[0]
    env_cnpj = normalizar_cnpj(os.getenv("BDR_CNPJ_FUNDO") or "")
    if env_cnpj:
        return {
            "id": 0,
            "codigo": "env",
            "nome": "Fundo (.env)",
            "cnpj": env_cnpj,
            "cnpj_formatado": formatar_cnpj(env_cnpj),
            "data_inicio": os.getenv("BDR_DATA_INICIO"),
            "idsf_carteiras": os.getenv("IDSF_CARTEIRAS") or "",
            "tabela_estoque": os.getenv("SUPABASE_TABLE") or "BD_Estoque",
            "bdr_tp_contabil_estoque": os.getenv("BDR_TP_CONTABIL_ESTOQUE") or "P",
            "bdr_tp_contabil_mov": os.getenv("BDR_TP_CONTABIL_MOV") or "A",
            "ativo": True,
            "observacao": "Fallback sem tabela fidc_fundos",
        }
    return None


def criar_fundo(payload: dict[str, Any]) -> dict[str, Any]:
    sb = get_supabase()
    codigo = str(payload.get("codigo") or "").strip().lower()
    nome = str(payload.get("nome") or "").strip()
    cnpj = normalizar_cnpj(str(payload.get("cnpj") or ""))
    if not codigo or not nome or len(cnpj) != 14:
        raise ValueError("codigo, nome e cnpj (14 dígitos) são obrigatórios")

    data_inicio = payload.get("data_inicio")
    if isinstance(data_inicio, str) and data_inicio.strip():
        data_inicio = data_inicio.strip()[:10]
    else:
        data_inicio = None

    row = {
        "codigo": codigo,
        "nome": nome,
        "cnpj": cnpj,
        "data_inicio": data_inicio,
        "idsf_carteiras": str(payload.get("idsf_carteiras") or "").strip(),
        "tabela_estoque": str(payload.get("tabela_estoque") or "BD_Estoque").strip(),
        "bdr_tp_contabil_estoque": str(payload.get("bdr_tp_contabil_estoque") or "P").strip()
        or "P",
        "bdr_tp_contabil_mov": str(payload.get("bdr_tp_contabil_mov") or "A").strip() or "A",
        "ativo": bool(payload.get("ativo", True)),
        "observacao": payload.get("observacao"),
        "atualizado_em": datetime.utcnow().isoformat() + "Z",
    }
    inserted = sb.table("fidc_fundos").insert(row).execute().data
    if not inserted:
        raise RuntimeError("Falha ao inserir fundo")
    return _row_to_fundo(inserted[0])


def atualizar_fundo(id_fundo: int, payload: dict[str, Any]) -> dict[str, Any]:
    sb = get_supabase()
    atual: dict[str, Any] = {"atualizado_em": datetime.utcnow().isoformat() + "Z"}
    if "nome" in payload and payload["nome"] is not None:
        atual["nome"] = str(payload["nome"]).strip()
    if "cnpj" in payload and payload["cnpj"] is not None:
        cnpj = normalizar_cnpj(str(payload["cnpj"]))
        if len(cnpj) != 14:
            raise ValueError("cnpj deve ter 14 dígitos")
        atual["cnpj"] = cnpj
    if "data_inicio" in payload:
        di = payload["data_inicio"]
        atual["data_inicio"] = str(di).strip()[:10] if di else None
    if "idsf_carteiras" in payload and payload["idsf_carteiras"] is not None:
        atual["idsf_carteiras"] = str(payload["idsf_carteiras"]).strip()
    if "tabela_estoque" in payload and payload["tabela_estoque"] is not None:
        atual["tabela_estoque"] = str(payload["tabela_estoque"]).strip() or "BD_Estoque"
    if "bdr_tp_contabil_estoque" in payload and payload["bdr_tp_contabil_estoque"] is not None:
        atual["bdr_tp_contabil_estoque"] = str(payload["bdr_tp_contabil_estoque"]).strip() or "P"
    if "bdr_tp_contabil_mov" in payload and payload["bdr_tp_contabil_mov"] is not None:
        atual["bdr_tp_contabil_mov"] = str(payload["bdr_tp_contabil_mov"]).strip() or "A"
    if "ativo" in payload and payload["ativo"] is not None:
        atual["ativo"] = bool(payload["ativo"])
    if "observacao" in payload:
        atual["observacao"] = payload["observacao"]

    updated = (
        sb.table("fidc_fundos").update(atual).eq("id", id_fundo).execute().data or []
    )
    if not updated:
        raise LookupError(f"Fundo id={id_fundo} não encontrado")
    return _row_to_fundo(updated[0])


def data_inicio_fundo(fundo: dict[str, Any]) -> date | None:
    raw = fundo.get("data_inicio")
    if not raw:
        return None
    if isinstance(raw, date):
        return raw
    try:
        return datetime.strptime(str(raw)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
