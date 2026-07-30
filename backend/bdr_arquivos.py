"""Cliente da API BDR de arquivos (estoque, aquisições, liquidações).

Fluxo:
  1) GET /api/auth  (Basic) -> token (~3h)
  2) POST /api/arquivos/{tipo} -> ticket
  3) GET /api/arquivos/{ticket} até status processado + urls
  4) Download do CSV
"""

from __future__ import annotations

import csv
import hashlib
import io
import os
import time
from datetime import date, datetime
from typing import Any, Literal
from urllib.parse import urljoin

import requests
from dotenv import load_dotenv

load_dotenv()

TipoArquivo = Literal["estoque", "estoqueBDR", "aquisicoes", "liquidacoes"]
# Endpoint case-sensitive: /api/arquivos/estoqueBDR (colunas extras vs /estoque).
TIPOS_ESTOQUE = frozenset({"estoque", "estoqueBDR"})

DEFAULT_BASE = "https://api.services.bdrasset.com.br/"
STATUS_PRONTO = {
    "processado",
    "concluido",
    "concluído",
    "disponivel",
    "disponível",
    "ready",
    "ok",
    "success",
    "sucesso",
}
STATUS_ERRO = {"erro", "error", "falha", "failed", "cancelado", "cancelled"}
STATUS_SEM_DADOS = {
    "nenhuma informação disponível",
    "nenhuma informacao disponivel",
    "sem dados",
    "não encontrado",
    "nao encontrado",
}


def _base_url() -> str:
    return (os.getenv("BDR_API_BASE") or DEFAULT_BASE).rstrip("/") + "/"


def _auth_basic() -> tuple[str, str]:
    user = (os.getenv("BDR_BASIC_USER") or "").strip()
    password = (os.getenv("BDR_BASIC_PASSWORD") or "").strip()
    if not user or not password:
        raise RuntimeError(
            "Defina BDR_BASIC_USER e BDR_BASIC_PASSWORD no .env (Basic auth da API BDR)"
        )
    return user, password


def cnpj_fundo(cnpj: str | None = None) -> str:
    """CNPJ do fundo (14 dígitos). Prefere argumento; senão fundo cadastrado; senão .env."""
    if cnpj and str(cnpj).strip():
        digits = "".join(ch for ch in str(cnpj) if ch.isdigit())
        if len(digits) == 14:
            return digits
        raise ValueError(f"CNPJ inválido: {cnpj!r}")
    try:
        from fundos import fundo_padrao, normalizar_cnpj

        fundo = fundo_padrao()
        if fundo and fundo.get("cnpj"):
            return normalizar_cnpj(str(fundo["cnpj"]))
    except Exception:  # noqa: BLE001
        pass
    env = "".join(ch for ch in (os.getenv("BDR_CNPJ_FUNDO") or "") if ch.isdigit())
    if len(env) == 14:
        return env
    raise RuntimeError(
        "Defina o CNPJ do fundo em fidc_fundos ou BDR_CNPJ_FUNDO no .env"
    )


def obter_token(session: requests.Session | None = None) -> str:
    """GET /api/auth com Basic -> token Bearer/header authToken."""
    sess = session or requests.Session()
    user, password = _auth_basic()
    url = urljoin(_base_url(), "api/auth")

    ultimo_erro: Exception | None = None
    for tentativa in range(1, 6):
        try:
            resp = sess.get(url, auth=(user, password), timeout=60)
            resp.raise_for_status()
            data = resp.json()
            token = data.get("token") or data.get("authToken")
            if not token:
                raise RuntimeError(f"Resposta de /api/auth sem token: {data!r}")
            return str(token)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            ultimo_erro = exc
            espera = min(2 ** tentativa, 30)
            print(f"[bdr] auth falhou ({exc}); retry {tentativa}/5 em {espera}s")
            time.sleep(espera)
            sess = requests.Session()
    raise RuntimeError(f"Falha ao autenticar na BDR após retries: {ultimo_erro}")


