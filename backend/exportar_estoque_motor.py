"""Exporta estoque do motor (CSV) para confrontar com EstoqueBDR."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from carteira_movimentacoes import (
    DATA_MINIMA,
    RELATORIOS_DIR,
    _aplicar_eventos_ate,
    _carregar_eventos,
    anexar_prazo_atual_do_dia,
    carregar_estoque_base,
)
from marcacao_carteira import atualizar_marcacao

load_dotenv()


def _parse(texto: str):
    t = texto.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(t[:10], fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Data inválida: {texto}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    d = _parse(args.data)

    print(f"Montando carteira motor {d.isoformat()}…", flush=True)
    base = carregar_estoque_base()
    ev = _carregar_eventos(desde=DATA_MINIMA, ate=d)
    print(f"eventos={len(ev)}", flush=True)
    ab = _aplicar_eventos_ate(ev, d, base=base)
    anexar_prazo_atual_do_dia(ab, d)
    if d != DATA_MINIMA:
        ab = atualizar_marcacao(ab, data_ref=DATA_MINIMA, data_alvo=d)

    campos = [
        "documento",
        "cedente",
        "sacado",
        "doc_sacado",
        "tipo_recebivel",
        "data_emissao",
        "data_aquisicao",
        "data_vencimento",
        "valor_face",
        "valor_descontado",
        "taxa_operacao",
        "prazo",
        "prazo_atual",
        "vl_presente_adm",
        "vl_pdd",
        "fx_pdd",
    ]
    destino = Path(args.out) if args.out else (
        RELATORIOS_DIR / f"EstoqueMotor_{d.isoformat()}.csv"
    )
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=campos, delimiter=";", extrasaction="ignore")
        w.writeheader()
        for pos in ab.values():
            row = {c: pos.get(c) for c in campos}
            # BR decimal
            for k in (
                "valor_face",
                "valor_descontado",
                "taxa_operacao",
                "vl_presente_adm",
                "vl_pdd",
            ):
                v = row.get(k)
                if v is None or v == "":
                    continue
                try:
                    row[k] = f"{float(v):.2f}".replace(".", ",")
                except (TypeError, ValueError):
                    pass
            w.writerow(row)

    vp = sum(float(p.get("vl_presente_adm") or 0) for p in ab.values())
    pdd = sum(float(p.get("vl_pdd") or 0) for p in ab.values())
    print(
        f"saved={destino} titulos={len(ab)} vp={vp:,.2f} pdd={pdd:,.2f}",
        flush=True,
    )


if __name__ == "__main__":
    main()
