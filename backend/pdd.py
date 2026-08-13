"""PDD da carteira (motor): por empresa/cedente × evento do cadastro consignado."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pandas as pd

from consignado import DOCS_CEDENTE_CONSIGNADO, TABELA
from db import get_supabase

PAGE = 1000

# E-consig nos gráficos: só BMP e Via Capital (sem Cartos).
DOCS_E_CONSIG = frozenset(
    {
        "FD34337707000100",  # BMP
        "FD48632754000190",  # Via Capital
    }
)
NOMES_E_CONSIG = ("BMP", "VIA CAPITAL")

EVENTOS = ("afastamento", "demissao", "rescisao", "nc_outros")
LABEL_EVENTO = {
    "afastamento": "Afastamento",
    "demissao": "Demissão",
    "rescisao": "Rescisão",
    "nc_outros": "NC/Outros",
}
FAIXAS_ORDEM = ("AA", "A", "B", "C", "D", "E", "F", "G", "H")
_FAIXA_RANK = {fx: i for i, fx in enumerate(FAIXAS_ORDEM)}


def _norm_faixa(fx: object) -> str:
    t = str(fx or "").strip().upper()
    return t if t in _FAIXA_RANK else "AA"


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


def _titulo_vencido(row: Any, dt: date) -> bool:
    status = str(row.get("status") or "").strip().upper()
    if status in ("VENCIDO", "ATRASO"):
        return True
    if status == "A VENCER":
        return False
    venc = row.get("data_vencimento")
    if isinstance(venc, datetime):
        venc_d = venc.date()
    elif isinstance(venc, date):
        venc_d = venc
    else:
        venc_d = _parse_iso(venc)
    return bool(venc_d is not None and venc_d < dt)


def _bucket_evento(tipo: str | None) -> str:
    t = (tipo or "").strip().lower()
    if t in ("afastamento", "demissao", "rescisao"):
        return t
    return "nc_outros"


def _zero_eventos() -> dict[str, float]:
    return {k: 0.0 for k in EVENTOS}


def _e_consig(meta: dict[str, Any] | None, cedente_motor: str) -> bool:
    if meta:
        doc = str(meta.get("doc_cedente") or "").strip()
        if doc in DOCS_E_CONSIG:
            return True
        nome = str(meta.get("nm_cedente") or "").upper()
        return any(n in nome for n in NOMES_E_CONSIG)
    nome = (cedente_motor or "").upper()
    return any(n in nome for n in NOMES_E_CONSIG)


def _carregar_cadastro() -> dict[str, dict[str, Any]]:
    """Mapa documento → atributos consignado (empresa/evento); vazio se tabela ausente."""
    try:
        sb = get_supabase()
    except Exception:  # noqa: BLE001
        return {}
    out: dict[str, dict[str, Any]] = {}
    offset = 0
    docs = list(DOCS_CEDENTE_CONSIGNADO)
    cols = (
        "documento,empresa,cnpj_empresa,tipo_evento,nm_cedente,doc_cedente,"
        "nm_sacado,doc_sacado,tp_sacado"
    )
    try:
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
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        if "PGRST205" in msg or "Could not find the table" in msg or TABELA in msg:
            return {}
        raise
    return out


def _historico_mensal(ate: date) -> list[dict[str, Any]]:
    """Último dia útil de cada mês na série do motor (PDD)."""
    from carteira_movimentacoes import mapa_dc_bdr_diario

    serie = mapa_dc_bdr_diario()
    por_mes: dict[str, tuple[str, float]] = {}
    for iso, row in serie.items():
        d = _parse_iso(iso)
        if d is None or d > ate:
            continue
        mes = iso[:7]
        pdd = _money(row.get("pdd"))
        atual = por_mes.get(mes)
        if atual is None or iso > atual[0]:
            por_mes[mes] = (iso, pdd)
    out: list[dict[str, Any]] = []
    for mes in sorted(por_mes):
        iso, pdd = por_mes[mes]
        y, m = mes.split("-")
        meses = (
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
        label = f"{meses[int(m) - 1]}/{y[2:]}"
        out.append(
            {
                "mes": mes,
                "label": label,
                "data_iso": iso,
                "pdd": round(pdd, 2),
            }
        )
    return out


def _acumular_empresa(
    por_emp: dict[str, dict[str, Any]],
    *,
    chave: str,
    rotulo: str,
    via_cedente: bool,
    nm_cedente: str | None,
    cnpj_empresa: str | None,
    bucket: str,
    pdd: float,
) -> None:
    if chave not in por_emp:
        por_emp[chave] = {
            "empresa": rotulo,
            "via_cedente": via_cedente,
            "cnpj_empresa": cnpj_empresa,
            "nm_cedente": nm_cedente,
            "eventos": _zero_eventos(),
            "total": 0.0,
            "n": 0,
        }
    emp = por_emp[chave]
    if not emp.get("cnpj_empresa") and cnpj_empresa:
        emp["cnpj_empresa"] = cnpj_empresa
    emp["eventos"][bucket] += pdd
    emp["total"] += pdd
    emp["n"] += 1


def montar_pdd(data_base: str) -> dict[str, Any]:
    """PDD de toda a carteira do motor, aberta por empresa/cedente e evento."""
    dt = _parse_data_base(data_base)
    cadastro = _carregar_cadastro()
    aviso: str | None = None
    if not cadastro:
        aviso = (
            "Cadastro de consignado vazio — eventos ficam em NC/Outros; "
            "agrupamento pelo cedente do motor."
        )

    from carteira_movimentacoes import carregar_carteira_movimentacoes

    df = carregar_carteira_movimentacoes(dt)
    if df is None or df.empty:
        return {
            "data_base": _br(dt),
            "data_base_iso": dt.isoformat(),
            "fonte_valores": "motor",
            "fonte_cadastro": TABELA,
            "labels_evento": LABEL_EVENTO,
            "totais": {**_zero_eventos(), "total": 0.0, "pct": 0.0, "n": 0},
            "empresas": [],
            "outros": [],
            "totais_outros": {"pdd": 0.0, "n": 0, "n_empresas": 0},
            "historico": _historico_mensal(dt),
            "e_consig": {
                "cedentes": ["BMP", "VIA CAPITAL"],
                "face_total": 0.0,
                "face_com_pdd": 0.0,
                "face_sem_pdd": 0.0,
                "pdd": 0.0,
                "face_pdd_vencido": 0.0,
                "face_pdd_a_vencer": 0.0,
                "pizza_face": [],
                "pizza_pdd": [],
            },
            "n_empresas": 0,
            "aviso": "Sem posição do motor nesta data base.",
        }

    por_emp: dict[str, dict[str, Any]] = {}
    por_outro: dict[str, dict[str, Any]] = {}
    # Totais de carteira (toda a base)
    face_carteira = 0.0
    face_carteira_pdd = 0.0
    pdd_carteira = 0.0
    n_titulos = 0
    # Subconjunto e-consig (cadastro consignado)
    face_consig = 0.0
    face_consig_pdd = 0.0
    face_pdd_vencido = 0.0
    face_pdd_a_vencer = 0.0
    pdd_consig = 0.0
    n_consig = 0

    for _, row in df.iterrows():
        documento = str(row.get("documento") or "").strip()
        if not documento:
            continue

        face = _money(row.get("valor_face"))
        pdd = _money(row.get("vl_pdd"))
        if pdd == 0.0:
            pdd = _money(row.get("provisao_pdd"))

        n_titulos += 1
        face_carteira += face
        pdd_carteira += pdd
        if pdd > 0:
            face_carteira_pdd += face

        meta = cadastro.get(documento)
        cedente_motor = str(row.get("cedente") or "").strip()
        faixa = _norm_faixa(row.get("fx_pdd"))

        if meta:
            n_consig += 1
            if _e_consig(meta, cedente_motor):
                face_consig += face
                pdd_consig += pdd
                if pdd > 0:
                    face_consig_pdd += face
                    if _titulo_vencido(row, dt):
                        face_pdd_vencido += face
                    else:
                        face_pdd_a_vencer += face

            empresa_raw = str(meta.get("empresa") or "").strip()
            nm_cedente = (
                str(meta.get("nm_cedente") or "").strip() or cedente_motor
            )
            bucket = _bucket_evento(str(meta.get("tipo_evento") or ""))
            cnpj = str(meta.get("cnpj_empresa") or "").strip() or None
            if empresa_raw:
                chave = f"emp|{empresa_raw}"
                rotulo = empresa_raw
                via_cedente = False
            else:
                rotulo = nm_cedente or "(sem empresa)"
                chave = f"ced|{rotulo}"
                via_cedente = True
            _acumular_empresa(
                por_emp,
                chave=chave,
                rotulo=rotulo,
                via_cedente=via_cedente,
                nm_cedente=nm_cedente or None,
                cnpj_empresa=cnpj,
                bucket=bucket,
                pdd=pdd,
            )
            continue

        if _e_consig(None, cedente_motor):
            face_consig += face
            pdd_consig += pdd
            if pdd > 0:
                face_consig_pdd += face
                if _titulo_vencido(row, dt):
                    face_pdd_vencido += face
                else:
                    face_pdd_a_vencer += face

        # Fora do consignado privado: cedente × faixa
        if pdd <= 0:
            continue
        rotulo = cedente_motor or "(sem cedente)"
        if rotulo not in por_outro:
            por_outro[rotulo] = {
                "empresa": rotulo,
                "pdd": 0.0,
                "n": 0,
                "por_faixa": {fx: 0.0 for fx in FAIXAS_ORDEM},
            }
        o = por_outro[rotulo]
        o["pdd"] += pdd
        o["n"] += 1
        o["por_faixa"][faixa] = float(o["por_faixa"].get(faixa) or 0) + pdd

    total_pdd_tab = sum(e["total"] for e in por_emp.values())
    empresas_out: list[dict[str, Any]] = []
    for emp in por_emp.values():
        total = round(float(emp["total"]), 2)
        if total <= 0:
            continue
        ev = {k: round(float(emp["eventos"][k]), 2) for k in EVENTOS}
        empresas_out.append(
            {
                "empresa": emp["empresa"],
                "via_cedente": emp["via_cedente"],
                "cnpj_empresa": emp.get("cnpj_empresa"),
                "nm_cedente": emp.get("nm_cedente"),
                "afastamento": ev["afastamento"],
                "demissao": ev["demissao"],
                "rescisao": ev["rescisao"],
                "nc_outros": ev["nc_outros"],
                "total": total,
                "pct": round(100.0 * total / total_pdd_tab, 2) if total_pdd_tab else 0.0,
                "n": int(emp["n"]),
            }
        )

    empresas_out.sort(key=lambda e: (-e["total"], e["empresa"].upper()))

    totais_ev = _zero_eventos()
    for e in empresas_out:
        for k in EVENTOS:
            totais_ev[k] += float(e[k])
    totais_ev_r = {k: round(totais_ev[k], 2) for k in EVENTOS}
    total_geral = round(sum(totais_ev_r.values()), 2)

    outros_out: list[dict[str, Any]] = []
    for o in por_outro.values():
        pdd_o = round(float(o["pdd"]), 2)
        if pdd_o <= 0:
            continue
        faixas_pos = [
            {"faixa": fx, "pdd": round(float(o["por_faixa"].get(fx) or 0), 2)}
            for fx in reversed(FAIXAS_ORDEM)
            if float(o["por_faixa"].get(fx) or 0) > 0
        ]
        faixa_principal = faixas_pos[0]["faixa"] if faixas_pos else "AA"
        outros_out.append(
            {
                "empresa": o["empresa"],
                "faixa": faixa_principal,
                "pdd": pdd_o,
                "n": int(o["n"]),
                "faixas": faixas_pos,
            }
        )
    outros_out.sort(key=lambda e: (-e["pdd"], e["empresa"].upper()))
    total_outros = round(sum(float(e["pdd"]) for e in outros_out), 2)
    n_outros = sum(int(e["n"]) for e in outros_out)

    face_sem_pdd = round(max(face_consig - face_consig_pdd, 0.0), 2)
    face_consig_r = round(face_consig, 2)
    face_consig_pdd_r = round(face_consig_pdd, 2)
    face_pdd_venc_r = round(face_pdd_vencido, 2)
    face_pdd_avenc_r = round(face_pdd_a_vencer, 2)
    pdd_consig_r = round(pdd_consig, 2)

    return {
        "data_base": _br(dt),
        "data_base_iso": dt.isoformat(),
        "fonte_valores": "motor",
        "fonte_cadastro": TABELA,
        "labels_evento": LABEL_EVENTO,
        "totais": {
            **totais_ev_r,
            "total": total_geral,
            "pct": 100.0 if total_geral else 0.0,
            "n": n_consig,
            "n_consignado": n_consig,
            "n_carteira": n_titulos,
            "pdd_carteira": round(pdd_carteira, 2),
            "face_carteira": round(face_carteira, 2),
        },
        "empresas": empresas_out,
        "outros": outros_out,
        "totais_outros": {
            "pdd": total_outros,
            "n": n_outros,
            "n_empresas": len(outros_out),
        },
        "historico": _historico_mensal(dt),
        "e_consig": {
            "cedentes": ["BMP", "VIA CAPITAL"],
            "face_total": face_consig_r,
            "face_com_pdd": face_consig_pdd_r,
            "face_sem_pdd": face_sem_pdd,
            "pdd": pdd_consig_r,
            "face_pdd_vencido": face_pdd_venc_r,
            "face_pdd_a_vencer": face_pdd_avenc_r,
            "pizza_face": [
                {
                    "nome": "Sem PDD",
                    "valor": face_sem_pdd,
                    "peso": round(100.0 * face_sem_pdd / face_consig_r, 2)
                    if face_consig_r
                    else 0.0,
                },
                {
                    "nome": "Com PDD",
                    "valor": face_consig_pdd_r,
                    "peso": round(100.0 * face_consig_pdd_r / face_consig_r, 2)
                    if face_consig_r
                    else 0.0,
                },
            ],
            "pizza_pdd": [
                {
                    "nome": "A vencer",
                    "valor": face_pdd_avenc_r,
                    "peso": round(100.0 * face_pdd_avenc_r / face_consig_pdd_r, 2)
                    if face_consig_pdd_r
                    else 0.0,
                },
                {
                    "nome": "Vencido",
                    "valor": face_pdd_venc_r,
                    "peso": round(100.0 * face_pdd_venc_r / face_consig_pdd_r, 2)
                    if face_consig_pdd_r
                    else 0.0,
                },
            ],
        },
        "n_empresas": len(empresas_out),
        "aviso": aviso,
    }
