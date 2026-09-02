"""Carteira aberta a partir do histórico BDR (aquisições − liquidações).

Não usa BD_Estoque. Replay de eventos até a data base → DataFrame canônico
para o motor de risco.

Cache: data/carteira_mov_eventos.jsonl (um evento por linha).
Rebuild: python carteira_movimentacoes.py --forcar
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from collections.abc import Callable
from typing import Any

import pandas as pd

from bdr_arquivos import cnpj_fundo, extrair_data_movimento
from marcacao_carteira import money_half_up

CACHE_PATH = Path(__file__).resolve().parent / "data" / "carteira_mov_eventos.jsonl"
META_PATH = Path(__file__).resolve().parent / "data" / "carteira_mov_meta.json"
DIARIO_PATH = Path(__file__).resolve().parent / "data" / "carteira_mov_diario.json"
MOTOR_ESTADO_PATH = (
    Path(__file__).resolve().parent / "data" / "motor_estado_conciliado.json"
)
MOTOR_ESTADO_VERSAO = "1"
PRAZO_PATH = Path(__file__).resolve().parent / "data" / "carteira_prazo_bdr.json"
RELATORIOS_DIR = Path(__file__).resolve().parent / "data" / "relatorios"
# Estoque BDR de abertura do dashboard (snapshot); movimentos anteriores são descartados.
ESTOQUE_BASE_PATH = RELATORIOS_DIR / "EstoqueBDR_2024-05-31.csv"
DATA_MINIMA = date(2024, 5, 31)
PAGE_SIZE = 1000


def _sem_disco_persistente() -> bool:
    """Vercel Functions não guardam o JSONL de eventos entre requests."""
    return bool(os.getenv("VERCEL"))

TOLERANCIA_DC_ABS = 500.0
TOLERANCIA_DC_PCT = 0.0001

OCORRENCIAS_BAIXA_TOTAL = {
    "LIQUIDACAO NORMAL",
    "LIQUIDAÇÃO NORMAL",
    "BAIXA POR DEPOSITO SACADO",
    "BAIXA POR DEPÓSITO SACADO",
    "BAIXA POR RECOMPRA",
}


def _parse_valor(valor: Any) -> float:
    if valor is None:
        return 0.0
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        return float(valor)
    texto = str(valor).strip()
    if not texto or texto.lower() in {"nan", "none", "null"}:
        return 0.0
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return 0.0


def _parse_data_campo(valor: Any) -> date | None:
    if valor is None:
        return None
    if isinstance(valor, date) and not isinstance(valor, datetime):
        return valor
    texto = str(valor).strip()[:10]
    if not texto:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(texto, fmt).date()
        except ValueError:
            continue
    return None


def _dados_dict(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _norm_key(*candidatos: Any) -> str:
    for c in candidatos:
        texto = str(c or "").strip()
        if texto and texto.lower() not in {"nan", "none", "null"}:
            return texto
    return ""


def _ocorrencia_norm(texto: str) -> str:
    return (
        str(texto or "")
        .strip()
        .upper()
        .replace("Ç", "C")
        .replace("Ã", "A")
        .replace("Õ", "O")
        .replace("É", "E")
        .replace("Ê", "E")
        .replace("Ó", "O")
    )


def _taxa_implicita_aa(compra: float, face: float, dias_prazo: float) -> float:
    """Taxa a.a. decimal implícita: compra = face / (1+am)^(dias/30)."""
    if compra <= 0 or face <= 0 or dias_prazo <= 0:
        return 0.0
    try:
        am = (face / compra) ** (30.0 / float(dias_prazo)) - 1.0
        if am <= -0.999999:
            return 0.0
        aa = (1.0 + am) ** 12.0 - 1.0
        if aa < -0.99 or aa > 50:
            return 0.0
        return float(aa)
    except (OverflowError, ValueError, ZeroDivisionError):
        return 0.0


def _evento_aquisicao(dados: dict[str, Any], data_ev: date) -> dict[str, Any] | None:
    chave = _norm_key(
        dados.get("SEU NUMERO"),
        dados.get("NUMERO DOCUMENTO"),
        dados.get("NM_CESSAO_BDR"),
        dados.get("NM_CESSAO"),
        dados.get("ID RECEBIVEL"),
    )
    if not chave:
        return None
    nm_bdr = _norm_key(dados.get("NM_CESSAO_BDR"), dados.get("NM_CESSAO"))
    face = _parse_valor(dados.get("VALOR DE VENCIMENTO"))
    compra = _parse_valor(dados.get("VALOR DE COMPRA"))
    venc = _parse_data_campo(dados.get("DATA VENCIMENTO"))
    entrada = _parse_data_campo(dados.get("ENTRADA")) or data_ev
    dias = (venc - entrada).days if venc else 0
    return {
        "tipo": "aquisicao",
        "data": data_ev.isoformat(),
        "chave": chave,
        "documento": _norm_key(dados.get("NUMERO DOCUMENTO"), chave),
        "nm_cessao_bdr": nm_bdr or chave,
        "cedente": str(dados.get("CEDENTE") or "").strip(),
        "sacado": str(dados.get("NOME SACADO") or dados.get("SACADO") or "").strip(),
        "doc_sacado": str(
            dados.get("CPF_CNPJ_SACADO")
            or dados.get("DOC SACADO")
            or dados.get("DOCUMENTO SACADO")
            or dados.get("CPF/CNPJ SACADO")
            or dados.get("CNPJ SACADO")
            or dados.get("CPF SACADO")
            or ""
        ).strip(),
        "tipo_recebivel": str(dados.get("TIPO RECEBIVEL") or "").strip(),
        "data_emissao": entrada.isoformat(),
        "data_vencimento": venc.isoformat() if venc else None,
        "valor_face": round(face, 8),
        "valor_descontado": round(compra, 8),
        "taxa_operacao": _taxa_implicita_aa(compra, face, float(dias)),
    }


def _evento_liquidacao(dados: dict[str, Any], data_ev: date) -> dict[str, Any] | None:
    chave = _norm_key(
        dados.get("SEU NUMERO"),
        dados.get("DOCUMENTO"),
        dados.get("NM_CESSAO_BDR"),
        dados.get("NM_CESSAO"),
        dados.get("ID_RECEBIVEL"),
        dados.get("ID RECEBIVEL"),
    )
    if not chave:
        return None
    oc = str(dados.get("OCORRENCIA") or "").strip()
    oc_n = _ocorrencia_norm(oc)
    parcial = "PARCIAL" in oc_n
    return {
        "tipo": "liquidacao",
        "data": data_ev.isoformat(),
        "chave": chave,
        "nm_cessao_bdr": _norm_key(dados.get("NM_CESSAO_BDR"), dados.get("NM_CESSAO"), chave),
        "ocorrencia": oc,
        "parcial": parcial,
        "valor_pago": round(_parse_valor(dados.get("VALOR DE PAGO")), 8),
        "valor_aquisicao": round(_parse_valor(dados.get("VALOR DE AQUISICAO")), 8),
    }


def _paginar_tabela(tabela: str, cnpj: str) -> list[dict[str, Any]]:
    from db import get_supabase

    sb = get_supabase()
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        resp = (
            sb.table(tabela)
            .select("dados")
            .eq("cnpj_fundo", cnpj)
            .order("id")
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
        )
        batch = resp.data or []
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return rows


def reconstruir_eventos(cnpj: str | None = None, *, forcar: bool = False) -> dict[str, Any]:
    """Lê aq/liq no Supabase e grava JSONL de eventos ordenados."""
    cnpj_n = cnpj_fundo(cnpj)
    if not forcar and CACHE_PATH.exists() and META_PATH.exists():
        try:
            meta = json.loads(META_PATH.read_text(encoding="utf-8"))
            if meta.get("cnpj_fundo") == cnpj_n and int(meta.get("eventos") or 0) > 0:
                return meta
        except (OSError, json.JSONDecodeError, TypeError):
            pass

    eventos: list[dict[str, Any]] = []
    sem_data = 0
    sem_chave = 0

    for row in _paginar_tabela("fidc_aquisicoes", cnpj_n):
        dados = _dados_dict(row.get("dados"))
        dm = extrair_data_movimento(dados) or _parse_data_campo(dados.get("ENTRADA"))
        if dm is None:
            sem_data += 1
            continue
        ev = _evento_aquisicao(dados, dm)
        if ev is None:
            sem_chave += 1
            continue
        eventos.append(ev)

    for row in _paginar_tabela("fidc_liquidacoes", cnpj_n):
        dados = _dados_dict(row.get("dados"))
        dm = extrair_data_movimento(dados)
        if dm is None:
            sem_data += 1
            continue
        ev = _evento_liquidacao(dados, dm)
        if ev is None:
            sem_chave += 1
            continue
        eventos.append(ev)

    # Ordem estável: data, aquisições antes de liquidações no mesmo dia, chave
    ordem_tipo = {"aquisicao": 0, "liquidacao": 1}
    eventos.sort(
        key=lambda e: (
            e["data"],
            ordem_tipo.get(e["tipo"], 9),
            e.get("chave") or "",
        )
    )

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CACHE_PATH.open("w", encoding="utf-8") as fh:
        for ev in eventos:
            fh.write(json.dumps(ev, ensure_ascii=False) + "\n")

    meta = {
        "cnpj_fundo": cnpj_n,
        "atualizado_em": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "eventos": len(eventos),
        "sem_data": sem_data,
        "sem_chave": sem_chave,
        "cache": str(CACHE_PATH.name),
    }
    META_PATH.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


_EVENTOS_MEM: tuple[tuple[float, int], list[dict[str, Any]]] | None = None


def _idx_evento_depois(eventos: list[dict[str, Any]], data_iso: str) -> int:
    """Primeiro índice com data > data_iso (eventos ordenados por data)."""
    lo, hi = 0, len(eventos)
    while lo < hi:
        mid = (lo + hi) // 2
        if str(eventos[mid].get("data") or "") <= data_iso:
            lo = mid + 1
        else:
            hi = mid
    return lo


def _eventos_todos() -> list[dict[str, Any]]:
    """JSONL parseado uma vez; invalida quando o arquivo muda."""
    global _EVENTOS_MEM
    if not CACHE_PATH.exists():
        reconstruir_eventos(forcar=True)
    st = CACHE_PATH.stat()
    sig = (st.st_mtime, st.st_size)
    if _EVENTOS_MEM is not None and _EVENTOS_MEM[0] == sig:
        return _EVENTOS_MEM[1]
    eventos: list[dict[str, Any]] = []
    with CACHE_PATH.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            eventos.append(json.loads(line))
    _EVENTOS_MEM = (sig, eventos)
    return eventos


def _carregar_eventos(
    *,
    desde: date | None = DATA_MINIMA,
    ate: date | None = None,
) -> list[dict[str, Any]]:
    todos = _eventos_todos()
    inicio = _idx_evento_depois(todos, desde.isoformat()) if desde else 0
    fim = _idx_evento_depois(todos, ate.isoformat()) if ate else len(todos)
    return todos[inicio:fim]


def _row_get(row: pd.Series, *names: str) -> Any:
    """Busca coluna ignorando maiúsculas/minúsculas."""
    lower = {str(c).lower(): c for c in row.index}
    for n in names:
        if n in row.index:
            return row.get(n)
        key = lower.get(n.lower())
        if key is not None:
            return row.get(key)
    return None


_ESTOQUE_BASE_CACHE: dict[str, dict[str, dict[str, Any]]] = {}
_PRAZO_CACHE: tuple[tuple[tuple[str, float, int], ...], dict[str, int]] | None = None
# v3: aliases do schema /estoqueBDR (pz_total, nm_cessao, …).
_PRAZO_CACHE_VERSAO = 3


def _assinatura_estoques_bdr() -> tuple[tuple[str, float, int], ...]:
    """Assinatura dos CSVs EstoqueBDR (nome, mtime, tamanho) para invalidar o cache."""
    out: list[tuple[str, float, int]] = []
    for path in sorted(RELATORIOS_DIR.glob("EstoqueBDR_*.csv")):
        try:
            st = path.stat()
            out.append((path.name, st.st_mtime, st.st_size))
        except OSError:
            continue
    return tuple(out)


def chave_prazo_safra(documento: object, vencimento: object) -> str:
    """Chave ``documento|vencimento`` usada para desambiguar safras."""
    doc = str(documento or "").strip()
    venc = str(vencimento or "").strip()[:10]
    return f"{doc}|{venc}"


def resolver_prazo(
    mapa: dict[str, int],
    documento: object,
    vencimento: object = None,
    *documentos_alternativos: object,
) -> int | None:
    """
    PRAZO do registrador para um título.

    Números de documento (SEU_NUMERO) são reciclados pelos cedentes: o mesmo
    número reaparece anos depois em outro título, com outro PRAZO. Quando há
    conflito, o mapa guarda chaves ``documento|vencimento``; a busca por
    documento puro só resolve quando existe um PRAZO único para ele.
    """
    docs = [documento, *documentos_alternativos]
    if vencimento:
        for doc in docs:
            if not str(doc or "").strip():
                continue
            prazo = mapa.get(chave_prazo_safra(doc, vencimento))
            if prazo:
                return int(prazo)
    for doc in docs:
        chave = str(doc or "").strip()
        if not chave:
            continue
        prazo = mapa.get(chave)
        if prazo:
            return int(prazo)
    return None


def mapa_prazo_bdr(*, forcar: bool = False) -> dict[str, int]:
    """
    PRAZO contratual por título (coluna PRAZO do EstoqueBDR), congelado na
    aquisição. Varre todos os EstoqueBDR_*.csv; a primeira ocorrência ganha.

    Documentos reciclados (mesmo SEU_NUMERO em safras distintas, com PRAZO
    diferente) ganham chaves extras ``documento|vencimento``. Use
    :func:`resolver_prazo` para consultar o mapa.
    """
    global _PRAZO_CACHE

    assinatura = _assinatura_estoques_bdr()
    if not forcar and _PRAZO_CACHE is not None and _PRAZO_CACHE[0] == assinatura:
        return _PRAZO_CACHE[1]

    mapa: dict[str, int] = {}
    if not forcar and PRAZO_PATH.exists() and assinatura:
        try:
            raw = json.loads(PRAZO_PATH.read_text(encoding="utf-8"))
            if int(raw.get("versao") or 1) == _PRAZO_CACHE_VERSAO and raw.get(
                "assinatura"
            ) == [list(x) for x in assinatura]:
                mapa = {
                    str(k): int(v)
                    for k, v in (raw.get("por_titulo") or {}).items()
                    if v not in (None, "", 0)
                }
                _PRAZO_CACHE = (assinatura, mapa)
                return mapa
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            mapa = {}

    # doc -> {vencimento: prazo} (primeira ocorrência de cada safra)
    por_safra: dict[str, dict[str, int]] = {}
    for path in sorted(RELATORIOS_DIR.glob("EstoqueBDR_*.csv")):
        try:
            df = pd.read_csv(
                path,
                sep=";",
                dtype=str,
                encoding="utf-8-sig",
                usecols=lambda c: str(c).upper()
                in {
                    "SEU_NUMERO",
                    "NU_DOCUMENTO",
                    "NM_CESSAO",
                    "NM_CESSAO_BDR",
                    "N_CONTROLE_LASTRO_ORIGEM",
                    "N_CONTROLE_LASTRO_BDR",
                    "PRAZO",
                    "PZ_TOTAL",
                    "DATA_VENCIMENTO_AJUSTADA",
                    "DATA_VENCIMENTO_ORIGINAL",
                    "DT_VENC_AJUSTADO",
                    "DT_VENC_ORIGEM",
                },
            )
        except (OSError, ValueError, pd.errors.EmptyDataError):
            continue
        cols = {str(c).upper(): c for c in df.columns}
        col_doc = (
            cols.get("NM_CESSAO")
            or cols.get("NM_CESSAO_BDR")
            or cols.get("N_CONTROLE_LASTRO_ORIGEM")
            or cols.get("N_CONTROLE_LASTRO_BDR")
            or cols.get("SEU_NUMERO")
            or cols.get("NU_DOCUMENTO")
        )
        col_prazo = cols.get("PZ_TOTAL") or cols.get("PRAZO")
        col_venc = (
            cols.get("DT_VENC_AJUSTADO")
            or cols.get("DATA_VENCIMENTO_AJUSTADA")
            or cols.get("DT_VENC_ORIGEM")
            or cols.get("DATA_VENCIMENTO_ORIGINAL")
        )
        if col_doc is None or col_prazo is None:
            continue
        vencs = (
            df[col_venc] if col_venc is not None else pd.Series([""] * len(df))
        )
        for doc, prazo_raw, venc_raw in zip(
            df[col_doc], df[col_prazo], vencs, strict=False
        ):
            chave = str(doc or "").strip()
            if not chave or chave.lower() in {"nan", "none", "null"}:
                continue
            try:
                prazo = int(float(str(prazo_raw).replace(",", ".")))
            except (TypeError, ValueError):
                continue
            if prazo <= 0:
                continue
            if chave not in mapa:
                mapa[chave] = prazo
            venc = str(venc_raw or "").strip()[:10]
            if venc:
                por_safra.setdefault(chave, {}).setdefault(venc, prazo)

    # Só desambigua o que de fato conflita: documento reciclado com PRAZO
    # diferente entre safras. O resto continua resolvendo pelo documento puro.
    for chave, safras in por_safra.items():
        if len(set(safras.values())) < 2:
            continue
        for venc, prazo in safras.items():
            mapa[chave_prazo_safra(chave, venc)] = prazo

    try:
        PRAZO_PATH.parent.mkdir(parents=True, exist_ok=True)
        PRAZO_PATH.write_text(
            json.dumps(
                {
                    "atualizado_em": datetime.now(timezone.utc)
                    .isoformat(timespec="seconds")
                    .replace("+00:00", "Z"),
                    "versao": _PRAZO_CACHE_VERSAO,
                    "titulos": len(mapa),
                    "assinatura": [list(x) for x in assinatura],
                    "por_titulo": mapa,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except OSError:
        pass

    _PRAZO_CACHE = (assinatura, mapa)
    return mapa


def _col_series(df: pd.DataFrame, *names: str) -> pd.Series | None:
    lower = {str(c).lower(): c for c in df.columns}
    for n in names:
        if n in df.columns:
            return df[n]
        key = lower.get(n.lower())
        if key is not None:
            return df[key]
    return None


def carregar_estoque_base(caminho: Path | None = None) -> dict[str, dict[str, Any]]:
    """Abre posição a partir do CSV EstoqueBDR (snapshot DATA_MINIMA)."""
    path = caminho or ESTOQUE_BASE_PATH
    cache_key = str(path.resolve())
    cached = _ESTOQUE_BASE_CACHE.get(cache_key)
    if cached is not None:
        # Cópia rasa das posições (valores imutáveis o bastante para o replay)
        return {k: dict(v) for k, v in cached.items()}

    if not path.exists():
        raise FileNotFoundError(
            f"Estoque-base BDR não encontrado: {path}. "
            "Rode: python baixar_estoque_bdr.py --data 2024-05-31"
        )
    df = pd.read_csv(path, sep=";", dtype=str, encoding="utf-8-sig")
    s_chave = _col_series(
        df,
        "nm_cessao",
        "nm_cessao_bdr",
        "n_controle_lastro_origem",
        "n_controle_lastro_bdr",
        "SEU_NUMERO",
        "NU_DOCUMENTO",
    )
    s_face = _col_series(df, "vl_face", "VALOR_NOMINAL", "valor_nominal")
    s_compra = _col_series(df, "vl_aquisicao", "VALOR_AQUISICAO", "valor_aquisicao")
    s_taxa = _col_series(df, "tx_cessao", "TAXA_CESSAO", "TX_RECEBIVEL")
    s_venc = _col_series(
        df,
        "dt_venc_ajustado",
        "DATA_VENCIMENTO_AJUSTADA",
        "dt_venc_origem",
        "DATA_VENCIMENTO_ORIGINAL",
    )
    s_emis = _col_series(df, "dt_emissao", "DATA_EMISSAO")
    s_aq = _col_series(df, "dt_aquisicao", "DATA_AQUISICAO")
    s_vp = _col_series(
        df, "vl_presente_adm", "vl_presente_bdr", "VALOR_PRESENTE", "valor_presente"
    )
    s_pdd = _col_series(df, "vl_pdd", "VALOR_PDD")
    s_fx = _col_series(df, "fx_pdd", "FAIXA_PDD")
    s_prazo = _col_series(df, "pz_total", "prazo", "PRAZO")
    s_ced = _col_series(df, "nm_cedente", "NOME_CEDENTE")
    s_sac = _col_series(df, "nm_sacado", "NOME_SACADO")
    s_doc_sac = _col_series(df, "doc_sacado", "DOC_SACADO", "cpf_cnpj_sacado")
    s_tipo = _col_series(df, "tp_recebivel", "TIPO_RECEBIVEL")

    abertos: dict[str, dict[str, Any]] = {}
    n = len(df)
    for i in range(n):
        chave = str(s_chave.iloc[i] if s_chave is not None else "").strip()
        if not chave or chave.lower() in {"nan", "none", "null"}:
            continue
        venc = _parse_data_campo(s_venc.iloc[i] if s_venc is not None else None)
        emis = _parse_data_campo(s_emis.iloc[i] if s_emis is not None else None)
        aq = _parse_data_campo(s_aq.iloc[i] if s_aq is not None else None)
        # O CSV da BDR grava os valores em float32 (185.11999512 = 185,12);
        # normalizar em centavos evita propagar esse ruído na marcação.
        face = money_half_up(_parse_valor(s_face.iloc[i] if s_face is not None else 0))
        compra = money_half_up(
            _parse_valor(s_compra.iloc[i] if s_compra is not None else 0)
        )
        taxa = _parse_valor(s_taxa.iloc[i] if s_taxa is not None else 0)
        vp_adm = money_half_up(_parse_valor(s_vp.iloc[i] if s_vp is not None else 0))
        doc_sac = str(s_doc_sac.iloc[i] if s_doc_sac is not None else "").strip()
        if doc_sac.lower() in {"", "nan", "none", "null"}:
            doc_sac = ""
        prazo = None
        if s_prazo is not None:
            try:
                prazo_i = int(float(str(s_prazo.iloc[i]).replace(",", ".")))
                if prazo_i > 0:
                    prazo = prazo_i
            except (TypeError, ValueError):
                prazo = None
        abertos[chave] = {
            "documento": chave,
            "cedente": str(s_ced.iloc[i] if s_ced is not None else "").strip(),
            "sacado": str(s_sac.iloc[i] if s_sac is not None else "").strip(),
            "doc_sacado": doc_sac,
            "tipo_recebivel": str(s_tipo.iloc[i] if s_tipo is not None else "").strip(),
            "data_emissao": emis.isoformat() if emis else None,
            "data_aquisicao": aq.isoformat() if aq else None,
            "data_vencimento": venc.isoformat() if venc else None,
            "valor_face": face,
            "valor_descontado": compra,
            "taxa_operacao": taxa if taxa else 0.0,
            "prazo": prazo,
            "vl_presente_adm": vp_adm if vp_adm else None,
            "vl_pdd": money_half_up(
                _parse_valor(s_pdd.iloc[i] if s_pdd is not None else 0)
            ),
            "fx_pdd": str(s_fx.iloc[i] if s_fx is not None else "").strip() or None,
        }

    _ESTOQUE_BASE_CACHE[cache_key] = abertos
    return {k: dict(v) for k, v in abertos.items()}


# Repactuações confirmadas que não entraram em fidc_aquisicoes/liquidacoes.
# Aplicadas no replay a partir de ``desde`` (inclusive).
REPACTUACOES: tuple[dict[str, Any], ...] = (
    {
        "chave": "2927001",  # Batatas Premium LTDA
        "desde": "2025-08-01",
        "data_vencimento": "2025-09-30",
        "prazo": 42,  # PRAZO no EstoqueBDR após a repactuação
        "motivo": "Repactuação de vencimento não lançada nas movimentações",
    },
)


def _aplicar_repactuacoes(
    abertos: dict[str, dict[str, Any]],
    data_limite: date,
) -> dict[str, dict[str, Any]]:
    """Sobrescreve vencimento/prazo de títulos com repactuação manual."""
    if not abertos or not REPACTUACOES:
        return abertos
    limite = data_limite.isoformat()
    for adj in REPACTUACOES:
        desde = str(adj.get("desde") or "")
        if not desde or limite < desde:
            continue
        chave = str(adj.get("chave") or "").strip()
        if not chave:
            continue
        pos = abertos.get(chave)
        if pos is None:
            for p in abertos.values():
                if str(p.get("documento") or "").strip() == chave:
                    pos = p
                    break
        if pos is None:
            continue
        venc = adj.get("data_vencimento")
        if venc:
            pos["data_vencimento"] = str(venc)
        prazo = adj.get("prazo")
        if prazo not in (None, "", 0, 0.0):
            try:
                pos["prazo"] = int(prazo)
            except (TypeError, ValueError):
                pass
        pos["repactuacao"] = {
            "desde": desde,
            "data_vencimento": str(venc) if venc else None,
            "prazo": pos.get("prazo"),
            "motivo": adj.get("motivo") or "",
        }
    return abertos


def _aplicar_eventos_ate(
    eventos: list[dict[str, Any]],
    data_limite: date,
    *,
    base: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    limite = data_limite.isoformat()
    abertos: dict[str, dict[str, Any]] = {
        k: dict(v) for k, v in (base or {}).items()
    }
    prazos = mapa_prazo_bdr()

    for ev in eventos:
        if str(ev.get("data") or "") > limite:
            break
        chave = str(ev.get("chave") or "")
        if not chave:
            continue

        if ev.get("tipo") == "aquisicao":
            prev = abertos.get(chave)
            if prev is None:
                prazo = resolver_prazo(
                    prazos,
                    chave,
                    ev.get("data_vencimento"),
                    ev.get("documento"),
                )
                abertos[chave] = {
                    "documento": ev.get("documento") or chave,
                    "nm_cessao_bdr": ev.get("nm_cessao_bdr") or ev.get("documento") or chave,
                    "cedente": ev.get("cedente") or "",
                    "sacado": ev.get("sacado") or "",
                    "doc_sacado": str(ev.get("doc_sacado") or "").strip(),
                    "tipo_recebivel": ev.get("tipo_recebivel") or "",
                    "data_emissao": ev.get("data_emissao"),
                    "data_vencimento": ev.get("data_vencimento"),
                    "data_aquisicao": ev.get("data"),
                    "valor_face": float(ev.get("valor_face") or 0),
                    "valor_descontado": float(ev.get("valor_descontado") or 0),
                    "taxa_operacao": float(ev.get("taxa_operacao") or 0),
                    "prazo": prazo,
                    "vl_presente_adm": None,
                    "vl_pdd": None,
                    "fx_pdd": None,
                }
            else:
                prev["valor_face"] = float(prev["valor_face"]) + float(
                    ev.get("valor_face") or 0
                )
                prev["valor_descontado"] = float(prev["valor_descontado"]) + float(
                    ev.get("valor_descontado") or 0
                )
                venc_prev = prev.get("data_vencimento")
                venc_novo = ev.get("data_vencimento")
                venc_mudou = False
                if venc_novo and (not venc_prev or str(venc_novo) > str(venc_prev)):
                    prev["data_vencimento"] = venc_novo
                    prev["taxa_operacao"] = float(ev.get("taxa_operacao") or 0)
                    venc_mudou = True
                # Aditamento move o vencimento e o registrador recalcula o PRAZO.
                if venc_mudou or not prev.get("prazo"):
                    prev["prazo"] = (
                        resolver_prazo(
                            prazos,
                            chave,
                            prev.get("data_vencimento"),
                            ev.get("documento"),
                        )
                        or prev.get("prazo")
                    )
                prev["vl_presente_adm"] = None
            continue

        pos = abertos.get(chave)
        if pos is None:
            continue
        if ev.get("parcial"):
            # LIQUIDAÇÃO PARCIAL: BDR reduz a face pelo valor_pago (não pelo
            # valor_aquisicao, que no arquivo de movimento vem como custo cheio
            # remanescente e zerava o título indevidamente).
            face_rest = float(pos.get("valor_face") or 0)
            pago = float(ev.get("valor_pago") or 0)
            if face_rest <= 0 or pago <= 0:
                continue
            baixa_face = min(pago, face_rest)
            novo_face = face_rest - baixa_face
            fator = (novo_face / face_rest) if face_rest else 0.0
            pos["valor_face"] = round(novo_face, 8)
            aq_rest = float(pos.get("valor_descontado") or 0)
            pos["valor_descontado"] = round(aq_rest * fator, 8)
            vp_ref = pos.get("vl_presente_adm")
            if vp_ref not in (None, 0, 0.0):
                pos["vl_presente_adm"] = float(vp_ref) * fator
            else:
                pos["vl_presente_adm"] = None
            if pos["valor_face"] <= 0.005:
                del abertos[chave]
        else:
            del abertos[chave]

    return _aplicar_repactuacoes(abertos, data_limite)


def _ler_mapa_prazo_atual_bdr(path: Path) -> dict[str, int]:
    try:
        df = pd.read_csv(
            path,
            sep=";",
            dtype=str,
            encoding="utf-8-sig",
            usecols=lambda c: str(c).upper()
            in {
                "SEU_NUMERO",
                "NU_DOCUMENTO",
                "NM_CESSAO",
                "NM_CESSAO_BDR",
                "N_CONTROLE_LASTRO_ORIGEM",
                "N_CONTROLE_LASTRO_BDR",
                "PRAZO_ATUAL",
                "PZ_ATUAL",
            },
        )
    except (OSError, ValueError, pd.errors.EmptyDataError):
        return {}
    cols = {str(c).upper(): c for c in df.columns}
    col_doc = (
        cols.get("NM_CESSAO")
        or cols.get("NM_CESSAO_BDR")
        or cols.get("N_CONTROLE_LASTRO_ORIGEM")
        or cols.get("N_CONTROLE_LASTRO_BDR")
        or cols.get("SEU_NUMERO")
        or cols.get("NU_DOCUMENTO")
    )
    col_atual = cols.get("PZ_ATUAL") or cols.get("PRAZO_ATUAL")
    if col_doc is None or col_atual is None:
        return {}
    mapa: dict[str, int] = {}
    for doc, raw in zip(df[col_doc], df[col_atual], strict=False):
        chave = str(doc or "").strip()
        if not chave or chave in mapa:
            continue
        try:
            atual = int(float(str(raw).replace(",", ".")))
        except (TypeError, ValueError):
            continue
        if atual > 0:
            mapa[chave] = atual
    return mapa


def _estoque_bdr_util_anterior(data_ref: date, *, max_retro: int = 10) -> tuple[date, Path] | None:
    """Último EstoqueBDR em dia útil estritamente anterior a data_ref."""
    from calendario import dia_util_anterior

    d = dia_util_anterior(data_ref)
    for _ in range(max_retro):
        path = RELATORIOS_DIR / f"EstoqueBDR_{d.isoformat()}.csv"
        if path.exists() and path.stat().st_size > 1000:
            return d, path
        d = dia_util_anterior(d)
    return None


def anexar_prazo_atual_do_dia(
    abertos: dict[str, dict[str, Any]],
    data_ref: date,
) -> dict[str, dict[str, Any]]:
    """
    Se existir EstoqueBDR do dia, copia PRAZO_ATUAL para cada título aberto.
    Assim a marcação usa a mesma contagem remanescente do registrador naquela data.

    Exceção: se o PRAZO_ATUAL cair mais do que o esperado entre o estoque útil
    anterior e o do dia (salto < −N DU), ignora o valor do BDR e deixa o motor
    recalcular pelo calendário próprio. Os títulos afetados ficam marcados em
    ``prazo_atual_ignorado`` / ``salto_prazo_atual`` para log e tolerância.
    """
    from calendario import dias_uteis_entre

    path = RELATORIOS_DIR / f"EstoqueBDR_{data_ref.isoformat()}.csv"
    if not path.exists() or not abertos:
        return abertos
    mapa = _ler_mapa_prazo_atual_bdr(path)
    if not mapa:
        return abertos

    mapa_ant: dict[str, int] = {}
    data_ant: date | None = None
    esperado = 1
    ant = _estoque_bdr_util_anterior(data_ref)
    if ant is not None:
        data_ant, path_ant = ant
        mapa_ant = _ler_mapa_prazo_atual_bdr(path_ant)
        esperado = max(1, int(dias_uteis_entre(data_ant, data_ref)))

    saltos: list[dict[str, Any]] = []
    for chave, pos in abertos.items():
        doc = chave if chave in mapa else str(pos.get("documento") or "").strip()
        atual = mapa.get(chave) or mapa.get(doc)
        if not atual:
            continue
        pos.pop("prazo_atual_ignorado", None)
        pos.pop("salto_prazo_atual", None)
        anterior = mapa_ant.get(chave) or mapa_ant.get(doc)
        if anterior is not None:
            delta = int(atual) - int(anterior)
            # Ex.: esperado=-1 (1 DU), delta=-2 → salto anômalo.
            if delta < -esperado:
                pos["prazo_atual_ignorado"] = True
                pos["salto_prazo_atual"] = {
                    "prazo_atual_bdr": int(atual),
                    "prazo_atual_anterior": int(anterior),
                    "delta": delta,
                    "esperado": -esperado,
                    "data_anterior": data_ant.isoformat() if data_ant else None,
                }
                saltos.append(
                    {
                        "doc": doc or chave,
                        "sacado": str(pos.get("sacado") or ""),
                        "prazo_atual_bdr": int(atual),
                        "prazo_atual_anterior": int(anterior),
                        "delta": delta,
                        "esperado": -esperado,
                    }
                )
                # Não anexa PRAZO_ATUAL → vp_por_prazo usa calendário do motor.
                pos.pop("prazo_atual", None)
                continue
        pos["prazo_atual"] = atual

    if saltos:
        pos0 = next(iter(abertos.values()))
        pos0["_saltos_prazo_atual_dia"] = {
            "data": data_ref.isoformat(),
            "data_anterior": data_ant.isoformat() if data_ant else None,
            "esperado": -esperado,
            "n": len(saltos),
            "titulos": saltos,
        }
    return abertos


def saltos_prazo_atual_do_dia(
    abertos: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Metadados do salto anômalo de PRAZO_ATUAL detectado em anexar_prazo_atual_do_dia."""
    for pos in abertos.values():
        meta = pos.get("_saltos_prazo_atual_dia")
        if isinstance(meta, dict) and int(meta.get("n") or 0) > 0:
            return meta
    return None


