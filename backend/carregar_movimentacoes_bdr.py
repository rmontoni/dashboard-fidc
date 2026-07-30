"""Carga histórica de aquisições e liquidações (API BDR -> Supabase).

Pré-requisitos:
  1) Rodar backend/sql/fidc_movimentacoes_bdr.sql no Supabase
  2) Preencher no .env:
       BDR_BASIC_USER, BDR_BASIC_PASSWORD, BDR_CNPJ_FUNDO
       BDR_DATA_INICIO=2021-03-01   # momento zero / início do Alpha
  3) python carregar_movimentacoes_bdr.py

A API gera CSV de forma assíncrona. O script solicita por mês (chunk),
espera o ticket, baixa e faz upsert por (cnpj_fundo, linha_hash).

Uso:
  python carregar_movimentacoes_bdr.py
  python carregar_movimentacoes_bdr.py --tipo aquisicoes
  python carregar_movimentacoes_bdr.py --tipo liquidacoes
  python carregar_movimentacoes_bdr.py --inicio 2021-03-01 --fim 2026-06-30
"""

from __future__ import annotations

import argparse
import os
import time
from calendar import monthrange
from datetime import date, datetime
from typing import Any, Literal

import requests
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv

from bdr_arquivos import (
    aguardar_arquivo,
    baixar_csv_linhas,
    extrair_data_movimento,
    hash_linha,
    obter_token,
    solicitar_arquivo,
)
from db import get_supabase
from fundos import data_inicio_fundo, obter_fundo

load_dotenv()

TipoMov = Literal["aquisicoes", "liquidacoes"]
TABELA = {
    "aquisicoes": "fidc_aquisicoes",
    "liquidacoes": "fidc_liquidacoes",
}


def resolver_fundo(codigo: str | None) -> dict:
    if codigo:
        fundo = obter_fundo(codigo=codigo)
    else:
        from fundos import fundo_padrao

        fundo = fundo_padrao()
    if not fundo:
        raise RuntimeError(
            "Nenhum fundo encontrado. Rode sql/fidc_fundos.sql e cadastre o FIDC."
        )
    return fundo


def _parse_date(texto: str) -> date:
    return datetime.strptime(texto.strip(), "%Y-%m-%d").date()


def data_inicio_padrao() -> date:
    raw = (os.getenv("BDR_DATA_INICIO") or "2021-03-01").strip()
    return _parse_date(raw)


def meses_entre(inicio: date, fim: date) -> list[tuple[date, date]]:
    """Gera pares (primeiro_dia, ultimo_dia) mês a mês inclusive."""
    if fim < inicio:
        return []
    cursor = date(inicio.year, inicio.month, 1)
    ultimo = date(fim.year, fim.month, 1)
    faixas: list[tuple[date, date]] = []
    while cursor <= ultimo:
        last_day = monthrange(cursor.year, cursor.month)[1]
        start = max(inicio, cursor)
        end = min(fim, date(cursor.year, cursor.month, last_day))
        faixas.append((start, end))
        cursor = cursor + relativedelta(months=1)
    return faixas


def upsert_linhas(
    tipo: TipoMov,
    linhas: list[dict[str, str]],
    *,
    ticket: str,
    periodo_inicio: date,
    periodo_fim: date,
    cnpj: str,
) -> int:
    sb = get_supabase()
    tabela = TABELA[tipo]
    registros: list[dict[str, Any]] = []
    vistos: set[str] = set()
    for row in linhas:
        h = hash_linha(row)
        if h in vistos:
            continue
        vistos.add(h)
        registros.append(
            {
                "cnpj_fundo": cnpj,
                "data_movimento": (
                    extrair_data_movimento(row).isoformat()
                    if extrair_data_movimento(row)
                    else None
                ),
                "linha_hash": h,
                "dados": row,
                "ticket": ticket,
                "periodo_inicio": periodo_inicio.isoformat(),
                "periodo_fim": periodo_fim.isoformat(),
                "fonte": "bdr_arquivos",
            }
        )

    if not registros:
        return 0

    # Upsert em lotes
    batch = 500
    gravados = 0
    for i in range(0, len(registros), batch):
        chunk = registros[i : i + batch]
        (
            sb.table(tabela)
            .upsert(chunk, on_conflict="cnpj_fundo,linha_hash")
            .execute()
        )
        gravados += len(chunk)
    return gravados


