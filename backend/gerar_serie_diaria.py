"""
Gera a série diária do motor (carteira_mov_diario.json) usada pelo calendário
do dashboard: VP/PDD/DC do motor em cada data com liquidez IDSF.
"""

from __future__ import annotations

import argparse
import time

from dotenv import load_dotenv

from carteira_movimentacoes import (
    DIARIO_PATH,
    mapa_dc_bdr_diario,
    reconstruir_serie_diaria,
)

load_dotenv()


def main() -> None:
    parser = argparse.ArgumentParser(description="Série diária do motor")
    parser.add_argument(
        "--mostrar",
        type=int,
        default=5,
        help="Quantos dias da série imprimir no fim",
    )
    args = parser.parse_args()

    t0 = time.perf_counter()

    def progresso(dia: str, row: dict[str, float]) -> None:
        marca = "ok " if row.get("conciliada") else "DIV"
        print(
            f"[{time.perf_counter() - t0:>6.0f}s] {dia} {marca} "
            f"vp={row.get('vp', 0):>14,.2f} Δvp={row.get('delta_vp', 0):>10,.2f} "
            f"Δpdd={row.get('delta_pdd', 0):>10,.2f}",
            flush=True,
        )

    payload = reconstruir_serie_diaria(progresso=progresso)
    dt = time.perf_counter() - t0

    print(f"dias={payload.get('dias')} em {dt:,.1f}s → {DIARIO_PATH}")
    serie = mapa_dc_bdr_diario()
    for d in sorted(serie)[-args.mostrar :]:
        row = serie[d]
        print(
            f"{d} n={int(row.get('n') or 0):>6} vp={row.get('vp'):>14,.2f} "
            f"pdd={row.get('pdd'):>12,.2f} dc={row.get('dc_bdr'):>14,.2f}"
        )


if __name__ == "__main__":
    main()
