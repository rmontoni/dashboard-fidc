"""Cache sob demanda de extratos sacado (grava ao abrir na API).

Pré-cálculo em massa (``reconstruir_cache``) é opcional e limitado — com milhares
de sacados o replay diário por sacado não escala para rodar no atualizar_bases.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

from carteira_movimentacoes import CACHE_PATH, META_PATH, _assinatura_estoques_bdr

CACHE_DIR = Path(__file__).resolve().parent / "data" / "extrato_sacado"
# Incrementar quando a lógica do extrato mudar (invalida JSONs antigos).
CACHE_ENGINE_VERSAO = "5"

ProgressoFn = Callable[[str, int, int], None]


def _agora_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _parse_data_base(texto: str) -> date:
    from extrato_sacado import _parse_data_base as parse

    return parse(texto)


def _br(d: date | None) -> str | None:
    return d.strftime("%d/%m/%Y") if d else None


def _normalizar_modo(modo: str) -> str:
    if modo in ("juros_pos_venc", "juros-pos-venc", "2"):
        return "juros_pos_venc"
    return "motor"


def slug_sacado(sacado: str) -> str:
    return hashlib.sha256(sacado.strip().upper().encode("utf-8")).hexdigest()[:16]


def assinatura_fontes() -> str:
    """Invalida cache quando eventos BDR ou estoque-base mudam."""
    partes: list[str] = []
    for path in (CACHE_PATH, META_PATH):
        try:
            st = path.stat()
            partes.append(f"{path.name}:{st.st_mtime}:{st.st_size}")
        except OSError:
            partes.append(f"{path.name}:ausente")
    partes.append(f"estoque:{hash(_assinatura_estoques_bdr())}")
    return "|".join(partes)


def _persistir_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _carregar_sacado_cache(sacado: str) -> dict[str, Any] | None:
    path = CACHE_DIR / f"{slug_sacado(sacado)}.json"
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    return raw if isinstance(raw, dict) else None


def _ultima_data_serie(bloco: dict[str, Any] | None) -> date | None:
    if not bloco:
        return None
    datas: list[date] = []
    for ponto in bloco.get("serie") or []:
        raw = str(ponto.get("data") or "")[:10]
        try:
            datas.append(date.fromisoformat(raw))
        except ValueError:
            continue
    return max(datas) if datas else None


def _merge_serie(
    antiga: list[dict[str, Any]],
    nova: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Une séries por data; pontos da série nova prevalecem no mesmo dia."""
    por_data: dict[str, dict[str, Any]] = {}
    for ponto in antiga:
        chave = str(ponto.get("data") or "")
        if chave:
            por_data[chave] = ponto
    for ponto in nova:
        chave = str(ponto.get("data") or "")
        if chave:
            por_data[chave] = ponto
    return [por_data[chave] for chave in sorted(por_data)]


def _cache_sacado_valido(bruto: dict[str, Any], fim: date, *, modo: str) -> bool:
    if str(bruto.get("engine") or "") != CACHE_ENGINE_VERSAO:
        return False
    if str(bruto.get("assinatura") or "") != assinatura_fontes():
        return False
    chave = _normalizar_modo(modo)
    bloco = bruto.get(chave)
    if not isinstance(bloco, dict) or not bloco.get("serie"):
        return False
    ultima = _ultima_data_serie(bloco)
    if ultima is None or ultima < fim:
        return False
    cache_ref = str(bruto.get("data_ref_iso") or "")
    if cache_ref and fim.isoformat() > cache_ref:
        return False
    return True


def _fatia_resposta(
    bruto: dict[str, Any],
    bloco: dict[str, Any],
    fim: date,
) -> dict[str, Any]:
    fim_iso = fim.isoformat()
    serie = [p for p in (bloco.get("serie") or []) if str(p.get("data") or "") <= fim_iso]
    ultimo = (
        serie[-1]
        if serie
        else {
            "face": 0.0,
            "vp": 0.0,
            "vencido": 0.0,
            "pdd": 0.0,
            "aquisicao": 0.0,
            "juros": 0.0,
            "liquidacao": 0.0,
        }
    )
    inicio_iso = serie[0]["data"] if serie else bruto.get("inicio_iso")
    inicio = date.fromisoformat(str(inicio_iso)[:10]) if inicio_iso else None
    modo = str(bloco.get("modo") or "motor")
    return {
        "data_ref": _br(fim),
        "data_ref_iso": fim_iso,
        "sacado": str(bruto.get("sacado") or ""),
        "modo": modo,
        "modo_label": bloco.get("modo_label")
        or (
            "Juros após vencimento"
            if modo == "juros_pos_venc"
            else "Sem juros após vencimento"
        ),
        "inicio": _br(inicio),
        "inicio_iso": inicio_iso,
        "serie": serie,
        "kpis": {
            "face": ultimo.get("face", 0.0),
            "vp": ultimo.get("vp", 0.0),
            "vencido": ultimo.get("vencido", 0.0),
            "pdd": ultimo.get("pdd", 0.0),
            "aquisicao": ultimo.get("aquisicao", 0.0),
            "juros": ultimo.get("juros", 0.0),
            "liquidacao": ultimo.get("liquidacao", 0.0),
        },
        "cache": True,
    }


