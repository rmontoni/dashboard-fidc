"""Baixa EstoqueBDR (endpoint /api/arquivos/estoqueBDR) para um período.

Substitui os CSVs locais existentes nas datas pedidas.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta

import requests
from dotenv import load_dotenv

from baixar_estoque_bdr import OUT_DIR, baixar_estoque
from bdr_arquivos import obter_token
from calendario import e_dia_util

load_dotenv()


def _parse(texto: str) -> date:
    t = texto.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(t[:10], fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Data inválida: {texto}")


def dias_uteis(inicio: date, fim: date) -> list[date]:
    out: list[date] = []
    d = inicio
    while d <= fim:
        if e_dia_util(d):
            out.append(d)
        d += timedelta(days=1)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inicio", default="2026-06-01")
    ap.add_argument("--fim", default="2026-07-31")
    ap.add_argument("--tipo", choices=("estoqueBDR", "estoque"), default="estoqueBDR")
    args = ap.parse_args()

    inicio = _parse(args.inicio)
    fim = _parse(args.fim)
    if fim > date.today():
        fim = date.today()
    datas = dias_uteis(inicio, fim)
    print(f"Datas úteis: {len(datas)} ({inicio} → {fim})", flush=True)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sess = requests.Session()
    print("Auth BDR…", flush=True)
    token = obter_token(sess)

    ok = 0
    falhas: list[tuple[date, str]] = []
    for d in datas:
        destino = OUT_DIR / f"EstoqueBDR_{d.isoformat()}.csv"
        try:
            baixar_estoque(
                d,
                out=destino,
                tipo=args.tipo,
                token=token,
                session=sess,
            )
            ok += 1
        except Exception as exc:  # noqa: BLE001
            print(f"ERRO {d}: {exc}", flush=True)
            falhas.append((d, str(exc)))
            sess = requests.Session()
            try:
                token = obter_token(sess)
            except Exception:  # noqa: BLE001
                pass

    print(f"\nConcluído: {ok}/{len(datas)}. Falhas: {len(falhas)}", flush=True)
    for d, msg in falhas:
        print(f"  - {d}: {msg}", flush=True)


if __name__ == "__main__":
    main()
