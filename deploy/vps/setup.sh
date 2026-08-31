#!/usr/bin/env bash
# Setup Dashboard FIDC API on Hostinger VPS (Ubuntu).
# Uso (na VPS):
#   curl -fsSL ... | bash
#   ou: bash deploy/vps/setup.sh
set -euo pipefail

APP_DIR=/opt/dashboard-fidc
REPO_URL="${REPO_URL:-https://github.com/rmontoni/dashboard-fidc.git}"
BRANCH="${BRANCH:-main}"

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y python3 python3-venv python3-pip nginx git rsync curl ufw

if [[ ! -d "$APP_DIR/.git" ]]; then
  mkdir -p "$(dirname "$APP_DIR")"
  git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
else
  git -C "$APP_DIR" fetch origin
  git -C "$APP_DIR" checkout "$BRANCH"
  git -C "$APP_DIR" pull --ff-only origin "$BRANCH"
fi

cd "$APP_DIR/backend"
python3 -m venv .venv
. .venv/bin/activate
pip install -U pip
pip install -r requirements.txt

if [[ ! -f .env ]]; then
  echo "AVISO: $APP_DIR/backend/.env ausente — copie o .env local antes de iniciar o serviço."
fi

install -m 644 "$APP_DIR/deploy/vps/fidc-api.service" /etc/systemd/system/fidc-api.service
install -m 644 "$APP_DIR/deploy/vps/fidc-atualizar.service" /etc/systemd/system/fidc-atualizar.service
install -m 644 "$APP_DIR/deploy/vps/fidc-atualizar.timer" /etc/systemd/system/fidc-atualizar.timer
install -m 644 "$APP_DIR/deploy/vps/nginx-fidc.conf" /etc/nginx/sites-available/fidc
ln -sfn /etc/nginx/sites-available/fidc /etc/nginx/sites-enabled/fidc
rm -f /etc/nginx/sites-enabled/default

ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable || true

systemctl daemon-reload
systemctl enable fidc-api nginx fidc-atualizar.timer
systemctl restart fidc-api
systemctl start fidc-atualizar.timer
systemctl reload nginx

echo "Timer atualização:"
systemctl list-timers fidc-atualizar.timer --no-pager || true

curl -fsS http://127.0.0.1:8003/health || true
curl -fsS http://127.0.0.1/health || true
echo "OK — API em http://$(hostname -I | awk '{print $1}')/health"
