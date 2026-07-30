"""
Concilia um intervalo de meses, dia a dia.

Uso:
  python conciliar_periodo.py --desde 2024-10 --ate 2026-06
  python conciliar_periodo.py --desde 2025-02 --ate 2026-06 --ate-dia 2026-06-27
"""

from __future__ import annotations

import argparse
import calendar
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def meses_entre(desde: str, ate: str) -> list[str]:
    ay, am = (int(x) for x in desde.split("-")[:2])
    by, bm = (int(x) for x in ate.split("-")[:2])
    out: list[str] = []
    y, m = ay, am
    while (y, m) <= (by, bm):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", required=True, help="AAAA-MM")
    ap.add_argument("--ate", required=True, help="AAAA-MM")
    ap.add_argument(
        "--ate-dia",
        default=None,
        help="AAAA-MM-DD — corta o último mês neste dia (inclusive)",
    )
    args = ap.parse_args()

    lista = meses_entre(args.desde, args.ate)
    print(f"Conciliação em lote: {lista[0]} → {lista[-1]}  ({len(lista)} meses)", flush=True)

    for i, mes in enumerate(lista, 1):
        cmd = [
            sys.executable,
            str(ROOT / "conciliar_junho_2024.py"),
            "--mes",
            mes,
            "--continuar-fora",
        ]
        if args.ate_dia and mes == args.ate:
            cmd.extend(["--ate", args.ate_dia])
        print(f"\n######## [{i}/{len(lista)}] {mes} ########", flush=True)
        proc = subprocess.run(cmd, cwd=str(ROOT))
        if proc.returncode != 0:
            print(f"FALHA em {mes} (exit={proc.returncode})", flush=True)
            # Segue para o próximo mês mesmo assim
            continue

    print("\n===== LOTE CONCLUÍDO =====", flush=True)
    # Consolida logs + regenera série
    subprocess.run(
        [sys.executable, str(ROOT / "log_erros_bdr.py"), "--consolidar"],
        cwd=str(ROOT),
    )
    subprocess.run(
        [sys.executable, str(ROOT / "gerar_serie_diaria.py"), "--mostrar", "3"],
        cwd=str(ROOT),
    )


if __name__ == "__main__":
    main()
