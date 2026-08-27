"""Orquestra a atualização de todas as bases até a última data possível."""

from __future__ import annotations

import builtins
import os
import sys
import threading
import traceback
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from dateutil.relativedelta import relativedelta

# MEZ IV passou a aparecer na IDSF por volta desta data.
MEZ_IV_DESDE = date(2026, 6, 23)
MEZ_IV_ID = 34691304


def _print_seguro(*args: Any, **kwargs: Any) -> None:
    """Stdout do uvicorn no Windows às vezes quebra no flush (Errno 22)."""
    kwargs.pop("flush", None)
    kwargs.setdefault("file", sys.stderr)
    try:
        builtins.print(*args, **kwargs)
    except OSError:
        pass


print = _print_seguro  # noqa: A001

_lock = threading.Lock()
_estado: dict[str, Any] = {
    "status": "idle",
    "etapa": None,
    "etapas": [],
    "iniciado_em": None,
    "terminado_em": None,
    "erro": None,
    "atualizacoes": None,
}


def status_job() -> dict[str, Any]:
    with _lock:
        return dict(_estado)


def _set(**kwargs: Any) -> None:
    with _lock:
        _estado.update(kwargs)


def _registrar_etapa(id_: str, label: str, status: str, detalhe: Any = None) -> None:
    with _lock:
        etapas: list[dict[str, Any]] = list(_estado.get("etapas") or [])
        encontrado = False
        for et in etapas:
            if et.get("id") == id_:
                et["status"] = status
                et["detalhe"] = detalhe
                encontrado = True
                break
        if not encontrado:
            etapas.append(
                {"id": id_, "label": label, "status": status, "detalhe": detalhe}
            )
        _estado["etapas"] = etapas
        _estado["etapa"] = label if status == "running" else _estado.get("etapa")


def _agora_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _fim_alvo() -> date:
    """Última data operacional para baixar/atualizar: D-2 (nunca o mesmo dia)."""
    from conciliacao import data_base_maxima

    return data_base_maxima()


def _etapa_liquidez(fim: date) -> dict[str, Any]:
    from atualizacoes import _ultima_data_liquidez
    from carregar_liquidez_idsf import carregar

    ultima = _ultima_data_liquidez()
    inicio = (ultima + timedelta(days=1)) if ultima else fim - relativedelta(months=1)
    if inicio > fim:
        return {"ok": True, "mensagem": f"já completo até {fim}", "registros": 0}
    return carregar(inicio=inicio, fim=fim, so_pendentes=True)


def _etapa_classes(fim: date) -> dict[str, Any]:
    from carregar_pl_pdd import (
        carregar,
        ids_carteira_no_cache,
        ultima_data_cache,
    )
    from idsf_pl_pdd import carteiras_idsf

    ultima = ultima_data_cache()
    inicio = (ultima - timedelta(days=3)) if ultima else fim - relativedelta(months=2)
    faltantes = set(carteiras_idsf()) - ids_carteira_no_cache()
    if MEZ_IV_ID in faltantes or MEZ_IV_ID not in ids_carteira_no_cache():
        inicio = min(inicio, MEZ_IV_DESDE)
    if inicio > fim:
        return {"ok": True, "mensagem": f"já completo até {fim}", "registros_upsert": 0}
    return carregar(inicio=inicio, fim=fim, mesclar_cache=True)


def _etapa_bdr_mov(fim: date) -> dict[str, Any]:
    from carregar_movimentacoes_bdr import (
        carregar_periodo,
        max_periodo_carregado,
        resolver_fundo,
    )

    fundo = resolver_fundo(None)
    cnpj = str(fundo["cnpj"])
    tp = str(fundo.get("bdr_tp_contabil_mov") or "A")
    resumos: list[dict[str, Any]] = []
    for tipo in ("aquisicoes", "liquidacoes"):
        ultimo = max_periodo_carregado(tipo, cnpj)  # type: ignore[arg-type]
        inicio = (ultimo + timedelta(days=1)) if ultimo else fim - relativedelta(months=1)
        if inicio > fim:
            resumos.append(
                {"tipo": tipo, "ok": True, "mensagem": f"já completo até {fim}"}
            )
            continue
        resumo = carregar_periodo(
            tipo,  # type: ignore[arg-type]
            inicio,
            fim,
            cnpj=cnpj,
            tp_contabil=tp,
        )
        resumos.append(resumo)
    return {"resumos": resumos}


