"""Baixa Estoque BDR para uma data e grava CSV local.

Por padrão usa ``/api/arquivos/estoqueBDR`` (schema ampliado).
Use ``--tipo estoque`` para o endpoint legado.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Literal

import requests
from dotenv import load_dotenv

from bdr_arquivos import (
    TipoArquivo,
    aguardar_arquivo,
    baixar_csv_bytes,
    obter_token,
    solicitar_arquivo,
)

load_dotenv()

OUT_DIR = Path(__file__).resolve().parent / "data" / "relatorios"
TipoEstoque = Literal["estoqueBDR", "estoque"]


def _parse_data(texto: str):
    t = texto.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(t[:10], fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Data inválida: {texto}")


def baixar_estoque(
    data,
    *,
    out: Path | None = None,
    delimiter: str = ";",
    decimal: str = ",",
    tipo: TipoEstoque = "estoqueBDR",
    token: str | None = None,
    session: requests.Session | None = None,
) -> Path:
    sess = session or requests.Session()
    if token is None:
        print("Auth BDR…", flush=True)
        token = obter_token(sess)
    tipo_req: TipoArquivo = tipo  # type: ignore[assignment]
    print(
        f"Solicitando {tipo_req} {data.isoformat()} "
        f"(delimiter={delimiter!r} decimal={decimal!r})…",
        flush=True,
    )
    ticket = solicitar_arquivo(
        tipo_req,
        token=token,
        ref_date=data,
        tp_contabil="A",
        delimiter=delimiter,
        decimal=decimal,
        session=sess,
    )
    print(f"ticket={ticket}", flush=True)
    info = aguardar_arquivo(ticket, token=token, session=sess, timeout_s=900)
    print(f"status={info.get('status')}", flush=True)
    raw = baixar_csv_bytes(info, session=sess)
    # Conta linhas de dados (sem cabeçalho) para log
    n_linhas = max(0, raw.count(b"\n") - 1)
    print(f"bytes={len(raw)} linhas~={n_linhas}", flush=True)
    if n_linhas <= 0:
        raise RuntimeError("Estoque BDR vazio")
    destino = out or (OUT_DIR / f"EstoqueBDR_{data.isoformat()}.csv")
    destino.parent.mkdir(parents=True, exist_ok=True)
    # Preserva o CSV cru da API (schema novo ou legado).
    texto = raw.decode("utf-8-sig", errors="replace")
    destino.write_text(texto, encoding="utf-8-sig", newline="\n")
    print(f"saved={destino} size={destino.stat().st_size}", flush=True)
    return destino


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="2022-01-01")
    parser.add_argument("--delimiter", default=";")
    parser.add_argument("--decimal", default=",")
    parser.add_argument(
        "--tipo",
        choices=("estoqueBDR", "estoque"),
        default="estoqueBDR",
        help="Endpoint BDR (default: estoqueBDR)",
    )
    args = parser.parse_args()
    baixar_estoque(
        _parse_data(args.data),
        delimiter=args.delimiter,
        decimal=args.decimal,
        tipo=args.tipo,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"ERRO: {exc}", file=sys.stderr, flush=True)
        raise
