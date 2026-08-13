"""Datas da última atualização das fontes usadas no dashboard."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from carteira_movimentacoes import CACHE_PATH, DIARIO_PATH, META_PATH, RELATORIOS_DIR


def _br(d: date | None) -> str | None:
    if d is None:
        return None
    return d.strftime("%d/%m/%Y")


def _parse_iso(texto: object) -> date | None:
    s = str(texto or "").strip()[:10]
    if len(s) < 10 or s[4] != "-":
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def _ultima_data_liquidez() -> date | None:
    from db import mapa_liquidez_diario

    mapa = mapa_liquidez_diario()
    if not mapa:
        return None
    return max((_parse_iso(k) for k in mapa), default=None)


def _ultima_data_classes() -> date | None:
    """Última data de PL/PDD por classe (cache local ou Supabase)."""
    cache = Path(__file__).resolve().parent / "data" / "pl_pdd_cache.json"
    datas: list[date] = []
    if cache.exists():
        try:
            regs = json.loads(cache.read_text(encoding="utf-8"))
            for reg in regs if isinstance(regs, list) else []:
                d = _parse_iso(reg.get("data_posicao"))
                if d is not None:
                    datas.append(d)
        except (OSError, json.JSONDecodeError, TypeError):
            pass
    if datas:
        return max(datas)
    try:
        from db import get_supabase

        rows = (
            get_supabase()
            .table("fidc_pl_pdd_diario")
            .select("data_posicao")
            .order("data_posicao", desc=True)
            .limit(1)
            .execute()
            .data
            or []
        )
        if rows:
            return _parse_iso(rows[0].get("data_posicao"))
    except Exception:  # noqa: BLE001
        pass
    return None


def _ultima_data_eventos() -> date | None:
    """Última data de movimento no cache JSONL (ou meta, se houver)."""
    if CACHE_PATH.exists():
        # Lê só o final do arquivo (eventos ordenados por data).
        try:
            with CACHE_PATH.open("rb") as fh:
                fh.seek(0, 2)
                size = fh.tell()
                fh.seek(max(0, size - 65536))
                chunk = fh.read().decode("utf-8", errors="replace")
            datas: list[date] = []
            for line in chunk.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                d = _parse_iso(ev.get("data"))
                if d is not None:
                    datas.append(d)
            if datas:
                return max(datas)
        except OSError:
            pass
    if META_PATH.exists():
        try:
            meta = json.loads(META_PATH.read_text(encoding="utf-8"))
            d = _parse_iso(meta.get("incremental_desde") or meta.get("atualizado_em"))
            return d
        except (OSError, json.JSONDecodeError, TypeError):
            pass
    return None


def _ultima_data_estoque_bdr() -> date | None:
    datas: list[date] = []
    for path in RELATORIOS_DIR.glob("EstoqueBDR_*.csv"):
        stem = path.stem.replace("EstoqueBDR_", "")
        d = _parse_iso(stem)
        if d is not None:
            datas.append(d)
    return max(datas) if datas else None


def _ultima_data_carteira_propria() -> date | None:
    """Última data em que o motor consegue montar a carteira.

    Considera série diária, export EstoqueMotor_*.csv e último evento BDR
    (movimentações), pois a série pode atrasar quando a IDSF não tem liquidez.
    """
    datas: list[date] = []
    if DIARIO_PATH.exists():
        try:
            raw = json.loads(DIARIO_PATH.read_text(encoding="utf-8"))
            por_dia = raw.get("por_dia") or {}
            for k in por_dia:
                d = _parse_iso(k)
                if d is not None:
                    datas.append(d)
        except (OSError, json.JSONDecodeError, TypeError):
            pass
    for path in RELATORIOS_DIR.glob("EstoqueMotor_*.csv"):
        d = _parse_iso(path.stem.replace("EstoqueMotor_", ""))
        if d is not None:
            datas.append(d)
    ev = _ultima_data_eventos()
    if ev is not None:
        datas.append(ev)
    return max(datas) if datas else None


def status_atualizacoes() -> dict[str, Any]:
    out: list[dict[str, Any]] = []
    for id_, label, data in (
        ("idsf", "IDSF", _ultima_data_liquidez()),
        ("idsf_classes", "IDSF - Classes", _ultima_data_classes()),
        ("bdr_movimentacoes", "BDR - Movimentações", _ultima_data_eventos()),
        ("bdr_estoque", "BDR - Estoque", _ultima_data_estoque_bdr()),
        ("carteira_propria", "Carteira Própria", _ultima_data_carteira_propria()),
    ):
        out.append(
            {
                "id": id_,
                "label": label,
                "data": _br(data),
                "data_iso": data.isoformat() if data else None,
            }
        )
    return {"itens": out}