def extrato_do_cache(sacado: str, data_base: str, *, modo: str = "motor") -> dict[str, Any] | None:
    """Lê cache por sacado (sem índice global)."""
    bruto = _carregar_sacado_cache(sacado)
    if not bruto:
        return None

    fim = _parse_data_base(data_base)
    if not _cache_sacado_valido(bruto, fim, modo=modo):
        return None

    chave = _normalizar_modo(modo)
    bloco = bruto.get(chave)
    if not isinstance(bloco, dict) or not bloco.get("serie"):
        return None
    return _fatia_resposta(bruto, bloco, fim)


def gravar_extrato_modo(
    sacado: str,
    data_base: str,
    modo: str,
    resultado: dict[str, Any],
) -> None:
    """Persiste um modo após cálculo ao vivo (cache incremental)."""
    data_ref = _parse_data_base(data_base)
    chave = _normalizar_modo(modo)
    path = CACHE_DIR / f"{slug_sacado(sacado)}.json"
    bruto = _carregar_sacado_cache(sacado) or {
        "sacado": sacado.strip(),
        "data_ref_iso": data_ref.isoformat(),
        "inicio_iso": resultado.get("inicio_iso"),
        "assinatura": assinatura_fontes(),
        "engine": CACHE_ENGINE_VERSAO,
    }
    bloco_ant = bruto.get(chave) if isinstance(bruto.get(chave), dict) else None
    antiga_serie = (bloco_ant or {}).get("serie") or []
    nova_serie = resultado.get("serie") or []
    serie = _merge_serie(antiga_serie, nova_serie)
    ultima = _ultima_data_serie({"serie": serie})
    bruto["data_ref_iso"] = (ultima or data_ref).isoformat()
    bruto["assinatura"] = assinatura_fontes()
    bruto["engine"] = CACHE_ENGINE_VERSAO
    if resultado.get("inicio_iso"):
        bruto["inicio_iso"] = resultado.get("inicio_iso")
    bruto[chave] = {
        "modo": chave,
        "modo_label": resultado.get("modo_label"),
        "serie": serie,
    }
    _persistir_json(path, bruto)


def reconstruir_cache(
    data_ref: date,
    *,
    forcar: bool = False,
    limite: int | None = None,
    progresso: ProgressoFn | None = None,
) -> dict[str, Any]:
    """
    Pré-calcula extratos para os sacados com maior VP (uso manual).

    ``limite`` é obrigatório — sem limite o job não inicia (evita dias de CPU).
    """
    from extrato_sacado import _listar_sacados_live, _montar_extrato_sacado_live

    if limite is None or limite <= 0:
        return {
            "ok": False,
            "erro": (
                "Informe --limite N (ex.: 50). Pré-cálculo de todos os sacados "
                "não é viável — use cache sob demanda na API."
            ),
        }

    data_br = _br(data_ref) or data_ref.isoformat()
    lista = _listar_sacados_live(data_br)
    sacados = list(lista.get("sacados") or [])[:limite]
    if not sacados:
        return {"ok": True, "data_ref": data_ref.isoformat(), "sacados": 0, "gerados": 0}

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if forcar:
        for slug in {slug_sacado(str(s.get("sacado") or "")) for s in sacados}:
            path = CACHE_DIR / f"{slug}.json"
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

    erros: list[dict[str, str]] = []
    total = len(sacados)

    for i, row in enumerate(sacados, start=1):
        nome = str(row.get("sacado") or "").strip()
        if not nome:
            continue
        if progresso is not None:
            progresso(nome, i, total)
        try:
            motor = _montar_extrato_sacado_live(nome, data_br, modo="motor")
            juros = _montar_extrato_sacado_live(nome, data_br, modo="juros_pos_venc")
            gravar_extrato_modo(nome, data_br, "motor", motor)
            gravar_extrato_modo(nome, data_br, "juros_pos_venc", juros)
        except Exception as exc:  # noqa: BLE001
            erros.append({"sacado": nome, "erro": str(exc)})

    return {
        "ok": len(erros) == 0,
        "data_ref": data_ref.isoformat(),
        "limite": limite,
        "gerados": total - len(erros),
        "erros": erros,
        "pulado": False,
    }


def main() -> None:
    import argparse
    import sys

    from atualizacoes import _ultima_data_serie

    parser = argparse.ArgumentParser(
        description=(
            "Pré-calcula extratos dos sacados com maior VP (manual). "
            "O cache normal é sob demanda ao abrir na API."
        ),
    )
    parser.add_argument(
        "--forcar",
        action="store_true",
        help="Apaga cache dos sacados selecionados antes de recalcular.",
    )
    parser.add_argument(
        "--limite",
        type=int,
        default=50,
        metavar="N",
        help="Quantos sacados (por VP) pré-calcular (padrão: 50).",
    )
    parser.add_argument(
        "--data",
        metavar="YYYY-MM-DD",
        help="Data de referência (padrão: última da série diária).",
    )
    args = parser.parse_args()

    if args.data:
        data_ref = date.fromisoformat(args.data[:10])
    else:
        data_ref = _ultima_data_serie()
    if data_ref is None:
        print("Série diária ausente — rode atualizar_bases antes.", file=sys.stderr)
        raise SystemExit(2)

    def progresso(sacado: str, atual: int, total: int) -> None:
        print(f"[{atual}/{total}] {sacado}", file=sys.stderr)

    print(
        f"Pré-cálculo extrato sacado: top {args.limite} até {data_ref.isoformat()}…",
        file=sys.stderr,
    )
    resultado = reconstruir_cache(
        data_ref,
        forcar=args.forcar,
        limite=args.limite,
        progresso=progresso,
    )
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    raise SystemExit(0 if resultado.get("ok") else 1)


if __name__ == "__main__":
    main()