def _etapa_eventos() -> dict[str, Any]:
    from atualizacoes import _ultima_data_eventos
    from atualizar_eventos_desde import atualizar_eventos

    ultima = _ultima_data_eventos()
    # Reprocessa uma semana de overlap para capturar atrasos de upsert.
    desde = (ultima - timedelta(days=7)) if ultima else date.today() - relativedelta(months=1)
    meta = atualizar_eventos(desde)
    try:
        from aquisicoes_volume import reconstruir_cache

        reconstruir_cache(forcar=True)
        meta = {**(meta or {}), "aquisicoes_agg_cache": "ok"}
    except Exception as exc:  # noqa: BLE001
        meta = {**(meta or {}), "aquisicoes_agg_cache": f"erro: {exc}"}
    return meta


def _etapa_estoque(fim: date) -> dict[str, Any]:
    import requests

    from atualizacoes import _ultima_data_estoque_bdr
    from baixar_estoque_bdr import OUT_DIR, baixar_estoque
    from bdr_arquivos import obter_token
    from carregar_consignado_cadastro import sincronizar_cadastro, tabela_disponivel
    from conciliacao import dias_uteis

    ultima = _ultima_data_estoque_bdr()
    inicio = (ultima + timedelta(days=1)) if ultima else fim - relativedelta(days=14)
    datas = dias_uteis(inicio, fim) if inicio <= fim else []
    faltantes = [
        d
        for d in datas
        if not (OUT_DIR / f"EstoqueBDR_{d.isoformat()}.csv").exists()
    ]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ok = 0
    falhas: list[dict[str, str]] = []
    if faltantes:
        sess = requests.Session()
        token = obter_token(sess)
        for d in faltantes:
            destino = OUT_DIR / f"EstoqueBDR_{d.isoformat()}.csv"
            try:
                # Sempre EstoqueBDR (schema ampliado), nunca o endpoint legado /estoque.
                baixar_estoque(
                    d,
                    out=destino,
                    tipo="estoqueBDR",
                    token=token,
                    session=sess,
                )
                ok += 1
            except Exception as exc:  # noqa: BLE001
                falhas.append({"data": d.isoformat(), "erro": str(exc)})
                sess = requests.Session()
                try:
                    token = obter_token(sess)
                except Exception:  # noqa: BLE001
                    pass

    # Cadastro consignado: só contratos novos (documento = nm_cessao_bdr).
    cadastro: dict[str, Any] | None = None
    latest = sorted(OUT_DIR.glob("EstoqueBDR_*.csv"))
    if latest:
        if not tabela_disponivel():
            cadastro = {
                "ok": False,
                "erro": (
                    "Tabela fidc_consignado_cadastro ausente — "
                    "execute sql/fidc_consignado_cadastro.sql"
                ),
            }
        else:
            try:
                cadastro = {"ok": True, **sincronizar_cadastro(latest[-1])}
            except Exception as exc:  # noqa: BLE001
                cadastro = {"ok": False, "erro": str(exc)}

    return {
        "baixados": ok,
        "faltantes": len(faltantes),
        "falhas": falhas,
        "cadastro_consignado": cadastro,
    }


def _etapa_pdfs_sub(fim: date) -> dict[str, Any]:
    """Guarda PDF da carteira SUB (IDSF 566391) até o fim operacional (D-2)."""
    from baixar_carteiras_pdf_mensal import OUT_DIR as PDF_DIR
    from baixar_carteiras_pdf_mensal import baixar_pdfs_periodo

    existentes = sorted(PDF_DIR.glob("Carteira_566391_*.pdf"))
    if existentes:
        inicio = fim - relativedelta(days=21)
        for p in existentes:
            partes = p.stem.split("_")
            # Carteira_566391_d_m_yyyy
            if len(partes) >= 5:
                try:
                    d = date(int(partes[-1]), int(partes[-2]), int(partes[-3]))
                    inicio = max(inicio, d + timedelta(days=1))
                except ValueError:
                    pass
    else:
        inicio = date(2026, 8, 11)

    if inicio > fim:
        return {"ok": True, "mensagem": f"PDFs SUB já completos até {fim}", "baixados": 0}
    return baixar_pdfs_periodo(inicio, fim, forcar=False)


def _etapa_serie() -> dict[str, Any]:
    from atualizacoes import _parse_iso, _ultima_data_liquidez
    from carteira_movimentacoes import mapa_dc_bdr_diario, reconstruir_serie_diaria

    serie = mapa_dc_bdr_diario()
    datas_serie = [_parse_iso(k) for k in serie]
    datas_serie = [d for d in datas_serie if d is not None]
    ultima_serie = max(datas_serie) if datas_serie else None
    ultima_liq = _ultima_data_liquidez()

    # Sem dias novos de liquidez, a série não avança (datas_alvo vêm da IDSF).
    if (
        ultima_serie is not None
        and ultima_liq is not None
        and ultima_serie >= ultima_liq
        and len(serie) > 0
    ):
        return {
            "ok": True,
            "pulado": True,
            "mensagem": (
                f"série já cobre a liquidez até {ultima_liq.isoformat()} "
                f"({len(serie)} dias)"
            ),
            "dias": len(serie),
            "ultima": ultima_serie.isoformat(),
        }

    def progresso(fase: str, info: dict[str, float]) -> None:
        _registrar_etapa(
            "serie",
            "Carteira própria (série)",
            "running",
            {"fase": fase, **{k: info.get(k) for k in info}},
        )

    payload = reconstruir_serie_diaria(progresso=progresso)
    por_dia = (payload.get("por_dia") or {}) if isinstance(payload, dict) else {}
    return {
        "dias": len(por_dia),
        "ultima": max(por_dia.keys()) if por_dia else None,
        "pulado": False,
    }


