"""Snapshot de metadados das classes (GetPortfolio + %CDI da Composition)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from typing import Any

import requests
from dotenv import load_dotenv

from db import get_supabase
from idsf_pl_pdd import (
    carteiras_idsf,
    extrair_pct_cdi_da_composicao,
    token_idsf,
)
from passivo import CLASSES_ORDEM, ID_SUB, _classe_por_id

TABELA = "fidc_classes_meta"
SQL_HINT = "backend/sql/fidc_classes_meta.sql (+ fidc_classes_meta_pct_cdi.sql)"
URL = "https://prod.idsf.com.br/api/Fundo/GetPortfolio"

# Seed se Composition não trouxer o texto no dia
PCT_CDI_SEED: dict[int, float] = {
    34691: 170.0,  # MEZ I
    34691302: 150.0,
    34691303: 150.0,
    34691304: 150.0,
}


def tabela_disponivel() -> bool:
    try:
        get_supabase().table(TABELA).select("id_carteira").limit(1).execute()
        return True
    except Exception:  # noqa: BLE001
        return False


def _parse_date(texto: object) -> date | None:
    s = str(texto or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s[:10] if fmt.startswith("%Y") else s, fmt).date()
        except ValueError:
            continue
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def buscar_portfolio(
    id_carteira: int, *, token: str | None = None, timeout: int = 60
) -> dict[str, Any]:
    """GetPortfolio retorna lista JSON (não envelopada em Model)."""
    tok = token or token_idsf()
    resp = requests.get(
        f"{URL}/{id_carteira}",
        headers={"token": tok, "Token": tok, "Content-Type": "application/json"},
        timeout=timeout,
    )
    resp.raise_for_status()
    payload = resp.json()
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict) and int(item.get("IdCarteira") or 0) == id_carteira:
                return item
        return payload[0] if payload and isinstance(payload[0], dict) else {}
    if isinstance(payload, dict):
        model = payload.get("Model", payload)
        if isinstance(model, str):
            model = json.loads(model) if model.strip() else {}
        if isinstance(model, list):
            return model[0] if model and isinstance(model[0], dict) else {}
        return model if isinstance(model, dict) else {}
    return {}


def _extrair_apelido(dados: dict[str, Any], fallback: str) -> str:
    for chave in ("Apelido", "apelido", "Nome", "nome", "NmCarteira"):
        v = str(dados.get(chave) or "").strip()
        if v:
            return v
    return fallback


def _float(v: object) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def carregar() -> dict[str, Any]:
    if not tabela_disponivel():
        raise RuntimeError(f"Tabela {TABELA} ausente. Execute {SQL_HINT}.")

    token = token_idsf()
    ids = carteiras_idsf()
    registros: list[dict[str, Any]] = []
    erros: list[str] = []

    for id_carteira in ids:
        codigo, nome = _classe_por_id(id_carteira)
        try:
            dados = buscar_portfolio(id_carteira, token=token)
            apelido = _extrair_apelido(dados, nome)
            cota_inicial = _float(dados.get("CotaInicial"))
            data_inicio = _parse_date(dados.get("DataInicioCota"))

            pct_cdi: float | None = None
            venc: date | None = None
            if id_carteira != ID_SUB and codigo.startswith("MEZ"):
                pct_cdi, venc = extrair_pct_cdi_da_composicao(
                    id_carteira, token=token
                )
                if pct_cdi is None:
                    pct_cdi = PCT_CDI_SEED.get(id_carteira)

            registros.append(
                {
                    "id_carteira": id_carteira,
                    "apelido": apelido,
                    "classe": codigo,
                    "vencimento": venc.isoformat() if venc else None,
                    "pct_cdi": pct_cdi,
                    "cota_inicial": cota_inicial,
                    "data_inicio_cota": data_inicio.isoformat() if data_inicio else None,
                    "dados": {
                        **(dados or {}),
                        "_passivo": {
                            "pct_cdi": pct_cdi,
                            "cota_inicial": cota_inicial,
                            "data_inicio_cota": data_inicio.isoformat()
                            if data_inicio
                            else None,
                            "vencimento": venc.isoformat() if venc else None,
                        },
                    }
                    if dados or pct_cdi or cota_inicial
                    else None,
                }
            )
            print(
                f"  ok {id_carteira} {codigo} pct_cdi={pct_cdi} "
                f"cota0={cota_inicial} inicio={data_inicio} venc={venc}",
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001
            erros.append(f"{id_carteira}: {exc}")
            registros.append(
                {
                    "id_carteira": id_carteira,
                    "apelido": nome,
                    "classe": codigo,
                    "vencimento": None,
                    "pct_cdi": PCT_CDI_SEED.get(id_carteira)
                    if codigo.startswith("MEZ")
                    else None,
                    "cota_inicial": None,
                    "data_inicio_cota": None,
                    "dados": None,
                }
            )
            print(f"  erro {id_carteira}: {exc}", flush=True)

    if registros:
        # upsert tolerante a colunas ainda não migradas
        try:
            get_supabase().table(TABELA).upsert(
                registros, on_conflict="id_carteira"
            ).execute()
        except Exception:  # noqa: BLE001
            basicos = [
                {
                    "id_carteira": r["id_carteira"],
                    "apelido": r["apelido"],
                    "classe": r["classe"],
                    "vencimento": r.get("vencimento"),
                    "dados": r.get("dados"),
                }
                for r in registros
            ]
            get_supabase().table(TABELA).upsert(
                basicos, on_conflict="id_carteira"
            ).execute()
            erros.append(
                "Colunas pct_cdi/cota_inicial ausentes — rode sql/fidc_classes_meta_pct_cdi.sql"
            )
    return {"registros": len(registros), "erros": erros}


def main() -> int:
    load_dotenv()
    argparse.ArgumentParser(description="Carga meta das classes IDSF").parse_args()
    try:
        print(json.dumps(carregar(), ensure_ascii=False, indent=2))
    except Exception as exc:  # noqa: BLE001
        print(f"Falha: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
