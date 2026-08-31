"""Matrizes de vencidos (consignado privado): estoque e VNP / vencimentos."""

from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from consignado import DOCS_CEDENTE_CONSIGNADO, TABELA
from db import get_supabase

PAGE = 1000
INDICE_PATH = Path(__file__).resolve().parent / "data" / "inadimplencia_indice.json"
INDICE_FUNDO_PATH = (
    Path(__file__).resolve().parent / "data" / "inadimplencia_indice_fundo.json"
)
INDICE_VERSAO = 2
_CADASTRO_TTL_S = 30 * 60
_CADASTRO_MEM: tuple[float, dict[str, dict[str, Any]]] | None = None
_INDICE_MEM: tuple[str, list[dict[str, Any]]] | None = None
_INDICE_FUNDO_MEM: tuple[str, list[dict[str, Any]]] | None = None
_PAYLOAD_MEM: dict[str, tuple[str, dict[str, Any]]] = {}
NOMES_CONSIG = ("BMP", "VIA CAPITAL", "CARTOS")
MESES_PT = (
    "jan",
    "fev",
    "mar",
    "abr",
    "mai",
    "jun",
    "jul",
    "ago",
    "set",
    "out",
    "nov",
    "dez",
)


def _parse_data_base(texto: str) -> date:
    t = texto.strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(t[:10] if fmt.startswith("%Y") else t, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Data base inválida: {texto}")


def _parse_iso(texto: object) -> date | None:
    s = str(texto or "").strip()[:10]
    if len(s) < 10:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def _money(v: object) -> float:
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return 0.0
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _br(d: date | None) -> str | None:
    return d.strftime("%d/%m/%Y") if d else None


def _to_date(v: object) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    ts = pd.to_datetime(v, errors="coerce")
    if pd.isna(ts):
        return _parse_iso(v)
    return ts.date()


def _ym(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _label_mes(ym: str) -> str:
    y, m = ym.split("-")
    return f"{MESES_PT[int(m) - 1]}/{y[2:]}"


def _meses_entre(inicio: date, fim: date) -> list[str]:
    y, m = inicio.year, inicio.month
    out: list[str] = []
    while (y, m) <= (fim.year, fim.month):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


def _e_consignado(meta: dict[str, Any] | None, cedente_motor: str) -> bool:
    if meta:
        return True
    nome = (cedente_motor or "").upper()
    return any(n in nome for n in NOMES_CONSIG)


def _carregar_cadastro() -> dict[str, dict[str, Any]]:
    global _CADASTRO_MEM
    agora = time.monotonic()
    if _CADASTRO_MEM is not None and agora - _CADASTRO_MEM[0] < _CADASTRO_TTL_S:
        return _CADASTRO_MEM[1]
    try:
        sb = get_supabase()
    except Exception:  # noqa: BLE001
        return {}
    out: dict[str, dict[str, Any]] = {}
    offset = 0
    docs = list(DOCS_CEDENTE_CONSIGNADO)
    cols = "documento,doc_cedente,nm_cedente"
    try:
        while True:
            batch = (
                sb.table(TABELA)
                .select(cols)
                .eq("tp_sacado", "PF")
                .in_("doc_cedente", docs)
                .range(offset, offset + PAGE - 1)
                .execute()
                .data
                or []
            )
            if not batch:
                break
            for row in batch:
                doc = str(row.get("documento") or "").strip()
                if doc:
                    out[doc] = row
            if len(batch) < PAGE:
                break
            offset += PAGE
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        if "PGRST205" in msg or "Could not find the table" in msg or TABELA in msg:
            return {}
        raise
    _CADASTRO_MEM = (agora, out)
    return out


def _assinatura_indice() -> str:
    from carteira_movimentacoes import CACHE_PATH, ESTOQUE_BASE_PATH

    parts = [f"v{INDICE_VERSAO}"]
    for path in (CACHE_PATH, ESTOQUE_BASE_PATH):
        try:
            st = path.stat()
            parts.append(f"{path.name}:{st.st_mtime_ns}:{st.st_size}")
        except OSError:
            parts.append(f"{path.name}:0")
    return "|".join(parts)


def _titulo_novo(
    chave: str,
    documento: str,
    cedente: str,
    orig: date | None,
    venc: date | None,
    face: float,
    aquisicao: float,
) -> dict[str, Any]:
    return {
        "chave": chave,
        "documento": documento,
        "cedente": cedente,
        "orig": orig.isoformat() if orig else None,
        "venc": venc.isoformat() if venc else None,
        "face_orig0": face,
        "face_rest0": face,
        "aquisicao0": aquisicao,
        "evs": [],
    }


def _compactar_titulo(t: dict[str, Any]) -> dict[str, Any]:
    orig = t.get("orig")
    venc = t.get("venc") or ""
    fo = float(t.get("face_orig0") or 0)
    fr = float(t.get("face_rest0") or 0)
    aq = float(t.get("aquisicao0") or 0)
    rest = [["", fr]]
    fos = [["", fo]]
    aqs = [["", aq]]
    vencs = [["", venc]]
    pagos: list[list[Any]] = []
    for ev in t.get("evs") or []:
        if not ev:
            continue
        data_ev = str(ev[1] or "")[:10]
        if ev[0] == "A":
            fo += float(ev[2] or 0)
            fr += float(ev[2] or 0)
            aq += float(ev[3] or 0)
            fos.append([data_ev, fo])
            rest.append([data_ev, fr])
            aqs.append([data_ev, aq])
            venc_ev = str(ev[4] or "")[:10] if len(ev) > 4 else ""
            if venc_ev:
                venc = venc_ev
                vencs.append([data_ev, venc])
            if not orig:
                orig = data_ev
            continue
        pago = float(ev[2] or 0)
        if pago > 0:
            pagos.append([data_ev, pago])
        if ev[3]:
            if fr > 0 and pago > 0:
                fr = max(0.0, fr - min(pago, fr))
        else:
            fr = 0.0
        rest.append([data_ev, fr])
    return {
        "chave": t.get("chave"),
        "documento": t.get("documento"),
        "cedente": t.get("cedente") or "",
        "orig": orig,
        "rest": rest,
        "fo": fos,
        "aq": aqs,
        "vencs": vencs,
        "pagos": pagos,
    }


def _ultimo_curva(curva: list, limite: str):
    val = curva[0][1] if curva else None
    for data_ev, item in curva:
        if data_ev and data_ev > limite:
            break
        val = item
    return val


def _montar_indice(
    cadastro: dict[str, dict[str, Any]],
    *,
    consignado_only: bool = True,
) -> list[dict[str, Any]]:
    """Histórico compacto (base + eventos). Consignado ou fundo inteiro."""
    from carteira_movimentacoes import (
        DATA_MINIMA,
        _carregar_eventos,
        _parse_data_campo,
        carregar_estoque_base,
    )

    base = carregar_estoque_base()
    cohort: dict[str, dict[str, Any]] = {}
    for chave, pos in base.items():
        doc = str(pos.get("documento") or chave)
        cedente = str(pos.get("cedente") or "")
        if consignado_only and not _e_consignado(cadastro.get(doc), cedente):
            continue
        orig = _parse_data_campo(pos.get("data_aquisicao")) or _parse_data_campo(
            pos.get("data_emissao")
        )
        venc = _parse_data_campo(pos.get("data_vencimento"))
        face = float(pos.get("valor_face") or 0)
        cohort[chave] = _titulo_novo(
            chave, doc, cedente, orig, venc, face, float(pos.get("valor_descontado") or 0)
        )

    eventos = _carregar_eventos(desde=DATA_MINIMA, ate=None)
    for ev in eventos:
        chave = str(ev.get("chave") or "")
        if not chave:
            continue
        data_ev = str(ev.get("data") or "")[:10]
        if ev.get("tipo") == "aquisicao":
            doc = str(ev.get("documento") or chave)
            cedente = str(ev.get("cedente") or "")
            if chave not in cohort:
                if consignado_only and not _e_consignado(cadastro.get(doc), cedente):
                    continue
                cohort[chave] = _titulo_novo(chave, doc, cedente, None, None, 0.0, 0.0)
            c = cohort[chave]
            venc = _parse_data_campo(ev.get("data_vencimento"))
            c["evs"].append(
                [
                    "A",
                    data_ev,
                    float(ev.get("valor_face") or 0),
                    float(ev.get("valor_descontado") or 0),
                    venc.isoformat() if venc else "",
                ]
            )
            if cedente:
                c["cedente"] = cedente
            continue
        c = cohort.get(chave)
        if c is None:
            continue
        c["evs"].append(
            [
                "L",
                data_ev,
                float(ev.get("valor_pago") or 0),
                1 if ev.get("parcial") else 0,
            ]
        )
    return [_compactar_titulo(t) for t in cohort.values()]


def _carregar_indice_arquivo(
    path: Path,
    mem: tuple[str, list[dict[str, Any]]] | None,
    *,
    consignado_only: bool,
    cadastro: dict[str, dict[str, Any]] | None = None,
) -> tuple[tuple[str, list[dict[str, Any]]] | None, list[dict[str, Any]]]:
    sig = _assinatura_indice()
    if mem is not None and mem[0] == sig:
        return mem, mem[1]
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if raw.get("assinatura") == sig and isinstance(raw.get("titulos"), list):
                titulos = raw["titulos"]
                return (sig, titulos), titulos
        except (OSError, json.JSONDecodeError, TypeError):
            pass
    if cadastro is None:
        cadastro = _carregar_cadastro() if consignado_only else {}
    titulos = _montar_indice(cadastro, consignado_only=consignado_only)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"assinatura": sig, "titulos": titulos},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
    except OSError:
        pass
    return (sig, titulos), titulos


def _carregar_indice(cadastro: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    global _INDICE_MEM, _PAYLOAD_MEM
    _INDICE_MEM, titulos = _carregar_indice_arquivo(
        INDICE_PATH,
        _INDICE_MEM,
        consignado_only=True,
        cadastro=cadastro,
    )
    _PAYLOAD_MEM.clear()
    return titulos


def _carregar_indice_fundo() -> list[dict[str, Any]]:
    global _INDICE_FUNDO_MEM
    _INDICE_FUNDO_MEM, titulos = _carregar_indice_arquivo(
        INDICE_FUNDO_PATH,
        _INDICE_FUNDO_MEM,
        consignado_only=False,
    )
    return titulos


def _titulo_asof(t: dict[str, Any], dt: date, limite: str) -> dict[str, Any] | None:
    orig_s = t.get("orig")
    if orig_s and str(orig_s) > limite:
        return None
    orig = date.fromisoformat(str(orig_s)[:10]) if orig_s and len(str(orig_s)) >= 10 else None
    if orig is None:
        return None
    venc_s = _ultimo_curva(t.get("vencs") or [["", t.get("venc") or ""]], limite) or ""
    venc = date.fromisoformat(str(venc_s)[:10]) if venc_s and len(str(venc_s)) >= 10 else None
    mes_lim = limite[:7]
    pagos: dict[str, float] = {}
    for par in t.get("pagos") or []:
        data_pg = str(par[0] or "")[:10]
        if data_pg > limite:
            break
        mes = data_pg[:7]
        if len(mes) == 7 and mes <= mes_lim:
            pagos[mes] = pagos.get(mes, 0.0) + float(par[1] or 0)
    return {
        "chave": t.get("chave"),
        "documento": t.get("documento"),
        "cedente": t.get("cedente") or "",
        "orig": orig,
        "venc": venc,
        "face_orig": float(_ultimo_curva(t.get("fo") or [["", t.get("face_orig0") or 0]], limite) or 0),
        "face_rest": float(_ultimo_curva(t.get("rest") or [["", t.get("face_rest0") or 0]], limite) or 0),
        "aquisicao": float(_ultimo_curva(t.get("aq") or [["", t.get("aquisicao0") or 0]], limite) or 0),
        "pagos": pagos,
    }


def _cohort_asof(dt: date, indice: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Títulos na data base (abertos e baixados), com repactuações."""
    from carteira_movimentacoes import REPACTUACOES

    limite = dt.isoformat()
    out: list[dict[str, Any]] = []
    by_chave: dict[str, dict[str, Any]] = {}
    for t in indice:
        c = _titulo_asof(t, dt, limite)
        if c is None:
            continue
        out.append(c)
        ch = str(c.get("chave") or "")
        if ch:
            by_chave[ch] = c
    for adj in REPACTUACOES:
        desde = str(adj.get("desde") or "")
        if not desde or limite < desde:
            continue
        chave = str(adj.get("chave") or "").strip()
        pos = by_chave.get(chave)
        if pos is None:
            for c in out:
                if str(c.get("documento") or "").strip() == chave:
                    pos = c
                    break
        if pos is None:
            continue
        venc = adj.get("data_vencimento")
        if venc:
            pos["venc"] = _to_date(venc)
    return out


def _cohort_consignado(dt: date, cadastro: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Títulos consignados (abertos e baixados) na data base, a partir do índice."""
    return _cohort_asof(dt, _carregar_indice(cadastro))


def _cohort_fundo(dt: date) -> list[dict[str, Any]]:
    """Todos os títulos do fundo na data base."""
    return _cohort_asof(dt, _carregar_indice_fundo())


def _totais_vnp_vencimentos(titulos: list[dict[str, Any]], dt: date) -> dict[str, float]:
    """VNP acumulado / vencimentos totais (face vencida / face original)."""
    tot_vnp = 0.0
    tot_venc = 0.0
    for t in titulos:
        orig_d = t.get("orig")
        venc_d = t.get("venc")
        if orig_d is None:
            continue
        rest = _money(t.get("face_rest"))
        orig_face = _money(t.get("face_orig"))
        if orig_face <= 0 and rest <= 0:
            continue
        if venc_d is None:
            continue
        if venc_d < dt:
            tot_vnp += rest
            tot_venc += orig_face if orig_face > 0 else rest
    return {
        "pct": _pct(tot_vnp, tot_venc),
        "vnp": round(tot_vnp, 2),
        "vencimentos": round(tot_venc, 2),
    }


def _vazio_vnp() -> dict[str, Any]:
    return {
        "linhas": [],
        "colunas": [],
        "labels_linha": [],
        "labels_coluna": [],
        "celulas": [],
        "totais_linha": [],
        "totais_coluna": [],
        "total": {"pct": 0.0, "vnp": 0.0, "vencimentos": 0.0, "a_vencer": 0.0, "n": 0},
        "max_pct": 0.0,
    }


def _vazio_caixa() -> dict[str, Any]:
    return {
        "linhas": [],
        "colunas": [],
        "labels_linha": [],
        "labels_coluna": [],
        "celulas": [],
        "totais_linha": [],
        "totais_coluna": [],
        "total": {"aquisicao": 0.0, "pago": 0.0},
        "max_celula": 0.0,
    }


def _vazio(dt: date, aviso: str | None) -> dict[str, Any]:
    return {
        "data_base": _br(dt),
        "data_base_iso": dt.isoformat(),
        "universo": "consignado_privado",
        "cedentes": ["BMP", "VIA CAPITAL", "CARTOS"],
        "metrica": "valor_face",
        "linhas": [],
        "colunas": [],
        "labels_linha": [],
        "labels_coluna": [],
        "celulas": [],
        "totais_linha": [],
        "totais_coluna": [],
        "total": {
            "valor": 0.0,
            "n": 0,
            "face_consig": 0.0,
            "n_consig": 0,
            "pct": 0.0,
        },
        "max_celula": 0.0,
        "matriz_vnp": _vazio_vnp(),
        "matriz_caixa": _vazio_caixa(),
        "aviso": aviso,
    }


def _pct(num: float, den: float) -> float:
    return round(100.0 * num / den, 2) if den > 0 else 0.0


def _passos_mes(mes_a: str, mes_b: str) -> int:
    y1, m1 = int(mes_a[:4]), int(mes_a[5:7])
    y2, m2 = int(mes_b[:4]), int(mes_b[5:7])
    return (y2 - y1) * 12 + (m2 - m1)


def _tir_mensal(fluxos: list[float]) -> float | None:
    """TIR mensal (decimal). None se não houver mudança de sinal ou não convergir."""
    if len(fluxos) < 2:
        return None
    if not any(x < -1e-9 for x in fluxos) or not any(x > 1e-9 for x in fluxos):
        return None
    r = 0.0
    for _ in range(80):
        npv = 0.0
        dnpv = 0.0
        for t, cf in enumerate(fluxos):
            base = (1.0 + r) ** t
            if base == 0:
                return None
            npv += cf / base
            if t:
                dnpv -= t * cf / ((1.0 + r) ** (t + 1))
        if abs(dnpv) < 1e-18:
            break
        nxt = r - npv / dnpv
        if nxt <= -0.9999:
            nxt = -0.9999
        if abs(nxt - r) < 1e-10:
            r = nxt
            break
        r = nxt
    if r <= -0.999 or r > 5:
        return None
    return r


def _ultimo_dia_mes(ym: str) -> date:
    y, m = int(ym[:4]), int(ym[5:7])
    if m == 12:
        return date(y, 12, 31)
    return date(y, m + 1, 1) - timedelta(days=1)


def _cdi_am_ate(
    mapa: dict[date, float],
    ini: date,
    dt: date,
    fim: date,
    n_passos: int,
) -> float | None:
    """CDI equivalente a.m. até dt (real) e, se fim > dt, projeta o último CDI."""
    if n_passos <= 0:
        return None
    fat = _fator_cdi(mapa, ini, min(dt, fim))
    if fim > dt and mapa:
        refs = [d for d in mapa if d <= dt]
        last = mapa.get(dt) if dt in mapa else (mapa[max(refs)] if refs else None)
        if last is not None:
            d = dt + timedelta(days=1)
            while d <= fim:
                if d.weekday() < 5:
                    fat *= 1.0 + float(last) / 100.0
                d += timedelta(days=1)
    if fat <= 0:
        return None
    return fat ** (1.0 / n_passos) - 1.0


def _fator_cdi(mapa: dict[date, float], ini: date, fim: date) -> float:
    fat = 1.0
    d = ini
    while d <= fim:
        v = mapa.get(d)
        if v is not None:
            fat *= 1.0 + float(v) / 100.0
        d += timedelta(days=1)
    return fat


def _carregar_cdi(ini: date, fim: date) -> dict[date, float]:
    try:
        from cdi_bcb import mapa_cdi

        mapa = mapa_cdi(ini, fim, atualizar=False)
        if not mapa:
            mapa = mapa_cdi(ini, fim, atualizar=True)
        return mapa
    except Exception:  # noqa: BLE001
        return {}


def _guardar_payload(chave: str, sig: str, payload: dict[str, Any]) -> None:
    _PAYLOAD_MEM[chave] = (sig, payload)
    while len(_PAYLOAD_MEM) > 24:
        _PAYLOAD_MEM.pop(next(iter(_PAYLOAD_MEM)))


def montar_inadimplencia(data_base: str) -> dict[str, Any]:
    """Estoque vencido e VNP/vencimentos do consignado privado."""
    dt = _parse_data_base(data_base)
    sig = _assinatura_indice()
    chave_dt = f"{dt.isoformat()}:vnp-aq1"
    hit = _PAYLOAD_MEM.get(chave_dt)
    if hit and hit[0] == sig:
        return hit[1]
    aviso: str | None = None

    titulos = _cohort_consignado(dt)
    if not titulos:
        vazio = _vazio(dt, aviso or "Sem títulos de consignado privado nesta data.")
        _guardar_payload(chave_dt, sig, vazio)
        return vazio

    face_consig = 0.0
    n_consig = 0
    buckets_est: dict[tuple[str, str], list[float]] = {}
    buckets_vnp: dict[tuple[str, str], list[float]] = {}
    a_vencer_por: dict[str, float] = {}
    aquisicao_por: dict[str, float] = {}
    pago_por: dict[tuple[str, str], float] = {}
    face_avencer_por: dict[tuple[str, str], float] = {}
    origens: set[str] = set()
    meses_col: set[str] = set()
    total_venc_est = 0.0
    n_venc_est = 0

    for t in titulos:
        orig_d = t.get("orig")
        venc_d = t.get("venc")
        if orig_d is None:
            continue
        mes_orig = _ym(orig_d)
        origens.add(mes_orig)
        rest = _money(t.get("face_rest"))
        orig_face = _money(t.get("face_orig"))
        aquisicao_por[mes_orig] = aquisicao_por.get(mes_orig, 0.0) + _money(
            t.get("aquisicao")
        )
        for mes_liq, pago in (t.get("pagos") or {}).items():
            if not mes_liq:
                continue
            chave_p = (mes_orig, str(mes_liq)[:7])
            pago_por[chave_p] = pago_por.get(chave_p, 0.0) + _money(pago)
        if orig_face <= 0 and rest <= 0:
            continue
        n_consig += 1
        face_consig += rest

        if venc_d is None:
            a_vencer_por[mes_orig] = a_vencer_por.get(mes_orig, 0.0) + rest
            continue

        mes_venc = _ym(venc_d)
        vencido = venc_d < dt
        if vencido:
            meses_col.add(mes_venc)
            kest = (mes_orig, mes_venc)
            if kest not in buckets_est and rest > 0:
                buckets_est[kest] = [0.0, 0.0]
            if rest > 0:
                buckets_est[kest][0] += rest
                buckets_est[kest][1] += 1
                total_venc_est += rest
                n_venc_est += 1
            kv = (mes_orig, mes_venc)
            if kv not in buckets_vnp:
                buckets_vnp[kv] = [0.0, 0.0, 0.0]
            buckets_vnp[kv][0] += rest
            buckets_vnp[kv][1] += orig_face if orig_face > 0 else rest
            buckets_vnp[kv][2] += 1
        else:
            a_vencer_por[mes_orig] = a_vencer_por.get(mes_orig, 0.0) + rest
            if rest > 0:
                chave_av = (mes_orig, mes_venc)
                face_avencer_por[chave_av] = face_avencer_por.get(chave_av, 0.0) + rest

    if not origens:
        return _vazio(dt, aviso or "Sem títulos de consignado privado nesta data.")

    linhas = sorted(origens)
    if meses_col:
        vmin = min(date(int(m[:4]), int(m[5:7]), 1) for m in meses_col)
        colunas = _meses_entre(vmin, date(dt.year, dt.month, 1))
    else:
        colunas = _meses_entre(
            date(int(linhas[0][:4]), int(linhas[0][5:7]), 1),
            date(dt.year, dt.month, 1),
        )

    max_cel = 0.0
    grade: list[list[dict[str, Any]]] = []
    totais_linha: list[dict[str, Any]] = []
    totais_col_acc = {c: [0.0, 0] for c in colunas}

    for mes_orig in linhas:
        row_cells: list[dict[str, Any]] = []
        soma_l = 0.0
        n_l = 0
        for mes_venc in colunas:
            valor, n = buckets_est.get((mes_orig, mes_venc), [0.0, 0.0])
            valor_r = round(float(valor), 2)
            n_i = int(n)
            row_cells.append({"valor": valor_r, "n": n_i})
            soma_l += valor_r
            n_l += n_i
            totais_col_acc[mes_venc][0] += valor_r
            totais_col_acc[mes_venc][1] += n_i
            if valor_r > max_cel:
                max_cel = valor_r
        grade.append(row_cells)
        totais_linha.append(
            {
                "mes": mes_orig,
                "valor": round(soma_l, 2),
                "n": n_l,
                "aquisicao": round(float(aquisicao_por.get(mes_orig, 0.0)), 2),
            }
        )

    totais_coluna = [
        {
            "mes": c,
            "valor": round(totais_col_acc[c][0], 2),
            "n": int(totais_col_acc[c][1]),
        }
        for c in colunas
    ]

    max_pct = 0.0
    grade_vnp: list[list[dict[str, Any]]] = []
    totais_vnp_l: list[dict[str, Any]] = []
    acc_col = {c: [0.0, 0.0] for c in colunas}
    tot_vnp = 0.0
    tot_venc = 0.0
    tot_av = 0.0

    for mes_orig in linhas:
        row_cells: list[dict[str, Any]] = []
        soma_vnp = 0.0
        soma_venc = 0.0
        for mes_venc in colunas:
            vnp, vencim, n = buckets_vnp.get((mes_orig, mes_venc), [0.0, 0.0, 0.0])
            vnp_r = round(float(vnp), 2)
            venc_r = round(float(vencim), 2)
            pct = _pct(vnp_r, venc_r)
            row_cells.append(
                {
                    "pct": pct,
                    "vnp": vnp_r,
                    "vencimentos": venc_r,
                    "n": int(n),
                }
            )
            soma_vnp += vnp_r
            soma_venc += venc_r
            acc_col[mes_venc][0] += vnp_r
            acc_col[mes_venc][1] += venc_r
            if venc_r > 0 and pct > max_pct:
                max_pct = pct
        av = round(float(a_vencer_por.get(mes_orig, 0.0)), 2)
        tot_vnp += soma_vnp
        tot_venc += soma_venc
        tot_av += av
        grade_vnp.append(row_cells)
        totais_vnp_l.append(
            {
                "mes": mes_orig,
                "pct": _pct(soma_vnp, soma_venc),
                "vnp": round(soma_vnp, 2),
                "vencimentos": round(soma_venc, 2),
                "a_vencer": av,
                "aquisicao": round(float(aquisicao_por.get(mes_orig, 0.0)), 2),
            }
        )

    totais_vnp_c = [
        {
            "mes": c,
            "pct": _pct(acc_col[c][0], acc_col[c][1]),
            "vnp": round(acc_col[c][0], 2),
            "vencimentos": round(acc_col[c][1], 2),
        }
        for c in colunas
    ]

    colunas_cx = _meses_entre(
        date(int(linhas[0][:4]), int(linhas[0][5:7]), 1),
        date(dt.year, dt.month, 1),
    )
    ini_cdi = date(int(linhas[0][:4]), int(linhas[0][5:7]), 1)
    cdi_mapa = _carregar_cdi(ini_cdi, dt)
    mes_atual = _ym(dt)
    vnp_por = {t["mes"]: float(t.get("pct") or 0) for t in totais_vnp_l}

    max_cx = 0.0
    grade_cx: list[list[dict[str, Any]]] = []
    totais_cx_l: list[dict[str, Any]] = []
    acc_cx = {c: 0.0 for c in colunas_cx}
    tot_aq = 0.0
    tot_pg = 0.0

    for mes_orig in linhas:
        row_cells: list[dict[str, Any]] = []
        soma_pg = 0.0
        fluxos: list[float] = []
        aq = round(float(aquisicao_por.get(mes_orig, 0.0)), 2)
        meses_fluxo = _meses_entre(
            date(int(mes_orig[:4]), int(mes_orig[5:7]), 1),
            date(dt.year, dt.month, 1),
        )
        for i_m, mes_pg in enumerate(meses_fluxo):
            pago = round(float(pago_por.get((mes_orig, mes_pg), 0.0)), 2)
            cf = pago - aq if i_m == 0 else pago
            fluxos.append(cf)
        for mes_pg in colunas_cx:
            pago = round(float(pago_por.get((mes_orig, mes_pg), 0.0)), 2)
            row_cells.append({"valor": pago})
            soma_pg += pago
            acc_cx[mes_pg] += pago
            if pago > max_cx:
                max_cx = pago
        tir = _tir_mensal(fluxos)
        n_passos = _passos_mes(mes_orig, mes_atual)
        pct_cdi: float | None = None
        cdi_am: float | None = None
        if n_passos > 0:
            ini_v = date(int(mes_orig[:4]), int(mes_orig[5:7]), 1)
            fat = _fator_cdi(cdi_mapa, ini_v, dt)
            if fat > 0:
                cdi_am = fat ** (1.0 / n_passos) - 1.0
        if tir is not None and cdi_am is not None and abs(cdi_am) > 1e-12:
            pct_cdi = round(100.0 * tir / cdi_am, 2)

        vnp_pct = float(vnp_por.get(mes_orig, 0.0))
        fator_rec = max(0.0, 1.0 - vnp_pct / 100.0)
        meses_fut = sorted(
            mes_v
            for (mo, mes_v), face in face_avencer_por.items()
            if mo == mes_orig and face > 0
        )
        ultimo_esp = max([mes_atual, *meses_fut]) if meses_fut else mes_atual
        meses_esp = _meses_entre(
            date(int(mes_orig[:4]), int(mes_orig[5:7]), 1),
            date(int(ultimo_esp[:4]), int(ultimo_esp[5:7]), 1),
        )
        fluxos_esp: list[float] = []
        face_av = 0.0
        residual = 0.0
        for i_m, mes_pg in enumerate(meses_esp):
            pago = round(float(pago_por.get((mes_orig, mes_pg), 0.0)), 2)
            face_m = round(float(face_avencer_por.get((mes_orig, mes_pg), 0.0)), 2)
            esperado = round(face_m * fator_rec, 2)
            face_av += face_m
            residual += esperado
            cf = (pago - aq if i_m == 0 else pago) + esperado
            fluxos_esp.append(cf)
        tir_esp = _tir_mensal(fluxos_esp)
        n_esp = _passos_mes(mes_orig, ultimo_esp)
        ini_v = date(int(mes_orig[:4]), int(mes_orig[5:7]), 1)
        cdi_am_esp = _cdi_am_ate(
            cdi_mapa, ini_v, dt, _ultimo_dia_mes(ultimo_esp), n_esp
        )
        pct_cdi_esp: float | None = None
        if tir_esp is not None and cdi_am_esp is not None and abs(cdi_am_esp) > 1e-12:
            pct_cdi_esp = round(100.0 * tir_esp / cdi_am_esp, 2)

        tot_aq += aq
        tot_pg += soma_pg
        grade_cx.append(row_cells)
        totais_cx_l.append(
            {
                "mes": mes_orig,
                "aquisicao": aq,
                "pago": round(soma_pg, 2),
                "tir_am": round(100.0 * tir, 4) if tir is not None else None,
                "pct_cdi": pct_cdi,
                "tir_esp_am": round(100.0 * tir_esp, 4) if tir_esp is not None else None,
                "pct_cdi_esp": pct_cdi_esp,
                "face_a_vencer": round(face_av, 2),
                "vnp_pct": round(vnp_pct, 2),
                "residual_esperado": round(residual, 2),
                "cdi_am": round(100.0 * cdi_am, 4) if cdi_am is not None else None,
                "n_meses": n_passos,
                "n_meses_esp": n_esp,
            }
        )

    totais_cx_c = [
        {"mes": c, "valor": round(acc_cx[c], 2)} for c in colunas_cx
    ]

    payload = {
        "data_base": _br(dt),
        "data_base_iso": dt.isoformat(),
        "universo": "consignado_privado",
        "cedentes": ["BMP", "VIA CAPITAL", "CARTOS"],
        "metrica": "valor_face",
        "linhas": linhas,
        "colunas": colunas,
        "labels_linha": [_label_mes(m) for m in linhas],
        "labels_coluna": [_label_mes(m) for m in colunas],
        "celulas": grade,
        "totais_linha": totais_linha,
        "totais_coluna": totais_coluna,
        "total": {
            "valor": round(total_venc_est, 2),
            "n": n_venc_est,
            "face_consig": round(face_consig, 2),
            "n_consig": n_consig,
            "pct": round(100.0 * total_venc_est / face_consig, 2) if face_consig else 0.0,
        },
        "max_celula": round(max_cel, 2),
        "matriz_vnp": {
            "linhas": linhas,
            "colunas": colunas,
            "labels_linha": [_label_mes(m) for m in linhas],
            "labels_coluna": [_label_mes(m) for m in colunas],
            "celulas": grade_vnp,
            "totais_linha": totais_vnp_l,
            "totais_coluna": totais_vnp_c,
            "total": {
                "pct": _pct(tot_vnp, tot_venc),
                "vnp": round(tot_vnp, 2),
                "vencimentos": round(tot_venc, 2),
                "a_vencer": round(tot_av, 2),
                "aquisicao": round(sum(float(aquisicao_por.get(m, 0.0)) for m in linhas), 2),
                "n": n_consig,
            },
            "max_pct": round(max_pct, 2),
        },
        "matriz_caixa": {
            "linhas": linhas,
            "colunas": colunas_cx,
            "labels_linha": [_label_mes(m) for m in linhas],
            "labels_coluna": [_label_mes(m) for m in colunas_cx],
            "celulas": grade_cx,
            "totais_linha": totais_cx_l,
            "totais_coluna": totais_cx_c,
            "total": {
                "aquisicao": round(tot_aq, 2),
                "pago": round(tot_pg, 2),
            },
            "max_celula": round(max_cx, 2),
        },
        "aviso": aviso,
    }
    _guardar_payload(chave_dt, sig, payload)
    return payload


def pct_vnp_vencimentos_total(data_base: str) -> dict[str, float]:
    """KPI do dashboard: VNP / vencimentos totais (fundo inteiro)."""
    dt = _parse_data_base(data_base)
    return _totais_vnp_vencimentos(_cohort_fundo(dt), dt)


def montar_fluxo_caixa(data_base: str) -> dict[str, Any]:
    """Matriz de aquisição × liquidações (consignado privado) com TIR e %CDI."""
    full = montar_inadimplencia(data_base)
    return {
        "data_base": full.get("data_base"),
        "data_base_iso": full.get("data_base_iso"),
        "universo": full.get("universo"),
        "cedentes": full.get("cedentes"),
        "matriz_caixa": full.get("matriz_caixa") or _vazio_caixa(),
        "aviso": full.get("aviso"),
    }