def _etapa_taxas(fim: date) -> dict[str, Any]:
    from carregar_taxas_idsf import carregar, tabela_disponivel

    if not tabela_disponivel():
        return {
            "ok": False,
            "erro": "Tabela fidc_taxas_classe ausente — execute sql/fidc_taxas_classe.sql",
        }
    try:
        return {"ok": True, **carregar(fim=fim)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "erro": str(exc)}


def _etapa_classes_meta() -> dict[str, Any]:
    from carregar_classes_meta import carregar, tabela_disponivel

    if not tabela_disponivel():
        return {
            "ok": False,
            "erro": "Tabela fidc_classes_meta ausente — execute sql/fidc_classes_meta.sql",
        }
    try:
        return {"ok": True, **carregar()}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "erro": str(exc)}


def _etapa_cdi(fim: date) -> dict[str, Any]:
    from cdi_bcb import carregar

    try:
        return {"ok": True, **carregar(fim=fim)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "erro": str(exc)}


def _etapa_passivo_dist(fim: date) -> dict[str, Any]:
    from carregar_passivo_movimentos import carregar

    try:
        return {"ok": True, **carregar(fim=fim)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "erro": str(exc)}


def _montar_etapas(fim: date) -> list[tuple[str, str, Callable[[], dict[str, Any]]]]:
    return [
        ("liquidez", "IDSF - Liquidez", lambda: _etapa_liquidez(fim)),
        ("classes", "IDSF - Classes (PL/PDD)", lambda: _etapa_classes(fim)),
        ("classes_meta", "IDSF - Meta classes (%CDI)", _etapa_classes_meta),
        ("cdi", "BCB - CDI (SGS 12)", lambda: _etapa_cdi(fim)),
        ("passivo_dist", "IDSF - Amort/Juros cotas", lambda: _etapa_passivo_dist(fim)),
        ("taxas", "IDSF - Taxas (classes)", lambda: _etapa_taxas(fim)),
        ("bdr_mov", "BDR - Movimentações", lambda: _etapa_bdr_mov(fim)),
        ("eventos", "Cache de eventos", _etapa_eventos),
        ("estoque", "BDR - Estoque", lambda: _etapa_estoque(fim)),
        ("pdfs_sub", "IDSF - PDFs carteira SUB", lambda: _etapa_pdfs_sub(fim)),
        ("serie", "Carteira própria (série)", _etapa_serie),
    ]


def rodar_atualizacao() -> None:
    fim = _fim_alvo()
    _set(
        status="running",
        etapa=None,
        etapas=[],
        iniciado_em=_agora_iso(),
        terminado_em=None,
        erro=None,
        atualizacoes=None,
        fim_alvo=fim.isoformat(),
    )
    try:
        for id_, label, fn in _montar_etapas(fim):
            _registrar_etapa(id_, label, "running")
            _set(etapa=label)
            try:
                detalhe = fn()
                _registrar_etapa(id_, label, "ok", detalhe)
            except Exception as exc:  # noqa: BLE001
                _registrar_etapa(id_, label, "erro", {"erro": str(exc)})
                raise

        from atualizacoes import status_atualizacoes

        _set(
            status="ok",
            etapa=None,
            terminado_em=_agora_iso(),
            atualizacoes=status_atualizacoes(),
        )
    except Exception as exc:  # noqa: BLE001
        _set(
            status="erro",
            terminado_em=_agora_iso(),
            erro=str(exc),
            traceback=traceback.format_exc(),
        )


def iniciar_atualizacao() -> dict[str, Any]:
    if os.getenv("VERCEL"):
        return {
            "aceito": False,
            "motivo": (
                "Atualizar não roda no Vercel: não há disco persistente nem job "
                "em background. Execute no backend local (python -m uvicorn …)."
            ),
        }
    with _lock:
        if _estado.get("status") == "running":
            return {"aceito": False, "motivo": "Já existe uma atualização em andamento.", **dict(_estado)}
    thread = threading.Thread(target=rodar_atualizacao, name="atualizar-bases", daemon=True)
    thread.start()
    return {"aceito": True, **status_job()}
