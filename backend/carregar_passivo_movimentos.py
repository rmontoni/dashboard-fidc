"""Carga de amortização/juros do passivo (PortfolioLiabilityMovements)."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

import requests
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv

from pathlib import Path

from db import get_supabase
from idsf_pl_pdd import carteiras_idsf, token_idsf
from passivo import CLASSES_ORDEM

TABELA = "fidc_passivo_dist_diario"
SQL_HINT = "backend/sql/fidc_passivo_dist_diario.sql"
URL = "https://prod.idsf.com.br/api/Fundo/PortfolioLiabilityMovements"
TIPOS_DIST = frozenset({"Amortização", "Juros"})
CACHE_PATH = Path(__file__).resolve().parent / "data" / "passivo_dist_cache.json"


def tabela_disponivel() -> bool:
    try:
        get_supabase().table(TABELA).select("data").limit(1).execute()
        return True
    except Exception:  # noqa: BLE001
        return False


def _parse_date(texto: object) -> date | None:
    s = str(texto or "").strip()
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def buscar_movimentos(
    id_carteira: int,
    data_inicio: date,
    data_fim: date,
    *,
    token: str | None = None,
    timeout: int = 180,
) -> list[dict[str, Any]]:
    tok = token or token_idsf()
    body = {
        "idCarteira": id_carteira,
        "dataInicio": data_inicio.isoformat(),
        "dataFim": data_fim.isoformat(),
    }
    resp = requests.get(
        URL,
        headers={"token": tok, "Token": tok, "Content-Type": "application/json"},
        json=body,
        timeout=timeout,
    )
    if resp.status_code == 400:
        try:
            msg = str((resp.json() or {}).get("Message") or "")
        except Exception:  # noqa: BLE001
            msg = resp.text or ""
        if "vazia" in msg.lower() or "null" in msg.lower() or "reference" in msg.lower():
            return []
        resp.raise_for_status()
    resp.raise_for_status()
    payload = resp.json()
    if isinstance(payload, dict):
        model = payload.get("Model", payload)
        if isinstance(model, str):
            model = json.loads(model) if model.strip() else []
        payload = model
    if not isinstance(payload, list):
        return []
    return [m for m in payload if isinstance(m, dict)]


def _qtde_do_dia(id_carteira: int, dia: date) -> float | None:
    try:
        rows = (
            get_supabase()
            .table("fidc_pl_pdd_diario")
            .select("qtde_cotas")
            .eq("id_carteira", id_carteira)
            .eq("data_posicao", dia.isoformat())
            .limit(1)
            .execute()
            .data
            or []
        )
        if rows and rows[0].get("qtde_cotas") is not None:
            return float(rows[0]["qtde_cotas"])
    except Exception:  # noqa: BLE001
        pass
    return None


def _qtde_shares(
    id_carteira: int,
    dias: list[date],
    *,
    token: str | None = None,
) -> dict[str, float]:
    if not dias:
        return {}
    tok = token or token_idsf()
    ini = min(dias)
    fim = max(dias)
    url = (
        "https://prod.idsf.com.br/api/report/GetSharesHistoryJson/"
        f"{id_carteira}/{ini.isoformat()}/{fim.isoformat()}"
    )
    resp = requests.get(url, headers={"token": tok, "Token": tok}, timeout=180)
    if not resp.ok:
        return {}
    out: dict[str, float] = {}
    for row in resp.json() if isinstance(resp.json(), list) else []:
        if not isinstance(row, dict):
            continue
        d = str(row.get("Data") or "")[:10]
        try:
            out[d] = float(row.get("QtdeFechamento") or 0)
        except (TypeError, ValueError):
            continue
    return out


def _ultima_data(id_carteira: int) -> date | None:
    rows = (
        get_supabase()
        .table(TABELA)
        .select("data")
        .eq("id_carteira", id_carteira)
        .order("data", desc=True)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        return None
    return _parse_date(rows[0].get("data"))


def agregar_dist(
    movimentos: list[dict[str, Any]],
) -> dict[date, dict[str, float]]:
    agg: dict[date, dict[str, float]] = defaultdict(
        lambda: {"amort_bruto": 0.0, "juros_bruto": 0.0, "juros_ir": 0.0, "n": 0.0}
    )
    for row in movimentos:
        tipo = str(row.get("TipoOperacao") or "").strip()
        if tipo not in TIPOS_DIST:
            continue
        dia = _parse_date(row.get("DataConversao") or row.get("DataOperacao"))
        if dia is None:
            continue
        try:
            vb = float(row.get("ValorBruto") or 0)
            ir = float(row.get("ValorIR") or 0)
        except (TypeError, ValueError):
            continue
        if tipo == "Amortização":
            agg[dia]["amort_bruto"] += vb
        else:
            agg[dia]["juros_bruto"] += vb
            agg[dia]["juros_ir"] += ir
        agg[dia]["n"] += 1
    return agg


def _load_cache() -> dict[str, list[dict[str, Any]]]:
    if not CACHE_PATH.exists():
        return {}
    try:
        raw = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    return raw.get("por_carteira") if isinstance(raw, dict) else {}


def _save_cache_carteira(id_carteira: int, regs: list[dict[str, Any]]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = _load_cache()
    existentes = {
        str(r.get("data")): r
        for r in (data.get(str(id_carteira)) or [])
        if isinstance(r, dict)
    }
    for r in regs:
        existentes[str(r["data"])] = r
    data[str(id_carteira)] = sorted(existentes.values(), key=lambda x: str(x.get("data")))
    payload = {
        "atualizado_em": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "por_carteira": data,
    }
    CACHE_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def carregar(
    *,
    inicio: date | None = None,
    fim: date | None = None,
) -> dict[str, Any]:
    tem_tabela = tabela_disponivel()
    fim = fim or date.today()
    ids = [cid for cid, codigo, _ in CLASSES_ORDEM if codigo.startswith("MEZ")]
    permitidos = set(carteiras_idsf())
    ids = [i for i in ids if i in permitidos]
    if not ids:
        return {"registros": 0, "aviso": "nenhuma mez em IDSF_CARTEIRAS"}

    token = token_idsf()
    total = 0
    por_carteira: dict[int, int] = {}

    for id_carteira in ids:
        if inicio is None:
            ult = _ultima_data(id_carteira) if tem_tabela else None
            # Tabela vazia mas cache local tem histórico → semeia a tabela
            # (senão o incremental pula tudo usando a data do cache).
            if tem_tabela and ult is None:
                cached = [
                    r
                    for r in (_load_cache().get(str(id_carteira)) or [])
                    if isinstance(r, dict) and r.get("data")
                ]
                if cached:
                    get_supabase().table(TABELA).upsert(
                        cached, on_conflict="data,id_carteira"
                    ).execute()
                    try:
                        ult = max(
                            date.fromisoformat(str(r["data"])[:10]) for r in cached
                        )
                    except (ValueError, KeyError):
                        ult = None
                    print(
                        f"  seed {id_carteira} {len(cached)} do cache -> tabela",
                        flush=True,
                    )
            if ult is None and not tem_tabela:
                cached = _load_cache().get(str(id_carteira)) or []
                if cached:
                    try:
                        ult = max(
                            date.fromisoformat(str(r["data"])[:10]) for r in cached
                        )
                    except (ValueError, KeyError):
                        ult = None
            ini_c = (ult + timedelta(days=1)) if ult else (fim - relativedelta(months=36))
        else:
            ini_c = inicio
        if ini_c > fim:
            por_carteira[id_carteira] = 0
            continue

        movs = buscar_movimentos(id_carteira, ini_c, fim, token=token)
        agg = agregar_dist(movs)
        if not agg:
            por_carteira[id_carteira] = 0
            print(f"  ok {id_carteira} 0 dists ({ini_c}..{fim})", flush=True)
            continue

        dias = sorted(agg.keys())
        qtde_map: dict[str, float] = {}
        if tem_tabela:
            for dia in dias:
                q = _qtde_do_dia(id_carteira, dia)
                if q is not None and q > 0:
                    qtde_map[dia.isoformat()] = q
        faltam = [d for d in dias if d.isoformat() not in qtde_map]
        if faltam:
            qtde_map.update(_qtde_shares(id_carteira, faltam, token=token))

        regs = []
        for dia, vals in agg.items():
            regs.append(
                {
                    "data": dia.isoformat(),
                    "id_carteira": id_carteira,
                    "amort_bruto": round(vals["amort_bruto"], 2),
                    "juros_bruto": round(vals["juros_bruto"], 2),
                    "juros_ir": round(vals["juros_ir"], 2),
                    "qtde_cotas": qtde_map.get(dia.isoformat()),
                    "n_lancamentos": int(vals["n"]),
                }
            )
        if tem_tabela:
            get_supabase().table(TABELA).upsert(
                regs, on_conflict="data,id_carteira"
            ).execute()
        _save_cache_carteira(id_carteira, regs)
        por_carteira[id_carteira] = len(regs)
        total += len(regs)
        print(f"  ok {id_carteira} {len(regs)} dias dist", flush=True)

    return {
        "registros": total,
        "por_carteira": por_carteira,
        "inicio": str(inicio) if inicio else None,
        "fim": str(fim),
        "tabela": tem_tabela,
        "cache": str(CACHE_PATH),
    }


def mapa_dist_por_carteira(
    id_carteira: int, inicio: date, fim: date
) -> dict[date, dict[str, float]]:
    """amort+juros e qtde por dia para a marcação."""
    rows: list[dict[str, Any]] = []
    if tabela_disponivel():
        rows = (
            get_supabase()
            .table(TABELA)
            .select("data,amort_bruto,juros_bruto,juros_ir,qtde_cotas")
            .eq("id_carteira", id_carteira)
            .gte("data", inicio.isoformat())
            .lte("data", fim.isoformat())
            .execute()
            .data
            or []
        )
    if not rows:
        cached = _load_cache().get(str(id_carteira)) or []
        rows = [
            r
            for r in cached
            if isinstance(r, dict)
            and inicio.isoformat() <= str(r.get("data") or "")[:10] <= fim.isoformat()
        ]

    out: dict[date, dict[str, float]] = {}
    for row in rows:
        d = _parse_date(row.get("data"))
        if d is None:
            continue
        amort = float(row.get("amort_bruto") or 0)
        juros = float(row.get("juros_bruto") or 0)
        qtde = row.get("qtde_cotas")
        out[d] = {
            "dist_bruto": amort + juros,
            "amort_bruto": amort,
            "juros_bruto": juros,
            "juros_ir": float(row.get("juros_ir") or 0),
            "qtde_cotas": float(qtde) if qtde is not None else 0.0,
        }
    return out


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Carga amort/juros passivo IDSF")
    parser.add_argument("--inicio", help="YYYY-MM-DD")
    parser.add_argument("--fim", help="YYYY-MM-DD")
    args = parser.parse_args()
    try:
        ini = date.fromisoformat(args.inicio) if args.inicio else None
        fim = date.fromisoformat(args.fim) if args.fim else None
        print(json.dumps(carregar(inicio=ini, fim=fim), indent=2, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001
        print(f"Falha: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
