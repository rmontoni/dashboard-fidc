import os
from functools import lru_cache

import pandas as pd
from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()

PAGE_SIZE = 1000


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
    return os.getenv("SUPABASE_TABLE", "BD_FIDC_Recebiveis")


def _br_para_float(serie: pd.Series) -> pd.Series:
    """Converte strings no formato brasileiro (1.234,56 ou 1234,56) para float."""
    texto = (
        serie.astype(str)
        .str.strip()
        .str.replace(".", "", regex=False)
        .str.replace(",", ".", regex=False)
        .replace({"": None, "nan": None, "None": None})
    )
    return pd.to_numeric(texto, errors="coerce")


def carregar_recebiveis(data_base: str | None = None) -> pd.DataFrame:
    """Busca recebíveis no Supabase (com paginação) e normaliza tipos."""
    sb = get_supabase()
    tabela = nome_tabela()
    colunas = (
        "data_base,documento,cedente,sacado,tipo_recebivel,"
        "data_emissao,data_vencimento,valor_face,taxa_operacao,"
        "valor_descontado,fee,status"
    )

    rows: list[dict] = []
    offset = 0
    while True:
        query = sb.table(tabela).select(colunas)
        if data_base:
            query = query.eq("data_base", data_base)
        response = query.range(offset, offset + PAGE_SIZE - 1).execute()
        batch = response.data or []
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    if not rows:
        return pd.DataFrame(
            columns=[
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
            ]
        )

    df = pd.DataFrame(rows)

    for col in ("data_base", "data_emissao", "data_vencimento"):
        df[col] = pd.to_datetime(df[col], dayfirst=True, errors="coerce")

    for col in ("valor_face", "valor_descontado", "taxa_operacao", "fee"):
        if col in df.columns:
            df[col] = _br_para_float(df[col])

    if "status" in df.columns:
        df["status"] = df["status"].astype(str).str.strip().str.upper()

    return df


def listar_datas_base() -> list[str]:
    """Retorna datas base distintas no formato dd/mm/yyyy."""
    sb = get_supabase()
    tabela = nome_tabela()

    rows: list[dict] = []
    offset = 0
    while True:
        response = (
            sb.table(tabela)
            .select("data_base")
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
        pd.Series([r["data_base"] for r in rows]),
        dayfirst=True,
        errors="coerce",
    ).dropna()
    unicas = sorted(datas.unique())
    return [pd.Timestamp(d).strftime("%d/%m/%Y") for d in unicas]
