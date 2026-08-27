"""Aplica backend/sql/fidc_passivo_alpha.sql via DATABASE_URL (Postgres).

Uso:
  # no backend/.env:
  # DATABASE_URL=postgresql://postgres.[ref]:[senha]@aws-0-....pooler.supabase.com:6543/postgres

  cd backend
  python aplicar_sql_passivo_alpha.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

SQL_PATH = Path(__file__).resolve().parent / "sql" / "fidc_passivo_alpha.sql"


def main() -> int:
    root = Path(__file__).resolve().parent
    load_dotenv(root / ".env")
    load_dotenv()
    url = (
        os.getenv("DATABASE_URL")
        or os.getenv("SUPABASE_DB_URL")
        or os.getenv("POSTGRES_URL")
        or ""
    ).strip()
    if not url:
        print(
            "Defina DATABASE_URL no backend/.env (connection string do Supabase → "
            "Project Settings → Database → URI) e rode de novo.\n"
            "Alternativa: cole o conteúdo de sql/fidc_passivo_alpha.sql no SQL Editor."
        )
        return 2
    try:
        import psycopg
    except ImportError:
        try:
            import psycopg2 as psycopg  # type: ignore
        except ImportError:
            print("Instale psycopg: python -m pip install psycopg[binary]")
            return 1

    sql = SQL_PATH.read_text(encoding="utf-8")
    if "psycopg2" in sys.modules or getattr(psycopg, "__name__", "") == "psycopg2":
        conn = psycopg.connect(url)  # type: ignore[attr-defined]
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
            conn.commit()
        finally:
            conn.close()
    else:
        with psycopg.connect(url) as conn:  # type: ignore[attr-defined]
            with conn.cursor() as cur:
                cur.execute(sql)
            conn.commit()
    print("OK: sql/fidc_passivo_alpha.sql aplicado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
