"""Conciliação de uma data base: baixa estoque BDR, confere totais e registra status.

Uso (depois das movimentações históricas):
  python conciliar_data_base_bdr.py --data 2026-06-30
  python conciliar_data_base_bdr.py --data 30/06/2026 --gravar-estoque

Sem --gravar-estoque apenas registra totais na fidc_conciliacao_data_base.
Com --gravar-estoque também faz upsert em BD_Estoque (SUPABASE_TABLE).
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime
from typing import Any

import pandas as pd
import requests
from dotenv import load_dotenv

from bdr_arquivos import (
    aguardar_arquivo,
    baixar_csv_linhas,
    cnpj_fundo,
    obter_token,
    solicitar_arquivo,
)
from db import get_supabase, nome_tabela

load_dotenv()


def _parse_data(texto: str):
    t = texto.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Data inválida: {texto}")


def _br_para_float(serie: pd.Series) -> pd.Series:
    texto = (
        serie.astype(str)
        .str.strip()
        .str.replace(".", "", regex=False)
        .str.replace(",", ".", regex=False)
        .replace({"": None, "nan": None, "None": None})
    )
    return pd.to_numeric(texto, errors="coerce")


def _totais(linhas: list[dict[str, str]]) -> dict[str, Any]:
    vazio = {
        "estoque_linhas": 0,
        "estoque_vl_face": 0.0,
        "estoque_vl_aquisicao": 0.0,
        "estoque_vl_pdd": 0.0,
    }
    if not linhas:
        return vazio
    df = pd.DataFrame(linhas)
    lower = {str(c).lower(): c for c in df.columns}

    def col(*nomes: str) -> str | None:
        for n in nomes:
            if n in df.columns:
                return n
            if n.lower() in lower:
                return lower[n.lower()]
        return None

    def soma(*nomes: str) -> float:
        c = col(*nomes)
        if c is None:
            return 0.0
        return float(_br_para_float(df[c]).fillna(0.0).sum())

    return {
        "estoque_linhas": int(len(df)),
        "estoque_vl_face": soma("vl_face", "valor_face", "VlFace", "vlFace"),
        "estoque_vl_aquisicao": soma(
            "vl_aquisicao", "valor_descontado", "VlAquisicao", "vlAquisicao"
        ),
        "estoque_vl_pdd": soma("vl_pdd", "VlPdd", "vlPdd", "pdd"),
    }


def registrar_conciliacao(
    data_base,
    *,
    status: str,
    ticket: str | None,
    totais: dict[str, Any],
    observacao: str | None = None,
) -> None:
    sb = get_supabase()
    row = {
        "data_base": data_base.isoformat(),
        "cnpj_fundo": cnpj_fundo(),
        "status": status,
        "ticket_estoque": ticket,
        "estoque_linhas": totais.get("estoque_linhas"),
        "estoque_vl_face": totais.get("estoque_vl_face"),
        "estoque_vl_aquisicao": totais.get("estoque_vl_aquisicao"),
        "estoque_vl_pdd": totais.get("estoque_vl_pdd"),
        "observacao": observacao,
        "conferido_em": datetime.utcnow().isoformat() + "Z",
        "atualizado_em": datetime.utcnow().isoformat() + "Z",
    }
    sb.table("fidc_conciliacao_data_base").upsert(row, on_conflict="data_base").execute()


def gravar_estoque_supabase(data_base, linhas: list[dict[str, str]]) -> int:
    """Upsert bruto na tabela de estoque (SUPABASE_TABLE). Ajuste de colunas conforme CSV."""
    if not linhas:
        return 0
    sb = get_supabase()
    tabela = nome_tabela()
    # Mantém as chaves do CSV; garante dt_ref
    registros = []
    for row in linhas:
        item = dict(row)
        item.setdefault("dt_ref", data_base.isoformat())
        registros.append(item)
    batch = 500
    n = 0
    for i in range(0, len(registros), batch):
        # Sem on_conflict genérico: insert em lotes (tabela atual pode não ter PK natural)
        sb.table(tabela).insert(registros[i : i + batch]).execute()
        n += len(registros[i : i + batch])
    return n


def conciliar(data_base, *, gravar_estoque: bool = False) -> dict[str, Any]:
    sess = requests.Session()
    token = obter_token(sess)
    registrar_conciliacao(
        data_base,
        status="baixando",
        ticket=None,
        totais={"estoque_linhas": 0, "estoque_vl_face": 0, "estoque_vl_aquisicao": 0, "estoque_vl_pdd": 0},
    )
    ticket = solicitar_arquivo("estoque", token=token, ref_date=data_base, session=sess)
    print(f"ticket estoque={ticket}")
    meta = aguardar_arquivo(ticket, token=token, session=sess)
    linhas = baixar_csv_linhas(meta, session=sess)
    totais = _totais(linhas)
    print("totais", totais)

    obs = None
    status = "ok"
    if gravar_estoque:
        try:
            n = gravar_estoque_supabase(data_base, linhas)
            obs = f"estoque gravado: {n} linhas em {nome_tabela()}"
        except Exception as exc:  # noqa: BLE001
            status = "erro"
            obs = f"falha ao gravar estoque: {exc}"

    registrar_conciliacao(
        data_base,
        status=status,
        ticket=ticket,
        totais=totais,
        observacao=obs,
    )
    return {"data_base": data_base.isoformat(), "status": status, "ticket": ticket, **totais}


def main() -> None:
    parser = argparse.ArgumentParser(description="Concilia data base via estoque BDR")
    parser.add_argument("--data", required=True, help="YYYY-MM-DD ou dd/mm/yyyy")
    parser.add_argument(
        "--gravar-estoque",
        action="store_true",
        help=f"Insere o CSV na tabela {nome_tabela()}",
    )
    args = parser.parse_args()
    data_base = _parse_data(args.data)
    print(conciliar(data_base, gravar_estoque=args.gravar_estoque))


if __name__ == "__main__":
    main()