def carregar_periodo(
    tipo: TipoMov,
    inicio: date,
    fim: date,
    *,
    cnpj: str,
    tp_contabil: str,
    timeout_s: float = 600,
    pausa_entre_meses_s: float = 3.0,
) -> dict[str, Any]:
    sess = requests.Session()
    token = obter_token(sess)
    token_em = time.time()
    resumo = {"tipo": tipo, "meses": 0, "linhas": 0, "tickets": []}

    for start, end in meses_entre(inicio, fim):
        ok_mes = False
        for tentativa_mes in range(1, 4):
            try:
                # Token BDR ~3h; renova a cada ~2h ou na falha
                if time.time() - token_em > 7200:
                    token = obter_token(sess)
                    token_em = time.time()

                print(f"[{tipo}] solicitando {start} .. {end}")
                ticket = solicitar_arquivo(
                    tipo,
                    token=token,
                    start_date=start,
                    end_date=end,
                    tp_contabil=tp_contabil,
                    cnpj=cnpj,
                    session=sess,
                )
                print(f"[{tipo}] ticket={ticket} aguardando...")
                meta = aguardar_arquivo(
                    ticket, token=token, timeout_s=timeout_s, session=sess
                )
                try:
                    linhas = baixar_csv_linhas(meta, session=sess)
                except Exception as exc:  # noqa: BLE001
                    print(
                        f"[{tipo}] falha download ({exc}); "
                        "renovando token e consultando de novo"
                    )
                    token = obter_token(sess)
                    token_em = time.time()
                    meta = aguardar_arquivo(
                        ticket, token=token, timeout_s=120, session=sess
                    )
                    linhas = baixar_csv_linhas(meta, session=sess)

                n = upsert_linhas(
                    tipo,
                    linhas,
                    ticket=ticket,
                    periodo_inicio=start,
                    periodo_fim=end,
                    cnpj=cnpj,
                )
                print(f"[{tipo}] {start}..{end}: {n} linhas upsert")
                resumo["meses"] += 1
                resumo["linhas"] += n
                resumo["tickets"].append(ticket)
                ok_mes = True
                break
            except (
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                TimeoutError,
                RuntimeError,
            ) as exc:
                espera = min(5 * tentativa_mes, 30)
                print(
                    f"[{tipo}] mês {start} falhou ({exc}); "
                    f"tentativa {tentativa_mes}/3, pausa {espera}s"
                )
                time.sleep(espera)
                sess = requests.Session()
                token = obter_token(sess)
                token_em = time.time()

        if not ok_mes:
            print(
                f"[{tipo}] PULANDO {start}..{end} após 3 falhas "
                "(BDR não entregou o arquivo). Continuando."
            )
            continue

        if pausa_entre_meses_s > 0:
            time.sleep(pausa_entre_meses_s)

    return resumo


def max_periodo_carregado(tipo: TipoMov, cnpj: str) -> date | None:
    sb = get_supabase()
    rows = (
        sb.table(TABELA[tipo])
        .select("periodo_fim")
        .eq("cnpj_fundo", cnpj)
        .order("periodo_fim", desc=True)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows or not rows[0].get("periodo_fim"):
        return None
    return _parse_date(str(rows[0]["periodo_fim"])[:10])


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Carga histórica aquisições/liquidações BDR → Supabase"
    )
    parser.add_argument(
        "--tipo",
        choices=["aquisicoes", "liquidacoes", "ambos"],
        default="ambos",
    )
    parser.add_argument(
        "--fundo",
        default=None,
        help="Código do fundo em fidc_fundos (ex.: alpha)",
    )
    parser.add_argument("--inicio", default=None, help="YYYY-MM-DD")
    parser.add_argument("--fim", default=None, help="YYYY-MM-DD")
    parser.add_argument(
        "--retomar",
        action="store_true",
        help="Continua após o último periodo_fim já gravado no Supabase",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.getenv("BDR_TICKET_TIMEOUT_S", "600")),
    )
    args = parser.parse_args()

    fundo = resolver_fundo(args.fundo)
    cnpj = str(fundo["cnpj"])
    inicio_base = (
        _parse_date(args.inicio)
        if args.inicio
        else (data_inicio_fundo(fundo) or data_inicio_padrao())
    )
    fim = _parse_date(args.fim) if args.fim else date.today()

    tipos: list[TipoMov]
    if args.tipo == "ambos":
        tipos = ["aquisicoes", "liquidacoes"]
    else:
        tipos = [args.tipo]  # type: ignore[list-item]

    print(f"Fundo: {fundo['nome']} ({fundo['codigo']}) CNPJ={cnpj}")
    for tipo in tipos:
        inicio = inicio_base
        if args.retomar:
            ultimo = max_periodo_carregado(tipo, cnpj)
            if ultimo is not None:
                inicio = ultimo + relativedelta(days=1)
                print(f"[{tipo}] retomando após {ultimo} -> início {inicio}")
        if inicio > fim:
            print(f"[{tipo}] já está completo até {fim}")
            continue
        print(f"[{tipo}] período: {inicio} -> {fim}")
        resumo = carregar_periodo(
            tipo,
            inicio,
            fim,
            cnpj=cnpj,
            tp_contabil=str(fundo.get("bdr_tp_contabil_mov") or "A"),
            timeout_s=args.timeout,
        )
        print("OK", resumo)


if __name__ == "__main__":
    main()
