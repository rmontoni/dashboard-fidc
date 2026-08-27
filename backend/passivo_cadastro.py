"""CRUD e leitura de classes/cotistas/chamadas do passivo mezanino."""

from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any

from db import get_supabase

TAB_CLASSES = "fidc_passivo_classes"
TAB_COTISTAS = "fidc_cotistas"
TAB_CHAMADAS = "fidc_passivo_chamadas"

ID_CARTEIRA_POR_NOME = {
    "Mezanino I": 34691,
    "Mezanino II": 34691302,
    "Mezanino III": 34691303,
    "Mezanino IV": 34691304,
}

_SQLITE_CANDIDATES = [
    Path(__file__).resolve().parent / "data" / "passivo_alpha.db",
    Path(r"C:\Users\raulm\OneDrive\Documentos\Projetos\acompanhamento-passivo-alpha\instance\passivo.db"),
    Path(__file__).resolve().parents[1].parent
    / "acompanhamento-passivo-alpha"
    / "instance"
    / "passivo.db",
]


def _tabela_ausente(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "pgrst205" in msg or "could not find the table" in msg


def _sqlite_path() -> Path | None:
    env = (os.getenv("PASSIVO_ALPHA_DB") or "").strip()
    if env:
        p = Path(env)
        if p.exists():
            return p
    for cand in _SQLITE_CANDIDATES:
        if cand.exists():
            return cand
    return None


def _sqlite_classes(*, apenas_ativos: bool = False) -> list[dict[str, Any]]:
    path = _sqlite_path()
    if not path:
        return []
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute("SELECT * FROM classes_cota").fetchall()]
    conn.close()
    out = []
    for r in rows:
        out.append(
            {
                "id": int(r["id"]),
                "id_carteira": ID_CARTEIRA_POR_NOME.get(str(r["nome"])),
                "nome": str(r["nome"]),
                "percentual_cdi": float(r["percentual_cdi"]),
                "meses_primeira": int(r["meses_primeira"]),
                "meses_segunda": int(r["meses_segunda"]),
                "perc_primeira": float(r["perc_primeira"] or 50),
                "ativo": True,
            }
        )
    if apenas_ativos:
        out = [x for x in out if x.get("ativo")]
    return out


def _sqlite_cotistas() -> list[dict[str, Any]]:
    path = _sqlite_path()
    if not path:
        return []
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute("SELECT * FROM cotistas ORDER BY nome").fetchall()]
    conn.close()
    out = []
    for r in rows:
        doc = "".join(c for c in str(r["documento"] or "") if c.isdigit())
        out.append({"id": int(r["id"]), "nome": str(r["nome"]), "documento": doc})
    return out


def _sqlite_chamadas(
    *,
    classe_id: int | None = None,
    cotista_id: int | None = None,
) -> list[dict[str, Any]]:
    path = _sqlite_path()
    if not path:
        return []
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    sql = "SELECT * FROM chamadas"
    params: list[Any] = []
    wheres: list[str] = []
    if classe_id is not None:
        wheres.append("classe_id = ?")
        params.append(classe_id)
    if cotista_id is not None:
        wheres.append("cotista_id = ?")
        params.append(cotista_id)
    if wheres:
        sql += " WHERE " + " AND ".join(wheres)
    sql += " ORDER BY data_prazo, id"
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    conn.close()
    out = []
    for ch in rows:
        out.append(
            {
                "id": int(ch["id"]),
                "classe_id": int(ch["classe_id"]),
                "cotista_id": int(ch["cotista_id"]),
                "numero": int(ch["numero"]),
                "data_prazo": str(ch["data_prazo"] or ch["data_aporte"])[:10],
                "data_aporte": str(ch["data_aporte"])[:10],
                "valor_nominal": float(ch["valor_nominal"]),
                "origem": ch["origem"] if "origem" in ch.keys() else None,
                "principal_amortizado": float(ch["principal_amortizado"] or 0)
                if "principal_amortizado" in ch.keys()
                else 0.0,
                "valor_amortizado_bruto": float(ch["valor_amortizado_bruto"] or 0)
                if "valor_amortizado_bruto" in ch.keys()
                else 0.0,
                "perc_primeira": float(ch["perc_primeira"])
                if ch["perc_primeira"] is not None
                else None,
                "credito_vp": float(ch["credito_vp"] or 0)
                if "credito_vp" in ch.keys()
                else 0.0,
            }
        )
    return out


