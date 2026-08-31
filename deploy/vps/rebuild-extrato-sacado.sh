#!/usr/bin/env bash
# Reconstrói cache de extratos sacado na VPS (rodar após git pull).
set -euo pipefail
cd /opt/dashboard-fidc/backend
source .venv/bin/activate
exec python extrato_sacado_cache.py --forcar "$@"
