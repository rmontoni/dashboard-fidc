"""Conciliação dia a dia: motor × EstoqueBDR × IDSF.

Uso:
  python conciliar_junho_2024.py --mes 2024-07
  python conciliar_junho_2024.py --mes 2024-07 --baixar-bdr
  python conciliar_junho_2024.py --mes 2024-07 --continuar-fora
"""

from __future__ import annotations

import argparse
import calendar
import json
import traceback
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv

from calendario import e_dia_util
from carteira_movimentacoes import (
    DATA_MINIMA,
    _aplicar_eventos_ate,
    _carregar_eventos,
    anexar_prazo_atual_do_dia,
    carregar_estoque_base,
    reconstruir_eventos,
    saltos_prazo_atual_do_dia,
)
from excecoes_bdr import (
    calcular_efeito_residuos,
    calcular_efeito_salto_prazo,
    combinar_efeitos,
    dentro_tolerancia,
    registrar_ajuste_tolerancia,
    registrar_saltos_prazo_atual,
)
from idsf_pl_pdd import buscar_posicoes_caixa_aplicacoes
from log_erros_bdr import (
    classificar_erros_do_dia,
    consolidar_logs,
    reescrever_log_mensal,
)
from marcacao_carteira import atualizar_marcacao
from risco import TOLERANCIA_DC_ABS

load_dotenv()

REL = Path(__file__).resolve().parent / "data" / "relatorios"
OUT_ROOT = Path(__file__).resolve().parent / "data" / "relatorios"


