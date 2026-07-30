"""Calendário de dias úteis (feriados oficiais Bacen/ANBIMA).

A marcação desconta VP em dias úteis. Em feriado não há acúmulo de juros e o
dashboard não disponibiliza relatório.

Fonte primária: data/feriados_oficiais.json (exportada de Feriados.xlsx).
Fallback: feriados nacionais fixos + móveis da Páscoa (sem municipais).
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

FERIADOS_PATH = Path(__file__).resolve().parent / "data" / "feriados_oficiais.json"

# Consciência Negra (20/11) é feriado nacional a partir de 2024 (Lei 14.759/2023).
# Só entra no fallback se a lista oficial não cobrir o ano.
_ANO_CONSCIENCIA_NEGRA = 2024

_FIXOS = (
    (1, 1),   # Confraternização Universal
    (4, 21),  # Tiradentes
    (5, 1),   # Dia do Trabalho
    (9, 7),   # Independência
    (10, 12), # Nossa Senhora Aparecida
    (11, 2),  # Finados
    (11, 15), # Proclamação da República
    (12, 25), # Natal
)


def _pascoa(ano: int) -> date:
    """Domingo de Páscoa (algoritmo de Meeus/Jones/Butcher)."""
    a = ano % 19
    b, c = divmod(ano, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    lo = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * lo) // 451
    mes, dia = divmod(h + lo - 7 * m + 114, 31)
    return date(ano, mes, dia + 1)


def _feriados_algoritmicos(ano: int) -> frozenset[date]:
    dias = {date(ano, mes, dia) for mes, dia in _FIXOS}
    if ano >= _ANO_CONSCIENCIA_NEGRA:
        dias.add(date(ano, 11, 20))
    pascoa = _pascoa(ano)
    dias.add(pascoa - timedelta(days=48))  # Carnaval (segunda)
    dias.add(pascoa - timedelta(days=47))  # Carnaval (terça)
    dias.add(pascoa - timedelta(days=2))   # Sexta-feira Santa
    dias.add(pascoa + timedelta(days=60))  # Corpus Christi
    return frozenset(dias)


@lru_cache(maxsize=1)
def _carregar_feriados_oficiais(
    mtime_ns: int | None = None,
) -> dict[date, str]:
    """Mapa data → nome do feriado a partir do JSON oficial."""
    del mtime_ns  # só invalida o cache quando o mtime muda
    if not FERIADOS_PATH.exists():
        return {}
    try:
        raw = json.loads(FERIADOS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    out: dict[date, str] = {}
    for item in raw.get("feriados") or []:
        if not isinstance(item, dict):
            continue
        texto = str(item.get("data") or "").strip()[:10]
        if len(texto) < 10:
            continue
        try:
            d = date.fromisoformat(texto)
        except ValueError:
            continue
        nome = str(item.get("nome") or "Feriado").strip() or "Feriado"
        out[d] = nome
    return out


def mapa_feriados_oficiais() -> dict[date, str]:
    mtime = None
    try:
        mtime = FERIADOS_PATH.stat().st_mtime_ns
    except OSError:
        pass
    return _carregar_feriados_oficiais(mtime)


def anos_cobertos_oficiais() -> frozenset[int]:
    return frozenset(d.year for d in mapa_feriados_oficiais())


@lru_cache(maxsize=None)
def feriados_ano(ano: int) -> frozenset[date]:
    """Feriados oficiais do ano (lista Bacen/ANBIMA quando disponível)."""
    oficiais = mapa_feriados_oficiais()
    if ano in anos_cobertos_oficiais():
        dias = {d for d in oficiais if d.year == ano}
        # Lei 14.759/2023 — planilha histórica às vezes omite 20/11.
        if ano >= _ANO_CONSCIENCIA_NEGRA:
            dias.add(date(ano, 11, 20))
        return frozenset(dias)
    return _feriados_algoritmicos(ano)


def nome_feriado(dia: date) -> str | None:
    oficiais = mapa_feriados_oficiais()
    if dia in oficiais:
        return oficiais[dia]
    if dia.month == 11 and dia.day == 20 and dia.year >= _ANO_CONSCIENCIA_NEGRA:
        return "Dia Nacional de Zumbi e da Consciência Negra"
    if dia in feriados_ano(dia.year):
        return "Feriado"
    return None


def e_feriado(dia: date) -> bool:
    return dia in feriados_ano(dia.year)


def e_dia_util(dia: date) -> bool:
    """Dia útil bancário: seg–sex e não feriado oficial."""
    return dia.weekday() < 5 and not e_feriado(dia)


@lru_cache(maxsize=None)
def _uteis_no_ano(ano: int) -> tuple[int, tuple[date, ...]]:
    """(total de dias úteis do ano, tupla ordenada desses dias)."""
    dias: list[date] = []
    d = date(ano, 1, 1)
    fim = date(ano, 12, 31)
    fer = feriados_ano(ano)
    while d <= fim:
        if d.weekday() < 5 and d not in fer:
            dias.append(d)
        d += timedelta(days=1)
    return len(dias), tuple(dias)


@lru_cache(maxsize=None)
def _indice_ano(ano: int) -> dict[date, int]:
    """Mapa dia -> nº de dias úteis do ano estritamente antes dele."""
    idx: dict[date, int] = {}
    d = date(ano, 1, 1)
    fim = date(ano, 12, 31)
    fer = feriados_ano(ano)
    n = 0
    while d <= fim:
        idx[d] = n
        if d.weekday() < 5 and d not in fer:
            n += 1
        d += timedelta(days=1)
    return idx


def dias_uteis_entre(inicio: date, fim: date) -> int:
    """Dias úteis em (inicio, fim] — exclui o dia inicial, inclui o final."""
    if fim <= inicio:
        return 0
    if inicio.year == fim.year:
        idx = _indice_ano(inicio.year)
        total = idx[fim] - idx[inicio]
    else:
        total = _uteis_no_ano(inicio.year)[0] - _indice_ano(inicio.year)[inicio]
        for ano in range(inicio.year + 1, fim.year):
            total += _uteis_no_ano(ano)[0]
        total += _indice_ano(fim.year)[fim]
    # até aqui o intervalo é [inicio, fim); desloca para (inicio, fim]
    if e_dia_util(inicio):
        total -= 1
    if e_dia_util(fim):
        total += 1
    return max(0, total)


def dias_uteis_prazo(inicio: date, fim: date) -> int:
    """
    Dias úteis do prazo, em [inicio, fim): conta a data de referência e não conta
    o vencimento. É a contagem usada na marcação — conferida contra os estoques
    de 31/05 e 03/06/2024. Vencimento já passado devolve 0.
    """
    if fim <= inicio:
        return 0
    n = dias_uteis_entre(inicio, fim)
    if e_dia_util(inicio):
        n += 1
    if e_dia_util(fim):
        n -= 1
    return max(0, n)


def dia_util_anterior(dia: date) -> date:
    d = dia - timedelta(days=1)
    while not e_dia_util(d):
        d -= timedelta(days=1)
    return d


def dia_util_seguinte(dia: date) -> date:
    d = dia + timedelta(days=1)
    while not e_dia_util(d):
        d += timedelta(days=1)
    return d
