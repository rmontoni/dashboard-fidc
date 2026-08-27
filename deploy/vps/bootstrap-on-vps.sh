#!/usr/bin/env bash
# Cole na sessão SSH já aberta (root@srv1341649) e rode: bash /tmp/fidc-bootstrap.sh
set -euo pipefail
APP=/opt/dashboard-fidc
REPO=https://github.com/rmontoni/dashboard-fidc.git

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y python3 python3-venv python3-pip nginx git curl ufw

if [[ ! -d "$APP/.git" ]]; then
  # preserva data/ se já existir
  if [[ -d "$APP/backend/data" && ! -d /tmp/fidc-data-bak ]]; then
    mv "$APP/backend/data" /tmp/fidc-data-bak
  fi
  rm -rf "$APP"
  git clone "$REPO" "$APP"
  if [[ -d /tmp/fidc-data-bak ]]; then
    mkdir -p "$APP/backend"
    rm -rf "$APP/backend/data"
    mv /tmp/fidc-data-bak "$APP/backend/data"
  fi
else
  git -C "$APP" fetch origin
  git -C "$APP" checkout main
  git -C "$APP" pull --ff-only origin main || true
fi

# Manifests de deploy (se ainda não estiverem no main, cria na hora)
mkdir -p "$APP/deploy/vps"
cat > /etc/systemd/system/fidc-api.service <<'EOF'
[Unit]
Description=Dashboard FIDC API (FastAPI/uvicorn)
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/dashboard-fidc/backend
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=-/opt/dashboard-fidc/backend/.env
ExecStart=/opt/dashboard-fidc/backend/.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8003
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/nginx/sites-available/fidc <<'EOF'
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;
    client_max_body_size 50m;

    location /health {
        proxy_pass http://127.0.0.1:8003/health;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /fidc/ {
        proxy_pass http://127.0.0.1:8003/fidc/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
    }

    location / {
        return 200 'fidc-api ok — use /health ou /fidc/*';
        add_header Content-Type text/plain;
    }
}
EOF
ln -sfn /etc/nginx/sites-available/fidc /etc/nginx/sites-enabled/fidc
rm -f /etc/nginx/sites-enabled/default

cd "$APP/backend"
python3 -m venv .venv
. .venv/bin/activate
pip install -U pip
pip install -r requirements.txt

if [[ ! -f .env ]]; then
  echo "ERRO: falta $APP/backend/.env — copie do PC (scp) e rode: systemctl restart fidc-api"
  exit 2
fi

# Garante CORS do Vercel
if ! grep -q 'CORS_ORIGINS' .env; then
  echo 'CORS_ORIGINS=https://dashboard-fidc.vercel.app' >> .env
elif ! grep -q 'dashboard-fidc.vercel.app' .env; then
  sed -i 's|^CORS_ORIGINS=.*|CORS_ORIGINS=https://dashboard-fidc.vercel.app|' .env || \
    echo 'CORS_ORIGINS=https://dashboard-fidc.vercel.app' >> .env
fi

ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable || true

systemctl daemon-reload
systemctl enable fidc-api nginx
systemctl restart fidc-api
systemctl reload nginx

sleep 2
curl -fsS http://127.0.0.1:8003/health; echo
curl -fsS http://127.0.0.1/health; echo
echo "OK — teste externo: http://76.13.233.251/health"
