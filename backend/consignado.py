"""Consignado Privado: cadastro (Supabase) × posição do motor."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pandas as pd

from db import get_supabase

TABELA = "fidc_consignado_cadastro"

# Cedentes de consignado privado (doc_cedente no EstoqueBDR).
DOCS_CEDENTE_CONSIGNADO = frozenset(
    {
        "FD21332862000191",
        "FD34337707000100",
        "FD48632754000190",
    }
)

PAGE = 1000
_MAX_TENTATIVAS_CADASTRO = 4


def _erro_transiente(exc: BaseException) -> bool:
    msg = str(exc).lower()
    nome = type(exc).__name__.lower()
    return any(
        s in msg or s in nome
        for s in (
            "10035",
            "10054",
            "10053",
            "10060",
            "wouldblock",
            "temporarily unavailable",
            "timeout",
            "timed out",
            "connection reset",
            "connection aborted",
            "server disconnected",
            "remoteprotocolerror",
            "connecterror",
        )
    )


def _carregar_cadastro() -> dict[str, dict[str, Any]]:
    """Mapa documento → atributos do cadastro (só PF nos cedentes filtrados)."""
    import time

    sb = get_supabase()
    out: dict[str, dict[str, Any]] = {}
    offset = 0
    docs = list(DOCS_CEDENTE_CONSIGNADO)
    cols = (
        "documento,empresa,cnpj_empresa,tipo_evento,entrada_afastamento_rescisao,"
        "saida_afastamento,nm_sacado,doc_sacado,doc_cedente,tp_sacado"
    )
    while True:
        batch: list[dict[str, Any]] = []
        ultimo_erro: Exception | None = None
        for tentativa in range(1, _MAX_TENTATIVAS_CADASTRO + 1):
            try:
                batch = (
                    sb.table(TABELA)
                    .select(cols)
                    .eq("tp_sacado", "PF")
                    .in_("doc_cedente", docs)
                    .range(offset, offset + PAGE - 1)
                    .execute()
                    .data
                    or []
                )
                ultimo_erro = None
                break
            except Exception as exc:  # noqa: BLE001
                ultimo_erro = exc
                if not _erro_transiente(exc) or tentativa >= _MAX_TENTATIVAS_CADASTRO:
                    raise
                time.sleep(0.35 * tentativa)
        if ultimo_erro is not None:
            raise ultimo_erro
        if not batch:
            break
        for row in batch:
            doc = str(row.get("documento") or "").strip()
            if doc:
                out[doc] = row
        if len(batch) < PAGE:
            break
        offset += PAGE
    return out


def _parse_data_base(texto: str) -> date:
    t = texto.strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(t[:10] if fmt.startswith("%Y") else t, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Data base inválida: {texto}")


def _parse_iso(texto: object) -> date | None:
    s = str(texto or "").strip()[:10]
    if len(s) < 10:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def _money(v: object) -> float:
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return 0.0
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _br(d: date | None) -> str | None:
    return d.strftime("%d/%m/%Y") if d else None


def _totais() -> dict[str, float]:
    return {"vp": 0.0, "a_vencer": 0.0, "vencidos": 0.0, "pdd": 0.0, "n": 0}


def _acumular(dest: dict[str, float], vp: float, pdd: float, vencido: bool) -> None:
    dest["vp"] += vp
    dest["pdd"] += pdd
    dest["n"] += 1
    if vencido:
        dest["vencidos"] += vp
    else:
        dest["a_vencer"] += vp


def _round_tot(t: dict[str, float]) -> dict[str, Any]:
    return {
        "vp": round(t["vp"], 2),
        "a_vencer": round(t["a_vencer"], 2),
        "vencidos": round(t["vencidos"], 2),
        "pdd": round(t["pdd"], 2),
        "n": int(t["n"]),
    }


def _carregar_cadastro() -> dict[str, dict[str, Any]]:
    """Mapa documento → atributos do cadastro (só PF nos cedentes filtrados)."""
    sb = get_supabase()
    out: dict[str, dict[str, Any]] = {}
    offset = 0
    docs = list(DOCS_CEDENTE_CONSIGNADO)
    cols = (
        "documento,empresa,cnpj_empresa,tipo_evento,entrada_afastamento_rescisao,"
        "saida_afastamento,nm_sacado,doc_sacado,doc_cedente,tp_sacado"
    )
    while True:
        batch = (
            sb.table(TABELA)
            .select(cols)
            .eq("tp_sacado", "PF")
            .in_("doc_cedente", docs)
            .range(offset, offset + PAGE - 1)
            .execute()
            .data
            or []
        )
        if not batch:
            break
        for row in batch:
            doc = str(row.get("documento") or "").strip()
            if doc:
                out[doc] = row
        if len(batch) < PAGE:
            break
        offset += PAGE
    return out


def montar_consignado(data_base: str) -> dict[str, Any]:
    """Agrega Consignado Privado: motor (VP/PDD) × cadastro (empresa/evento)."""
    dt = _parse_data_base(data_base)

    try:
        cadastro = _carregar_cadastro()
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        if "PGRST205" in msg or "Could not find the table" in msg or TABELA in msg:
            raise RuntimeError(
                f"Tabela {TABELA} ausente. Execute backend/sql/fidc_consignado_cadastro.sql "
                "e rode: python carregar_consignado_cadastro.py"
            ) from exc
        raise

    if not cadastro:
        return {
            "data_base": _br(dt),
            "data_base_iso": dt.isoformat(),
            "fonte": TABELA,
            "fonte_valores": "motor",
            "filtros": {
                "tp_sacado": "PF",
                "doc_cedente": sorted(DOCS_CEDENTE_CONSIGNADO),
            },
            "totais": _round_tot(_totais()),
            "empresas": [],
            "n_empresas": 0,
            "n_linhas": 0,
            "aviso": "Cadastro de consignado vazio — rode a sincronização a partir do EstoqueBDR.",
        }

    from carteira_movimentacoes import carregar_carteira_movimentacoes

    df = carregar_carteira_movimentacoes(dt)
    if df is None or df.empty:
        return {
            "data_base": _br(dt),
            "data_base_iso": dt.isoformat(),
            "fonte": TABELA,
            "fonte_valores": "motor",
            "filtros": {
                "tp_sacado": "PF",
                "doc_cedente": sorted(DOCS_CEDENTE_CONSIGNADO),
            },
            "totais": _round_tot(_totais()),
            "empresas": [],
            "n_empresas": 0,
            "n_linhas": 0,
            "aviso": "Sem posição do motor nesta data base.",
        }

    por_emp: dict[str, dict[str, Any]] = {}
    n_join = 0

    for _, row in df.iterrows():
        documento = str(row.get("documento") or "").strip()
        if not documento or documento not in cadastro:
            continue
        meta = cadastro[documento]
        n_join += 1

        empresa = str(meta.get("empresa") or "").strip()
        nm_sacado = (
            str(meta.get("nm_sacado") or row.get("sacado") or "").strip()
            or "(sem sacado)"
        )
        doc_sacado = str(meta.get("doc_sacado") or row.get("doc_sacado") or "").strip()
        tipo_evento = str(meta.get("tipo_evento") or "").strip()
        entrada = str(meta.get("entrada_afastamento_rescisao") or "").strip()
        saida = str(meta.get("saida_afastamento") or "").strip()

        vp = _money(row.get("vl_presente_adm"))
        if vp == 0.0:
            vp = _money(row.get("valor_presente_calc"))
        pdd = _money(row.get("vl_pdd"))
        if pdd == 0.0:
            pdd = _money(row.get("provisao_pdd"))

        venc = row.get("data_vencimento")
        if isinstance(venc, datetime):
            venc_d = venc.date()
        elif isinstance(venc, date):
            venc_d = venc
        else:
            venc_d = _parse_iso(venc)
        status = str(row.get("status") or "").strip().upper()
        if status == "VENCIDO":
            vencido = True
        elif status == "A VENCER":
            vencido = False
        else:
            vencido = bool(venc_d is not None and venc_d < dt)

        if empresa not in por_emp:
            por_emp[empresa] = {
                "empresa": empresa,
                "empresa_vazia": empresa == "",
                "cnpj_empresa": str(meta.get("cnpj_empresa") or "").strip() or None,
                "totais": _totais(),
                "sacados": {},
            }
        emp = por_emp[empresa]
        if not emp.get("cnpj_empresa") and meta.get("cnpj_empresa"):
            emp["cnpj_empresa"] = str(meta.get("cnpj_empresa")).strip()
        _acumular(emp["totais"], vp, pdd, vencido)

        sk = f"{doc_sacado}|{nm_sacado}"
        sacados: dict[str, Any] = emp["sacados"]
        if sk not in sacados:
            sacados[sk] = {
                "sacado": nm_sacado,
                "doc_sacado": doc_sacado or None,
                "totais": _totais(),
                "eventos": {},
            }
        sac = sacados[sk]
        _acumular(sac["totais"], vp, pdd, vencido)

        ek = f"{tipo_evento}|{entrada}|{saida}"
        eventos: dict[str, Any] = sac["eventos"]
        if ek not in eventos:
            eventos[ek] = {
                "tipo_evento": tipo_evento or None,
                "entrada": entrada or None,
                "saida_afastamento": saida or None,
                "totais": _totais(),
            }
        _acumular(eventos[ek]["totais"], vp, pdd, vencido)

    empresas_out: list[dict[str, Any]] = []
    total = _totais()
    for emp in por_emp.values():
        for k, v in emp["totais"].items():
            total[k] += v
        sacados_out: list[dict[str, Any]] = []
        for sac in emp["sacados"].values():
            eventos_out = []
            for ev in sac["eventos"].values():
                item = {
                    "tipo_evento": ev["tipo_evento"],
                    "entrada": ev["entrada"],
                    "saida_afastamento": ev["saida_afastamento"],
                    **_round_tot(ev["totais"]),
                }
                if (ev["tipo_evento"] or "").lower() != "afastamento" and not ev[
                    "saida_afastamento"
                ]:
                    item["saida_afastamento"] = None
                eventos_out.append(item)
            eventos_out.sort(
                key=lambda e: (
                    -e["vp"],
                    str(e.get("tipo_evento") or ""),
                    str(e.get("entrada") or ""),
                )
            )
            principal = eventos_out[0] if len(eventos_out) == 1 else None
            sacados_out.append(
                {
                    "sacado": sac["sacado"],
                    "doc_sacado": sac["doc_sacado"],
                    **_round_tot(sac["totais"]),
                    "tipo_evento": principal["tipo_evento"] if principal else None,
                    "entrada": principal["entrada"] if principal else None,
                    "saida_afastamento": (
                        principal["saida_afastamento"] if principal else None
                    ),
                    "eventos": eventos_out,
                }
            )
        sacados_out.sort(key=lambda s: (-s["vp"], s["sacado"]))
        empresas_out.append(
            {
                "empresa": emp["empresa"] or "(sem empresa)",
                "empresa_vazia": emp["empresa_vazia"],
                "cnpj_empresa": emp.get("cnpj_empresa"),
                **_round_tot(emp["totais"]),
                "sacados": sacados_out,
            }
        )

    empresas_out.sort(
        key=lambda e: (1 if e["empresa_vazia"] else 0, e["empresa"].upper())
    )

    aviso = None
    if n_join == 0 and len(cadastro) > 0:
        aviso = (
            "Cadastro existe, mas nenhum documento cruzou com a carteira do motor "
            "nesta data."
        )

    return {
        "data_base": _br(dt),
        "data_base_iso": dt.isoformat(),
        "fonte": TABELA,
        "fonte_valores": "motor",
        "filtros": {
            "tp_sacado": "PF",
            "doc_cedente": sorted(DOCS_CEDENTE_CONSIGNADO),
        },
        "totais": _round_tot(total),
        "empresas": empresas_out,
        "n_empresas": len(empresas_out),
        "n_linhas": int(total["n"]),
        "n_cadastro": len(cadastro),
        "n_join": n_join,
        "aviso": aviso,
    }
