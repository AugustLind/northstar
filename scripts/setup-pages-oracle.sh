#!/usr/bin/env bash
# One-time Oracle setup for a Pages frontend. No credentials go into Pages files.
set -euo pipefail
task_domain="${1:-}"
task_github_user="${2:-}"
task_domain="${task_domain,,}"
task_github_user="${task_github_user,,}"
if [[ ! "$task_domain" =~ ^[a-zA-Z0-9]([a-zA-Z0-9.-]*[a-zA-Z0-9])?\.[a-zA-Z]{2,63}$ || ! "$task_github_user" =~ ^[a-zA-Z0-9][a-zA-Z0-9-]{0,38}$ ]]; then
  echo 'Usage: bash scripts/setup-pages-oracle.sh api.example.com YOUR_GITHUB_USERNAME' >&2
  exit 1
fi
sudo -n true
cd "$(dirname -- "${BASH_SOURCE[0]}")/.."
python3 -c 'import app; assert callable(app.api_authorized), "Upload the latest app.py first"'
sudo apt-get update
sudo apt-get install -y nginx certbot
sudo mkdir -p /var/www/northstar-acme
if [[ -f /etc/nginx/sites-available/northstar ]]; then
  sudo cp -p /etc/nginx/sites-available/northstar "/etc/nginx/northstar-backup-$(date +%s).conf"
fi
task_config="$(mktemp)"
task_env="$(mktemp)"
trap 'rm -f "$task_config" "$task_env"' EXIT
cat > "$task_config" <<NGINX
server {
    listen 80;
    server_name $task_domain;
    location /.well-known/acme-challenge/ { root /var/www/northstar-acme; }
    location / { return 404; }
}
NGINX
sudo install -m 644 "$task_config" /etc/nginx/sites-available/northstar
sudo ln -sf /etc/nginx/sites-available/northstar /etc/nginx/sites-enabled/northstar
sudo nginx -t
sudo systemctl enable --now nginx
sudo systemctl reload nginx
sudo certbot certonly --webroot -w /var/www/northstar-acme -d "$task_domain" --non-interactive --agree-tos --register-unsafely-without-email --keep-until-expiring
python3 - "$task_domain" "$task_github_user" > "$task_env" <<'PY'
import hashlib, os, re, secrets, sys
from pathlib import Path
key_path = Path.home()/'.config/northstar/access-key'
key_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
if not key_path.exists():
    fd=os.open(key_path, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
    with os.fdopen(fd,'w') as f:
        f.write(secrets.token_urlsafe(32)+'\n')
key_path.chmod(0o600)
key=key_path.read_text().strip()
if not re.fullmatch(r'[A-Za-z0-9_-]{40,100}',key):
    raise SystemExit('Existing access key is invalid')
print('NORTHSTAR_PUBLIC_ORIGIN=https://'+sys.argv[1])
print('NORTHSTAR_PAGES_ORIGIN=https://'+sys.argv[2]+'.github.io')
print('NORTHSTAR_ACCESS_KEY_HASH='+hashlib.sha256(key.encode()).hexdigest())
PY
sudo install -m 600 "$task_env" /etc/northstar.env
sudo systemctl restart northstar
cat > "$task_config" <<NGINX
server {
    listen 80;
    server_name $task_domain;
    location /.well-known/acme-challenge/ { root /var/www/northstar-acme; }
    location / { return 301 https://\$host\$request_uri; }
}
server {
    listen 443 ssl;
    server_name $task_domain;
    ssl_certificate /etc/letsencrypt/live/$task_domain/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$task_domain/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$http_host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 240s;
    }
}
NGINX
sudo install -m 644 "$task_config" /etc/nginx/sites-available/northstar
sudo nginx -t
sudo systemctl reload nginx
printf '%s\n' '#!/bin/sh' 'systemctl reload nginx' | sudo tee /etc/letsencrypt/renewal-hooks/deploy/northstar-nginx >/dev/null
sudo chmod 755 /etc/letsencrypt/renewal-hooks/deploy/northstar-nginx
sudo systemctl enable --now certbot.timer
printf '\nOracle API: https://%s\n' "$task_domain"
printf 'Your website access key is in ~/.config/northstar/access-key (paste it only into your dashboard, not GitHub or chat).\n'