def _digitos(texto: object) -> str:
    return "".join(c for c in str(texto or "") if c.isdigit())


def _parse_date(texto: object) -> date | None:
    s = str(texto or "").strip()[:10]
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _next_id(tabela: str) -> int:
    sb = get_supabase()
    rows = sb.table(tabela).select("id").order("id", desc=True).limit(1).execute().data or []
    if not rows:
        return 1
    return int(rows[0]["id"]) + 1


def listar_classes(*, apenas_ativos: bool = False) -> list[dict[str, Any]]:
    try:
        sb = get_supabase()
        q = sb.table(TAB_CLASSES).select("*").order("id")
        if apenas_ativos:
            q = q.eq("ativo", True)
        rows = q.execute().data or []
        if rows:
            return rows
    except Exception as exc:  # noqa: BLE001
        if not _tabela_ausente(exc):
            raise
    return _sqlite_classes(apenas_ativos=apenas_ativos)


def listar_cotistas() -> list[dict[str, Any]]:
    try:
        sb = get_supabase()
        rows = sb.table(TAB_COTISTAS).select("*").order("nome").execute().data or []
        if rows:
            return rows
    except Exception as exc:  # noqa: BLE001
        if not _tabela_ausente(exc):
            raise
    return _sqlite_cotistas()


def listar_chamadas(
    *,
    classe_id: int | None = None,
    cotista_id: int | None = None,
) -> list[dict[str, Any]]:
    try:
        sb = get_supabase()
        q = sb.table(TAB_CHAMADAS).select("*").order("data_prazo").order("id")
        if classe_id is not None:
            q = q.eq("classe_id", classe_id)
        if cotista_id is not None:
            q = q.eq("cotista_id", cotista_id)
        rows = q.execute().data or []
        if rows:
            return rows
    except Exception as exc:  # noqa: BLE001
        if not _tabela_ausente(exc):
            raise
    return _sqlite_chamadas(classe_id=classe_id, cotista_id=cotista_id)


def obter_cotista(id_cotista: int) -> dict[str, Any] | None:
    try:
        sb = get_supabase()
        rows = (
            sb.table(TAB_COTISTAS).select("*").eq("id", id_cotista).limit(1).execute().data
            or []
        )
        if rows:
            return rows[0]
    except Exception as exc:  # noqa: BLE001
        if not _tabela_ausente(exc):
            raise
    for c in _sqlite_cotistas():
        if int(c["id"]) == int(id_cotista):
            return c
    return None


def criar_classe(dados: dict[str, Any]) -> dict[str, Any]:
    sb = get_supabase()
    row = {
        "id": _next_id(TAB_CLASSES),
        "id_carteira": dados.get("id_carteira"),
        "nome": str(dados["nome"]).strip(),
        "percentual_cdi": float(dados["percentual_cdi"]),
        "meses_primeira": int(dados["meses_primeira"]),
        "meses_segunda": int(dados["meses_segunda"]),
        "perc_primeira": float(dados.get("perc_primeira") or 50),
        "ativo": bool(dados.get("ativo", True)),
    }
    return sb.table(TAB_CLASSES).insert(row).execute().data[0]


def atualizar_classe(id_: int, dados: dict[str, Any]) -> dict[str, Any]:
    sb = get_supabase()
    patch: dict[str, Any] = {}
    for k in (
        "nome",
        "percentual_cdi",
        "meses_primeira",
        "meses_segunda",
        "perc_primeira",
        "ativo",
    ):
        if k in dados and dados[k] is not None:
            patch[k] = dados[k]
    if "id_carteira" in dados:
        patch["id_carteira"] = dados["id_carteira"]
    if "nome" in patch:
        patch["nome"] = str(patch["nome"]).strip()
    rows = sb.table(TAB_CLASSES).update(patch).eq("id", id_).execute().data or []
    if not rows:
        raise ValueError(f"Classe {id_} não encontrada")
    return rows[0]


def excluir_classe(id_: int) -> None:
    sb = get_supabase()
    n = (
        sb.table(TAB_CHAMADAS)
        .select("id", count="exact")
        .eq("classe_id", id_)
        .limit(1)
        .execute()
    )
    if (n.count or 0) > 0 or (n.data or []):
        raise ValueError("Não é possível excluir classe com chamadas vinculadas.")
    sb.table(TAB_CLASSES).delete().eq("id", id_).execute()


