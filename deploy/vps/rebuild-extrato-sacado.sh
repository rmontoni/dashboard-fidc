#!/usr/bin/env bash
# Pré-calcula extratos dos sacados com maior VP (opcional; padrão top 50).
# O cache normal é sob demanda — gravado ao abrir um sacado na API.
set -euo pipefail
cd /opt/dashboard-fidc/backend
source .venv/bin/activate
exec python extrato_sacado_cache.py --limite "${1:-50}" "${@:2}"