def _headers(token: str) -> dict[str, str]:
    return {
        "authToken": token,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def solicitar_arquivo(
    tipo: TipoArquivo,
    *,
    token: str,
    ref_date: date | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    tp_contabil: str | None = None,
    cnpj: str | None = None,
    delimiter: str | None = None,
    decimal: str | None = None,
    session: requests.Session | None = None,
) -> str:
    """POST /api/arquivos/{tipo} -> ticket."""
    sess = session or requests.Session()
    url = urljoin(_base_url(), f"api/arquivos/{tipo}")
    # Estoque: padrão BR (; / ,). Movimentações mantêm CSV US se não informado.
    e_estoque = tipo in TIPOS_ESTOQUE
    if e_estoque:
        delim = delimiter if delimiter is not None else ";"
        dec = decimal if decimal is not None else ","
    else:
        delim = delimiter if delimiter is not None else ","
        dec = decimal if decimal is not None else "."
    body: dict[str, Any] = {
        "cnpj": cnpj_fundo(cnpj),
        "delimiter": delim,
        "decimal": dec,
        "fileFormat": "csv",
    }
    if e_estoque:
        if ref_date is None:
            raise ValueError(f"{tipo} exige ref_date")
        body["refDate"] = ref_date.isoformat()
        # Alpha / este fundo: estoque só responde com tpContabil=A (P → "sem info")
        body["tpContabil"] = tp_contabil or os.getenv("BDR_TP_CONTABIL_ESTOQUE", "A")
    else:
        if start_date is None or end_date is None:
            raise ValueError(f"{tipo} exige start_date e end_date")
        body["startDate"] = start_date.isoformat()
        body["endDate"] = end_date.isoformat()
        body["dateFormat"] = "dd/mm/yyyy"
        body["tpContabil"] = tp_contabil or os.getenv("BDR_TP_CONTABIL_MOV", "A")

    ultimo_erro: Exception | None = None
    token_atual = token
    for tentativa in range(1, 6):
        try:
            resp = sess.post(
                url, headers=_headers(token_atual), json=body, timeout=120
            )
            if resp.status_code in (401, 403) and tentativa < 5:
                token_atual = obter_token(sess)
                continue
            resp.raise_for_status()
            data = resp.json()
            ticket = data.get("ticket")
            if not ticket:
                raise RuntimeError(f"Resposta sem ticket ({tipo}): {data!r}")
            return str(ticket)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            ultimo_erro = exc
            espera = min(2 ** tentativa, 30)
            print(f"[bdr] solicitar {tipo} falhou ({exc}); retry {tentativa}/5 em {espera}s")
            time.sleep(espera)
            sess = requests.Session()
            token_atual = obter_token(sess)
    raise RuntimeError(f"Falha ao solicitar {tipo} após retries: {ultimo_erro}")


def consultar_ticket(
    ticket: str,
    *,
    token: str,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    sess = session or requests.Session()
    url = urljoin(_base_url(), f"api/arquivos/{ticket}")
    resp = sess.get(url, headers=_headers(token), timeout=60)
    resp.raise_for_status()
    return resp.json()


def aguardar_arquivo(
    ticket: str,
    *,
    token: str,
    timeout_s: float = 600,
    intervalo_s: float = 5,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    """Polling até haver URL de download ou status pronto."""
    sess = session or requests.Session()
    deadline = time.time() + timeout_s
    ultimo: dict[str, Any] = {}
    token_atual = token
    inicio = time.time()
    ultimo_log = 0.0
    while time.time() < deadline:
        try:
            ultimo = consultar_ticket(ticket, token=token_atual, session=sess)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            print(f"[bdr] poll {ticket[:8]}… conexão ({exc}); renovando sessão")
            time.sleep(3)
            sess = requests.Session()
            token_atual = obter_token(sess)
            continue
        except requests.exceptions.HTTPError as exc:
            if exc.response is not None and exc.response.status_code in (401, 403):
                token_atual = obter_token(sess)
                continue
            raise

        status = str(ultimo.get("status") or "").strip().lower()
        urls = ultimo.get("urls") or []
        zip_url = ultimo.get("zipUrl")
        agora = time.time()
        if agora - ultimo_log >= 120:
            print(
                f"[bdr] ticket={ticket[:8]}… status={status or '?'} "
                f"urls={len(urls)} elapsed={int(agora - inicio)}s"
            )
            ultimo_log = agora
        if urls or zip_url:
            return ultimo
        if status in STATUS_PRONTO and not urls and not zip_url:
            # Status pronto sem URL ainda — continua um pouco
            pass
        if status in STATUS_ERRO or status in STATUS_SEM_DADOS:
            raise RuntimeError(f"Ticket {ticket} falhou: {ultimo!r}")
        time.sleep(intervalo_s)
    raise TimeoutError(f"Timeout aguardando ticket {ticket}. Último: {ultimo!r}")


def _primeira_url(meta: dict[str, Any]) -> str:
    urls = meta.get("urls") or []
    if urls:
        u = urls[0].get("url") if isinstance(urls[0], dict) else None
        if u:
            return str(u)
    zip_url = meta.get("zipUrl")
    if zip_url:
        return str(zip_url)
    raise RuntimeError(f"Sem URL de download na resposta: {meta!r}")


def baixar_bytes(url: str, *, session: requests.Session | None = None) -> bytes:
    sess = session or requests.Session()
    resp = sess.get(url, timeout=300)
    resp.raise_for_status()
    return resp.content


def baixar_csv_bytes(
    meta: dict[str, Any],
    *,
    session: requests.Session | None = None,
) -> bytes:
    """Baixa o arquivo bruto (CSV) apontado pelo ticket."""
    url = _primeira_url(meta)
    raw = baixar_bytes(url, session=session)
    if raw[:2] == b"PK":
        raise RuntimeError(
            "Download veio como ZIP. Extraia manualmente ou evolua o cliente para unzip."
        )
    return raw


def baixar_csv_linhas(
    meta: dict[str, Any],
    *,
    session: requests.Session | None = None,
    delimiter: str | None = None,
) -> list[dict[str, str]]:
    """Baixa o arquivo e devolve lista de dicts (cabeçalho CSV)."""
    raw = baixar_csv_bytes(meta, session=session)
    texto = raw.decode("utf-8-sig", errors="replace")
    if delimiter:
        delim = delimiter
    else:
        sample = texto[:4096]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=";,\t")
            delim = dialect.delimiter
        except csv.Error:
            # CSVs BR da BDR usam ';' — o sniffer confunde com decimal ','
            delim = ";" if texto.count(";") >= texto.count(",") else ","
    reader = csv.DictReader(io.StringIO(texto), delimiter=delim)
    return [dict(row) for row in reader]


def hash_linha(dados: dict[str, Any]) -> str:
    """Hash estável da linha (ordem de chaves ordenada)."""
    itens = sorted((str(k).strip().lower(), str(v).strip()) for k, v in dados.items())
    canon = "|".join(f"{k}={v}" for k, v in itens)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def extrair_data_movimento(dados: dict[str, Any]) -> date | None:
    """Tenta achar uma data de movimento nos campos comuns do CSV BDR."""
    candidatos = (
        "data movimento",  # CSV BDR: "DATA MOVIMENTO"
        "data_movimento",
        "dt_movimento",
        "entrada",  # aquisições BDR
        "data liquidacao",
        "data_liquidacao",
        "dt_liquidacao",
        "data aquisicao",
        "data_aquisicao",
        "dt_aquisicao",
        "data",
        "refdate",
        "ref_date",
    )
    # Normaliza espaços/underscores para casar "DATA MOVIMENTO" e "data_movimento"
    lower_map = {
        str(k).strip().lower().replace("_", " "): v for k, v in dados.items()
    }
    for nome in candidatos:
        chave = nome.lower().replace("_", " ")
        val = lower_map.get(chave)
        if val is None or str(val).strip() == "":
            continue
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                return datetime.strptime(str(val).strip()[:10], fmt).date()
            except ValueError:
                continue
    return None