def criar_cotista(dados: dict[str, Any]) -> dict[str, Any]:
    sb = get_supabase()
    doc = _digitos(dados.get("documento"))
    if len(doc) not in (11, 14):
        raise ValueError("Documento deve ser CPF (11) ou CNPJ (14).")
    row = {
        "id": _next_id(TAB_COTISTAS),
        "nome": str(dados["nome"]).strip(),
        "documento": doc,
    }
    return sb.table(TAB_COTISTAS).insert(row).execute().data[0]


def atualizar_cotista(id_: int, dados: dict[str, Any]) -> dict[str, Any]:
    sb = get_supabase()
    patch: dict[str, Any] = {}
    if "nome" in dados and dados["nome"] is not None:
        patch["nome"] = str(dados["nome"]).strip()
    if "documento" in dados and dados["documento"] is not None:
        doc = _digitos(dados["documento"])
        if len(doc) not in (11, 14):
            raise ValueError("Documento deve ser CPF (11) ou CNPJ (14).")
        patch["documento"] = doc
    rows = sb.table(TAB_COTISTAS).update(patch).eq("id", id_).execute().data or []
    if not rows:
        raise ValueError(f"Cotista {id_} não encontrado")
    return rows[0]


def excluir_cotista(id_: int) -> None:
    sb = get_supabase()
    n = (
        sb.table(TAB_CHAMADAS)
        .select("id")
        .eq("cotista_id", id_)
        .limit(1)
        .execute()
        .data
        or []
    )
    if n:
        raise ValueError("Não é possível excluir cotista com chamadas vinculadas.")
    sb.table(TAB_COTISTAS).delete().eq("id", id_).execute()


def criar_chamada(dados: dict[str, Any]) -> dict[str, Any]:
    sb = get_supabase()
    prazo = _parse_date(dados.get("data_prazo"))
    aporte = _parse_date(dados.get("data_aporte"))
    if not prazo or not aporte:
        raise ValueError("data_prazo e data_aporte são obrigatórias.")
    row = {
        "id": _next_id(TAB_CHAMADAS),
        "classe_id": int(dados["classe_id"]),
        "cotista_id": int(dados["cotista_id"]),
        "numero": int(dados["numero"]),
        "data_prazo": prazo.isoformat(),
        "data_aporte": aporte.isoformat(),
        "valor_nominal": float(dados["valor_nominal"]),
        "origem": dados.get("origem"),
        "principal_amortizado": float(dados.get("principal_amortizado") or 0),
        "valor_amortizado_bruto": float(dados.get("valor_amortizado_bruto") or 0),
        "perc_primeira": float(dados["perc_primeira"])
        if dados.get("perc_primeira") is not None
        else None,
        "credito_vp": float(dados.get("credito_vp") or 0),
    }
    return sb.table(TAB_CHAMADAS).insert(row).execute().data[0]


def atualizar_chamada(id_: int, dados: dict[str, Any]) -> dict[str, Any]:
    sb = get_supabase()
    patch: dict[str, Any] = {}
    for k in (
        "classe_id",
        "cotista_id",
        "numero",
        "valor_nominal",
        "origem",
        "principal_amortizado",
        "valor_amortizado_bruto",
        "perc_primeira",
        "credito_vp",
    ):
        if k in dados and dados[k] is not None:
            patch[k] = dados[k]
    if "data_prazo" in dados and dados["data_prazo"] is not None:
        d = _parse_date(dados["data_prazo"])
        if not d:
            raise ValueError("data_prazo inválida")
        patch["data_prazo"] = d.isoformat()
    if "data_aporte" in dados and dados["data_aporte"] is not None:
        d = _parse_date(dados["data_aporte"])
        if not d:
            raise ValueError("data_aporte inválida")
        patch["data_aporte"] = d.isoformat()
    rows = sb.table(TAB_CHAMADAS).update(patch).eq("id", id_).execute().data or []
    if not rows:
        raise ValueError(f"Chamada {id_} não encontrada")
    return rows[0]


def excluir_chamada(id_: int) -> None:
    sb = get_supabase()
    sb.table(TAB_CHAMADAS).delete().eq("id", id_).execute()
