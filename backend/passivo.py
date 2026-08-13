"""Passivo por classe de cota (MEZ / SUB).

Conferência da SUB usa sempre o PL do motor, nunca o PL consolidado IDSF.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from db import get_supabase
from idsf_pl_pdd import carteiras_idsf
from marcar_cota_passivo import comparar_com_idsf, marcar_cota

TABELA_PL = "fidc_pl_pdd_diario"
TABELA_META = "fidc_classes_meta"

# Ordem de exibição e rótulos
CLASSES_ORDEM: list[tuple[int, str, str]] = [
    (34691, "MEZ", "Mezanino I"),
    (34691302, "MEZ_II", "Mezanino II"),
    (34691303, "MEZ_III", "Mezanino III"),
    (34691304, "MEZ_IV", "Mezanino IV"),
    (566391, "SUB", "Subordinada"),
]

ID_SUB = 566391
ID_CONSOLIDADO = 0
TOLERANCIA_SUB_ABS = 1.0  # R$ |PL calc − PL IDSF|

# Seed se meta ainda sem pct_cdi
PCT_CDI_SEED: dict[int, float] = {
    34691: 170.0,
    34691302: 150.0,
    34691303: 150.0,
    34691304: 150.0,
}


def _parse_data_base(texto: str) -> date:
    t = texto.strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(t[:10] if fmt.startswith("%Y") else t, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Data base inválida: {texto}")


def _br(d: date | None) -> str | None:
    return d.strftime("%d/%m/%Y") if d else None


def _float(v: object) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _classe_por_id(id_carteira: int) -> tuple[str, str]:
    for cid, codigo, nome in CLASSES_ORDEM:
        if cid == id_carteira:
            return codigo, nome
    return f"C_{id_carteira}", f"Carteira {id_carteira}"


def _dt_ref_pl(data_base: date) -> date | None:
    """Última data com PL ≤ data_base (pode faltar SUB em dias recentes)."""
    sb = get_supabase()
    rows = (
        sb.table(TABELA_PL)
        .select("data_posicao")
        .eq("id_carteira", ID_CONSOLIDADO)
        .lte("data_posicao", data_base.isoformat())
        .order("data_posicao", desc=True)
        .limit(1)
        .execute()
        .data
        or []
    )
    if rows:
        return date.fromisoformat(str(rows[0]["data_posicao"])[:10])
    rows = (
        sb.table(TABELA_PL)
        .select("data_posicao")
        .lte("data_posicao", data_base.isoformat())
        .order("data_posicao", desc=True)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        return None
    return date.fromisoformat(str(rows[0]["data_posicao"])[:10])


def _pl_do_dia(dt: date) -> dict[int, dict[str, Any]]:
    sb = get_supabase()
    cols_full = "id_carteira,apelido,pl,pdd,qtde_cotas,valor_cota"
    cols_basic = "id_carteira,apelido,pl,pdd"
    try:
        rows = (
            sb.table(TABELA_PL)
            .select(cols_full)
            .eq("data_posicao", dt.isoformat())
            .execute()
            .data
            or []
        )
    except Exception:  # noqa: BLE001
        rows = (
            sb.table(TABELA_PL)
            .select(cols_basic)
            .eq("data_posicao", dt.isoformat())
            .execute()
            .data
            or []
        )
    out: dict[int, dict[str, Any]] = {}
    for row in rows:
        try:
            cid = int(row["id_carteira"])
        except (TypeError, ValueError, KeyError):
            continue
        out[cid] = row
    return out


def _cotas_mais_recentes(id_carteira: int, ate: date) -> dict[str, float | None]:
    """Última qtde/valor_cota não nulos ≤ data (cargas antigas podem ter PL sem cotas)."""
    try:
        rows = (
            get_supabase()
            .table(TABELA_PL)
            .select("qtde_cotas,valor_cota,data_posicao")
            .eq("id_carteira", id_carteira)
            .lte("data_posicao", ate.isoformat())
            .not_.is_("qtde_cotas", "null")
            .order("data_posicao", desc=True)
            .limit(1)
            .execute()
            .data
            or []
        )
    except Exception:  # noqa: BLE001
        return {"qtde_cotas": None, "valor_cota": None}
    if not rows:
        return {"qtde_cotas": None, "valor_cota": None}
    return {
        "qtde_cotas": _float(rows[0].get("qtde_cotas")),
        "valor_cota": _float(rows[0].get("valor_cota")),
    }


def _meta_classes() -> dict[int, dict[str, Any]]:
    try:
        rows = get_supabase().table(TABELA_META).select("*").execute().data or []
    except Exception:  # noqa: BLE001
        return {}
    out: dict[int, dict[str, Any]] = {}
    for row in rows:
        try:
            out[int(row["id_carteira"])] = row
        except (TypeError, ValueError, KeyError):
            continue
    return out


def _parse_meta_date(raw: object) -> date | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def subordinacao_pct(pl_por_carteira: dict[int, dict[str, Any]]) -> float | None:
    pl_sub = _float((pl_por_carteira.get(ID_SUB) or {}).get("pl"))
    pl_tot = _float((pl_por_carteira.get(ID_CONSOLIDADO) or {}).get("pl"))
    if pl_tot is None or pl_tot <= 0:
        ids = [cid for cid, _, _ in CLASSES_ORDEM]
        pl_tot = sum(_float((pl_por_carteira.get(i) or {}).get("pl")) or 0.0 for i in ids)
    if not pl_tot or pl_sub is None:
        return None
    return round(float(pl_sub) / float(pl_tot) * 100.0, 2)


def _meta_campo(m: dict[str, Any], chave: str) -> object:
    if m.get(chave) is not None and m.get(chave) != "":
        return m.get(chave)
    dados = m.get("dados")
    if isinstance(dados, dict):
        nested = dados.get("_passivo")
        if isinstance(nested, dict) and nested.get(chave) is not None:
            return nested.get(chave)
    return None


def montar_passivo(data_base: str) -> dict[str, Any]:
    dt_pedida = _parse_data_base(data_base)
    try:
        dt = _dt_ref_pl(dt_pedida)
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        if "PGRST205" in msg or TABELA_PL in msg:
            raise RuntimeError(
                f"Tabela {TABELA_PL} ausente ou incompleta. "
                "Execute sql/fidc_pl_pdd_diario.sql e sql/fidc_pl_pdd_diario_cotas.sql."
            ) from exc
        raise

    if dt is None:
        return {
            "data_base": _br(dt_pedida),
            "data_base_iso": dt_pedida.isoformat(),
            "dt_ref_pl": None,
            "classes": [],
            "subordinacao_pct": None,
            "conferencia_sub": None,
            "aviso": "Sem PL/PDD carregado para esta data.",
        }

    pl_dia = _pl_do_dia(dt)
    meta = _meta_classes()
    ids_env = set(carteiras_idsf())
    classes_out: list[dict[str, Any]] = []

    # Pré-carrega CDI cobrindo o início mais antigo das mez
    inicios: list[date] = []
    for cid, codigo, _ in CLASSES_ORDEM:
        if not codigo.startswith("MEZ"):
            continue
        m = meta.get(cid) or {}
        di = _parse_meta_date(_meta_campo(m, "data_inicio_cota"))
        if di:
            inicios.append(di)
    cdi_mapa = None
    if inicios:
        try:
            from cdi_bcb import mapa_cdi

            cdi_mapa = mapa_cdi(min(inicios) - timedelta(days=5), dt, atualizar=True)
        except Exception:  # noqa: BLE001
            cdi_mapa = None

    for id_carteira, codigo, nome in CLASSES_ORDEM:
        if id_carteira not in ids_env and id_carteira not in pl_dia:
            continue
        row = dict(pl_dia.get(id_carteira) or {})
        m = meta.get(id_carteira) or {}
        pl = _float(row.get("pl")) or 0.0
        qtde = _float(row.get("qtde_cotas"))
        valor_idsf = _float(row.get("valor_cota"))
        if qtde is None or qtde <= 0:
            fb = _cotas_mais_recentes(id_carteira, dt)
            qtde = fb.get("qtde_cotas")
            if valor_idsf is None:
                valor_idsf = fb.get("valor_cota")

        pct_cdi = _float(_meta_campo(m, "pct_cdi"))
        if pct_cdi is None and codigo.startswith("MEZ"):
            pct_cdi = PCT_CDI_SEED.get(id_carteira)

        cota_inicial = _float(_meta_campo(m, "cota_inicial"))
        data_inicio = _parse_meta_date(_meta_campo(m, "data_inicio_cota"))
        venc = _parse_meta_date(_meta_campo(m, "vencimento") or m.get("vencimento"))

        valor_app: float | None = None
        aviso_marcacao: str | None = None
        dias_uteis_marcacao: int | None = None

        if codigo.startswith("MEZ") and pct_cdi and cota_inicial and data_inicio:
            try:
                from carregar_passivo_movimentos import mapa_dist_por_carteira

                dist = mapa_dist_por_carteira(id_carteira, data_inicio, dt)
            except Exception:  # noqa: BLE001
                dist = {}
            marc = marcar_cota(
                cota_inicial=cota_inicial,
                data_inicio=data_inicio,
                data_fim=dt,
                pct_cdi=pct_cdi,
                cdi_por_dia=cdi_mapa,
                dist_por_dia=dist,
            )
            valor_app = marc.get("valor_cota")
            aviso_marcacao = marc.get("aviso")
            dias_uteis_marcacao = marc.get("dias_uteis")
            n_dist = marc.get("n_distribuicoes")
            total_dist = marc.get("total_distribuido")
        elif qtde and qtde > 0:
            # SUB ou sem meta: PL ÷ qtde
            valor_app = round(pl / qtde, 8)
            n_dist = None
            total_dist = None
        else:
            n_dist = None
            total_dist = None

        cmp_ = comparar_com_idsf(valor_app, valor_idsf)

        classes_out.append(
            {
                "id_carteira": id_carteira,
                "classe": codigo,
                "nome": nome,
                "apelido": str(row.get("apelido") or m.get("apelido") or nome),
                "pl": round(pl, 2),
                "pdd": round(_float(row.get("pdd")) or 0.0, 2),
                "qtde_cotas": qtde,
                "valor_cota_idsf": valor_idsf,
                "valor_cota_app": valor_app,
                "pct_cdi": pct_cdi,
                "cota_inicial": cota_inicial,
                "data_inicio_cota": _br(data_inicio),
                "data_inicio_cota_iso": data_inicio.isoformat() if data_inicio else None,
                "dias_uteis_marcacao": dias_uteis_marcacao,
                "n_distribuicoes": n_dist,
                "total_distribuido": total_dist,
                "aviso_marcacao": aviso_marcacao,
                "delta_cota": cmp_.get("delta_cota"),
                "delta_pct": cmp_.get("delta_pct"),
                "ok_marcacao": cmp_.get("ok_marcacao"),
                "vencimento": _br(venc),
                "vencimento_iso": venc.isoformat() if venc else None,
                "n_cotistas": None,
            }
        )

    from risco import pl_motor_do_dia

    motor = pl_motor_do_dia(dt)
    pl_fundo = _float(motor.get("pl"))
    aviso_pl: str | None = None
    if pl_fundo is None or pl_fundo <= 0:
        aviso_pl = "Sem PL do motor para esta data — conferência da SUB não usa PL IDSF."
        pl_fundo = 0.0

    passivo_mez_idsf = 0.0
    passivo_mez_app = 0.0
    pl_sub_idsf = 0.0
    qtde_sub: float | None = None
    cota_sub_idsf: float | None = None
    for c in classes_out:
        codigo = str(c.get("classe") or "")
        pl_c = float(c.get("pl") or 0)
        qtde_c = _float(c.get("qtde_cotas"))
        cota_app = _float(c.get("valor_cota_app"))
        if codigo.startswith("MEZ"):
            passivo_mez_idsf += pl_c
            if qtde_c and qtde_c > 0 and cota_app:
                passivo_mez_app += qtde_c * cota_app
            else:
                passivo_mez_app += pl_c
        elif codigo == "SUB":
            pl_sub_idsf = pl_c
            qtde_sub = qtde_c
            cota_sub_idsf = _float(c.get("valor_cota_idsf"))

    # Identidade: PL motor − PL mez = PL SUB
    tem_motor = not motor.get("sem_serie") and pl_fundo > 0
    pl_sub_calc = round(pl_fundo - passivo_mez_idsf, 2) if tem_motor else None
    delta_sub = (
        round(pl_sub_calc - pl_sub_idsf, 2) if pl_sub_calc is not None else None
    )
    cota_sub_calc = (
        round(pl_sub_calc / qtde_sub, 8)
        if pl_sub_calc is not None and qtde_sub and qtde_sub > 0
        else None
    )
    pl_sub_via_app = (
        round(pl_fundo - passivo_mez_app, 2) if tem_motor else None
    )
    conferencia_sub = {
        "pl_fundo": round(pl_fundo, 2) if tem_motor else None,
        "fonte_pl": "motor",
        "passivo_mez": round(passivo_mez_idsf, 2),
        "passivo_mez_app": round(passivo_mez_app, 2),
        "pl_sub_calc": pl_sub_calc,
        "pl_sub_idsf": round(pl_sub_idsf, 2),
        "delta": delta_sub,
        "ok": (
            delta_sub is not None and abs(delta_sub) <= TOLERANCIA_SUB_ABS
        ),
        "pl_sub_via_app": pl_sub_via_app,
        "delta_via_app": (
            round(pl_sub_via_app - pl_sub_idsf, 2)
            if pl_sub_via_app is not None
            else None
        ),
        "cota_sub_calc": cota_sub_calc,
        "cota_sub_idsf": cota_sub_idsf,
        "formula": "PL motor - PL mez = PL SUB",
    }

    return {
        "data_base": _br(dt_pedida),
        "data_base_iso": dt_pedida.isoformat(),
        "dt_ref_pl": dt.isoformat(),
        "dt_ref_pl_br": _br(dt),
        "pl_consolidado": round(pl_fundo, 2) if tem_motor else None,
        "subordinacao_pct": subordinacao_pct(pl_dia),
        "conferencia_sub": conferencia_sub,
        "classes": classes_out,
        "aviso": aviso_pl,
    }


def calcular_subordinacao_para_data(data_base: date) -> float | None:
    """Helper para o KPI do dashboard / risco."""
    try:
        dt = _dt_ref_pl(data_base)
        if dt is None:
            return None
        return subordinacao_pct(_pl_do_dia(dt))
    except Exception:  # noqa: BLE001
        return None
