"""Motor de VP e vencimentos do passivo mezanino (portado do Alpha)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Any

from dateutil.relativedelta import relativedelta

from calendario import e_dia_util
from cdi_bcb import mapa_cdi

# Hardcodes históricos do Alpha (cisão/cessão) — já refletidos no passivo.db migrado;
# mantidos como referência; UI de edição fica fora desta fase.
DATA_CISAO_MELQUISEDEC_DIOLINDA = date(2024, 12, 30)
DATA_CESSAO_FRAGALI = date(2025, 3, 31)
DATA_CESSAO_THIAGO_MEZ_III = date(2025, 6, 30)


@dataclass(frozen=True)
class Classe:
    id: int
    nome: str
    percentual_cdi: float
    meses_primeira: int
    meses_segunda: int
    perc_primeira: float
    id_carteira: int | None = None


@dataclass
class Parcela:
    ordem: int
    rotulo: str
    data_vencimento: date
    fracao: float
    valor_original: float
    valor_presente: float
    valor_na_liquidacao: float
    liquidada: bool


@dataclass
class PosicaoChamada:
    chamada_id: int
    classe: Classe
    cotista_id: int
    cotista_nome: str
    cotista_documento: str
    numero: int
    data_prazo: date
    data_aporte: date
    data_base: date
    valor_nominal: float
    principal_amortizado: float
    principal_restante: float
    perc_primeira: float
    credito_vp: float
    fator_ate_hoje: float
    valor_presente_cheio: float
    valor_presente_remanescente: float
    parcelas: list[Parcela]


def add_meses(dia: date, meses: int) -> date:
    return dia + relativedelta(months=meses)


def proximo_dia_util(dia: date, cdi_datas: set[date] | None = None) -> date:
    atual = dia
    for _ in range(20):
        if cdi_datas and min(cdi_datas) <= atual <= max(cdi_datas):
            if atual in cdi_datas:
                return atual
        elif e_dia_util(atual):
            return atual
        atual += timedelta(days=1)
    return atual


def dia_util_anterior(dia: date, cdi_datas: set[date] | None = None) -> date:
    atual = dia - timedelta(days=1)
    for _ in range(20):
        if cdi_datas and min(cdi_datas) <= atual <= max(cdi_datas):
            if atual in cdi_datas:
                return atual
        elif e_dia_util(atual):
            return atual
        atual -= timedelta(days=1)
    return atual


class FatorCDI:
    """Fator acumulado de X% do CDI (série BCB % a.d.)."""

    def __init__(self, cdi: dict[date, float]):
        self.datas = sorted(cdi)
        self.datas_set = set(self.datas)
        self.taxa = cdi
        self._idx = {d: i for i, d in enumerate(self.datas)}
        self._cum: dict[float, list[float]] = {}

    def _curva(self, percentual: float) -> list[float]:
        if percentual in self._cum:
            return self._cum[percentual]
        mult = percentual / 100.0
        acc = [1.0]
        fator = 1.0
        for dia in self.datas:
            fator *= 1.0 + (self.taxa[dia] / 100.0) * mult
            acc.append(fator)
        self._cum[percentual] = acc
        return acc

    def _primeiro_idx(self, dia: date) -> int:
        if not self.datas or dia > self.datas[-1]:
            return len(self.datas)
        if dia <= self.datas[0]:
            return 0
        if dia in self._idx:
            return self._idx[dia]
        lo, hi = 0, len(self.datas) - 1
        ans = len(self.datas)
        while lo <= hi:
            mid = (lo + hi) // 2
            if self.datas[mid] >= dia:
                ans = mid
                hi = mid - 1
            else:
                lo = mid + 1
        return ans

    def fator(self, inicio: date, fim: date, percentual: float) -> float:
        if fim <= inicio or not self.datas:
            return 1.0
        curva = self._curva(percentual)
        i_ini = self._primeiro_idx(inicio)
        i_fim = self._primeiro_idx(fim)
        if i_ini >= len(self.datas) or i_fim <= i_ini:
            return 1.0
        return curva[i_fim] / curva[i_ini]


def ancora_liquidacao(prazo: date, aportes: list[date]) -> date:
    validos = [d for d in aportes if d >= prazo]
    return min(validos) if validos else prazo


def ancoras_por_chamada(chamadas: list[dict[str, Any]]) -> dict[tuple[int, int], date]:
    grupos: dict[tuple[int, int], list] = defaultdict(list)
    for ch in chamadas:
        grupos[(int(ch["classe_id"]), int(ch["numero"]))].append(ch)
    out: dict[tuple[int, int], date] = {}
    for chave, rows in grupos.items():
        prazos = [
            date.fromisoformat(str(r.get("data_prazo") or r["data_aporte"])[:10])
            for r in rows
        ]
        prazo = min(prazos)
        aportes = [date.fromisoformat(str(r["data_aporte"])[:10]) for r in rows]
        out[chave] = ancora_liquidacao(prazo, aportes)
    return out


def _parcela_liquidada_em(
    ordem: int,
    ref: date,
    venc_parcela: date,
    *,
    principal_amortizado: float,
    principal_restante: float,
) -> bool:
    """Parcela liquidada na data ref (extrato histórico / motor passivo)."""
    if ref < venc_parcela:
        return False
    if ordem == 1:
        return principal_amortizado > 0.005
    return principal_restante <= 0.005


def _principais_parcelas(
    chamada: dict[str, Any],
    classe: Classe,
    nominal: float,
    principal_amortizado: float,
) -> tuple[float, float, float]:
    """(fracao_1, principal_1, principal_2) — paridade com montar_posicao."""
    fracao_1 = _fracao_primeira(chamada, classe)
    raw_perc = chamada.get("perc_primeira")
    if principal_amortizado > 0.005 or (
        raw_perc is not None and float(raw_perc or 0) > 0
    ):
        if raw_perc is not None and float(raw_perc) > 0:
            fracao_1 = min(1.0, float(raw_perc) / 100.0)
            principal_1 = nominal * fracao_1
        else:
            principal_1 = min(principal_amortizado, nominal)
            fracao_1 = principal_1 / nominal if nominal else 0.0
        principal_2 = max(0.0, nominal - principal_1)
    else:
        principal_1 = nominal * fracao_1
        principal_2 = nominal * max(0.0, 1.0 - fracao_1)
    return fracao_1, principal_1, principal_2


def preparar_ctx_extrato(
    chamada: dict[str, Any],
    classe: Classe,
    data_base: date,
    fatorador: FatorCDI,
) -> dict[str, Any]:
    """Metadados pré-calculados para extrato diário (evita montar_posicao completa)."""
    data_aporte = date.fromisoformat(str(chamada["data_aporte"])[:10])
    d1 = proximo_dia_util(
        add_meses(data_base, classe.meses_primeira), fatorador.datas_set
    )
    d2 = proximo_dia_util(
        add_meses(data_base, classe.meses_segunda), fatorador.datas_set
    )
    nominal = float(chamada["valor_nominal"])
    principal_amortizado = float(chamada.get("principal_amortizado") or 0)
    fracao_1, principal_1, principal_2 = _principais_parcelas(
        chamada, classe, nominal, principal_amortizado
    )
    return {
        "data_aporte": data_aporte,
        "nominal": nominal,
        "principal_amortizado": principal_amortizado,
        "principal_restante": max(0.0, nominal - principal_amortizado),
        "valor_amortizado_bruto": float(chamada.get("valor_amortizado_bruto") or 0),
        "credito_vp": float(chamada.get("credito_vp") or 0),
        "fracao_1": fracao_1,
        "principal_1": principal_1,
        "principal_2": principal_2,
        "perc_cdi": classe.percentual_cdi,
        "d1": d1,
        "d2": d2,
    }


def _liquidacao_historica(
    ctx: dict[str, Any],
    ref: date,
) -> tuple[bool, bool]:
    """Parcelas liquidadas na data ref (estado conhecido no cadastro, não o saldo atual)."""
    if ref < ctx["data_aporte"]:
        return False, False
    p1_pago = ref >= ctx["d1"] and ctx["principal_amortizado"] > 0.005
    p2_pago = ref >= ctx["d2"] and ctx["principal_restante"] <= 0.005
    return p1_pago, p2_pago


def extrato_chamada_dia(
    ctx: dict[str, Any],
    fatorador: FatorCDI,
    ref: date,
) -> dict[str, float]:
    """Saldo, VP e movimentos do dia (layout Britech: aporte / amort / juros)."""
    vazio = {
        "saldo": 0.0,
        "vp": 0.0,
        "aporte": 0.0,
        "amortizacao": 0.0,
        "juros": 0.0,
    }
    if ref < ctx["data_aporte"]:
        return vazio

    p1_pago, p2_pago = _liquidacao_historica(ctx, ref)
    nominal = ctx["nominal"]
    principal_1 = ctx["principal_1"]
    principal_2 = ctx["principal_2"]
    perc_cdi = ctx["perc_cdi"]
    data_aporte = ctx["data_aporte"]

    if p2_pago:
        saldo, vp = 0.0, 0.0
    elif p1_pago:
        saldo = ctx["principal_restante"]
        fator = fatorador.fator(data_aporte, ref, perc_cdi)
        vp = saldo * fator
    else:
        saldo = nominal
        fator = fatorador.fator(data_aporte, ref, perc_cdi)
        vp = nominal * fator

    aporte = nominal if ref == data_aporte else 0.0
    amortizacao = 0.0
    juros = 0.0

    if ref == ctx["d1"] and p1_pago and principal_1 > 0.005:
        amortizacao = principal_1
        bruto_db = float(ctx.get("valor_amortizado_bruto") or 0)
        if bruto_db > amortizacao + 0.005:
            juros = max(0.0, bruto_db - amortizacao)
        else:
            f_pag = fatorador.fator(data_aporte, ctx["d1"], perc_cdi)
            juros = max(0.0, principal_1 * f_pag - principal_1)

    if ref == ctx["d2"] and p2_pago and principal_2 > 0.005:
        amortizacao = principal_2
        f_pag = fatorador.fator(data_aporte, ctx["d2"], perc_cdi)
        total = principal_2 * f_pag
        credito = float(ctx.get("credito_vp") or 0)
        if credito > 0:
            total = max(0.0, total - credito)
        juros = max(0.0, total - amortizacao)

    return {
        "saldo": round(saldo, 2),
        "vp": round(vp, 2),
        "aporte": round(aporte, 2),
        "amortizacao": round(amortizacao, 2),
        "juros": round(juros, 2),
    }


def totais_chamada_dia(
    ctx: dict[str, Any],
    fatorador: FatorCDI,
    ref: date,
) -> tuple[float, float]:
    """(saldo principal, vp_remanescente) na data ref — paridade com montar_posicao."""
    dia = extrato_chamada_dia(ctx, fatorador, ref)
    return dia["saldo"], dia["vp"]


def _fracao_primeira(chamada: dict[str, Any], classe: Classe) -> float:
    raw = chamada.get("perc_primeira")
    if raw is not None and float(raw) > 0:
        return min(1.0, float(raw) / 100.0)
    principal = float(chamada.get("principal_amortizado") or 0)
    nominal = float(chamada["valor_nominal"])
    if principal > 0 and nominal > 0:
        return min(1.0, principal / nominal)
    return classe.perc_primeira / 100.0


def montar_posicao(
    chamada: dict[str, Any],
    classe: Classe,
    cotista: dict[str, Any],
    fatorador: FatorCDI,
    hoje: date,
    data_base: date,
    credito_vp: float = 0.0,
) -> PosicaoChamada:
    data_prazo = date.fromisoformat(
        str(chamada.get("data_prazo") or chamada["data_aporte"])[:10]
    )
    data_aporte = date.fromisoformat(str(chamada["data_aporte"])[:10])
    nominal = float(chamada["valor_nominal"])
    perc_cdi = classe.percentual_cdi
    principal_amortizado = float(chamada.get("principal_amortizado") or 0)
    principal_restante = max(0.0, nominal - principal_amortizado)
    if chamada.get("credito_vp") is not None:
        credito_vp = float(chamada.get("credito_vp") or 0)
    fracao_1 = _fracao_primeira(chamada, classe)
    fracao_2 = max(0.0, 1.0 - fracao_1)

    d1 = proximo_dia_util(add_meses(data_base, classe.meses_primeira), fatorador.datas_set)
    d2 = proximo_dia_util(add_meses(data_base, classe.meses_segunda), fatorador.datas_set)
    v1 = dia_util_anterior(d1, fatorador.datas_set)
    v2 = dia_util_anterior(d2, fatorador.datas_set)

    fator_hoje = fatorador.fator(data_aporte, hoje, perc_cdi)
    vp_cheio = nominal * fator_hoje

    raw_perc = chamada.get("perc_primeira")
    if principal_amortizado > 0 or (raw_perc is not None and float(raw_perc or 0) > 0):
        if raw_perc is not None and float(raw_perc) > 0:
            fracao_1 = min(1.0, float(raw_perc) / 100.0)
            principal_1 = nominal * fracao_1
        else:
            principal_1 = min(principal_amortizado, nominal)
            fracao_1 = principal_1 / nominal if nominal else 0.0
        principal_2 = max(0.0, nominal - principal_1)
        fracao_2 = principal_2 / nominal if nominal else 0.0
    else:
        principal_1 = nominal * fracao_1
        principal_2 = nominal * fracao_2
        fracao_2 = max(0.0, 1.0 - fracao_1)

    def parcela(
        ordem: int,
        rotulo: str,
        venc: date,
        pagamento: date,
        fracao: float,
        principal: float,
        liquidada: bool,
        principal_vp: float | None = None,
    ) -> Parcela:
        fator_venc = fatorador.fator(data_aporte, pagamento, perc_cdi)
        valor_liq = principal * fator_venc
        if ordem == 2 and not liquidada and credito_vp:
            valor_liq = max(0.0, valor_liq - credito_vp)
        face_vp = principal if principal_vp is None else principal_vp
        if liquidada:
            vp = 0.0
        elif ordem == 2 or (ordem == 1 and principal_amortizado <= 0):
            vp = face_vp * fator_hoje
        else:
            vp = 0.0
        return Parcela(
            ordem=ordem,
            rotulo=rotulo,
            data_vencimento=venc,
            fracao=fracao,
            valor_original=principal,
            valor_presente=vp,
            valor_na_liquidacao=valor_liq,
            liquidada=liquidada,
        )

    p1_liq = _parcela_liquidada_em(
        1, hoje, d1, principal_amortizado=principal_amortizado, principal_restante=principal_restante
    )
    p2_liq = _parcela_liquidada_em(
        2, hoje, d2, principal_amortizado=principal_amortizado, principal_restante=principal_restante
    )
    p1 = parcela(
        1,
        f"1ª ({fracao_1 * 100:.1f}% face)",
        d1,
        d1,
        fracao_1,
        principal_1,
        p1_liq,
    )
    p2 = parcela(
        2,
        f"2ª ({fracao_2 * 100:.1f}% face)",
        d2,
        d2,
        fracao_2,
        principal_2,
        p2_liq,
        principal_vp=principal_restante,
    )
    remanescente = principal_restante * fator_hoje
    return PosicaoChamada(
        chamada_id=int(chamada["id"]),
        classe=classe,
        cotista_id=int(cotista["id"]),
        cotista_nome=str(cotista["nome"]),
        cotista_documento=str(cotista["documento"]),
        numero=int(chamada["numero"]),
        data_prazo=data_prazo,
        data_aporte=data_aporte,
        data_base=data_base,
        valor_nominal=nominal,
        principal_amortizado=principal_amortizado,
        principal_restante=principal_restante,
        perc_primeira=fracao_1 * 100.0,
        credito_vp=credito_vp,
        fator_ate_hoje=fator_hoje,
        valor_presente_cheio=vp_cheio,
        valor_presente_remanescente=remanescente,
        parcelas=[p1, p2],
    )


def _classe_from_row(row: dict[str, Any]) -> Classe:
    return Classe(
        id=int(row["id"]),
        nome=str(row["nome"]),
        percentual_cdi=float(row["percentual_cdi"]),
        meses_primeira=int(row["meses_primeira"]),
        meses_segunda=int(row["meses_segunda"]),
        perc_primeira=float(row["perc_primeira"] or 50),
        id_carteira=int(row["id_carteira"]) if row.get("id_carteira") else None,
    )


def carregar_fatorador(hoje: date) -> FatorCDI:
    """CDI para o fatorador de VP das mezaninos.

    Estratégia: lê o SQLite do Alpha (paridade histórica) e completa datas
    mais novas com o cdi_cache.json atualizado pelo job diário (BCB SGS-12).
    Assim o fatorador nunca fica congelado na última carga do Alpha.
    """
    from passivo_cadastro import _sqlite_path

    mapa: dict[date, float] = {}

    # 1. SQLite do Alpha (fonte primária, pode estar desatualizado)
    path = _sqlite_path()
    if path and path.exists():
        import sqlite3

        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("SELECT data, taxa FROM cdi ORDER BY data").fetchall()
        except sqlite3.Error:
            rows = []
        finally:
            conn.close()
        for r in rows:
            try:
                mapa[date.fromisoformat(str(r["data"])[:10])] = float(r["taxa"])
            except (ValueError, TypeError):
                pass

    # 2. Completa / estende com o cache BCB (cdi_cache.json) — cobre datas novas
    max_sqlite = max(mapa) if mapa else date(2000, 1, 1)
    inicio_bcb = date(2021, 1, 1)
    bcb = mapa_cdi(inicio_bcb, hoje + timedelta(days=5), atualizar=False)
    if not bcb:
        bcb = mapa_cdi(inicio_bcb, hoje + timedelta(days=5), atualizar=True)
    for d, taxa in bcb.items():
        if d > max_sqlite:   # só sobrescreve onde o SQLite não tem dados
            mapa[d] = taxa

    if mapa:
        return FatorCDI(mapa)

    # Fallback: só BCB
    return FatorCDI(bcb)


def montar_todas_posicoes(
    classes: list[dict[str, Any]],
    cotistas: list[dict[str, Any]],
    chamadas: list[dict[str, Any]],
    hoje: date | None = None,
) -> tuple[date, list[PosicaoChamada]]:
    # Paridade Alpha: data_valoracao = hoje (não capar no último CDI).
    hoje = hoje or date.today()
    fatorador = carregar_fatorador(hoje)

    mapa_cls = {int(r["id"]): _classe_from_row(r) for r in classes}
    mapa_cot = {int(r["id"]): r for r in cotistas}
    ancoras = ancoras_por_chamada(chamadas)
    posicoes: list[PosicaoChamada] = []
    for ch in chamadas:
        classe = mapa_cls.get(int(ch["classe_id"]))
        cotista = mapa_cot.get(int(ch["cotista_id"]))
        if not classe or not cotista:
            continue
        data_base = ancoras[(int(ch["classe_id"]), int(ch["numero"]))]
        posicoes.append(
            montar_posicao(ch, classe, cotista, fatorador, hoje, data_base)
        )
    return hoje, posicoes


def posicao_to_dict(p: PosicaoChamada) -> dict[str, Any]:
    d = asdict(p)
    d["classe"] = asdict(p.classe)
    d["data_prazo"] = p.data_prazo.isoformat()
    d["data_aporte"] = p.data_aporte.isoformat()
    d["data_base"] = p.data_base.isoformat()
    for parc in d["parcelas"]:
        parc["data_vencimento"] = (
            parc["data_vencimento"].isoformat()
            if hasattr(parc["data_vencimento"], "isoformat")
            else parc["data_vencimento"]
        )
    return d
