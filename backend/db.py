import json
import os
from datetime import date
from functools import lru_cache
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()

PAGE_SIZE = 1000

# Colunas canônicas usadas pelo motor de risco (risco.py)
COLUNAS_CANONICAS = [
    "data_base",
    "documento",
    "cedente",
    "sacado",
    "tipo_recebivel",
    "data_emissao",
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

# BD_Estoque -> canônico
COLUNAS_ESTOQUE = (
    "dt_ref,n_controle_lastro_origem,nm_cessao,nm_cedente,nm_sacado,tp_recebivel,"
    "dt_emissao,dt_venc_ajustado,dt_venc_origem,vl_face,tx_cessao,vl_aquisicao,"
    "vl_presente_adm,vl_pdd,fx_pdd,sit_recebivel,status"
)


@lru_cache(maxsize=1)
def get_supabase() -> Client:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError(
            "Defina SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY no arquivo .env"
        )
    return create_client(url, key)


def nome_tabela() -> str:
    return os.getenv("SUPABASE_TABLE", "BD_Estoque")


def _data_filtro_para_banco(data_base: str) -> str:
    """Converte dd/mm/yyyy (UI) para yyyy-mm-dd (BD_Estoque.dt_ref)."""
    dt = pd.to_datetime(data_base, dayfirst=True, errors="coerce")
    if pd.isna(dt):
        return data_base
    return pd.Timestamp(dt).strftime("%Y-%m-%d")


def _br_para_float(serie: pd.Series) -> pd.Series:
    """Converte valores monetários/taxas (float ou string BR) para float."""

    def _um(valor: object) -> float | None:
        if valor is None or (isinstance(valor, float) and pd.isna(valor)):
            return None
        if isinstance(valor, (int, float)) and not isinstance(valor, bool):
            return float(valor)
        texto = str(valor).strip()
        if not texto or texto.lower() in {"nan", "none", "null"}:
            return None
        # BR: 1.234.567,89  |  1234,89  |  já decimal com ponto
        if "," in texto:
            texto = texto.replace(".", "").replace(",", ".")
        try:
            return float(texto)
        except ValueError:
            return None

    return serie.map(_um).astype("float64")


def _mapear_status_estoque(sit_recebivel: pd.Series) -> pd.Series:
    """sit_recebivel da BD_Estoque -> status usado no motor de risco."""
    sit = sit_recebivel.astype(str).str.strip().str.lower()
    status = pd.Series("A VENCER", index=sit.index, dtype="object")
    status = status.mask(sit.str.contains("vencid", na=False), "VENCIDO")
    status = status.mask(sit.isin(["", "none", "nan", "null"]), "A VENCER")
    return status


def _normalizar_estoque(df: pd.DataFrame) -> pd.DataFrame:
    """Renomeia/deriva colunas da BD_Estoque para o schema canônico do risco."""
    out = pd.DataFrame()
    out["data_base"] = df.get("dt_ref")
    doc = df.get("n_controle_lastro_origem")
    if doc is None:
        doc = df.get("nm_cessao")
    else:
        doc = doc.fillna(df.get("nm_cessao"))
    out["documento"] = doc
    out["cedente"] = df.get("nm_cedente")
    out["sacado"] = df.get("nm_sacado")
    out["tipo_recebivel"] = df.get("tp_recebivel")
    out["data_emissao"] = df.get("dt_emissao")
    venc = df.get("dt_venc_ajustado")
    if venc is None:
        venc = df.get("dt_venc_origem")
    else:
        venc = venc.fillna(df.get("dt_venc_origem"))
    out["data_vencimento"] = venc
    out["valor_face"] = df.get("vl_face")
    out["taxa_operacao"] = df.get("tx_cessao")
    out["valor_descontado"] = df.get("vl_aquisicao")
    out["fee"] = 0.0
    out["vl_presente_adm"] = df.get("vl_presente_adm")
    out["vl_pdd"] = df.get("vl_pdd")
    out["fx_pdd"] = df.get("fx_pdd")
    if "sit_recebivel" in df.columns:
        out["status"] = _mapear_status_estoque(df["sit_recebivel"])
    else:
        out["status"] = "A VENCER"
    return out


def carregar_recebiveis(data_base: str | None = None) -> pd.DataFrame:
    """Busca estoque no Supabase (BD_Estoque), pagina e normaliza para o risco."""
    sb = get_supabase()
    tabela = nome_tabela()

    rows: list[dict] = []
    offset = 0
    dt_ref = _data_filtro_para_banco(data_base) if data_base else None
    while True:
        query = sb.table(tabela).select(COLUNAS_ESTOQUE)
        if dt_ref:
            query = query.eq("dt_ref", dt_ref)
        response = query.range(offset, offset + PAGE_SIZE - 1).execute()
        batch = response.data or []
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    if not rows:
        return pd.DataFrame(columns=COLUNAS_CANONICAS)

    df = _normalizar_estoque(pd.DataFrame(rows))

    for col in ("data_base", "data_emissao", "data_vencimento"):
        df[col] = pd.to_datetime(df[col], errors="coerce")

    for col in ("valor_face", "valor_descontado", "taxa_operacao", "fee", "vl_presente_adm", "vl_pdd"):
        if col in df.columns:
            df[col] = _br_para_float(df[col])

    if "status" in df.columns:
        df["status"] = df["status"].astype(str).str.strip().str.upper()

    return df


def listar_datas_base() -> list[str]:
    """Datas conciliadas (ok), formato dd/mm/yyyy — usáveis no motor de risco."""
    from conciliacao import listar_datas_conciliadas

    try:
        return listar_datas_conciliadas()
    except Exception:  # noqa: BLE001
        # Fallback legado: datas presentes em BD_Estoque
        pass

    sb = get_supabase()
    tabela = nome_tabela()

    rows: list[dict] = []
    offset = 0
    while True:
        response = (
            sb.table(tabela)
            .select("dt_ref")
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
        )
        batch = response.data or []
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    if not rows:
        return []

    datas = pd.to_datetime(
        pd.Series([r["dt_ref"] for r in rows]),
        errors="coerce",
    ).dropna()
    unicas = sorted(datas.unique())
    return [pd.Timestamp(d).strftime("%d/%m/%Y") for d in unicas]


def carregar_pl_pdd_diario(id_carteira: int = 0) -> pd.DataFrame:
    """Série diária de PL/PDD (id_carteira=0 = consolidado do fundo)."""
    sb = get_supabase()
    tabela = os.getenv("SUPABASE_PL_PDD_TABLE", "fidc_pl_pdd_diario")

    rows: list[dict] = []
    offset = 0
    while True:
        response = (
            sb.table(tabela)
            .select("data_posicao,id_carteira,apelido,pl,pdd")
            .eq("id_carteira", id_carteira)
            .order("data_posicao")
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
        )
        batch = response.data or []
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    if not rows:
        return pd.DataFrame(columns=["data_posicao", "id_carteira", "apelido", "pl", "pdd"])

    df = pd.DataFrame(rows)
    df["data_posicao"] = pd.to_datetime(df["data_posicao"], errors="coerce")
    df["pl"] = pd.to_numeric(df["pl"], errors="coerce").fillna(0.0)
    df["pdd"] = pd.to_numeric(df["pdd"], errors="coerce").fillna(0.0)
    return df.sort_values("data_posicao").reset_index(drop=True)


def carregar_liquidez_dia(data_posicao: date | str, id_carteira: int | None = None) -> dict | None:
    """Lê um dia de fidc_liquidez_diaria (ou cache local)."""
    from idsf_pl_pdd import carteira_composicao_idsf

    if isinstance(data_posicao, str):
        data_iso = data_posicao[:10]
    else:
        data_iso = data_posicao.isoformat()
    carteira = id_carteira if id_carteira is not None else carteira_composicao_idsf()

    sb = get_supabase()
    tabela = os.getenv("SUPABASE_LIQUIDEZ_TABLE", "fidc_liquidez_diaria")
    if carteira is not None:
        try:
            response = (
                sb.table(tabela)
                .select("*")
                .eq("data_posicao", data_iso)
                .eq("id_carteira", carteira)
                .limit(1)
                .execute()
            )
            rows = response.data or []
            if rows:
                return rows[0]
        except Exception:  # noqa: BLE001
            pass

    # Fallback: cache local (carregar_liquidez_idsf.py)
    cache_path = Path(__file__).resolve().parent / "data" / "liquidez_cache.json"
    if cache_path.exists():
        try:
            raw = json.loads(cache_path.read_text(encoding="utf-8"))
            itens = raw if isinstance(raw, list) else list((raw or {}).values())
            for row in itens:
                if str(row.get("data_posicao") or "")[:10] == data_iso:
                    if carteira is None or int(row.get("id_carteira") or 0) == int(carteira):
                        return row
        except Exception:  # noqa: BLE001
            pass
    return None


def mapa_liquidez_diario(id_carteira: int | None = None) -> dict[str, dict]:
    """Mapa data_iso → registro de liquidez (para calendário)."""
    from idsf_pl_pdd import carteira_composicao_idsf

    carteira = id_carteira if id_carteira is not None else carteira_composicao_idsf()
    mapa: dict[str, dict] = {}

    # Cache local primeiro (rápido e disponível sem SQL)
    cache_path = Path(__file__).resolve().parent / "data" / "liquidez_cache.json"
    if cache_path.exists():
        try:
            raw = json.loads(cache_path.read_text(encoding="utf-8"))
            itens = raw if isinstance(raw, list) else list((raw or {}).values())
            for row in itens:
                if carteira is not None and int(row.get("id_carteira") or 0) != int(carteira):
                    continue
                raw_d = str(row.get("data_posicao") or "")[:10]
                if raw_d:
                    mapa[raw_d] = row
        except Exception:  # noqa: BLE001
            pass

    sb = get_supabase()
    tabela = os.getenv("SUPABASE_LIQUIDEZ_TABLE", "fidc_liquidez_diaria")
    if carteira is None:
        return mapa
    offset = 0
    try:
        while True:
            response = (
                sb.table(tabela)
                .select(
                    "data_posicao,caixa,caixa_cpr,aplicacoes,dc_idsf,pl_estimado,pl_carteira"
                )
                .eq("id_carteira", carteira)
                .order("data_posicao")
                .range(offset, offset + PAGE_SIZE - 1)
                .execute()
            )
            batch = response.data or []
            for row in batch:
                raw_d = str(row.get("data_posicao") or "")[:10]
                if raw_d:
                    mapa[raw_d] = row
            if len(batch) < PAGE_SIZE:
                break
            offset += PAGE_SIZE
    except Exception:  # noqa: BLE001
        pass
    return mapa
