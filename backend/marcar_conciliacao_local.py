"""Marca uma data base como conciliada usando estoque já no Supabase.

Uso:
  python marcar_conciliacao_local.py --data 2026-06-30 --fundo alpha
"""

from __future__ import annotations

import argparse
import json

from conciliacao import conciliar_estoque_existente


def main() -> None:
    parser = argparse.ArgumentParser(description="Concilia data base a partir do estoque local")
    parser.add_argument("--data", required=True, help="YYYY-MM-DD ou dd/mm/yyyy")
    parser.add_argument("--fundo", default="alpha", help="Código em fidc_fundos")
    args = parser.parse_args()
    resultado = conciliar_estoque_existente(args.data, codigo_fundo=args.fundo)
    print(json.dumps(resultado, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
