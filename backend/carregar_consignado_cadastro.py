"""Cadastro incremental de consignado (EstoqueBDR → Supabase).

Só insere contratos novos (documento = nm_cessao_bdr).
Não grava snapshot diário do estoque.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from consignado import DOCS_CEDENTE_CONSIGNADO
from db import get_supabase

TABELA = "fidc_consignado_cadastro"
SQL_HINT = "backend/sql/fidc_consignado_cadastro.sql"
RELATORIOS_DIR = Path(__file__).resolve().parent / "data" / "relatorios"
COL_ENTRADA = "entrada_afastamento/rescisao"
PAGE = 1000


def _parse_date(texto: object) -> date | None:
    s = str(texto or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def _txt(texto: object) -> str | None:
    s = str(texto or "").strip()
    return s or None


def tabela_disponivel() -> bool:
    try:
        get_supabase().table(TABELA).select("documento").limit(1).execute()
        return True
    except Exception:  # noqa: BLE001
        return False


def documentos_existentes() -> set[str]:
    sb = get_supabase()
    out: set[str] = set()
    offset = 0
    while True:
        batch = (
            sb.table(TABELA)
            .select("documento")
            .range(offset, offset + PAGE - 1)
            .execute()
            .data
            or []
        )
        if not batch:
            break
        for row in batch:
            doc = str(row.get("documento") or "").strip()
            if doc:
                out.add(doc)
        if len(batch) < PAGE:
            break
        offset += PAGE
    return out


def _linha_cadastro(row: dict[str, Any], fonte_dt_ref: date | None) -> dict[str, Any] | None:
    if (row.get("tp_sacado") or "").strip().upper() != "PF":
        return None
    doc_cedente = (row.get("doc_cedente") or "").strip()
    if doc_cedente not in DOCS_CEDENTE_CONSIGNADO:
        return None
    documento = (row.get("nm_cessao_bdr") or row.get("nm_cessao") or "").strip()
    if not documento:
        return None
    return {
        "documento": documento,
        "empresa": _txt(row.get("empresa")),
        "cnpj_empresa": _txt(row.get("cnpj_empresa")),
        "tipo_evento": _txt(row.get("tipo_evento")),
        "entrada_afastamento_rescisao": _txt(row.get(COL_ENTRADA)),
        "saida_afastamento": _txt(row.get("saida_afastamento")),
        "nm_cedente": _txt(row.get("nm_cedente")),
        "doc_cedente": doc_cedente,
        "tp_cedente": _txt(row.get("tp_cedente")),
        "nm_sacado": _txt(row.get("nm_sacado")),
        "doc_sacado": _txt(row.get("doc_sacado")),
        "tp_sacado": "PF",
        "nm_cessao": _txt(row.get("nm_cessao")),
        "n_controle_lastro_origem": _txt(row.get("n_controle_lastro_origem")),
        "fonte_dt_ref": fonte_dt_ref.isoformat() if fonte_dt_ref else None,
    }


def ler_candidatos_csv(path: Path) -> tuple[date | None, list[dict[str, Any]]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh, delimiter=";")
        rows = list(reader)
    if not rows:
        return None, []
    dt = _parse_date(rows[0].get("dt_ref")) or _parse_date(
        path.stem.replace("EstoqueBDR_", "")
    )
    out: list[dict[str, Any]] = []
    vistos: set[str] = set()
    for row in rows:
        reg = _linha_cadastro(row, dt)
        if reg is None:
            continue
        doc = reg["documento"]
        if doc in vistos:
            continue
        vistos.add(doc)
        out.append(reg)
    return dt, out


def inserir_novos(registros: list[dict[str, Any]], *, batch_size: int = 500) -> int:
    if not registros:
        return 0
    sb = get_supabase()
    total = 0
    for i in range(0, len(registros), batch_size):
        batch = registros[i : i + batch_size]
        # ignoreDuplicates: não atualiza existentes
        sb.table(TABELA).upsert(
            batch, on_conflict="documento", ignore_duplicates=True
        ).execute()
        total += len(batch)
        print(f"  insert tentado {total}/{len(registros)}", flush=True)
    return total


def sincronizar_cadastro(path: Path | str) -> dict[str, Any]:
    """Lê EstoqueBDR e acrescenta só documentos ainda inexistentes no cadastro."""
    path = Path(path)
    if not tabela_disponivel():
        raise RuntimeError(
            f"Tabela {TABELA} ausente no Supabase. Execute {SQL_HINT} no SQL Editor."
        )
    dt_ref, candidatos = ler_candidatos_csv(path)
    existentes = documentos_existentes()
    novos = [r for r in candidatos if r["documento"] not in existentes]
    print(
        f"Cadastro consignado ← {path.name} | candidatos={len(candidatos)} "
        f"| já={len(existentes)} | novos={len(novos)}",
        flush=True,
    )
    inseridos = inserir_novos(novos)
    return {
        "arquivo": path.name,
        "fonte_dt_ref": dt_ref.isoformat() if dt_ref else None,
        "candidatos": len(candidatos),
        "ja_cadastrados": len(existentes),
        "novos": len(novos),
        "inseridos": inseridos,
        "tabela": TABELA,
    }


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Sincroniza cadastro consignado (só contratos novos)"
    )
    parser.add_argument("--arquivo", help="Caminho do EstoqueBDR_*.csv")
    parser.add_argument("--data", help="YYYY-MM-DD → data/relatorios/EstoqueBDR_<data>.csv")
    args = parser.parse_args()
    if args.arquivo:
        path = Path(args.arquivo)
    elif args.data:
        path = RELATORIOS_DIR / f"EstoqueBDR_{args.data[:10]}.csv"
    else:
        arquivos = sorted(RELATORIOS_DIR.glob("EstoqueBDR_*.csv"))
        if not arquivos:
            print("Nenhum EstoqueBDR_*.csv em data/relatorios", file=sys.stderr)
            return 1
        path = arquivos[-1]
    try:
        resumo = sincronizar_cadastro(path)
        print(json.dumps(resumo, ensure_ascii=False, indent=2))
    except Exception as exc:  # noqa: BLE001
        print(f"Falha: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
