"""CDI diário via API do BCB (SGS série 12)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

SERIE_CDI = 12
URL = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{SERIE_CDI}/dados"
CACHE_PATH = Path(__file__).resolve().parent / "data" / "cdi_cache.json"


def _parse_br(texto: str) -> date | None:
    s = str(texto or "").strip()[:10]
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _br(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def _load_cache() -> dict[str, float]:
    if not CACHE_PATH.exists():
        return {}
    try:
        raw = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    serie = raw.get("serie") if isinstance(raw, dict) else None
    if not isinstance(serie, dict):
        return {}
    out: dict[str, float] = {}
    for k, v in serie.items():
        try:
            out[str(k)[:10]] = float(v)
        except (TypeError, ValueError):
            continue
    return out


def _save_cache(serie: dict[str, float]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "serie_id": SERIE_CDI,
        "atualizado_em": datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
            "+00:00", "Z"
        ),
        "serie": dict(sorted(serie.items())),
    }
    CACHE_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def buscar_bcb(inicio: date, fim: date, *, timeout: int = 60) -> dict[str, float]:
    """Retorna mapa ISO date → CDI % a.d. (ex. 0.052531)."""
    if inicio > fim:
        return {}
    resp = requests.get(
        URL,
        params={
            "formato": "json",
            "dataInicial": _br(inicio),
            "dataFinal": _br(fim),
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    rows = resp.json()
    out: dict[str, float] = {}
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        d = _parse_br(str(row.get("data") or ""))
        if d is None:
            continue
        try:
            out[d.isoformat()] = float(str(row.get("valor")).replace(",", "."))
        except (TypeError, ValueError):
            continue
    return out


def mapa_cdi(
    inicio: date | None = None,
    fim: date | None = None,
    *,
    atualizar: bool = True,
) -> dict[date, float]:
    """CDI em cache, opcionalmente atualizando o intervalo pedido."""
    fim = fim or date.today()
    inicio = inicio or (fim - timedelta(days=30))
    cache = _load_cache()

    if atualizar:
        faltam = False
        d = inicio
        while d <= fim:
            if d.isoformat() not in cache and d.weekday() < 5:
                faltam = True
                break
            d += timedelta(days=1)
        # sempre puxa se cache vazio ou último < fim-3
        ultima = max(cache.keys()) if cache else None
        if not cache or faltam or (ultima and ultima < (fim - timedelta(days=3)).isoformat()):
            # janela com folga
            ini_fetch = min(inicio, date.fromisoformat(ultima) if ultima else inicio) - timedelta(
                days=5
            )
            novos = buscar_bcb(ini_fetch, fim + timedelta(days=1))
            cache.update(novos)
            _save_cache(cache)

    out: dict[date, float] = {}
    for k, v in cache.items():
        try:
            dk = date.fromisoformat(k[:10])
        except ValueError:
            continue
        if inicio <= dk <= fim:
            out[dk] = v
    return out


def cdi_do_dia(dia: date, *, mapa: dict[date, float] | None = None) -> float | None:
    """CDI % a.d. do dia; se ausente, tenta dia útil anterior no mapa."""
    m = mapa if mapa is not None else mapa_cdi(dia - timedelta(days=10), dia)
    if dia in m:
        return m[dia]
    d = dia
    for _ in range(10):
        d -= timedelta(days=1)
        if d in m:
            return m[d]
    return None


def carregar(*, inicio: date | None = None, fim: date | None = None) -> dict[str, Any]:
    fim = fim or date.today()
    inicio = inicio or (fim - timedelta(days=90))
    serie = mapa_cdi(inicio, fim, atualizar=True)
    return {
        "registros": len(serie),
        "inicio": inicio.isoformat(),
        "fim": fim.isoformat(),
        "cache": str(CACHE_PATH),
        "ultima": max(serie.keys()).isoformat() if serie else None,
    }


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Atualiza cache CDI BCB (SGS 12)")
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
