#!/usr/bin/env bash
# Optional: requires a domain pointing at this VM and inbound TCP 80/443.
set -euo pipefail
task_domain="${1:-}"
if [[ ! "$task_domain" =~ ^[a-zA-Z0-9]([a-zA-Z0-9.-]*[a-zA-Z0-9])?\.[a-zA-Z]{2,63}$ ]]; then
  echo 'Usage: bash scripts/enable-public-https.sh northstar.example.com' >&2
  exit 1
fi
sudo -v
sudo apt-get update
sudo apt-get install -y nginx apache2-utils certbot
sudo mkdir -p /var/www/northstar-acme
task_config="$(mktemp)"
trap 'rm -f "$task_config"' EXIT
if [[ -e /etc/nginx/sites-available/northstar ]]; then
  echo 'A Northstar nginx configuration already exists; review it before replacing it.' >&2
  exit 1
fi
# Only ACME challenges are served before HTTPS is ready; the app stays private.
cat > "$task_config" <<EOF
server {
    listen 80;
    server_name $task_domain;
    location /.well-known/acme-challenge/ { root /var/www/northstar-acme; }
    location / { return 404; }
}
EOF
sudo install -m 644 "$task_config" /etc/nginx/sites-available/northstar
sudo ln -s /etc/nginx/sites-available/northstar /etc/nginx/sites-enabled/northstar
sudo nginx -t
sudo systemctl enable --now nginx
sudo systemctl reload nginx
sudo certbot certonly --webroot -w /var/www/northstar-acme -d "$task_domain" --non-interactive --agree-tos --register-unsafely-without-email
echo 'Choose a website password for username northstar (input is hidden):'
sudo htpasswd -cB /etc/nginx/northstar.htpasswd northstar
sudo chown root:www-data /etc/nginx/northstar.htpasswd
sudo chmod 640 /etc/nginx/northstar.htpasswd
cat > "$task_config" <<EOF
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
    auth_basic "Northstar";
    auth_basic_user_file /etc/nginx/northstar.htpasswd;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$http_host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_read_timeout 240s;
    }
}
EOF
sudo install -m 644 "$task_config" /etc/nginx/sites-available/northstar
sudo nginx -t
printf 'NORTHSTAR_PUBLIC_ORIGIN=https://%s\n' "$task_domain" | sudo tee /etc/northstar.env >/dev/null
sudo systemctl restart northstar
sudo systemctl reload nginx
# Renewed certificates need nginx reload to become active.
printf '%s\n' '#!/bin/sh' 'systemctl reload nginx' | sudo tee /etc/letsencrypt/renewal-hooks/deploy/northstar-nginx >/dev/null
sudo chmod 755 /etc/letsencrypt/renewal-hooks/deploy/northstar-nginx
sudo systemctl enable --now certbot.timer
printf '\nOpen https://%s/recommendations and sign in as northstar.\n' "$task_domain"
