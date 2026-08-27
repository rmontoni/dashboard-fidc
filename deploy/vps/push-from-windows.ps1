# Deploy rápido para a VPS Hostinger (rodar no PowerShell LOCAL).
# Pré-requisito: SSH sem senha (chave no hPanel) OU digitar a senha quando pedir.
#
# 1) Sobe código + unit files
# 2) Copia .env
# 3) Copia caches essenciais de backend/data (sem relatórios enormes opcional)
# 4) Roda setup.sh na VPS

$ErrorActionPreference = "Stop"
$VPS = "root@76.13.233.251"
$ROOT = Split-Path $PSScriptRoot -Parent | Split-Path -Parent
if (-not (Test-Path "$ROOT\backend\main.py")) {
  $ROOT = "C:\Users\raulm\OneDrive\Documentos\Projetos\dashboard-fidc"
}
Set-Location $ROOT
Write-Host "ROOT=$ROOT"
Write-Host "==> Sync código (git pull na VPS após push, ou rsync deste PC)"
# Envia só deploy/ + backend essentials via scp se o repo na VPS ainda não existir
ssh $VPS "mkdir -p /opt/dashboard-fidc"

# Preferível: na VPS clonar do GitHub. Aqui garantimos os manifests de deploy.
scp -r deploy/vps ${VPS}:/tmp/fidc-vps-deploy

Write-Host "==> .env"
if (Test-Path "backend\.env") {
  scp backend\.env ${VPS}:/tmp/fidc.env
} else {
  Write-Warning "backend\.env não encontrado"
}

Write-Host "==> Rodar setup na VPS"
ssh $VPS @'
set -e
mkdir -p /opt/dashboard-fidc/deploy
cp -a /tmp/fidc-vps-deploy /opt/dashboard-fidc/deploy/vps
if [ ! -d /opt/dashboard-fidc/.git ]; then
  git clone https://github.com/rmontoni/dashboard-fidc.git /opt/dashboard-fidc
fi
cp -a /opt/dashboard-fidc/deploy/vps /opt/dashboard-fidc/deploy/ 2>/dev/null || true
if [ -f /tmp/fidc.env ]; then
  mkdir -p /opt/dashboard-fidc/backend
  cp /tmp/fidc.env /opt/dashboard-fidc/backend/.env
  # CORS Vercel
  grep -q CORS_ORIGINS /opt/dashboard-fidc/backend/.env || echo "CORS_ORIGINS=https://dashboard-fidc.vercel.app" >> /opt/dashboard-fidc/backend/.env
fi
bash /opt/dashboard-fidc/deploy/vps/setup.sh
'@

Write-Host "==> Health"
ssh $VPS "curl -fsS http://127.0.0.1/health; echo; curl -fsS http://127.0.0.1:8003/health; echo"
