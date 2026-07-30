"""
Log de erros identificados na BDR (e reflexos no IDSF) durante a conciliação.

O motor NÃO é ajustado para acompanhar esses artefatos. Cada ocorrência fica
registrada em arquivo mensal; ao fim da conciliação de todos os meses, os
arquivos são unidos em um consolidado.

Uso:
  from log_erros_bdr import registrar_erros_do_dia, consolidar_logs
  python log_erros_bdr.py --consolidar
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOG_DIR = Path(__file__).resolve().parent / "data" / "relatorios" / "erros_bdr"
CONSOLIDADO_PATH = LOG_DIR / "erros_bdr_consolidado.json"
CONSOLIDADO_MD_PATH = LOG_DIR / "erros_bdr_consolidado.md"

# Tipos conhecidos — o principal padrão observado: resíduo VP≤0 no estoque BDR
# após liquidação parcial que zera a face, contagiar faixa de PDD do sacado.
TIPO_RESIDUO_VP_NEGATIVO = "residuo_vp_negativo"
TIPO_CONTAGIO_FAIXA = "contagio_faixa_por_residuo"
TIPO_IDSF_FURO = "idsf_diverge_motor_bate_bdr"
TIPO_SALTO_PRAZO = "salto_prazo_atual"
TIPO_NAO_CLASSIFICADO = "divergencia_nao_classificada"


def _path_mensal(ano: int, mes: int) -> Path:
    return LOG_DIR / f"erros_bdr_{ano:04d}_{mes:02d}.jsonl"


def _agora_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _cent(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def _carregar_so_bdr_completo(res: dict[str, Any]) -> list[dict[str, Any]]:
    """Lê so_bdr.csv do dia (completo) quando existir; senão usa a amostra do JSON."""
    data = str(res.get("data") or "")
    if len(data) >= 7:
        ano, mes = data.split("-")[:2]
        csv_path = (
            Path(__file__).resolve().parent
            / "data"
            / "relatorios"
            / f"conciliacao_{ano}_{mes}"
            / data
            / "so_bdr.csv"
        )
        if csv_path.exists():
            try:
                import pandas as pd

                df = pd.read_csv(csv_path, sep=";", dtype=str, encoding="utf-8-sig")
                rows = []
                for _, row in df.iterrows():
                    rows.append(
                        {
                            "doc": row.get("doc"),
                            "NOME_SACADO": row.get("NOME_SACADO"),
                            "FAIXA_BDR": row.get("FAIXA_BDR"),
                            "VP_BDR": row.get("VP_BDR"),
                            "PDD_BDR": row.get("PDD_BDR"),
                        }
                    )
                return rows
            except (OSError, ValueError):
                pass
    detalhe = res.get("detalhe_bdr") or {}
    return list(detalhe.get("amostra_so_bdr") or [])


def _carregar_faixa_divergente(res: dict[str, Any]) -> list[dict[str, Any]]:
    data = str(res.get("data") or "")
    if len(data) >= 7:
        ano, mes = data.split("-")[:2]
        csv_path = (
            Path(__file__).resolve().parent
            / "data"
            / "relatorios"
            / f"conciliacao_{ano}_{mes}"
            / data
            / "faixa_divergente.csv"
        )
        if csv_path.exists():
            try:
                import pandas as pd

                df = pd.read_csv(csv_path, sep=";", dtype=str, encoding="utf-8-sig")
                rows = []
                for _, row in df.iterrows():
                    rows.append(
                        {
                            "doc": row.get("doc"),
                            "sacado": row.get("sacado"),
                            "fx_pdd": row.get("fx_pdd"),
                            "FAIXA_BDR": row.get("FAIXA_BDR"),
                            "vl_presente_adm": row.get("vl_presente_adm"),
                            "vl_pdd": row.get("vl_pdd"),
                            "PDD_BDR": row.get("PDD_BDR"),
                            "DELTA_PDD": row.get("DELTA_PDD"),
                        }
                    )
                return rows
            except (OSError, ValueError):
                pass
    detalhe = res.get("detalhe_bdr") or {}
    return [
        t
        for t in (detalhe.get("top_pdd") or [])
        if str(t.get("fx_pdd") or "").upper() != str(t.get("FAIXA_BDR") or "").upper()
    ]


def classificar_erros_do_dia(res: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Classifica divergências do dia sem alterar o motor.

    Só gera registros quando o dia está fora da tolerância vs IDSF e/ou BDR.
    """
    if res.get("erro") or res.get("ok"):
        return []

    data = str(res.get("data") or "")
    tol = float(res.get("tol") or 500.0)
    ok_idsf = bool(res.get("ok_idsf"))
    ok_bdr = res.get("ok_bdr")
    detalhe = res.get("detalhe_bdr") or {}
    erros: list[dict[str, Any]] = []

    so_bdr_rows = _carregar_so_bdr_completo(res)
    residuos = []
    for t in so_bdr_rows:
        try:
            vp = float(t.get("VP_BDR") or 0)
        except (TypeError, ValueError):
            vp = 0.0
        if vp <= 0:
            residuos.append(t)

    faixa_rows = _carregar_faixa_divergente(res)
    faixa_n = int(detalhe.get("faixa_divergente") or len(faixa_rows) or 0)
    so_bdr_n = int(detalhe.get("so_bdr") or len(so_bdr_rows) or 0)

    # Docs de sacado com resíduo — para ligar contágio
    docs_residuo = {
        str(t.get("doc") or "").strip()
        for t in residuos
    }
    sacados_residuo = {
        str(t.get("NOME_SACADO") or "").strip().upper()
        for t in residuos
        if str(t.get("NOME_SACADO") or "").strip()
    }

    # 1) Resíduos VP≤0 só no BDR
    if residuos:
        erros.append(
            {
                "data": data,
                "tipo": TIPO_RESIDUO_VP_NEGATIVO,
                "resumo": (
                    f"{len(residuos)} título(s) só no BDR com VP≤0 "
                    f"(resíduo pós-liquidação; motor removeu face zerada)"
                ),
                "impacto_vp": _cent(sum(float(t.get("VP_BDR") or 0) for t in residuos)),
                "impacto_pdd": _cent(sum(float(t.get("PDD_BDR") or 0) for t in residuos)),
                "titulos": [
                    {
                        "doc": t.get("doc"),
                        "sacado": t.get("NOME_SACADO"),
                        "faixa_bdr": t.get("FAIXA_BDR"),
                        "vp_bdr": _cent(t.get("VP_BDR")),
                        "pdd_bdr": _cent(t.get("PDD_BDR")),
                    }
                    for t in residuos
                ],
                "delta_vp_idsf": _cent(res.get("delta_vp_idsf")),
                "delta_pdd_idsf": _cent(res.get("delta_pdd_idsf")),
                "delta_vp_bdr": _cent(res.get("delta_vp_bdr")),
                "delta_pdd_bdr": _cent(res.get("delta_pdd_bdr")),
                "decisao": "manter_motor",
            }
        )

    # 2) Contágio de faixa (padrão principal)
    contagio = []
    for t in faixa_rows:
        try:
            delta = abs(float(t.get("DELTA_PDD") or 0))
        except (TypeError, ValueError):
            delta = 0.0
        if delta < 0.01:
            continue
        contagio.append(t)

    if faixa_n > 0 and contagio:
        impacto = 0.0
        for t in contagio:
            try:
                impacto += float(t.get("DELTA_PDD") or 0)
            except (TypeError, ValueError):
                pass
        erros.append(
            {
                "data": data,
                "tipo": TIPO_CONTAGIO_FAIXA,
                "resumo": (
                    f"{len(contagio)} título(s) com faixa≠ BDR"
                    + (
                        f"; sacado(s) com resíduo VP≤0: {', '.join(sorted(sacados_residuo)[:3])}"
                        if sacados_residuo
                        else "; provável contágio por resíduo VP≤0"
                    )
                ),
                "impacto_pdd": _cent(impacto),
                "titulos": [
                    {
                        "doc": t.get("doc"),
                        "sacado": t.get("sacado"),
                        "faixa_motor": t.get("fx_pdd"),
                        "faixa_bdr": t.get("FAIXA_BDR"),
                        "vp": _cent(t.get("vl_presente_adm")),
                        "pdd_motor": _cent(t.get("vl_pdd")),
                        "pdd_bdr": _cent(t.get("PDD_BDR")),
                        "delta_pdd": _cent(t.get("DELTA_PDD")),
                    }
                    for t in contagio[:30]
                ],
                "docs_residuo": sorted(docs_residuo),
                "delta_vp_idsf": _cent(res.get("delta_vp_idsf")),
                "delta_pdd_idsf": _cent(res.get("delta_pdd_idsf")),
                "delta_vp_bdr": _cent(res.get("delta_vp_bdr")),
                "delta_pdd_bdr": _cent(res.get("delta_pdd_bdr")),
                "decisao": "manter_motor",
            }
        )

    # 3) Salto anômalo de PRAZO_ATUAL no BDR (motor ignora e usa calendário)
    salto = res.get("salto_prazo_atual") or {}
    if int(salto.get("n") or 0) > 0:
        erros.append(
            {
                "data": data,
                "tipo": TIPO_SALTO_PRAZO,
                "resumo": (
                    f"PRAZO_ATUAL do BDR caiu além do esperado em "
                    f"{int(salto.get('n') or 0)} título(s); motor recalcula "
                    f"pelo calendário próprio"
                ),
                "impacto_vp": _cent(res.get("delta_vp_idsf")),
                "impacto_pdd": _cent(res.get("delta_pdd_idsf")),
                "n_titulos": int(salto.get("n") or 0),
                "esperado": salto.get("esperado"),
                "data_anterior": salto.get("data_anterior"),
                "amostra": list(salto.get("titulos") or [])[:30],
                "delta_vp_idsf": _cent(res.get("delta_vp_idsf")),
                "delta_pdd_idsf": _cent(res.get("delta_pdd_idsf")),
                "delta_vp_bdr": _cent(res.get("delta_vp_bdr")),
                "delta_pdd_bdr": _cent(res.get("delta_pdd_bdr")),
                "decisao": "ignorar_prazo_atual_bdr_usar_calendario",
            }
        )

    # 4) Motor bate BDR, IDSF fura
    if ok_bdr is True and not ok_idsf:
        erros.append(
            {
                "data": data,
                "tipo": TIPO_IDSF_FURO,
                "resumo": (
                    "Motor conciliado com EstoqueBDR dentro da tolerância; "
                    "IDSF diverge (furo/atraso da carteira IDSF)"
                ),
                "impacto_vp": _cent(res.get("delta_vp_idsf")),
                "impacto_pdd": _cent(res.get("delta_pdd_idsf")),
                "delta_vp_idsf": _cent(res.get("delta_vp_idsf")),
                "delta_pdd_idsf": _cent(res.get("delta_pdd_idsf")),
                "delta_vp_bdr": _cent(res.get("delta_vp_bdr")),
                "delta_pdd_bdr": _cent(res.get("delta_pdd_bdr")),
                "sistema_vp": _cent((res.get("sistema") or {}).get("vp")),
                "idsf_vp": _cent((res.get("idsf") or {}).get("dc_bruto")),
                "bdr_vp": _cent((res.get("bdr") or {}).get("vp")),
                "decisao": "manter_motor",
            }
        )

    # 5) Sem classificação específica
    if not erros and (not ok_idsf or ok_bdr is False):
        erros.append(
            {
                "data": data,
                "tipo": TIPO_NAO_CLASSIFICADO,
                "resumo": (
                    f"Divergência fora da tolerância (tol=R$ {tol:.2f}); "
                    f"so_bdr={so_bdr_n} faixa≠={faixa_n}"
                ),
                "impacto_vp": _cent(res.get("delta_vp_idsf")),
                "impacto_pdd": _cent(res.get("delta_pdd_idsf")),
                "delta_vp_idsf": _cent(res.get("delta_vp_idsf")),
                "delta_pdd_idsf": _cent(res.get("delta_pdd_idsf")),
                "delta_vp_bdr": _cent(res.get("delta_vp_bdr")),
                "delta_pdd_bdr": _cent(res.get("delta_pdd_bdr")),
                "detalhe": {
                    "n_ambos": detalhe.get("n_ambos"),
                    "so_sistema": detalhe.get("so_sistema"),
                    "so_bdr": detalhe.get("so_bdr"),
                    "faixa_divergente": detalhe.get("faixa_divergente"),
                },
                "decisao": "manter_motor",
            }
        )

    for e in erros:
        e["registrado_em"] = _agora_iso()
        e["fonte"] = "conciliacao_mensal"
    return erros


