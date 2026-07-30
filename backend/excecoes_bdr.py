"""
Exceções de tolerância: títulos-resíduo da BDR que o motor removeu corretamente
(face zerada na liquidação) e que o registrador mantém com VP≤0.

Enquanto estiverem no EstoqueBDR, o ΔVP/ΔPDD causado por eles (e o contágio de
faixa PDD no mesmo sacado) é desconsiderado na tolerância de R$ 500.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from marcacao_carteira import money_half_up

# Resíduos persistentes identificados na conciliação (out/2024 em diante).
# Remover da lista quando saírem definitivamente do EstoqueBDR.
DOCS_RESIDUO_IGNORAR: frozenset[str] = frozenset(
    {
        "2687012",  # Kanuella Parana — VP≈-84,43
        "3168018",  # Vinicius de Oliveira — VP≈-8,85
        "5015010",  # Patricia Karlla — VP≈-8,47 (contagia 5015011/5015012)
    }
)

REL = Path(__file__).resolve().parent / "data" / "relatorios"
LOG_DIR = REL / "erros_bdr"
LOG_AJUSTES = LOG_DIR / "ajustes_tolerancia.jsonl"


def _parse_valor(x: Any) -> float:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return 0.0
    s = str(x).strip()
    if not s or s.lower() in {"nan", "none"}:
        return 0.0
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _cent(v: float) -> float:
    return money_half_up(v)


def caminho_estoque_bdr(data_ref: date | str) -> Path | None:
    if isinstance(data_ref, str):
        data_ref = date.fromisoformat(data_ref[:10])
    path = REL / f"EstoqueBDR_{data_ref.isoformat()}.csv"
    if path.exists() and path.stat().st_size > 1000:
        return path
    return None


def calcular_efeito_residuos(
    bdr_path: Path,
    abertos_motor: dict[str, dict[str, Any]] | None = None,
    *,
    docs_ignorar: frozenset[str] | set[str] = DOCS_RESIDUO_IGNORAR,
) -> dict[str, Any]:
    """
    Mede o efeito dos títulos-resíduo (e contágio de faixa) no total BDR.

    Retorna quantidades a SOMAR aos deltas (motor − referência) para limpar o
    artefato:
      delta_vp_limpo  = delta_vp  + efeito_vp
      delta_pdd_limpo = delta_pdd + efeito_pdd
    """
    vazio = {
        "efeito_vp": 0.0,
        "efeito_pdd": 0.0,
        "vp_residuos": 0.0,
        "pdd_residuos": 0.0,
        "pdd_contagio": 0.0,
        "docs_residuo": [],
        "titulos_contagio": [],
        "ativo": False,
    }
    if not bdr_path or not Path(bdr_path).exists():
        return vazio

    df = pd.read_csv(bdr_path, sep=";", dtype=str, encoding="utf-8-sig")
    if "SEU_NUMERO" not in df.columns:
        return vazio

    df["doc"] = df["SEU_NUMERO"].astype(str).str.strip()
    df["VP"] = [_cent(_parse_valor(x)) for x in df["VALOR_PRESENTE"]]
    df["PDD"] = [_cent(_parse_valor(x)) for x in df["VALOR_PDD"]]
    df["FAIXA"] = df["FAIXA_PDD"].astype(str).str.strip().str.upper()
    df["DOC_SAC"] = (
        df["DOC_SACADO"].astype(str).str.strip()
        if "DOC_SACADO" in df.columns
        else ""
    )
    df["NOME_SAC"] = (
        df["NOME_SACADO"].astype(str).str.strip()
        if "NOME_SACADO" in df.columns
        else ""
    )

    # Resíduo ativo: doc da lista E (ausente no motor OU VP_BDR ≤ 0).
    # Evita “ajustar” dias em que o título ainda está normal na carteira.
    motor_docs = set()
    if abertos_motor:
        for k, pos in abertos_motor.items():
            motor_docs.add(str(k).strip())
            motor_docs.add(str(pos.get("documento") or "").strip())

    mask_cand = df["doc"].isin(docs_ignorar)
    candidatos = df[mask_cand]
    if candidatos.empty:
        return vazio

    keep_idx = []
    for idx, row in candidatos.iterrows():
        doc = str(row["doc"])
        vp = float(row["VP"])
        no_motor = doc not in motor_docs
        if no_motor or vp <= 0.005:
            keep_idx.append(idx)
    if not keep_idx:
        return vazio

    residuos = df.loc[keep_idx]
    mask_res = df.index.isin(keep_idx)

    vp_res = _cent(float(residuos["VP"].sum()))
    pdd_res = _cent(float(residuos["PDD"].sum()))

    docs_sac = {
        str(x).strip()
        for x in residuos["DOC_SAC"].tolist()
        if str(x).strip() and str(x).strip().lower() not in {"nan", "none"}
    }
    nomes_sac = {
        str(x).strip().upper()
        for x in residuos["NOME_SAC"].tolist()
        if str(x).strip() and str(x).strip().lower() not in {"nan", "none"}
    }

    contagio_rows: list[dict[str, Any]] = []
    pdd_contagio = 0.0
    motor = abertos_motor or {}

    # Contágio: títulos do mesmo sacado que NÃO são o resíduo e têm faixa≠ motor
    outros = df[~mask_res]
    for _, row in outros.iterrows():
        doc = str(row["doc"])
        doc_sac = str(row["DOC_SAC"] or "").strip()
        nome = str(row["NOME_SAC"] or "").strip().upper()
        mesmo_sacado = (doc_sac and doc_sac in docs_sac) or (
            nome and nome in nomes_sac
        )
        if not mesmo_sacado:
            continue
        pos = motor.get(doc)
        if pos is None:
            # tentar por documento
            for p in motor.values():
                if str(p.get("documento") or "").strip() == doc:
                    pos = p
                    break
        if pos is None:
            continue
        fx_motor = str(pos.get("fx_pdd") or "").strip().upper()
        fx_bdr = str(row["FAIXA"] or "").strip().upper()
        if not fx_motor or fx_motor == fx_bdr:
            continue
        pdd_m = _cent(float(pos.get("vl_pdd") or 0))
        pdd_b = _cent(float(row["PDD"]))
        delta = _cent(pdd_b - pdd_m)
        if abs(delta) < 0.01:
            continue
        pdd_contagio = _cent(pdd_contagio + delta)
        contagio_rows.append(
            {
                "doc": doc,
                "sacado": row["NOME_SAC"],
                "faixa_motor": fx_motor,
                "faixa_bdr": fx_bdr,
                "pdd_motor": pdd_m,
                "pdd_bdr": pdd_b,
                "delta_pdd": delta,
            }
        )

    # delta_limpo = delta_bruto + efeito
    # efeito_vp = vp_res  (porque delta inclui −vp_res ao subtrair o total BDR)
    # efeito_pdd = pdd_res + pdd_contagio
    efeito_vp = vp_res
    efeito_pdd = _cent(pdd_res + pdd_contagio)

    return {
        "efeito_vp": efeito_vp,
        "efeito_pdd": efeito_pdd,
        "vp_residuos": vp_res,
        "pdd_residuos": pdd_res,
        "pdd_contagio": pdd_contagio,
        "docs_residuo": sorted({str(x) for x in residuos["doc"].tolist()}),
        "titulos_contagio": contagio_rows,
        "ativo": True,
    }


def deltas_com_excecao(
    delta_vp: float,
    delta_pdd: float,
    efeito: dict[str, Any],
) -> tuple[float, float]:
    """Aplica o efeito dos resíduos aos deltas brutos (motor − referência)."""
    if not efeito.get("ativo"):
        return _cent(delta_vp), _cent(delta_pdd)
    return (
        _cent(float(delta_vp) + float(efeito.get("efeito_vp") or 0)),
        _cent(float(delta_pdd) + float(efeito.get("efeito_pdd") or 0)),
    )


def dentro_tolerancia(
    delta_vp: float,
    delta_pdd: float,
    *,
    tol: float = 500.0,
    efeito: dict[str, Any] | None = None,
) -> tuple[bool, float, float]:
    """Retorna (ok, delta_vp_limpo, delta_pdd_limpo)."""
    if efeito:
        dv, dp = deltas_com_excecao(delta_vp, delta_pdd, efeito)
    else:
        dv, dp = _cent(delta_vp), _cent(delta_pdd)
    return abs(dv) <= tol and abs(dp) <= tol, dv, dp


def registrar_ajuste_tolerancia(
    data_iso: str,
    efeito: dict[str, Any],
    *,
    delta_vp_bruto: float,
    delta_pdd_bruto: float,
    delta_vp_limpo: float,
    delta_pdd_limpo: float,
    ok_bruto: bool,
    ok_limpo: bool,
    fonte: str = "conciliacao",
) -> None:
    """Loga quando a exceção altera o resultado da tolerância."""
    if not efeito.get("ativo"):
        return
    if ok_bruto == ok_limpo and abs(delta_vp_bruto - delta_vp_limpo) < 0.01:
        return
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    tipo = str(efeito.get("tipo") or "residuos")
    reg = {
        "registrado_em": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data": data_iso,
        "fonte": fonte,
        "tipo": tipo,
        "docs_residuo": efeito.get("docs_residuo"),
        "docs_salto": efeito.get("docs_salto"),
        "efeito_vp": efeito.get("efeito_vp"),
        "efeito_pdd": efeito.get("efeito_pdd"),
        "pdd_contagio": efeito.get("pdd_contagio"),
        "titulos_contagio": efeito.get("titulos_contagio"),
        "delta_vp_bruto": _cent(delta_vp_bruto),
        "delta_pdd_bruto": _cent(delta_pdd_bruto),
        "delta_vp_limpo": _cent(delta_vp_limpo),
        "delta_pdd_limpo": _cent(delta_pdd_limpo),
        "ok_bruto": ok_bruto,
        "ok_limpo": ok_limpo,
        "decisao": (
            "desconsiderar_salto_prazo_na_tolerancia"
            if tipo == "salto_prazo_atual"
            else "desconsiderar_residuos_na_tolerancia"
        ),
    }
    with LOG_AJUSTES.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(reg, ensure_ascii=False, default=str) + "\n")


# Persistência dos títulos com salto anômalo de PRAZO_ATUAL (BDR).
# extra_du = DUs que o BDR andou a mais no dia do salto; enquanto a IDSF
# permanecer atrasada, o ΔVP ≈ Σ(VP(pa) − VP(pa+extra)).
SALTOS_PATH = LOG_DIR / "saltos_prazo_atual.json"


def _carregar_saltos_persistidos() -> dict[str, dict[str, Any]]:
    if not SALTOS_PATH.exists():
        return {}
    try:
        raw = json.loads(SALTOS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    docs = raw.get("docs") if isinstance(raw, dict) else None
    if not isinstance(docs, dict):
        return {}
    return {str(k): dict(v) for k, v in docs.items() if isinstance(v, dict)}


def _salvar_saltos_persistidos(docs: dict[str, dict[str, Any]]) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "atualizado_em": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "docs": docs,
    }
    SALTOS_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def registrar_saltos_prazo_atual(
    data_iso: str,
    saltos: list[dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    """Acumula títulos com salto anômalo e devolve o mapa persistido atualizado."""
    if not saltos:
        return _carregar_saltos_persistidos()
    docs = _carregar_saltos_persistidos()
    for item in saltos:
        doc = str(item.get("doc") or "").strip()
        if not doc:
            continue
        delta = int(item.get("delta") or 0)
        esperado = int(item.get("esperado") or -1)
        # delta=-2, esperado=-1 → extra=1
        extra = max(0, (-delta) - (-esperado))
        if extra <= 0:
            continue
        prev = docs.get(doc) or {}
        docs[doc] = {
            "extra_du": max(int(prev.get("extra_du") or 0), extra),
            "primeira_data": prev.get("primeira_data") or data_iso,
            "ultima_data": data_iso,
            "sacado": item.get("sacado") or prev.get("sacado") or "",
            "delta": delta,
            "esperado": esperado,
        }
    _salvar_saltos_persistidos(docs)
    return docs


def calcular_efeito_salto_prazo(
    abertos_motor: dict[str, dict[str, Any]],
    *,
    data_ref: date | str | None = None,
    delta_vp_bruto: float | None = None,
    tol: float = 500.0,
) -> dict[str, Any]:
    """
    Estima o ΔVP causado pelo atraso da IDSF após salto de PRAZO_ATUAL no BDR.

    Para cada título persistido ainda aberto: VP(pa) − VP(pa+extra_du).
    Se o delta motor−IDSF for explicado por essa soma, a exceção fica ativa
    (delta_limpo = delta + efeito ≈ 0). Quando a IDSF alcança o motor, a
    exceção se desliga sozinha.
    """
    from marcacao_carteira import vp_por_prazo

    vazio = {
        "tipo": "salto_prazo_atual",
        "efeito_vp": 0.0,
        "efeito_pdd": 0.0,
        "docs_salto": [],
        "n": 0,
        "ativo": False,
    }
    persistidos = _carregar_saltos_persistidos()
    if not persistidos or not abertos_motor:
        return vazio

    data_alvo: date | None = None
    if isinstance(data_ref, date):
        data_alvo = data_ref
    elif isinstance(data_ref, str) and data_ref.strip():
        try:
            data_alvo = date.fromisoformat(data_ref.strip()[:10])
        except ValueError:
            data_alvo = None

    efeito_vp = 0.0
    docs_ok: list[str] = []
    for chave, pos in abertos_motor.items():
        doc = str(pos.get("documento") or chave).strip()
        meta = persistidos.get(doc) or persistidos.get(chave)
        if not meta:
            continue
        extra = int(meta.get("extra_du") or 0)
        if extra <= 0:
            continue
        face = float(pos.get("valor_face") or 0)
        compra = float(pos.get("valor_descontado") or 0)
        prazo_raw = pos.get("prazo")
        try:
            prazo = float(prazo_raw) if prazo_raw not in (None, "", 0, 0.0) else None
        except (TypeError, ValueError):
            prazo = None
        if face <= 0 or compra <= 0 or prazo is None or prazo <= 0:
            continue
        venc = pos.get("data_vencimento")
        from marcacao_carteira import _parse_data_simples

        venc_d = _parse_data_simples(venc)
        if venc_d is None or data_alvo is None:
            continue
        # pa efetivo do motor (calendário ou BDR sem salto)
        pa_motor = pos.get("prazo_atual")
        vp_motor = float(pos.get("vl_presente_adm") or 0)
        if vp_motor <= 0:
            vp_motor = vp_por_prazo(
                face, compra, venc_d, data_alvo, prazo, prazo_atual=pa_motor
            )
        # Simula IDSF ainda com extra_du a mais de prazo remanescente
        pa_base = pa_motor
        if pa_base is None:
            from calendario import dias_uteis_prazo

            pa_base = dias_uteis_prazo(data_alvo, venc_d)
        try:
            pa_idsf = int(pa_base) + extra
        except (TypeError, ValueError):
            continue
        if pa_idsf <= 0:
            continue
        vp_idsf_like = vp_por_prazo(
            face, compra, venc_d, data_alvo, prazo, prazo_atual=pa_idsf
        )
        # motor − idsf_like > 0; efeito a SOMAR ao delta (motor−idsf) é o negativo
        efeito_vp += float(vp_idsf_like) - float(vp_motor)
        docs_ok.append(doc)

    efeito_vp = _cent(efeito_vp)
    if not docs_ok or abs(efeito_vp) < 0.01:
        return vazio

    ativo = True
    if delta_vp_bruto is not None:
        limpo = _cent(float(delta_vp_bruto) + efeito_vp)
        # Só ativa se realmente explicar o furo; se IDSF já alcançou, desliga.
        if abs(limpo) > tol and abs(limpo) >= abs(float(delta_vp_bruto)) - 1.0:
            ativo = False

    return {
        "tipo": "salto_prazo_atual",
        "efeito_vp": efeito_vp,
        "efeito_pdd": 0.0,
        "docs_salto": sorted(set(docs_ok)),
        "n": len(set(docs_ok)),
        "ativo": ativo,
    }


def combinar_efeitos(
    *efeitos: dict[str, Any] | None,
) -> dict[str, Any]:
    """Soma efeitos ativos (resíduos + salto de prazo)."""
    ativo_qualquer = False
    efeito_vp = 0.0
    efeito_pdd = 0.0
    docs_residuo: list[str] = []
    docs_salto: list[str] = []
    contagio: list[dict[str, Any]] = []
    tipos: list[str] = []
    for ef in efeitos:
        if not ef or not ef.get("ativo"):
            continue
        ativo_qualquer = True
        efeito_vp += float(ef.get("efeito_vp") or 0)
        efeito_pdd += float(ef.get("efeito_pdd") or 0)
        docs_residuo.extend(str(x) for x in (ef.get("docs_residuo") or []))
        docs_salto.extend(str(x) for x in (ef.get("docs_salto") or []))
        contagio.extend(list(ef.get("titulos_contagio") or []))
        if ef.get("tipo"):
            tipos.append(str(ef["tipo"]))
    if not ativo_qualquer:
        return {"ativo": False, "efeito_vp": 0.0, "efeito_pdd": 0.0}
    tipo = "+".join(tipos) if tipos else "combinado"
    return {
        "tipo": tipo,
        "efeito_vp": _cent(efeito_vp),
        "efeito_pdd": _cent(efeito_pdd),
        "docs_residuo": sorted(set(docs_residuo)),
        "docs_salto": sorted(set(docs_salto)),
        "titulos_contagio": contagio,
        "pdd_contagio": _cent(
            sum(float(c.get("delta_pdd") or 0) for c in contagio)
        ),
        "ativo": True,
    }
