"""Migra acompanhamento-passivo-alpha (SQLite) → Supabase.

Pré-requisito: executar backend/sql/fidc_passivo_alpha.sql no Supabase.

Uso:
  cd backend
  python migrar_passivo_alpha.py
  python migrar_passivo_alpha.py --db "C:/.../acompanhamento-passivo-alpha/instance/passivo.db"
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from dotenv import load_dotenv

from db import get_supabase

DEFAULT_DB = Path(__file__).resolve().parent / "data" / "passivo_alpha.db"
# Se o dashboard e o alpha estão irmãos em Projetos/
ALT_DB = Path(r"C:\Users\raulm\OneDrive\Documentos\Projetos\acompanhamento-passivo-alpha\instance\passivo.db")
ALT_DB2 = (
    Path(__file__).resolve().parents[1].parent
    / "acompanhamento-passivo-alpha"
    / "instance"
    / "passivo.db"
)

ID_CARTEIRA_POR_NOME = {
    "Mezanino I": 34691,
    "Mezanino II": 34691302,
    "Mezanino III": 34691303,
    "Mezanino IV": 34691304,
}


def _resolver_db(caminho: str | None) -> Path:
    if caminho:
        p = Path(caminho)
        if not p.exists():
            raise FileNotFoundError(p)
        return p
    for cand in (DEFAULT_DB, ALT_DB, ALT_DB2):
        if cand.exists():
            return cand
    raise FileNotFoundError(
        "passivo.db não encontrado. Passe --db com o caminho do SQLite do Alpha."
    )


def migrar(db_path: Path) -> dict:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    sb = get_supabase()

    classes = [dict(r) for r in conn.execute("SELECT * FROM classes_cota").fetchall()]
    cotistas = [dict(r) for r in conn.execute("SELECT * FROM cotistas").fetchall()]
    chamadas = [dict(r) for r in conn.execute("SELECT * FROM chamadas").fetchall()]
    conn.close()

    rows_cls = []
    for c in classes:
        rows_cls.append(
            {
                "id": int(c["id"]),
                "id_carteira": ID_CARTEIRA_POR_NOME.get(str(c["nome"])),
                "nome": str(c["nome"]),
                "percentual_cdi": float(c["percentual_cdi"]),
                "meses_primeira": int(c["meses_primeira"]),
                "meses_segunda": int(c["meses_segunda"]),
                "perc_primeira": float(c["perc_primeira"] or 50),
                "ativo": True,
            }
        )
    if rows_cls:
        sb.table("fidc_passivo_classes").upsert(rows_cls, on_conflict="id").execute()

    rows_cot = []
    for c in cotistas:
        doc = "".join(ch for ch in str(c["documento"] or "") if ch.isdigit())
        rows_cot.append(
            {
                "id": int(c["id"]),
                "nome": str(c["nome"]),
                "documento": doc,
            }
        )
    if rows_cot:
        # upsert em lotes
        for i in range(0, len(rows_cot), 200):
            sb.table("fidc_cotistas").upsert(
                rows_cot[i : i + 200], on_conflict="id"
            ).execute()

    rows_ch = []
    for ch in chamadas:
        rows_ch.append(
            {
                "id": int(ch["id"]),
                "classe_id": int(ch["classe_id"]),
                "cotista_id": int(ch["cotista_id"]),
                "numero": int(ch["numero"]),
                "data_prazo": str(ch["data_prazo"] or ch["data_aporte"])[:10],
                "data_aporte": str(ch["data_aporte"])[:10],
                "valor_nominal": float(ch["valor_nominal"]),
                "origem": ch.get("origem"),
                "principal_amortizado": float(ch["principal_amortizado"] or 0)
                if "principal_amortizado" in ch.keys()
                else 0.0,
                "valor_amortizado_bruto": float(ch["valor_amortizado_bruto"] or 0)
                if "valor_amortizado_bruto" in ch.keys()
                else 0.0,
                "perc_primeira": float(ch["perc_primeira"])
                if ch.get("perc_primeira") is not None
                else None,
                "credito_vp": float(ch["credito_vp"] or 0)
                if "credito_vp" in ch.keys()
                else 0.0,
            }
        )
    if rows_ch:
        for i in range(0, len(rows_ch), 100):
            sb.table("fidc_passivo_chamadas").upsert(
                rows_ch[i : i + 100], on_conflict="id"
            ).execute()

    return {
        "db": str(db_path),
        "classes": len(rows_cls),
        "cotistas": len(rows_cot),
        "chamadas": len(rows_ch),
    }


def main() -> int:
    root = Path(__file__).resolve().parent
    load_dotenv(root / ".env")
    load_dotenv()
    parser = argparse.ArgumentParser(description="Migra passivo Alpha SQLite → Supabase")
    parser.add_argument("--db", default=None, help="Caminho do passivo.db")
    args = parser.parse_args()
    try:
        resumo = migrar(_resolver_db(args.db))
    except Exception as exc:  # noqa: BLE001
        print(f"Falha: {exc}")
        print("Confirme que rodou backend/sql/fidc_passivo_alpha.sql no Supabase.")
        return 1
    print("OK", resumo)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