def registrar_erros_do_dia(res: dict[str, Any]) -> list[dict[str, Any]]:
    """Classifica e acrescenta ao jsonl do mês. Retorna os registros gravados."""
    erros = classificar_erros_do_dia(res)
    if not erros:
        return []
    data = str(res.get("data") or "")
    ano, mes = (int(x) for x in data.split("-")[:2])
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = _path_mensal(ano, mes)
    with path.open("a", encoding="utf-8") as fh:
        for e in erros:
            fh.write(json.dumps(e, ensure_ascii=False, default=str) + "\n")
    return erros


def reescrever_log_mensal(ano: int, mes: int, resultados: list[dict[str, Any]]) -> Path:
    """Reconstrói o jsonl do mês a partir dos resultados da conciliação."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = _path_mensal(ano, mes)
    linhas: list[str] = []
    for res in resultados:
        for e in classificar_erros_do_dia(res):
            linhas.append(json.dumps(e, ensure_ascii=False, default=str))
    path.write_text("\n".join(linhas) + ("\n" if linhas else ""), encoding="utf-8")
    return path


def _ler_todos_mensais() -> list[dict[str, Any]]:
    if not LOG_DIR.exists():
        return []
    itens: list[dict[str, Any]] = []
    for path in sorted(LOG_DIR.glob("erros_bdr_????_??.jsonl")):
        for linha in path.read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if not linha:
                continue
            try:
                itens.append(json.loads(linha))
            except json.JSONDecodeError:
                continue
    itens.sort(key=lambda e: (str(e.get("data") or ""), str(e.get("tipo") or "")))
    return itens


def consolidar_logs() -> dict[str, Any]:
    """Une todos os jsonl mensais em um único JSON + resumo Markdown."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    itens = _ler_todos_mensais()
    por_tipo: dict[str, int] = {}
    por_mes: dict[str, int] = {}
    for e in itens:
        t = str(e.get("tipo") or "desconhecido")
        por_tipo[t] = por_tipo.get(t, 0) + 1
        data = str(e.get("data") or "")
        mes = data[:7] if len(data) >= 7 else "?"
        por_mes[mes] = por_mes.get(mes, 0) + 1

    payload = {
        "atualizado_em": _agora_iso(),
        "total": len(itens),
        "por_tipo": por_tipo,
        "por_mes": por_mes,
        "erros": itens,
    }
    CONSOLIDADO_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    linhas_md = [
        "# Erros BDR / IDSF identificados na conciliação",
        "",
        f"Atualizado em: `{payload['atualizado_em']}`",
        f"Total de registros: **{payload['total']}**",
        "",
        "## Por tipo",
        "",
    ]
    for t, n in sorted(por_tipo.items(), key=lambda kv: (-kv[1], kv[0])):
        linhas_md.append(f"- `{t}`: {n}")
    linhas_md.extend(["", "## Por mês", ""])
    for m, n in sorted(por_mes.items()):
        linhas_md.append(f"- `{m}`: {n}")
    linhas_md.extend(["", "## Detalhe", ""])
    for e in itens:
        linhas_md.append(
            f"- **{e.get('data')}** · `{e.get('tipo')}` — {e.get('resumo')} "
            f"(ΔVP IDSF={e.get('delta_vp_idsf')} ΔPDD IDSF={e.get('delta_pdd_idsf')}; "
            f"decisão: {e.get('decisao')})"
        )
    CONSOLIDADO_MD_PATH.write_text("\n".join(linhas_md) + "\n", encoding="utf-8")
    return payload


