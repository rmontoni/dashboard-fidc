"""Baixa EstoqueBDR CSV nos fechamentos mensais (desde jan/22).

Parâmetros BDR padrão: delimiter=';'  decimal=','
"""

from __future__ import annotations

import argparse
from calendar import monthrange
from datetime import date, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

from baixar_estoque_bdr import OUT_DIR, baixar_estoque
from bdr_arquivos import obter_token

load_dotenv()


def ultimo_dia_util(ano: int, mes: int) -> date:
    d = date(ano, mes, monthrange(ano, mes)[1])
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def meses_ate(inicio: date, fim: date) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    y, m = inicio.year, inicio.month
    while (y, m) <= (fim.year, fim.month):
        out.append((y, m))
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inicio", default="2022-01")
    parser.add_argument("--fim", default=None, help="YYYY-MM (default: mês atual)")
    parser.add_argument("--delimiter", default=";")
    parser.add_argument("--decimal", default=",")
    parser.add_argument(
        "--forcar",
        action="store_true",
        help="Rebaixa mesmo se o arquivo já existir",
    )
    args = parser.parse_args()

    yi, mi = (int(x) for x in args.inicio.split("-")[:2])
    inicio = date(yi, mi, 1)
    if args.fim:
        yf, mf = (int(x) for x in args.fim.split("-")[:2])
        fim = date(yf, mf, 1)
    else:
        hoje = date.today()
        fim = date(hoje.year, hoje.month, 1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sess = requests.Session()
    print("Auth BDR…", flush=True)
    token = obter_token(sess)

    ok = 0
    falhas: list[date] = []
    for y, m in meses_ate(inicio, fim):
        d = ultimo_dia_util(y, m)
        if d > date.today():
            d = date.today()
            while d.weekday() >= 5:
                d -= timedelta(days=1)
        destino = OUT_DIR / f"EstoqueBDR_{d.isoformat()}.csv"
        if destino.exists() and destino.stat().st_size > 1000 and not args.forcar:
            print(f"skip {destino.name}", flush=True)
            ok += 1
            continue
        try:
            baixar_estoque(
                d,
                out=destino,
                delimiter=args.delimiter,
                decimal=args.decimal,
                token=token,
                session=sess,
            )
            ok += 1
        except Exception as exc:  # noqa: BLE001
            print(f"ERRO {d}: {exc}", flush=True)
            falhas.append(d)
            # Renova sessão/token após falha
            sess = requests.Session()
            try:
                token = obter_token(sess)
            except Exception:  # noqa: BLE001
                pass

    print(f"\nConcluído: {ok} arquivos. Falhas: {len(falhas)}")
    for d in falhas:
        print(f"  - {d}")


if __name__ == "__main__":
    main()
