"""Baixa PDFs Carteira_566391 nos fechamentos mensais (desde jan/22).

API: GET .../GetPortfolioComposition/{id}/{inicio}/{fim}/PDF
Retorno: ZIP em Base64 com PDF(s) no padrão Carteira_{id}_{d}_{m}_{yyyy}.pdf
"""

from __future__ import annotations

import argparse
import base64
import io
import zipfile
from calendar import monthrange
from datetime import date, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

from idsf_pl_pdd import IDSF_BASE, token_idsf

load_dotenv()

OUT_DIR = Path(__file__).resolve().parent / "data" / "relatorios"
CARTEIRA = 566391


def ultimo_dia_util(ano: int, mes: int) -> date:
    d = date(ano, mes, monthrange(ano, mes)[1])
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def meses_ate(inicio: date, fim: date) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    y, m = inicio.year, inicio.month
    while (y, m) <= (fim.year, fim.month):
        out.append((y, m))
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


def nome_pdf_local(d: date) -> str:
    # Mesmo padrão da IDSF: Carteira_566391_29_5_2026.pdf
    return f"Carteira_{CARTEIRA}_{d.day}_{d.month}_{d.year}.pdf"


def baixar_pdf_dia(d: date, *, token: str, timeout: int = 180) -> bytes:
    url = f"{IDSF_BASE}/{CARTEIRA}/{d.isoformat()}/{d.isoformat()}/PDF"
    r = requests.get(url, headers={"token": token}, timeout=timeout)
    r.raise_for_status()
    payload = r.json()
    if not payload.get("Success", True):
        raise RuntimeError(f"IDSF {d}: {payload.get('Errors')}")
    model = payload.get("Model") or {}
    b64 = model.get("Base64")
    if not b64:
        raise RuntimeError(f"IDSF {d}: Model sem Base64")
    return base64.b64decode(b64)


def extrair_pdfs(raw: bytes) -> dict[str, bytes]:
    if raw[:4] == b"%PDF":
        return {"direct.pdf": raw}
    if raw[:2] != b"PK":
        raise RuntimeError(f"Conteúdo inesperado (magic={raw[:4]!r})")
    out: dict[str, bytes] = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = Path(info.filename).name
            if name.lower().endswith(".pdf"):
                out[name] = zf.read(info)
    return out


def salvar_fechamento(d: date, *, token: str, forcar: bool = False) -> Path | None:
    destino = OUT_DIR / nome_pdf_local(d)
    if destino.exists() and destino.stat().st_size > 1000 and not forcar:
        print(f"skip {destino.name} (já existe)", flush=True)
        return destino

    # Tenta o dia; se falhar, recua até 5 dias úteis (feriado)
    ultimo_erro: Exception | None = None
    for i in range(6):
        cand = d - timedelta(days=i)
        if cand.weekday() >= 5:
            continue
        try:
            raw = baixar_pdf_dia(cand, token=token)
            pdfs = extrair_pdfs(raw)
            if not pdfs:
                raise RuntimeError("ZIP sem PDF")
            # Preferir o PDF cujo nome bate com a data candidata
            preferido = nome_pdf_local(cand)
            conteudo = pdfs.get(preferido) or next(iter(pdfs.values()))
            nome_salvo = preferido if preferido in pdfs else next(iter(pdfs))
            path = OUT_DIR / nome_salvo
            path.write_bytes(conteudo)
            print(f"ok {path.name} size={path.stat().st_size} (ref={d})", flush=True)
            return path
        except Exception as exc:  # noqa: BLE001
            ultimo_erro = exc
            print(f"  falha {cand}: {exc}", flush=True)
    print(f"ERRO {d}: {ultimo_erro}", flush=True)
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inicio", default="2022-01")
    parser.add_argument("--fim", default=None, help="YYYY-MM (default: mês atual)")
    parser.add_argument("--forcar", action="store_true")
    args = parser.parse_args()

    yi, mi = (int(x) for x in args.inicio.split("-")[:2])
    inicio = date(yi, mi, 1)
    if args.fim:
        yf, mf = (int(x) for x in args.fim.split("-")[:2])
        fim = date(yf, mf, 1)
    else:
        hoje = date.today()
        fim = date(hoje.year, hoje.month, 1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    token = token_idsf()
    ok = 0
    falhas: list[date] = []
    for y, m in meses_ate(inicio, fim):
        d = ultimo_dia_util(y, m)
        # Não pedir futuro além de hoje
        if d > date.today():
            d = date.today()
            while d.weekday() >= 5:
                d -= timedelta(days=1)
        path = salvar_fechamento(d, token=token, forcar=args.forcar)
        if path:
            ok += 1
        else:
            falhas.append(d)

    print(f"\nConcluído: {ok} PDFs. Falhas: {len(falhas)}")
    for d in falhas:
        print(f"  - {d}")


if __name__ == "__main__":
    main()