def _totais_motor(abertos: dict[str, dict[str, Any]]) -> dict[str, float]:
    """Totais (VP, PDD, face) sobre posições já marcadas pelo motor."""
    if not abertos:
        return {"dc_bdr": 0.0, "face": 0.0, "n": 0.0, "vp": 0.0, "pdd": 0.0}

    face_t = 0.0
    vp_t = 0.0
    pdd_t = 0.0
    for pos in abertos.values():
        face_t += float(pos.get("valor_face") or 0)
        vp_t += float(pos.get("vl_presente_adm") or 0)
        pdd_t += float(pos.get("vl_pdd") or 0)

    return {
        "dc_bdr": round(vp_t - pdd_t, 2),
        "face": round(face_t, 2),
        "n": float(len(abertos)),
        "vp": round(vp_t, 2),
        "pdd": round(pdd_t, 2),
    }


def _idsf_do_dia(data_ref: date) -> dict[str, float]:
    """DC bruto, PDD e DC líquido da carteira IDSF na data."""
    from idsf_pl_pdd import buscar_posicoes_caixa_aplicacoes

    pos = buscar_posicoes_caixa_aplicacoes(data_ref)
    bruto = float(pos.get("total_dc_bruto_idsf") or 0)
    pdd = float(pos.get("total_pdd_idsf") or 0)
    liquido = float(pos.get("total_dc_idsf") or 0)
    if not bruto and (liquido or pdd):
        bruto = liquido + pdd
    return {
        "dc_bruto_idsf": round(bruto, 2),
        "pdd_idsf": round(pdd, 2),
        "dc_liquido_idsf": round(liquido, 2),
    }