def main() -> None:
    ap = argparse.ArgumentParser(description="Log de erros BDR da conciliação")
    ap.add_argument(
        "--consolidar",
        action="store_true",
        help="Une todos os logs mensais em erros_bdr_consolidado.json/.md",
    )
    ap.add_argument(
        "--from-resumo",
        default=None,
        help="Reconstrói o log mensal a partir de conciliacao_AAAA_MM/resumo.json",
    )
    args = ap.parse_args()

    if args.from_resumo:
        path = Path(args.from_resumo)
        if not path.is_absolute():
            path = Path(__file__).resolve().parent / "data" / "relatorios" / args.from_resumo
        if path.is_dir():
            path = path / "resumo.json"
        resumo = json.loads(path.read_text(encoding="utf-8"))
        mes = str(resumo.get("mes") or "")
        ano_i, mes_i = (int(x) for x in mes.split("-")[:2])
        out = reescrever_log_mensal(ano_i, mes_i, resumo.get("dias") or [])
        print(f"log mensal: {out} ({sum(1 for _ in out.open(encoding='utf-8') if _.strip())} linhas)")

    if args.consolidar or args.from_resumo:
        payload = consolidar_logs()
        print(
            f"consolidado: {CONSOLIDADO_PATH}  total={payload['total']}  "
            f"tipos={payload['por_tipo']}"
        )
        print(f"markdown: {CONSOLIDADO_MD_PATH}")
        return

    ap.print_help()


if __name__ == "__main__":
    main()
