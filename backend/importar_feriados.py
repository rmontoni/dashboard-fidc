"""Importa Feriados.xlsx → data/feriados_oficiais.json."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

DEST = Path(__file__).resolve().parent / "data" / "feriados_oficiais.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Importa feriados oficiais")
    parser.add_argument(
        "xlsx",
        nargs="?",
        default=r"C:\Users\raulm\OneDrive\Documentos\Pessoal\Planilhas\Feriados.xlsx",
    )
    args = parser.parse_args()
    path = Path(args.xlsx)
    df = pd.read_excel(path, sheet_name="Feriados")
    by: dict[str, dict[str, str]] = {}
    for _, row in df.iterrows():
        raw = row.get("Data")
        if pd.isna(raw):
            continue
        if isinstance(raw, datetime):
            d = raw.date()
        elif isinstance(raw, date):
            d = raw
        else:
            try:
                d = date.fromisoformat(str(raw).strip()[:10])
            except ValueError:
                continue
        nome = str(row.get("Feriado") or "").strip()
        if not nome or nome.lower() == "nan":
            continue
        by[d.isoformat()] = {
            "data": d.isoformat(),
            "nome": nome,
            "dia_semana": str(row.get("Dia da Semana") or "").strip(),
        }
    feriados = sorted(by.values(), key=lambda x: x["data"])
    payload = {
        "fonte": str(path),
        "atualizado_em": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "n": len(feriados),
        "feriados": feriados,
    }
    DEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK {len(feriados)} feriados → {DEST}")


if __name__ == "__main__":
    main()