def cent(valor: Any) -> float:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return 0.0
    return float(Decimal(str(float(valor))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def parse_valor(x: Any) -> float:
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


def dias_uteis_mes(inicio: date, fim: date) -> list[date]:
    out: list[date] = []
    d = inicio
    while d <= fim:
        if e_dia_util(d):
            out.append(d)
        d += timedelta(days=1)
    return out


def totais_sistema(abertos: dict[str, dict[str, Any]]) -> dict[str, float | int]:
    vp = 0.0
    pdd = 0.0
    face = 0.0
    for pos in abertos.values():
        vp += float(pos.get("vl_presente_adm") or 0)
        pdd += float(pos.get("vl_pdd") or 0)
        face += float(pos.get("valor_face") or 0)
    return {
        "n": len(abertos),
        "vp": cent(vp),
        "pdd": cent(pdd),
        "face": cent(face),
        "liquido": cent(vp - pdd),
    }


def idsf_do_dia(d: date) -> dict[str, Any]:
    pos = buscar_posicoes_caixa_aplicacoes(d)
    dc_bruto = float(pos.get("total_dc_bruto_idsf") or 0)
    pdd = float(pos.get("total_pdd_idsf") or 0)
    dc_liq = float(pos.get("total_dc_idsf") or 0)
    if dc_bruto == 0.0 and pdd > 0 and dc_liq != 0.0:
        dc_bruto = cent(dc_liq + pdd)
    elif dc_bruto == 0.0 and dc_liq != 0.0:
        dc_bruto = dc_liq
    return {
        "dc_bruto": cent(dc_bruto),
        "pdd": cent(pdd),
        "dc_liquido": cent(dc_liq),
        "aviso": pos.get("aviso"),
        "fonte": pos.get("fonte"),
    }


def totais_bdr(path: Path) -> dict[str, float | int]:
    df = pd.read_csv(path, sep=";", dtype=str, encoding="utf-8-sig")
    cols = {str(c).upper(): c for c in df.columns}

    def _col(*names: str):
        for n in names:
            c = cols.get(n.upper())
            if c is not None:
                return df[c]
        raise KeyError(f"Coluna não encontrada: {names}")

    vp = sum(
        cent(parse_valor(x))
        for x in _col("vl_presente_adm", "vl_presente_bdr", "VALOR_PRESENTE")
    )
    pdd = sum(cent(parse_valor(x)) for x in _col("vl_pdd", "VALOR_PDD"))
    face = sum(cent(parse_valor(x)) for x in _col("vl_face", "VALOR_NOMINAL"))
    return {"n": len(df), "vp": cent(vp), "pdd": cent(pdd), "face": cent(face)}


def _normalizar_colunas_bdr(df: pd.DataFrame) -> pd.DataFrame:
    """Aceita schema legado e /estoqueBDR (colunas novas)."""
    out = df.copy()
    cols = {str(c).upper(): c for c in out.columns}
    aliases = {
        "SEU_NUMERO": (
            "NM_CESSAO",
            "NM_CESSAO_BDR",
            "N_CONTROLE_LASTRO_ORIGEM",
            "N_CONTROLE_LASTRO_BDR",
            "SEU_NUMERO",
            "NU_DOCUMENTO",
        ),
        "VALOR_PRESENTE": ("VL_PRESENTE_ADM", "VL_PRESENTE_BDR", "VALOR_PRESENTE"),
        "VALOR_PDD": ("VL_PDD", "VALOR_PDD"),
        "VALOR_NOMINAL": ("VL_FACE", "VALOR_NOMINAL"),
        "FAIXA_PDD": ("FX_PDD", "FAIXA_PDD"),
        "NOME_SACADO": ("NM_SACADO", "NOME_SACADO"),
        "DOC_SACADO": ("DOC_SACADO",),
    }
    for destino, fontes in aliases.items():
        if destino in out.columns:
            continue
        for fonte in fontes:
            c = cols.get(fonte)
            if c is not None:
                out[destino] = out[c]
                break
    return out


def df_sistema(abertos: dict[str, dict[str, Any]], data_ref: date) -> pd.DataFrame:
    rows = []
    for chave, pos in abertos.items():
        venc = pos.get("data_vencimento")
        try:
            venc_d = pd.to_datetime(venc, errors="coerce")
        except Exception:  # noqa: BLE001
            venc_d = pd.NaT
        status = (
            "VENCIDO"
            if pd.notna(venc_d) and venc_d.date() < data_ref
            else "A VENCER"
        )
        rows.append(
            {
                "chave": chave,
                "documento": str(pos.get("documento") or chave).strip(),
                "sacado": pos.get("sacado") or "",
                "doc_sacado": str(pos.get("doc_sacado") or "").strip(),
                "status": status,
                "data_vencimento": venc_d,
                "valor_face": float(pos.get("valor_face") or 0),
                "vl_presente_adm": float(pos.get("vl_presente_adm") or 0),
                "vl_pdd": float(pos.get("vl_pdd") or 0),
                "fx_pdd": str(pos.get("fx_pdd") or "").strip().upper(),
            }
        )
    return pd.DataFrame(rows)


def detalhar_vs_bdr(
    abertos: dict[str, dict[str, Any]],
    bdr_path: Path,
    data_ref: date,
    out_dir: Path,
) -> dict[str, Any]:
    sis = df_sistema(abertos, data_ref)
    bdr = _normalizar_colunas_bdr(
        pd.read_csv(bdr_path, sep=";", dtype=str, encoding="utf-8-sig")
    )
    bdr["doc"] = bdr["SEU_NUMERO"].astype(str).str.strip()
    bdr["VP_BDR"] = [cent(parse_valor(x)) for x in bdr["VALOR_PRESENTE"]]
    bdr["PDD_BDR"] = [cent(parse_valor(x)) for x in bdr["VALOR_PDD"]]
    bdr["FAIXA_BDR"] = bdr["FAIXA_PDD"].astype(str).str.strip().str.upper()
    bdr["FACE_BDR"] = [cent(parse_valor(x)) for x in bdr["VALOR_NOMINAL"]]

    sis["doc"] = sis["documento"].astype(str).str.strip()
    m = sis.merge(
        bdr[
            [
                "doc",
                "VP_BDR",
                "PDD_BDR",
                "FAIXA_BDR",
                "FACE_BDR",
                "NOME_SACADO",
                "DOC_SACADO",
            ]
        ],
        on="doc",
        how="outer",
        indicator=True,
    )

    so_sistema = m[m["_merge"] == "left_only"].copy()
    so_bdr = m[m["_merge"] == "right_only"].copy()
    ambos = m[m["_merge"] == "both"].copy()
    ambos["DELTA_VP"] = (ambos["vl_presente_adm"].astype(float) - ambos["VP_BDR"]).round(2)
    ambos["DELTA_PDD"] = (ambos["vl_pdd"].astype(float) - ambos["PDD_BDR"]).round(2)
    faixa_diff = ambos[ambos["fx_pdd"] != ambos["FAIXA_BDR"]]

    top_vp = (
        ambos.reindex(ambos["DELTA_VP"].abs().sort_values(ascending=False).index)
        .head(15)[
            [
                "doc",
                "sacado",
                "fx_pdd",
                "FAIXA_BDR",
                "vl_presente_adm",
                "VP_BDR",
                "DELTA_VP",
                "vl_pdd",
                "PDD_BDR",
                "DELTA_PDD",
            ]
        ]
        .to_dict(orient="records")
    )
    top_pdd = (
        ambos.reindex(ambos["DELTA_PDD"].abs().sort_values(ascending=False).index)
        .head(15)[
            [
                "doc",
                "sacado",
                "fx_pdd",
                "FAIXA_BDR",
                "vl_presente_adm",
                "VP_BDR",
                "DELTA_VP",
                "vl_pdd",
                "PDD_BDR",
                "DELTA_PDD",
            ]
        ]
        .to_dict(orient="records")
    )

    # Persiste CSVs de diagnóstico
    dest = out_dir / data_ref.isoformat()
    dest.mkdir(parents=True, exist_ok=True)
    so_sistema[
        ["doc", "sacado", "doc_sacado", "status", "data_vencimento", "vl_presente_adm", "vl_pdd", "fx_pdd"]
    ].to_csv(dest / "so_sistema.csv", sep=";", index=False, encoding="utf-8-sig")
    so_bdr[
        ["doc", "NOME_SACADO", "DOC_SACADO", "VP_BDR", "PDD_BDR", "FAIXA_BDR", "FACE_BDR"]
    ].to_csv(dest / "so_bdr.csv", sep=";", index=False, encoding="utf-8-sig")
    faixa_diff[
        [
            "doc",
            "sacado",
            "fx_pdd",
            "FAIXA_BDR",
            "vl_presente_adm",
            "VP_BDR",
            "DELTA_VP",
            "vl_pdd",
            "PDD_BDR",
            "DELTA_PDD",
        ]
    ].to_csv(dest / "faixa_divergente.csv", sep=";", index=False, encoding="utf-8-sig")

    return {
        "n_ambos": int(len(ambos)),
        "so_sistema": int(len(so_sistema)),
        "so_bdr": int(len(so_bdr)),
        "faixa_divergente": int(len(faixa_diff)),
        "delta_vp_total": cent(ambos["DELTA_VP"].sum()) if len(ambos) else 0.0,
        "delta_pdd_total": cent(ambos["DELTA_PDD"].sum()) if len(ambos) else 0.0,
        "vp_abs": cent(ambos["DELTA_VP"].abs().sum()) if len(ambos) else 0.0,
        "pdd_abs": cent(ambos["DELTA_PDD"].abs().sum()) if len(ambos) else 0.0,
        "top_vp": top_vp,
        "top_pdd": top_pdd,
        "amostra_so_sistema": so_sistema.head(20)[
            ["doc", "sacado", "vl_presente_adm", "vl_pdd", "fx_pdd"]
        ].to_dict(orient="records"),
        "amostra_so_bdr": so_bdr.head(20)[
            ["doc", "NOME_SACADO", "VP_BDR", "PDD_BDR", "FAIXA_BDR"]
        ].to_dict(orient="records"),
    }


def garantir_bdr(d: date, *, baixar: bool) -> Path | None:
    path = REL / f"EstoqueBDR_{d.isoformat()}.csv"
    if path.exists() and path.stat().st_size > 1000:
        return path
    if not baixar:
        return None
    try:
        from baixar_estoque_bdr import baixar_estoque

        print(f"  baixando EstoqueBDR {d.isoformat()}…", flush=True)
        return baixar_estoque(d, out=path)
    except Exception as exc:  # noqa: BLE001
        print(f"  falha download BDR {d.isoformat()}: {exc}", flush=True)
        return None


def conciliar_dia(
    d: date,
    *,
    base: dict[str, dict[str, Any]],
    eventos: list[dict[str, Any]],
    baixar_bdr: bool,
    tol: float,
    out_dir: Path,
) -> dict[str, Any]:
    print(f"\n=== {d.isoformat()} ===", flush=True)
    # Preferir o EstoqueBDR do dia antes da marcação: assim o PRAZO_ATUAL do
    # registrador entra na fórmula. Se faltar e a tolerância estourar, baixa e
    # remarca uma vez.
    bdr_path = garantir_bdr(d, baixar=baixar_bdr)
    abertos = _aplicar_eventos_ate(eventos, d, base=base)
    anexar_prazo_atual_do_dia(abertos, d)
    abertos = atualizar_marcacao(abertos, data_ref=DATA_MINIMA, data_alvo=d)
    sis = totais_sistema(abertos)
    print(
        f"  sistema: n={sis['n']} VP={sis['vp']:,.2f} PDD={sis['pdd']:,.2f}",
        flush=True,
    )

    idsf = idsf_do_dia(d)
    print(
        f"  IDSF:    DC={idsf['dc_bruto']:,.2f} PDD={idsf['pdd']:,.2f}"
        + (f" ({idsf['aviso']})" if idsf.get("aviso") else ""),
        flush=True,
    )

    delta_vp_idsf = cent(float(sis["vp"]) - float(idsf["dc_bruto"]))
    delta_pdd_idsf = cent(float(sis["pdd"]) - float(idsf["pdd"]))
    ok_idsf = abs(delta_vp_idsf) <= tol and abs(delta_pdd_idsf) <= tol

    if not ok_idsf and bdr_path is None:
        bdr_path = garantir_bdr(d, baixar=True)
        if bdr_path is not None:
            print("  remarcar com PRAZO_ATUAL do EstoqueBDR…", flush=True)
            abertos = _aplicar_eventos_ate(eventos, d, base=base)
            anexar_prazo_atual_do_dia(abertos, d)
            abertos = atualizar_marcacao(abertos, data_ref=DATA_MINIMA, data_alvo=d)
            sis = totais_sistema(abertos)
            print(
                f"  sistema: n={sis['n']} VP={sis['vp']:,.2f} PDD={sis['pdd']:,.2f}",
                flush=True,
            )
            delta_vp_idsf = cent(float(sis["vp"]) - float(idsf["dc_bruto"]))
            delta_pdd_idsf = cent(float(sis["pdd"]) - float(idsf["pdd"]))
            ok_idsf = abs(delta_vp_idsf) <= tol and abs(delta_pdd_idsf) <= tol

    print(
        f"  Δ IDSF:  VP={delta_vp_idsf:+,.2f} PDD={delta_pdd_idsf:+,.2f} "
        f"{'OK' if ok_idsf else 'FORA'}",
        flush=True,
    )

    bdr_tot: dict[str, Any] | None = None
    delta_vp_bdr = None
    delta_pdd_bdr = None
    ok_bdr = None
    detalhe = None
    efeito = {"ativo": False}
    salto_meta = saltos_prazo_atual_do_dia(abertos)
    if salto_meta:
        registrar_saltos_prazo_atual(
            d.isoformat(), list(salto_meta.get("titulos") or [])
        )
        print(
            f"  salto PRAZO_ATUAL BDR: n={salto_meta.get('n')} "
            f"(esperado {salto_meta.get('esperado')}; motor usa calendário)",
            flush=True,
        )

    if bdr_path is not None:
        bdr_tot = totais_bdr(bdr_path)
        delta_vp_bdr = cent(float(sis["vp"]) - float(bdr_tot["vp"]))
        delta_pdd_bdr = cent(float(sis["pdd"]) - float(bdr_tot["pdd"]))
        ok_bdr = abs(delta_vp_bdr) <= tol and abs(delta_pdd_bdr) <= tol
        print(
            f"  BDR:     n={bdr_tot['n']} VP={bdr_tot['vp']:,.2f} PDD={bdr_tot['pdd']:,.2f}",
            flush=True,
        )
        print(
            f"  Δ BDR:   VP={delta_vp_bdr:+,.2f} PDD={delta_pdd_bdr:+,.2f} "
            f"{'OK' if ok_bdr else 'FORA'}",
            flush=True,
        )
        efeito_res = calcular_efeito_residuos(bdr_path, abertos)
        efeito_salto = calcular_efeito_salto_prazo(
            abertos,
            data_ref=d,
            delta_vp_bruto=delta_vp_idsf,
            tol=tol,
        )
        efeito = combinar_efeitos(efeito_res, efeito_salto)
        if efeito.get("ativo"):
            ok_bdr_limpo, dv_b, dp_b = dentro_tolerancia(
                delta_vp_bdr, delta_pdd_bdr, tol=tol, efeito=efeito_res
            )
            # Salto explica furo IDSF (não o Δ BDR — motor≈BDR após calendário).
            ok_idsf_limpo, dv_i, dp_i = dentro_tolerancia(
                delta_vp_idsf, delta_pdd_idsf, tol=tol, efeito=efeito
            )
            print(
                f"  exceção {efeito.get('tipo')}: "
                f"ΔBDR limpo VP={dv_b:+,.2f} PDD={dp_b:+,.2f} "
                f"{'OK' if ok_bdr_limpo else 'FORA'} | "
                f"ΔIDSF limpo VP={dv_i:+,.2f} PDD={dp_i:+,.2f} "
                f"{'OK' if ok_idsf_limpo else 'FORA'}",
                flush=True,
            )
            registrar_ajuste_tolerancia(
                d.isoformat(),
                efeito,
                delta_vp_bruto=delta_vp_idsf,
                delta_pdd_bruto=delta_pdd_idsf,
                delta_vp_limpo=dv_i,
                delta_pdd_limpo=dp_i,
                ok_bruto=ok_idsf and bool(ok_bdr),
                ok_limpo=ok_idsf_limpo and ok_bdr_limpo,
            )
            ok_bdr = ok_bdr_limpo
            ok_idsf = ok_idsf_limpo
        if not ok_bdr or not ok_idsf:
            print("  detalhando diferenças vs BDR…", flush=True)
            detalhe = detalhar_vs_bdr(abertos, bdr_path, d, out_dir)
            print(
                f"  títulos: ambos={detalhe['n_ambos']} "
                f"só_sistema={detalhe['so_sistema']} só_bdr={detalhe['so_bdr']} "
                f"faixa≠={detalhe['faixa_divergente']}",
                flush=True,
            )
    else:
        print("  BDR:     arquivo ausente", flush=True)
        efeito_salto = calcular_efeito_salto_prazo(
            abertos,
            data_ref=d,
            delta_vp_bruto=delta_vp_idsf,
            tol=tol,
        )
        if efeito_salto.get("ativo"):
            ok_idsf_limpo, dv_i, dp_i = dentro_tolerancia(
                delta_vp_idsf, delta_pdd_idsf, tol=tol, efeito=efeito_salto
            )
            registrar_ajuste_tolerancia(
                d.isoformat(),
                efeito_salto,
                delta_vp_bruto=delta_vp_idsf,
                delta_pdd_bruto=delta_pdd_idsf,
                delta_vp_limpo=dv_i,
                delta_pdd_limpo=dp_i,
                ok_bruto=ok_idsf,
                ok_limpo=ok_idsf_limpo,
            )
            ok_idsf = ok_idsf_limpo
            efeito = efeito_salto

    ok = bool(ok_idsf and (ok_bdr is None or ok_bdr))
    resultado = {
        "data": d.isoformat(),
        "ok": ok,
        "ok_idsf": ok_idsf,
        "ok_bdr": ok_bdr,
        "tol": tol,
        "sistema": sis,
        "idsf": idsf,
        "bdr": bdr_tot,
        "delta_vp_idsf": delta_vp_idsf,
        "delta_pdd_idsf": delta_pdd_idsf,
        "delta_vp_bdr": delta_vp_bdr,
        "delta_pdd_bdr": delta_pdd_bdr,
        "excecao_residuos": efeito if efeito.get("ativo") else None,
        "salto_prazo_atual": salto_meta,
        "detalhe_bdr": detalhe,
        "bdr_path": str(bdr_path) if bdr_path else None,
    }
    # Motor permanece intacto; erros da BDR/IDSF vão para o log mensal ao fim.
    erros_log = classificar_erros_do_dia(resultado)
    if erros_log:
        tipos = ", ".join(sorted({str(e.get("tipo")) for e in erros_log}))
        print(
            f"  log erros BDR/IDSF: {len(erros_log)} registro(s) [{tipos}] "
            f"(motor mantido)",
            flush=True,
        )
        resultado["erros_bdr_log"] = [
            {"tipo": e.get("tipo"), "resumo": e.get("resumo")} for e in erros_log
        ]
    return resultado


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mes", default="2024-06", help="AAAA-MM")
    ap.add_argument("--baixar-bdr", action="store_true")
    ap.add_argument("--ate", default=None, help="AAAA-MM-DD — para no dia (inclusive)")
    ap.add_argument("--desde", default=None, help="AAAA-MM-DD")
    ap.add_argument(
        "--continuar-fora",
        action="store_true",
        help="Não para no primeiro dia fora da tolerância",
    )
    args = ap.parse_args()

    ano, mes = (int(x) for x in args.mes.split("-")[:2])
    ultimo = calendar.monthrange(ano, mes)[1]
    inicio_mes = date(ano, mes, 1)
    fim_mes = date(ano, mes, ultimo)
    desde = date.fromisoformat(args.desde) if args.desde else inicio_mes
    ate = date.fromisoformat(args.ate) if args.ate else fim_mes
    tol = float(TOLERANCIA_DC_ABS)
    out_dir = OUT_ROOT / f"conciliacao_{ano:04d}_{mes:02d}"

    out_dir.mkdir(parents=True, exist_ok=True)
    print(
        f"Conciliação {mes:02d}/{ano}  tol=R$ {tol:.2f}  "
        f"(números do motor próprio × IDSF/BDR)",
        flush=True,
    )
    print("Carregando base + eventos…", flush=True)
    reconstruir_eventos(forcar=False)
    base = carregar_estoque_base()
    eventos = _carregar_eventos(desde=DATA_MINIMA, ate=ate)
    print(f"base={len(base)} eventos={len(eventos)}", flush=True)

    dias = dias_uteis_mes(desde, ate)
    resultados: list[dict[str, Any]] = []
    parado = False

    for d in dias:
        try:
            res = conciliar_dia(
                d,
                base=base,
                eventos=eventos,
                baixar_bdr=args.baixar_bdr,
                tol=tol,
                out_dir=out_dir,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  ERRO: {exc}", flush=True)
            traceback.print_exc()
            res = {"data": d.isoformat(), "ok": False, "erro": str(exc)}
            parado = True
        resultados.append(res)
        (out_dir / f"{d.isoformat()}.json").write_text(
            json.dumps(res, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        if not res.get("ok") and not args.continuar_fora:
            print(
                f"\nParando em {d.isoformat()}: fora da tolerância "
                f"(use --continuar-fora para seguir).",
                flush=True,
            )
            parado = True
            break

    resumo = {
        "mes": f"{ano:04d}-{mes:02d}",
        "tol": tol,
        "dias": resultados,
        "parado": parado,
        "ok": all(r.get("ok") for r in resultados),
    }
    (out_dir / "resumo.json").write_text(
        json.dumps(resumo, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    print("\n===== RESUMO =====", flush=True)
    for r in resultados:
        if r.get("erro"):
            print(f"{r['data']}  ERRO {r['erro']}", flush=True)
            continue
        flag = "OK" if r.get("ok") else "FORA"
        bdr_txt = (
            f"BDR ΔVP={r.get('delta_vp_bdr'):+.2f} ΔPDD={r.get('delta_pdd_bdr'):+.2f}"
            if r.get("delta_vp_bdr") is not None
            else "BDR=—"
        )
        print(
            f"{r['data']}  {flag:4}  "
            f"IDSF ΔVP={r.get('delta_vp_idsf'):+.2f} ΔPDD={r.get('delta_pdd_idsf'):+.2f}  "
            f"{bdr_txt}",
            flush=True,
        )
    print(f"\ngravado: {out_dir / 'resumo.json'}", flush=True)

    log_path = reescrever_log_mensal(ano, mes, resultados)
    n_erros = sum(1 for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip())
    print(f"log erros BDR do mês: {log_path} ({n_erros} registro(s))", flush=True)
    consolidado = consolidar_logs()
    print(
        f"consolidado parcial: {consolidado['total']} registro(s) "
        f"em data/relatorios/erros_bdr/erros_bdr_consolidado.json",
        flush=True,
    )


if __name__ == "__main__":
    main()
