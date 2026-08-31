"""Três cenários de fluxo de caixa — sacados NC (fora do sistema)."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any

import pandas as pd

from carteira_movimentacoes import carregar_carteira_movimentacoes
from passivo_vencimentos import montar_fluxo_passivo_caixa

REF = date(2026, 8, 25)

SACADOS_NC = {
    "batatas": ("BATATAS PREMIUM",),
    "borga": ("BORGA COMERCIO",),
    "fixcomm": ("FIXCOMM",),
    "kata": ("KATA NORDESTE",),
    "modernize": ("MODERNIZE PLASTICOS",),
    "nova_conquista": ("NOVA CONQUISTA",),
    "rc_gomes": ("RC GOMES",),
    "rexa": ("REXA",),
}

DATAS = {
    "kata": date(2026, 9, 7),
    "fixcomm": date(2026, 9, 7),
    "rexa": date(2026, 9, 7),
    "modernize": date(2026, 9, 25),
    "borga_parcial": date(2026, 9, 20),
}


def _match_sacado(nome: str, chaves: tuple[str, ...]) -> bool:
    u = (nome or "").upper()
    return any(k in u for k in chaves)


def _chave_sacado(nome: str) -> str | None:
    for chave, keys in SACADOS_NC.items():
        if _match_sacado(nome, keys):
            return chave
    return None


def carregar_titulos_nc() -> pd.DataFrame:
    df = carregar_carteira_movimentacoes(REF)
    df = df.copy()
    df["sacado_key"] = df["sacado"].astype(str).map(_chave_sacado)
    return df.loc[df["sacado_key"].notna()].copy()


def exposicao_por_sacado(titulos: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for key in SACADOS_NC:
        s = titulos.loc[titulos["sacado_key"] == key]
        face = float(s["valor_face"].sum()) if len(s) else 0.0
        desc = float(s["valor_descontado"].sum()) if len(s) else 0.0
        rows.append(
            {
                "sacado_key": key,
                "nome": s["sacado"].iloc[0] if len(s) else "— (sem posição)",
                "n_titulos": len(s),
                "face_total": round(face, 2),
                "descontado": round(desc, 2),
                "juros_face_menos_desc": round(face - desc, 2),
                "face_vencido": round(float(s.loc[s["status"] == "VENCIDO", "valor_face"].sum()), 2),
                "face_a_vencer": round(float(s.loc[s["status"] == "A VENCER", "valor_face"].sum()), 2),
            }
        )
    return pd.DataFrame(rows)


def entradas_pd_baseline(titulos_nc: pd.DataFrame) -> dict[str, float]:
    """Entradas projetadas pelo modelo PD (só A VENCER com venc > ref)."""
    from pd_estimada import pd_por_titulo

    df = carregar_carteira_movimentacoes(REF)
    df = df.copy()
    df["_pd"] = pd_por_titulo(df, REF).values
    df["_sk"] = df["sacado"].astype(str).map(_chave_sacado)
    out: dict[str, float] = defaultdict(float)
    av = df.loc[(df["status"] == "A VENCER") & df["_sk"].notna()]
    for _, row in av.iterrows():
        venc = pd.to_datetime(row["data_vencimento"]).date()
        if venc <= REF:
            continue
        face = float(row["valor_face"])
        fator = max(0.0, 1.0 - float(row["_pd"]) / 100.0)
        out[venc.isoformat()] += face * fator
    return dict(out)


def entradas_pd_completas() -> dict[str, float]:
    """Toda carteira A VENCER com PD (consignado + demais)."""
    from pd_estimada import pd_por_titulo

    df = carregar_carteira_movimentacoes(REF)
    df = df.copy()
    df["_pd"] = pd_por_titulo(df, REF).values
    out: dict[str, float] = defaultdict(float)
    av = df.loc[df["status"].astype(str).str.upper() == "A VENCER"]
    for _, row in av.iterrows():
        venc = pd.to_datetime(row["data_vencimento"]).date()
        if venc <= REF:
            continue
        face = float(row["valor_face"])
        fator = max(0.0, 1.0 - float(row["_pd"]) / 100.0)
        out[venc.isoformat()] += face * fator
    return dict(out)


def entradas_pd_nc_sacados() -> dict[str, float]:
    """Somente sacados NC da lista de stress, com PD."""
    from pd_estimada import pd_por_titulo

    df = carregar_carteira_movimentacoes(REF)
    df = df.copy()
    df["_pd"] = pd_por_titulo(df, REF).values
    df["_sk"] = df["sacado"].astype(str).map(_chave_sacado)
    out: dict[str, float] = defaultdict(float)
    av = df.loc[(df["status"] == "A VENCER") & df["_sk"].notna()]
    for _, row in av.iterrows():
        venc = pd.to_datetime(row["data_vencimento"]).date()
        if venc <= REF:
            continue
        face = float(row["valor_face"])
        fator = max(0.0, 1.0 - float(row["_pd"]) / 100.0)
        out[venc.isoformat()] += face * fator
    return dict(out)


def entradas_pd_resto(titulos_nc: pd.DataFrame) -> dict[str, float]:
    """Alias: carteira completa menos NC (legado)."""
    tot = entradas_pd_completas()
    nc = entradas_pd_nc_sacados()
    out: dict[str, float] = defaultdict(float)
    for iso, val in tot.items():
        out[iso] = val - nc.get(iso, 0.0)
    return dict(out)


def _face_total(titulos: pd.DataFrame, key: str) -> float:
    s = titulos.loc[titulos["sacado_key"] == key]
    return float(s["valor_face"].sum()) if len(s) else 0.0


def _juros_parcela(row: pd.Series) -> float:
    face = float(row["valor_face"])
    desc = float(row.get("valor_descontado") or 0)
    return max(0.0, face - desc)


def entradas_cenario(titulos: pd.DataFrame, cenario: int) -> dict[str, float]:
    out: dict[str, float] = defaultdict(float)

    if cenario == 1:
        return {}

    if cenario in (2, 3):
        for key, dt in [
            ("kata", DATAS["kata"]),
            ("fixcomm", DATAS["fixcomm"]),
            ("rexa", DATAS["rexa"]),
        ]:
            val = _face_total(titulos, key)
            if val > 0:
                out[dt.isoformat()] += val

        mod = _face_total(titulos, "modernize")
        if mod > 0:
            out[DATAS["modernize"].isoformat()] += mod

        # Nova Conquista: juros (face - descontado) nos vencimentos futuros
        nc = titulos.loc[
            (titulos["sacado_key"] == "nova_conquista") & (titulos["status"] == "A VENCER")
        ]
        for _, row in nc.iterrows():
            venc = pd.to_datetime(row["data_vencimento"]).date()
            if venc <= REF:
                continue
            out[venc.isoformat()] += _juros_parcela(row)

        if cenario == 3:
            borga_pago = min(400_000.0, _face_total(titulos, "borga"))
            if borga_pago > 0:
                out[DATAS["borga_parcial"].isoformat()] += borga_pago

    return dict(out)


def _dias_entre(inicio: date, fim: date) -> list[date]:
    out: list[date] = []
    d = inicio
    while d <= fim:
        out.append(d)
        d += timedelta(days=1)
    return out


def montar_fluxo_cenario(cenario: int, titulos: pd.DataFrame) -> dict[str, Any]:
    """Fluxo diário: carteira com PD (consignado incl.) + override sacados NC."""
    base = montar_fluxo_passivo_caixa(REF.strftime("%d/%m/%Y"))

    entradas_total = entradas_pd_completas()
    entradas_nc_pd = entradas_pd_nc_sacados()
    entradas_nc_cen = entradas_cenario(titulos, cenario)

    entradas: dict[str, float] = defaultdict(float)
    for iso in set(entradas_total) | set(entradas_nc_cen):
        entradas[iso] = (
            entradas_total.get(iso, 0.0)
            - entradas_nc_pd.get(iso, 0.0)
            + entradas_nc_cen.get(iso, 0.0)
        )

    saidas: dict[str, float] = defaultdict(float)
    for p in base["serie"]:
        if p.get("tipo") == "projetado" and p.get("saidas_passivo"):
            saidas[p["data"]] += float(p["saidas_passivo"])

    caixa = float(base["caixa_inicial"])
    for p in base["serie"]:
        if p.get("tipo") == "real":
            caixa = float(p["caixa"])

    corte = REF
    if base.get("ultima_liquidez_iso"):
        corte = date.fromisoformat(str(base["ultima_liquidez_iso"])[:10])

    caixa_ref = caixa
    for p in base["serie"]:
        if p.get("data") == REF.isoformat():
            caixa_ref = float(p["caixa"])
            break

    dias_fluxo = sorted(set(entradas) | set(saidas))
    if not dias_fluxo:
        return {"cenario": cenario, "serie": [], "totais": {}, "caixa_ref": caixa_ref}

    inicio_proj = corte + timedelta(days=1)
    fim_proj = date.fromisoformat(dias_fluxo[-1])

    serie: list[dict] = [
        {
            "data": REF.isoformat(),
            "entradas": 0.0,
            "entradas_nc": 0.0,
            "saidas_passivo": 0.0,
            "caixa": round(caixa_ref, 2),
            "tipo": "inicial",
        }
    ]

    caixa_atual = caixa
    tot_ent = 0.0
    tot_nc = 0.0
    tot_sai = 0.0

    for d in _dias_entre(inicio_proj, fim_proj):
        iso = d.isoformat()
        ent_nc = float(entradas_nc_cen.get(iso, 0.0))
        ent = float(entradas.get(iso, 0.0))
        sai = float(saidas.get(iso, 0.0))
        caixa_atual = round(caixa_atual + ent - sai, 2)
        tot_ent += ent
        tot_nc += ent_nc
        tot_sai += sai
        serie.append(
            {
                "data": iso,
                "entradas": round(ent, 2),
                "entradas_nc": round(ent_nc, 2),
                "saidas_passivo": round(sai, 2),
                "caixa": caixa_atual,
                "tipo": "projetado",
            }
        )

    return {
        "cenario": cenario,
        "caixa_inicial_proj": caixa_ref,
        "caixa_final": caixa_atual,
        "serie": serie,
        "totais": {
            "entradas": round(tot_ent, 2),
            "entradas_nc": round(tot_nc, 2),
            "saidas_passivo": round(tot_sai, 2),
        },
        "entradas_nc_por_data": dict(sorted(entradas_nc_cen.items())),
    }


def serie_mensal_canvas(fluxo: dict) -> tuple[list[str], list[float], float, float]:
    """Rótulos, caixa (R$ mil), yMin e yMax para o gráfico."""
    pts = fluxo.get("serie") or []
    if not pts:
        return [], [], 0, 0

    nomes = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
    rotulos: list[str] = []
    valores: list[float] = []

    ini = next((p for p in pts if p.get("tipo") == "inicial"), pts[0])
    d0 = date.fromisoformat(str(ini["data"]))
    rotulos.append(f"{d0.day:02d}/{nomes[d0.month - 1]}")
    valores.append(round(float(ini["caixa"]) / 1000, 1))

    por_mes: dict[str, float] = {}
    for p in pts:
        if p.get("tipo") == "inicial":
            continue
        d = date.fromisoformat(str(p["data"]))
        por_mes[d.strftime("%Y-%m")] = float(p["caixa"])

    for mes in sorted(por_mes):
        y, mo = mes.split("-")
        rotulos.append(f"{nomes[int(mo) - 1]}/{y[2:]}")
        valores.append(round(por_mes[mes] / 1000, 1))

    vmin = min(valores)
    vmax = max(valores)
    pad = max(200, (vmax - vmin) * 0.08)
    y_min = round(vmin - pad, 0)
    y_max = round(vmax + pad * 0.5, 0)
    if y_min > 0 and vmin < 0:
        y_min = round(vmin - pad, 0)
    elif vmin >= 0:
        y_min = 0

    return rotulos, valores, y_min, y_max


def resumo_mensal(fluxo: dict) -> pd.DataFrame:
    rows = []
    for p in fluxo["serie"]:
        d = date.fromisoformat(p["data"])
        rows.append(
            {
                "mes": d.strftime("%Y-%m"),
                "entradas": p["entradas"],
                "entradas_nc": p["entradas_nc"],
                "saidas": p["saidas_passivo"],
                "liquido": p["entradas"] - p["saidas_passivo"],
            }
        )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    g = df.groupby("mes", as_index=False).sum(numeric_only=True)
    return g


def main() -> None:
    titulos = carregar_titulos_nc()
    exp = exposicao_por_sacado(titulos)

    print("=" * 78)
    print(f"CENÁRIOS FLUXO DE CAIXA — NCs | data base {REF:%d/%m/%Y}")
    print("=" * 78)

    print("\n--- Exposição atual (face) dos sacados NC ---")
    for _, r in exp.iterrows():
        print(
            f"  {r['nome'][:52]:52} | total R$ {r['face_total']:>11,.2f} "
            f"(vencido {r['face_vencido']:,.2f} + a vencer {r['face_a_vencer']:,.2f})"
        )
    if _face_total(titulos, "rexa") == 0:
        print("  REXA COBRANCAS LTDA — sem posição na carteira em 25/08/2026")

    pd_nc = entradas_pd_baseline(titulos)
    print(f"\n  Entradas NC no modelo PD (A VENCER futuro): R$ {sum(pd_nc.values()):,.2f}")

    nomes = {
        1: "100% default em todos os sacados NC",
        2: "Pagamentos parciais (Kata/Fixcomm/Rexa 7/9, Modernize 25/9, NC juros; resto default)",
        3: "Cenário 2 + Borga R$ 400k em 20/9; RC Gomes e Batatas default",
    }

    resultados = {}
    for c in (1, 2, 3):
        resultados[c] = montar_fluxo_cenario(c, titulos)

    print("\n--- Comparativo agregado (projeção) ---")
    print(f"{'Cenário':<10} {'Entradas NC':>14} {'Entradas tot':>14} {'Saídas passivo':>16} {'Caixa final':>14}")
    base_fluxo = montar_fluxo_passivo_caixa(REF.strftime("%d/%m/%Y"))
    print(
        f"{'Baseline':<10} {'(PD embutido)':>14} "
        f"{base_fluxo['totais']['entradas_ativos']:>14,.0f} "
        f"{base_fluxo['totais']['saidas_passivo']:>16,.0f} "
        f"{base_fluxo['caixa_final']:>14,.0f}"
    )
    for c in (1, 2, 3):
        t = resultados[c]["totais"]
        print(
            f"Cenário {c:<3} {t['entradas_nc']:>14,.0f} {t['entradas']:>14,.0f} "
            f"{t['saidas_passivo']:>16,.0f} {resultados[c]['caixa_final']:>14,.0f}"
        )

    for c in (2, 3):
        print(f"\n--- Cenário {c}: entradas NC por data ---")
        for dt, val in resultados[c]["entradas_nc_por_data"].items():
            print(f"  {date.fromisoformat(dt):%d/%m/%Y}: R$ {val:,.2f}")

    print("\n--- Resumo mensal (set–dez/2026) — Cenário 1 vs 2 vs 3 ---")
    for c in (1, 2, 3):
        m = resumo_mensal(resultados[c])
        m = m[m["mes"] >= "2026-09"]
        print(f"\n  Cenário {c}:")
        for _, row in m.head(6).iterrows():
            print(
                f"    {row['mes']} | entradas R$ {row['entradas']:>12,.0f} "
                f"(NC R$ {row['entradas_nc']:>10,.0f}) | saídas R$ {row['saidas']:>10,.0f} | "
                f"líquido R$ {row['liquido']:>10,.0f}"
            )

    # Delta vs cenário 1
    print("\n--- Incremento de caixa vs Cenário 1 (default total NC) ---")
    cf1 = resultados[1]["caixa_final"]
    for c in (2, 3):
        print(f"  Cenário {c}: R$ {resultados[c]['caixa_final'] - cf1:+,.2f}")


if __name__ == "__main__":
    main()
