"""Taxas de baixa/recompra a partir do histórico BDR (fidc_liquidacoes).

Fórmula (até a data base, inclusive):
  denominador = liquidações + baixas + recompras  (volume = VALOR DE AQUISICAO)
  taxa_baixa     = baixas / denominador
  taxa_recompra  = recompras / denominador
  taxa_combinada = (baixas + recompras) / denominador

Agrega por dia e grava cache em data/liquidacoes_agg_cache.json para o
dashboard não precisar reler ~100k linhas a cada request.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from bdr_arquivos import cnpj_fundo, extrair_data_movimento

CACHE_PATH = Path(__file__).resolve().parent / "data" / "liquidacoes_agg_cache.json"
PAGE_SIZE = 1000

# Categorias de OCORRENCIA (BDR Alpha):
#   LIQUIDAÇÃO NORMAL / LIQUIDAÇÃO PARCIAL -> liquidacao
#   BAIXA POR DEPÓSITO SACADO             -> baixa
#   BAIXA POR RECOMPRA                    -> recompra


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


def _volume_linha(dados: dict[str, Any]) -> float:
    """Volume preferencial: aquisição; fallback pago / vencimento."""
    for chave in ("VALOR DE AQUISICAO", "VALOR DE PAGO", "VALOR DE VENCIMENTO"):
        vol = _parse_valor(dados.get(chave))
        if vol > 0:
            return vol
    return 0.0


def _categoria_ocorrencia(ocorrencia: str) -> str:
    oc = (ocorrencia or "").strip().upper()
    if "RECOMPRA" in oc:
        return "recompra"
    if "BAIXA" in oc:
        return "baixa"
    return "liquidacao"


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


def _vazio_dia() -> dict[str, float]:
    return {"liquidacao": 0.0, "baixa": 0.0, "recompra": 0.0}


def _carregar_cache() -> dict[str, Any] | None:
    if not CACHE_PATH.exists():
        return None
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _salvar_cache(payload: dict[str, Any]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def reconstruir_agregado(
    cnpj: str | None = None,
    *,
    forcar: bool = False,
) -> dict[str, Any]:
    """Lê fidc_liquidacoes e grava agregado diário no cache."""
    cnpj_n = cnpj_fundo(cnpj)
    if not forcar:
        atual = _carregar_cache()
        if (
            atual
            and atual.get("cnpj_fundo") == cnpj_n
            and isinstance(atual.get("por_dia"), dict)
            and atual.get("por_dia")
        ):
            return atual

    from db import get_supabase

    sb = get_supabase()
    por_dia: dict[str, dict[str, float]] = {}
    total_linhas = 0
    sem_data = 0
    offset = 0

    while True:
        resp = (
            sb.table("fidc_liquidacoes")
            .select("dados")
            .eq("cnpj_fundo", cnpj_n)
            .order("id")
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
        )
        batch = resp.data or []
        if not batch:
            break
        for row in batch:
            dados = _dados_dict(row.get("dados"))
            cat = _categoria_ocorrencia(str(dados.get("OCORRENCIA") or ""))
            vol = _volume_linha(dados)
            dm = extrair_data_movimento(dados)
            if dm is None:
                sem_data += 1
                continue
            chave = dm.isoformat()
            bucket = por_dia.setdefault(chave, _vazio_dia())
            bucket[cat] = round(bucket[cat] + vol, 2)
            total_linhas += 1
        if len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    payload = {
        "cnpj_fundo": cnpj_n,
        "atualizado_em": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "linhas_com_data": total_linhas,
        "linhas_sem_data": sem_data,
        "por_dia": por_dia,
    }
    _salvar_cache(payload)
    return payload


def _somas_ate(data_limite: date, cnpj: str | None = None) -> dict[str, float]:
    agg = reconstruir_agregado(cnpj)
    limite = data_limite.isoformat()
    soma = _vazio_dia()
    for dia, vols in (agg.get("por_dia") or {}).items():
        if str(dia) > limite:
            continue
        for cat in soma:
            soma[cat] += float((vols or {}).get(cat) or 0)
    return {k: round(v, 2) for k, v in soma.items()}


def calcular_taxas_baixa_recompra(
    data_base: date | str,
    cnpj: str | None = None,
) -> dict[str, Any]:
    """
    Retorna volumes e taxas (%) até a data base.

    data_base: date ou string dd/mm/yyyy / yyyy-mm-dd.
    """
    if isinstance(data_base, date):
        data_limite = data_base
    else:
        texto = str(data_base).strip()
        data_limite = None
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
            try:
                data_limite = datetime.strptime(texto[:10], fmt).date()
                break
            except ValueError:
                continue
        if data_limite is None:
            return {
                "taxa_baixa": 0.0,
                "taxa_recompra": 0.0,
                "taxa_baixa_recompra": 0.0,
                "tem_recompra": False,
                "volume_liquidacao": 0.0,
                "volume_baixa": 0.0,
                "volume_recompra": 0.0,
                "volume_total": 0.0,
                "erro": f"Data inválida: {data_base}",
            }

    vols = _somas_ate(data_limite, cnpj)
    vol_liq = vols["liquidacao"]
    vol_baixa = vols["baixa"]
    vol_recompra = vols["recompra"]
    denom = vol_liq + vol_baixa + vol_recompra

    def pct(num: float) -> float:
        return round(float(num / denom * 100), 2) if denom > 0 else 0.0

    return {
        "taxa_baixa": pct(vol_baixa),
        "taxa_recompra": pct(vol_recompra),
        "taxa_baixa_recompra": pct(vol_baixa + vol_recompra),
        "tem_recompra": bool(vol_recompra > 0),
        "volume_liquidacao": vol_liq,
        "volume_baixa": vol_baixa,
        "volume_recompra": vol_recompra,
        "volume_total": round(denom, 2),
        "data_limite": data_limite.isoformat(),
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Agrega liquidações BDR (taxas)")
    parser.add_argument("--forcar", action="store_true", help="Reconstrói o cache")
    parser.add_argument("--data", default="30/06/2026", help="Data base dd/mm/yyyy")
    args = parser.parse_args()
    if args.forcar or not CACHE_PATH.exists():
        print("Reconstruindo agregado...")
        info = reconstruir_agregado(forcar=True)
        print(
            f"OK: {info['linhas_com_data']} linhas, "
            f"{info['linhas_sem_data']} sem data, "
            f"{len(info['por_dia'])} dias"
        )
    taxas = calcular_taxas_baixa_recompra(args.data)
    print(json.dumps(taxas, ensure_ascii=False, indent=2))