def ultima_data_conciliada_serie() -> date | None:
    """Último dia da série com ``conciliada`` verdadeiro (imutável)."""
    datas: list[date] = []
    for iso, row in mapa_dc_bdr_diario().items():
        if not bool(row.get("conciliada")):
            continue
        d = _parse_data_campo(iso)
        if d is not None:
            datas.append(d)
    return max(datas) if datas else None


def gravar_estado_conciliado(
    data_ref: date,
    marcado: dict[str, dict[str, Any]],
) -> None:
    """Persiste posição marcada no fim de um dia conciliado (base do incremental)."""
    limpos: dict[str, dict[str, Any]] = {}
    for chave, pos in marcado.items():
        copia = {k: v for k, v in pos.items() if not str(k).startswith("_")}
        limpos[str(chave)] = copia
    payload = {
        "versao": MOTOR_ESTADO_VERSAO,
        "data_iso": data_ref.isoformat(),
        "gravado_em": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "estado": limpos,
    }
    MOTOR_ESTADO_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = MOTOR_ESTADO_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(MOTOR_ESTADO_PATH)


def carregar_estado_conciliado() -> tuple[date, dict[str, dict[str, Any]]] | None:
    if not MOTOR_ESTADO_PATH.exists():
        return None
    try:
        raw = json.loads(MOTOR_ESTADO_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    if str(raw.get("versao") or "") != MOTOR_ESTADO_VERSAO:
        return None
    data = _parse_data_campo(raw.get("data_iso"))
    estado = raw.get("estado")
    if data is None or not isinstance(estado, dict):
        return None
    abertos = {str(k): dict(v) for k, v in estado.items() if isinstance(v, dict)}
    return data, abertos


def reconstruir_estado_ate(data_limite: date) -> dict[str, dict[str, Any]]:
    """Bootstrap pontual da posição marcada (só quando snapshot ainda não existe)."""
    from marcacao_carteira import atualizar_marcacao

    eventos = _carregar_eventos(desde=DATA_MINIMA, ate=data_limite)
    estado = carregar_estoque_base()
    if eventos:
        estado = _aplicar_eventos_ate(eventos, data_limite, base=estado)
    _aplicar_repactuacoes(estado, data_limite)
    if data_limite == DATA_MINIMA:
        return {k: dict(v) for k, v in estado.items()}
    snapshot = {k: dict(v) for k, v in estado.items()}
    anexar_prazo_atual_do_dia(snapshot, data_limite)
    marcado = atualizar_marcacao(
        snapshot,
        data_ref=DATA_MINIMA,
        data_alvo=data_limite,
    )
    return {k: dict(v) for k, v in marcado.items()}


def datas_util_serie_ate(fim: date | None = None) -> list[str]:
    """Dias úteis da série do motor (DATA_MINIMA .. D-2 por padrão).

    Independente da liquidez IDSF — a conciliação com IDSF é opcional por dia.
    """
    from calendario import e_dia_util
    from conciliacao import data_base_maxima

    limite = fim or data_base_maxima()
    if limite < DATA_MINIMA:
        return []
    out: list[str] = []
    d = DATA_MINIMA
    while d <= limite:
        if e_dia_util(d):
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def reconstruir_serie_diaria(
    eventos: list[dict[str, Any]] | None = None,
    *,
    buscar_idsf: bool = True,
    reaproveitar_idsf: bool = True,
    progresso: Callable[[str, dict[str, float]], None] | None = None,
) -> dict[str, Any]:
    """
    Série do motor (VP/PDD/DC) nas datas com liquidez IDSF, em um passe
    cronológico: o estoque-base recebe os eventos do intervalo e, em cada data
    alvo, a posição é marcada (VP em dias úteis + faixa/PDD) — os mesmos
    números que /fidc/risco calcula para aquele dia. Cada dia guarda também o
    lado IDSF (DC bruto e PDD) e a conciliação, que alimentam o calendário.

    Datas anteriores a DATA_MINIMA não são cobertas pelo motor.
    A série cobre todos os dias úteis até D-2 (não depende da liquidez IDSF).
    """
    from marcacao_carteira import atualizar_marcacao

    if eventos is None:
        eventos = _carregar_eventos(desde=DATA_MINIMA)

    datas_alvo = datas_util_serie_ate()
    anterior = mapa_dc_bdr_diario() if reaproveitar_idsf else {}

    serie: dict[str, dict[str, float]] = {}
    estado = carregar_estoque_base()
    ev_idx = 0

    for d_iso in datas_alvo:
        d = _parse_data_campo(d_iso)
        if d is None:
            continue
        inicio = ev_idx
        while (
            ev_idx < len(eventos)
            and str(eventos[ev_idx].get("data") or "") <= d_iso
        ):
            ev_idx += 1
        if ev_idx > inicio:
            estado = _aplicar_eventos_ate(eventos[inicio:ev_idx], d, base=estado)
        # Repactuações podem cair em dias sem evento novo no intervalo.
        _aplicar_repactuacoes(estado, d)
        if d == DATA_MINIMA:
            marcado = estado
        else:
            snapshot = {k: dict(v) for k, v in estado.items()}
            anexar_prazo_atual_do_dia(snapshot, d)
            marcado = atualizar_marcacao(
                snapshot,
                data_ref=DATA_MINIMA,
                data_alvo=d,
            )
        row = _totais_motor(marcado)

        prev = anterior.get(d_iso) or {}
        idsf: dict[str, float] | None = None
        if float(prev.get("dc_bruto_idsf") or 0):
            idsf = {
                chave: float(prev.get(chave) or 0)
                for chave in ("dc_bruto_idsf", "pdd_idsf", "dc_liquido_idsf")
            }
        elif buscar_idsf:
            try:
                idsf = _idsf_do_dia(d)
            except Exception:  # noqa: BLE001
                idsf = None
            if idsf and not idsf["dc_bruto_idsf"]:
                idsf = None
        if idsf:
            delta_vp = round(row["vp"] - idsf["dc_bruto_idsf"], 2)
            delta_pdd = round(row["pdd"] - idsf["pdd_idsf"], 2)
            row.update(idsf)
            row["delta_vp"] = delta_vp
            row["delta_pdd"] = delta_pdd
            # Tolerância: resíduos BDR + salto anômalo de PRAZO_ATUAL.
            from excecoes_bdr import (
                calcular_efeito_residuos,
                calcular_efeito_salto_prazo,
                caminho_estoque_bdr,
                combinar_efeitos,
                dentro_tolerancia,
                registrar_saltos_prazo_atual,
            )

            salto_meta = saltos_prazo_atual_do_dia(marcado)
            if salto_meta:
                registrar_saltos_prazo_atual(
                    d_iso, list(salto_meta.get("titulos") or [])
                )

            bdr_csv = caminho_estoque_bdr(d)
            efeito_res = (
                calcular_efeito_residuos(bdr_csv, marcado)
                if bdr_csv is not None
                else {"ativo": False}
            )
            efeito_salto = calcular_efeito_salto_prazo(
                marcado,
                data_ref=d,
                delta_vp_bruto=delta_vp,
                tol=TOLERANCIA_DC_ABS,
            )
            efeito = combinar_efeitos(efeito_res, efeito_salto)
            ok, dv_l, dp_l = dentro_tolerancia(
                delta_vp, delta_pdd, tol=TOLERANCIA_DC_ABS, efeito=efeito
            )
            row["delta_vp_limpo"] = dv_l
            row["delta_pdd_limpo"] = dp_l
            row["excecao_residuos"] = float(bool(efeito_res.get("ativo")))
            row["excecao_salto_prazo"] = float(bool(efeito_salto.get("ativo")))
            row["conciliada"] = float(ok)
            if salto_meta:
                row["salto_prazo_n"] = float(salto_meta.get("n") or 0)
        serie[d_iso] = row
        if progresso is not None:
            progresso(d_iso, row)

    payload = {
        "atualizado_em": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "dias": len(serie),
        "por_dia": serie,
    }
    DIARIO_PATH.parent.mkdir(parents=True, exist_ok=True)
    DIARIO_PATH.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload


_DIARIO_CACHE: tuple[tuple[float, int], dict[str, dict[str, float]]] | None = None


def mapa_dc_bdr_diario() -> dict[str, dict[str, float]]:
    """Série diária do motor, com cache invalidado por mtime/tamanho do arquivo."""
    global _DIARIO_CACHE

    try:
        stat = DIARIO_PATH.stat()
    except OSError:
        return {}
    assinatura = (stat.st_mtime, stat.st_size)
    if _DIARIO_CACHE is not None and _DIARIO_CACHE[0] == assinatura:
        return _DIARIO_CACHE[1]
    try:
        raw = json.loads(DIARIO_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    serie = dict(raw.get("por_dia") or {})
    _DIARIO_CACHE = (assinatura, serie)
    return serie


def dc_bdr_conciliado(
    data_ref: date,
    dc_idsf: float,
) -> dict[str, Any]:
    mapa = mapa_dc_bdr_diario()
    iso = data_ref.isoformat()
    row = mapa.get(iso)
    if not row:
        return {
            "dc_bdr": 0.0,
            "dc_idsf": round(float(dc_idsf), 2),
            "delta_dc": 0.0,
            "tolerancia": TOLERANCIA_DC_ABS,
            "conciliada_idsf": False,
            "n_titulos": 0,
            "face": 0.0,
            "sem_snapshot": True,
        }
    # Mesma régua de risco.py: resíduo absoluto, sem folga proporcional.
    # Preferir flag/deltas já limpos na série (exceção dos 3 resíduos BDR).
    tol = float(TOLERANCIA_DC_ABS)
    bruto_idsf = float(row.get("dc_bruto_idsf") or 0)
    if bruto_idsf:
        vp = float(row.get("vp") or 0)
        delta_vp = round(vp - bruto_idsf, 2)
        delta_pdd = round(float(row.get("pdd") or 0) - float(row.get("pdd_idsf") or 0), 2)
        if "delta_vp_limpo" in row and "delta_pdd_limpo" in row:
            dv = float(row["delta_vp_limpo"])
            dp = float(row["delta_pdd_limpo"])
            ok = abs(dv) <= tol and abs(dp) <= tol
        elif "conciliada" in row:
            ok = bool(row.get("conciliada"))
            dv, dp = delta_vp, delta_pdd
        else:
            ok = abs(delta_vp) <= tol and abs(delta_pdd) <= tol
            dv, dp = delta_vp, delta_pdd
        return {
            "dc_bdr": round(vp, 2),
            "dc_idsf": round(bruto_idsf, 2),
            "delta_dc": delta_vp,
            "delta_pdd": delta_pdd,
            "delta_dc_limpo": round(dv, 2),
            "delta_pdd_limpo": round(dp, 2),
            "excecao_residuos_ativa": bool(row.get("excecao_residuos")),
            "tolerancia": tol,
            "conciliada_idsf": ok,
            "n_titulos": int(row.get("n") or 0),
            "face": float(row.get("face") or 0),
            "sem_snapshot": False,
        }

    dc_bdr = float(row.get("dc_bdr") or 0)
    delta = round(dc_bdr - float(dc_idsf), 2)
    return {
        "dc_bdr": round(dc_bdr, 2),
        "dc_idsf": round(float(dc_idsf), 2),
        "delta_dc": delta,
        "tolerancia": round(tol, 2),
        "conciliada_idsf": abs(delta) <= tol,
        "n_titulos": int(row.get("n") or 0),
        "face": float(row.get("face") or 0),
        "sem_snapshot": False,
    }


def carregar_carteira_movimentacoes(
    data_base: date | str,
    *,
    cnpj: str | None = None,
    forcar_cache: bool = False,
) -> pd.DataFrame:
    """
    Retorna DataFrame canônico (títulos abertos na data base).

    Base = EstoqueBDR em DATA_MINIMA (2024-05-31) + movimentos posteriores.
    Datas anteriores a DATA_MINIMA não são suportadas.
    VP = face/(face/compra)^(DU_atual/PRAZO), com PRAZO do registrador; DU_atual
    vem do PRAZO_ATUAL do EstoqueBDR do dia quando existir, senão do calendário
    do motor com o offset congelado no PRAZO. PDD = VP × fator da faixa.
    """
    if isinstance(data_base, date):
        data_limite = data_base
    else:
        data_limite = None
        texto = str(data_base).strip()
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
            try:
                data_limite = datetime.strptime(texto[:10], fmt).date()
                break
            except ValueError:
                continue
        if data_limite is None:
            return pd.DataFrame()

    if data_limite < DATA_MINIMA:
        return pd.DataFrame(
            columns=[
                "data_base",
                "documento",
                "cedente",
                "sacado",
                "tipo_recebivel",
                "data_emissao",
                "data_aquisicao",
                "data_vencimento",
                "valor_face",
                "taxa_operacao",
                "valor_descontado",
                "fee",
                "status",
                "vl_presente_adm",
                "vl_pdd",
                "fx_pdd",
            ]
        )

    if not CACHE_PATH.exists() and _sem_disco_persistente():
        return pd.DataFrame(
            columns=[
                "data_base",
                "documento",
                "cedente",
                "sacado",
                "tipo_recebivel",
                "data_emissao",
                "data_aquisicao",
                "data_vencimento",
                "valor_face",
                "taxa_operacao",
                "valor_descontado",
                "fee",
                "status",
                "vl_presente_adm",
                "vl_pdd",
                "fx_pdd",
            ]
        )

    reconstruir_eventos(cnpj, forcar=forcar_cache)
    base = carregar_estoque_base()
    if data_limite == DATA_MINIMA:
        abertos = base
    else:
        from marcacao_carteira import atualizar_marcacao

        eventos = _carregar_eventos(desde=DATA_MINIMA, ate=data_limite)
        abertos = _aplicar_eventos_ate(eventos, data_limite, base=base)
        # Rola VP (dias úteis) e atualiza faixa/PDD a partir do estoque-base
        anexar_prazo_atual_do_dia(abertos, data_limite)
        abertos = atualizar_marcacao(
            abertos, data_ref=DATA_MINIMA, data_alvo=data_limite
        )

    if not abertos:
        return pd.DataFrame(
            columns=[
                "data_base",
                "documento",
                "cedente",
                "sacado",
                "tipo_recebivel",
                "data_emissao",
                "data_aquisicao",
                "data_vencimento",
                "valor_face",
                "taxa_operacao",
                "valor_descontado",
                "fee",
                "status",
                "vl_presente_adm",
                "vl_pdd",
                "fx_pdd",
            ]
        )

    rows: list[dict[str, Any]] = []
    for pos in abertos.values():
        venc = _parse_data_campo(pos.get("data_vencimento"))
        emissao = _parse_data_campo(pos.get("data_emissao"))
        aquisicao = _parse_data_campo(pos.get("data_aquisicao"))
        status = "VENCIDO" if (venc and venc < data_limite) else "A VENCER"
        vp_adm = pos.get("vl_presente_adm")
        rows.append(
            {
                "data_base": data_limite.isoformat(),
                "documento": pos.get("documento"),
                "cedente": pos.get("cedente") or "",
                "sacado": pos.get("sacado") or "",
                "tipo_recebivel": pos.get("tipo_recebivel") or "",
                "data_emissao": emissao,
                "data_aquisicao": aquisicao,
                "data_vencimento": venc,
                "valor_face": float(pos.get("valor_face") or 0),
                "taxa_operacao": float(pos.get("taxa_operacao") or 0),
                "valor_descontado": float(pos.get("valor_descontado") or 0),
                "fee": 0.0,
                "status": status,
                "vl_presente_adm": vp_adm if vp_adm not in (None, 0, 0.0) else pd.NA,
                "vl_pdd": pos.get("vl_pdd") if pos.get("vl_pdd") is not None else pd.NA,
                "fx_pdd": pos.get("fx_pdd") or pd.NA,
            }
        )

    df = pd.DataFrame(rows)
    df["data_emissao"] = pd.to_datetime(df["data_emissao"], errors="coerce")
    df["data_aquisicao"] = pd.to_datetime(df["data_aquisicao"], errors="coerce")
    df["data_vencimento"] = pd.to_datetime(df["data_vencimento"], errors="coerce")
    return df

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Cache de eventos BDR → carteira")
    parser.add_argument("--forcar", action="store_true")
    parser.add_argument("--data", default="30/06/2026")
    args = parser.parse_args()
    meta = reconstruir_eventos(forcar=args.forcar or not CACHE_PATH.exists())
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    df = carregar_carteira_movimentacoes(args.data)
    face = float(df["valor_face"].sum()) if not df.empty else 0.0
    print(
        f"data={args.data} titulos={len(df)} face={face:,.2f} "
        f"a_vencer={(df['status']=='A VENCER').sum() if not df.empty else 0} "
        f"vencido={(df['status']=='VENCIDO').sum() if not df.empty else 0}"
    )
    if args.forcar or not DIARIO_PATH.exists():
        print("Gerando série diária (datas com liquidez)...")
        serie = reconstruir_serie_diaria()
        print(f"serie dias={serie.get('dias')}")
