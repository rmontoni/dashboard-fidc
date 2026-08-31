"""Cache de extratos sacado — gerado em ``atualizar_bases`` após a série diária."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

from carteira_movimentacoes import CACHE_PATH, META_PATH, _assinatura_estoques_bdr

INDEX_PATH = Path(__file__).resolve().parent / "data" / "extrato_sacado_index.json"
CACHE_DIR = Path(__file__).resolve().parent / "data" / "extrato_sacado"

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


def _carregar_index() -> dict[str, Any] | None:
    if not INDEX_PATH.exists():
        return None
    try:
        raw = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    return raw if isinstance(raw, dict) else None


def cache_atualizado(data_ref: date) -> bool:
    idx = _carregar_index()
    if not idx:
        return False
    if str(idx.get("data_ref_iso") or "") != data_ref.isoformat():
        return False
    return str(idx.get("assinatura") or "") == assinatura_fontes()


def _persistir_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _salvar_sacado(
    sacado: str,
    data_ref: date,
    *,
    motor: dict[str, Any],
    juros_pos_venc: dict[str, Any],
) -> str:
    slug = slug_sacado(sacado)
    path = CACHE_DIR / f"{slug}.json"
    payload = {
        "sacado": sacado.strip(),
        "data_ref_iso": data_ref.isoformat(),
        "inicio_iso": motor.get("inicio_iso") or juros_pos_venc.get("inicio_iso"),
        "motor": {
            "modo": "motor",
            "modo_label": motor.get("modo_label"),
            "serie": motor.get("serie") or [],
        },
        "juros_pos_venc": {
            "modo": "juros_pos_venc",
            "modo_label": juros_pos_venc.get("modo_label"),
            "serie": juros_pos_venc.get("serie") or [],
        },
    }
    _persistir_json(path, payload)
    return slug


def _carregar_sacado_cache(sacado: str) -> dict[str, Any] | None:
    path = CACHE_DIR / f"{slug_sacado(sacado)}.json"
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    return raw if isinstance(raw, dict) else None


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
            "pdd": ultimo.get("pdd", 0.0),
            "aquisicao": ultimo.get("aquisicao", 0.0),
            "juros": ultimo.get("juros", 0.0),
            "liquidacao": ultimo.get("liquidacao", 0.0),
        },
        "cache": True,
    }


def extrato_do_cache(sacado: str, data_base: str, *, modo: str = "motor") -> dict[str, Any] | None:
    idx = _carregar_index()
    if not idx:
        return None
    if str(idx.get("assinatura") or "") != assinatura_fontes():
        return None

    fim = _parse_data_base(data_base)
    cache_ref = str(idx.get("data_ref_iso") or "")
    if cache_ref and fim.isoformat() > cache_ref:
        return None

    bruto = _carregar_sacado_cache(sacado)
    if not bruto:
        return None

    chave = _normalizar_modo(modo)
    bloco = bruto.get(chave)
    if not isinstance(bloco, dict):
        return None
    return _fatia_resposta(bruto, bloco, fim)


def sacados_do_cache(data_base: str) -> dict[str, Any] | None:
    idx = _carregar_index()
    if not idx:
        return None
    if str(idx.get("assinatura") or "") != assinatura_fontes():
        return None

    ref = _parse_data_base(data_base)
    cache_ref = str(idx.get("data_ref_iso") or "")
    if cache_ref and ref.isoformat() > cache_ref:
        return None

    sacados = list(idx.get("sacados") or [])
    if cache_ref and ref.isoformat() < cache_ref:
        # Lista do índice reflete posição na data do cache; datas anteriores recalculam.
        return None

    return {
        "data_ref": _br(ref),
        "data_ref_iso": ref.isoformat(),
        "sacados": sacados,
        "cache": True,
    }


def reconstruir_cache(
    data_ref: date,
    *,
    forcar: bool = False,
    progresso: ProgressoFn | None = None,
) -> dict[str, Any]:
    """Pré-calcula extrato (motor + juros pós-venc) de todos os sacados abertos."""
    from extrato_sacado import _listar_sacados_live, _montar_extrato_sacado_live

    if not forcar and cache_atualizado(data_ref):
        idx = _carregar_index() or {}
        return {
            "ok": True,
            "pulado": True,
            "data_ref": data_ref.isoformat(),
            "sacados": len(idx.get("sacados") or []),
            "mensagem": "cache já atualizado para a série",
        }

    data_br = _br(data_ref) or data_ref.isoformat()
    lista = _listar_sacados_live(data_br)
    sacados = list(lista.get("sacados") or [])
    if not sacados:
        payload_index = {
            "atualizado_em": _agora_iso(),
            "data_ref_iso": data_ref.isoformat(),
            "assinatura": assinatura_fontes(),
            "sacados": [],
        }
        _persistir_json(INDEX_PATH, payload_index)
        return {"ok": True, "data_ref": data_ref.isoformat(), "sacados": 0, "gerados": 0}

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for antigo in CACHE_DIR.glob("*.json"):
        try:
            antigo.unlink()
        except OSError:
            pass

    index_rows: list[dict[str, Any]] = []
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
            arquivo = _salvar_sacado(
                nome,
                data_ref,
                motor=motor,
                juros_pos_venc=juros,
            )
            index_rows.append({**row, "arquivo": arquivo})
        except Exception as exc:  # noqa: BLE001
            erros.append({"sacado": nome, "erro": str(exc)})

    index_rows.sort(key=lambda s: (-float(s.get("vp") or 0), str(s.get("sacado") or "")))
    payload_index = {
        "atualizado_em": _agora_iso(),
        "data_ref_iso": data_ref.isoformat(),
        "assinatura": assinatura_fontes(),
        "sacados": index_rows,
    }
    _persistir_json(INDEX_PATH, payload_index)

    return {
        "ok": len(erros) == 0,
        "data_ref": data_ref.isoformat(),
        "sacados": len(index_rows),
        "gerados": len(index_rows),
        "erros": erros,
        "pulado": False,
    }


def main() -> None:
    import argparse
    import sys

    from atualizacoes import _ultima_data_serie

    parser = argparse.ArgumentParser(
        description="Reconstrói cache de extratos sacado (motor + juros pós-venc).",
    )
    parser.add_argument(
        "--forcar",
        action="store_true",
        help="Reconstrói mesmo se o cache já estiver atualizado.",
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

    print(f"Reconstruindo cache extrato sacado até {data_ref.isoformat()}…", file=sys.stderr)
    resultado = reconstruir_cache(data_ref, forcar=args.forcar, progresso=progresso)
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    raise SystemExit(0 if resultado.get("ok") else 1)


if __name__ == "__main__":
    main()
