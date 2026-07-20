import pandas as pd

from db import carregar_recebiveis


def _valor_presente_titulo(valor_face: float, taxa_operacao: float, dias_restantes: float) -> float:
    """Desconta o valor de face pela taxa mensal proporcional aos dias restantes."""
    if pd.isna(valor_face) or pd.isna(taxa_operacao):
        return 0.0
    if pd.isna(dias_restantes) or dias_restantes <= 0:
        return float(valor_face)
    fator = 1 - (float(taxa_operacao) / 100.0) * (float(dias_restantes) / 30.0)
    return float(valor_face) * max(fator, 0.0)


def calcular_risco_fidc(data_base_filtro: str) -> dict:
    # 1. Carregar os dados do Supabase já filtrados pela data base
    df_atual = carregar_recebiveis(data_base_filtro)

    # Converte a data do filtro para o formato datetime
    data_alvo = pd.to_datetime(data_base_filtro, format="%d/%m/%Y")

    if df_atual.empty:
        return {"erro": "Nenhum dado encontrado para esta data base."}

    # 2. Indicadores de carteira (definições do produto)
    status_atraso = ["VENCIDO", "ATRASO"]
    status_fora_atraso = ["LIQUIDADO", "BAIXADO", "RECOMPRADO", "CEDIDO"]

    df_atual["dias_restantes"] = (df_atual["data_vencimento"] - data_alvo).dt.days
    df_atual["valor_presente_calc"] = [
        _valor_presente_titulo(vf, tx, dias)
        for vf, tx, dias in zip(
            df_atual["valor_face"],
            df_atual["taxa_operacao"],
            df_atual["dias_restantes"],
            strict=False,
        )
    ]

    # Operações Ativas: quantidade com status A VENCER ou VENCIDO
    condicao_ativas = df_atual["status"].isin(["A VENCER", "VENCIDO"])
    operacoes_ativas = int(condicao_ativas.sum())

    # Volume Cedido: valor face com status CEDIDO (ainda inexistente na base)
    volume_cedido = float(
        df_atual.loc[df_atual["status"] == "CEDIDO", "valor_face"].sum()
    )

    # Valor Presente: desconto do valor face pela taxa, nas operações ativas
    valor_presente = float(
        df_atual.loc[condicao_ativas, "valor_presente_calc"].sum()
    )

    # Prazo médio: média ponderada (dias a partir da data base) dos A VENCER pelo VP
    df_a_vencer = df_atual.loc[df_atual["status"] == "A VENCER"].copy()
    soma_vp_a_vencer = float(df_a_vencer["valor_presente_calc"].sum())
    prazo_medio = (
        float(
            (df_a_vencer["dias_restantes"] * df_a_vencer["valor_presente_calc"]).sum()
            / soma_vp_a_vencer
        )
        if soma_vp_a_vencer > 0
        else 0.0
    )

    # Totais da carteira na data base (inclui resolvidos do snapshot)
    vol_face_total = df_atual["valor_face"].sum()
    vol_desc_total = df_atual["valor_descontado"].sum()

    # Lógica de Inadimplência (CEDIDO não entra no atraso)
    condicao_atraso = (df_atual["status"].isin(status_atraso)) | (
        (df_atual["data_vencimento"] < data_alvo)
        & (~df_atual["status"].isin(status_fora_atraso))
    )

    vol_atraso = df_atual.loc[condicao_atraso, "valor_face"].sum()

    # Aging de inadimplência e tops inadimplentes (somente status VENCIDO)
    df_inad = df_atual.loc[df_atual["status"] == "VENCIDO"].copy()
    df_inad["dias_atraso"] = (data_alvo - df_inad["data_vencimento"]).dt.days.clip(lower=0)

    def faixa_aging(dias: float) -> str:
        if pd.isna(dias) or dias <= 30:
            return "1-30 dias"
        if dias <= 60:
            return "31-60 dias"
        if dias <= 90:
            return "61-90 dias"
        if dias <= 180:
            return "91-180 dias"
        return ">180 dias"

    ordem_aging = [
        "1-30 dias",
        "31-60 dias",
        "61-90 dias",
        "91-180 dias",
        ">180 dias",
    ]
    if df_inad.empty:
        aging_inadimplencia = [
            {"faixa": faixa, "valor": 0.0, "qtd": 0, "peso": 0.0, "titulos": []}
            for faixa in ordem_aging
        ]
        top_sacados_inad = []
        top_cedentes_inad = []
    else:
        df_inad["faixa_aging"] = df_inad["dias_atraso"].map(faixa_aging)
        aging_grp = (
            df_inad.groupby("faixa_aging", as_index=False)
            .agg(valor=("valor_face", "sum"), qtd=("valor_face", "count"))
        )
        aging_map = aging_grp.set_index("faixa_aging")
        total_inad = float(df_inad["valor_face"].sum())
        aging_inadimplencia = []
        for faixa in ordem_aging:
            df_faixa = df_inad.loc[df_inad["faixa_aging"] == faixa].sort_values(
                by=["dias_atraso", "valor_face"], ascending=[False, False]
            )
            if faixa in aging_map.index:
                valor = float(aging_map.loc[faixa, "valor"])
                qtd = int(aging_map.loc[faixa, "qtd"])
            else:
                valor, qtd = 0.0, 0
            titulos = [
                {
                    "documento": str(row.get("documento", "")),
                    "cedente": str(row.get("cedente", "")),
                    "sacado": str(row.get("sacado", "")),
                    "status": str(row.get("status", "")),
                    "data_vencimento": (
                        pd.Timestamp(row["data_vencimento"]).strftime("%d/%m/%Y")
                        if pd.notna(row["data_vencimento"])
                        else ""
                    ),
                    "dias_atraso": int(row["dias_atraso"]),
                    "valor_face": round(float(row["valor_face"]), 2),
                }
                for _, row in df_faixa.iterrows()
            ]
            aging_inadimplencia.append(
                {
                    "faixa": faixa,
                    "valor": round(valor, 2),
                    "qtd": qtd,
                    "peso": round((valor / total_inad * 100), 1) if total_inad > 0 else 0.0,
                    "titulos": titulos,
                }
            )

        sacados_inad = (
            df_inad.groupby("sacado")["valor_face"]
            .sum()
            .reset_index()
            .sort_values(by="valor_face", ascending=False)
            .head(5)
        )
        cedentes_inad = (
            df_inad.groupby("cedente")["valor_face"]
            .sum()
            .reset_index()
            .sort_values(by="valor_face", ascending=False)
            .head(5)
        )
        top_sacados_inad = [
            {
                "nome": row["sacado"],
                "valor": round(float(row["valor_face"]), 2),
                "peso": f"{(row['valor_face'] / total_inad * 100):.1f}%",
            }
            for _, row in sacados_inad.iterrows()
        ]
        top_cedentes_inad = [
            {
                "nome": row["cedente"],
                "valor": round(float(row["valor_face"]), 2),
                "peso": f"{(row['valor_face'] / total_inad * 100):.1f}%",
            }
            for _, row in cedentes_inad.iterrows()
        ]

    # 3. Taxa Média (ponderada pelo valor descontado da base)
    df_atual["taxa_ponderada"] = df_atual["taxa_operacao"] * df_atual["valor_descontado"]
    taxa_media = (
        df_atual["taxa_ponderada"].sum() / vol_desc_total if vol_desc_total > 0 else 0
    )

    # 4. Cálculos de Concentração (Top 10, HHI e distribuição para pizza)
    cedentes_all = (
        df_atual.groupby("cedente")["valor_face"]
        .sum()
        .reset_index()
        .sort_values(by="valor_face", ascending=False)
    )
    cedentes_grp = cedentes_all.head(10)

    sacados_all = (
        df_atual.groupby("sacado")["valor_face"]
        .sum()
        .reset_index()
        .sort_values(by="valor_face", ascending=False)
    )
    sacados_all["peso_pct"] = (sacados_all["valor_face"] / vol_face_total) * 100
    atraso_por_sacado = (
        df_atual.loc[condicao_atraso]
        .groupby("sacado")["valor_face"]
        .sum()
    )
    sacados_all["vol_atraso"] = sacados_all["sacado"].map(atraso_por_sacado).fillna(0.0)
    sacados_all["pd_estimada"] = sacados_all.apply(
        lambda r: (float(r["vol_atraso"]) / float(r["valor_face"]) * 100 * 0.8)
        if float(r["valor_face"]) > 0
        else 0.0,
        axis=1,
    )
    hhi_calc = (sacados_all["peso_pct"] ** 2).sum()
    top_sacados = sacados_all.head(10)

    # Pizza: distribuição pelo Valor Presente das operações ativas
    df_pizza = df_atual.loc[condicao_ativas].copy()
    vp_total_pizza = float(df_pizza["valor_presente_calc"].sum())

    cedentes_pizza = (
        df_pizza.groupby("cedente")["valor_presente_calc"]
        .sum()
        .reset_index()
        .sort_values(by="valor_presente_calc", ascending=False)
    )
    sacados_pizza = (
        df_pizza.groupby("sacado")["valor_presente_calc"]
        .sum()
        .reset_index()
        .sort_values(by="valor_presente_calc", ascending=False)
    )

    def fatias_pizza(grp: pd.DataFrame, col_nome: str, top_n: int = 7) -> list[dict]:
        """Top N + Outros por Valor Presente (operações ativas)."""
        if grp.empty or vp_total_pizza <= 0:
            return []
        top = grp.head(top_n)
        resto_valor = (
            float(grp.iloc[top_n:]["valor_presente_calc"].sum())
            if len(grp) > top_n
            else 0.0
        )
        fatias = [
            {
                "nome": row[col_nome],
                "valor": round(float(row["valor_presente_calc"]), 2),
                "peso": round(float(row["valor_presente_calc"] / vp_total_pizza * 100), 1),
            }
            for _, row in top.iterrows()
        ]
        if resto_valor > 0:
            fatias.append(
                {
                    "nome": "Outros",
                    "valor": round(resto_valor, 2),
                    "peso": round(float(resto_valor / vp_total_pizza * 100), 1),
                }
            )
        return fatias

    distribuicao_cedentes = fatias_pizza(cedentes_pizza, "cedente")
    distribuicao_sacados = fatias_pizza(sacados_pizza, "sacado")

    # 5. Fluxo de caixa projetado (mensal) com PD por sacado
    pd_por_sacado = sacados_all.set_index("sacado")["pd_estimada"]
    df_fluxo = df_atual.loc[condicao_ativas].copy()
    df_fluxo["pd"] = df_fluxo["sacado"].map(pd_por_sacado).fillna(0.0)
    df_fluxo["fator_esperanca"] = (1 - df_fluxo["pd"] / 100.0).clip(lower=0.0)
    df_fluxo["fluxo_caixa"] = df_fluxo["valor_face"] * df_fluxo["fator_esperanca"]
    df_fluxo["receita_esperada"] = (
        df_fluxo["valor_face"] - df_fluxo["valor_presente_calc"]
    ) * df_fluxo["fator_esperanca"]

    # Vencidos entram no mês da data base; demais no mês de vencimento
    df_fluxo["data_pagamento"] = df_fluxo["data_vencimento"]
    df_fluxo.loc[df_fluxo["data_pagamento"] < data_alvo, "data_pagamento"] = data_alvo
    df_fluxo["mes_ano"] = df_fluxo["data_pagamento"].dt.strftime("%m/%Y")

    fluxo_mensal = df_fluxo.groupby("mes_ano", as_index=False).agg(
        fluxo_caixa=("fluxo_caixa", "sum"),
    )
    fluxo_mensal["sort_date"] = pd.to_datetime(fluxo_mensal["mes_ano"], format="%m/%Y")
    fluxo_mensal = fluxo_mensal.sort_values("sort_date").drop(columns=["sort_date"])

    receita_projetada_total = float(df_fluxo["receita_esperada"].sum())

    grafico_fluxo = [
        {
            "mes_ano": row["mes_ano"],
            "fluxo_caixa": round(float(row["fluxo_caixa"]), 2),
        }
        for _, row in fluxo_mensal.iterrows()
    ]

    # 6. Gráfico de Evolução (originação)
    df_atual["mes_ano_emissao"] = df_atual["data_emissao"].dt.strftime("%m/%Y")
    df_atual["receita_operacao"] = df_atual["valor_face"] - df_atual["valor_descontado"]

    grafico_originacao = df_atual.groupby("mes_ano_emissao", as_index=False).agg(
        volume_originado=("valor_descontado", "sum"),
        receita_projetada=("receita_operacao", "sum"),
    )
    grafico_originacao["sort_date"] = pd.to_datetime(
        grafico_originacao["mes_ano_emissao"], format="%m/%Y"
    )
    grafico_originacao = grafico_originacao.sort_values("sort_date").drop(
        columns=["sort_date"]
    )

    grafico_records = [
        {
            "mes_ano_emissao": row["mes_ano_emissao"],
            "volume_originado": round(float(row["volume_originado"]), 2),
            "receita_projetada": round(float(row["receita_projetada"]), 2),
        }
        for _, row in grafico_originacao.iterrows()
    ]

    resposta = {
        "kpis": {
            "operacoes_ativas": operacoes_ativas,
            "volume_cedido": round(volume_cedido, 2),
            "valor_presente": round(valor_presente, 2),
            "prazo_medio": round(prazo_medio, 1),
            "hhi": int(round(float(hhi_calc), 0)),
            "inadimplencia": round(float(vol_atraso / vol_face_total) * 100, 2)
            if vol_face_total > 0
            else 0.0,
            "receita_projetada": round(float(receita_projetada_total), 2),
            "taxa_media": round(float(taxa_media), 2),
        },
        "top_cedentes": [
            {
                "nome": row["cedente"],
                "valor": round(float(row["valor_face"]), 2),
                "peso": f"{(row['valor_face'] / vol_face_total * 100):.1f}%",
            }
            for _, row in cedentes_grp.iterrows()
        ],
        "top_sacados": [
            {
                "nome": row["sacado"],
                "valor": round(float(row["valor_face"]), 2),
                "peso": f"{row['peso_pct']:.1f}%",
                "pd_estimada": round(float(row["pd_estimada"]), 2),
            }
            for _, row in top_sacados.iterrows()
        ],
        "distribuicao_cedentes": distribuicao_cedentes,
        "distribuicao_sacados": distribuicao_sacados,
        "aging_inadimplencia": aging_inadimplencia,
        "top_sacados_inadimplentes": top_sacados_inad,
        "top_cedentes_inadimplentes": top_cedentes_inad,
        "grafico_fluxo_caixa": grafico_fluxo,
        "grafico_evolucao": grafico_records,
    }

    return resposta
