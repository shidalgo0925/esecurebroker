#!/usr/bin/env bash
# Tras crear DNS A esecurebroker-dev.etsrv.site → 86.48.20.243 (proxy naranja OK),
# emitir cert e instalar vhost HTTPS.
# Nota: usar un solo nivel bajo etsrv.site (NO dev.esecurebroker.etsrv.site).
set -euo pipefail

DOMAIN=esecurebroker-dev.etsrv.site
ORIGIN_HINT=86.48.20.243
REPO_CONF=/opt/corredores/deploy/esecurebroker-dev.etsrv.site.conf
NGINX_AVAIL=/etc/nginx/sites-available/${DOMAIN}.conf

echo "Checking DNS for ${DOMAIN}…"
if ! { dig +short A "${DOMAIN}" @1.1.1.1; dig +short A "${DOMAIN}" @8.8.8.8; dig +short A "${DOMAIN}"; } | grep -q .; then
  echo "ERROR: ${DOMAIN} aún no resuelve (NXDOMAIN)." >&2
  echo "Creá en Cloudflare un registro A → ${ORIGIN_HINT} (proxy naranja OK) y reintentá." >&2
  exit 2
fi

# HTTP bootstrap if cert not yet present
if [ ! -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ]; then
  sudo tee "${NGINX_AVAIL}" >/dev/null <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};
    include /etc/nginx/snippets/cloudflare-realip.conf;
    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
        default_type text/plain;
        try_files \$uri =404;
    }
    location / {
        proxy_pass http://127.0.0.1:8092;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
  sudo ln -sfn "${NGINX_AVAIL}" "/etc/nginx/sites-enabled/${DOMAIN}.conf"
  sudo nginx -t
  sudo systemctl reload nginx
fi

sudo certbot certonly --webroot -w /var/www/certbot -d "${DOMAIN}" \
  --non-interactive --agree-tos --register-unsafely-without-email \
  --keep-until-expiring

sudo cp "${REPO_CONF}" "${NGINX_AVAIL}"
sudo ln -sfn "${NGINX_AVAIL}" "/etc/nginx/sites-enabled/${DOMAIN}.conf"
# Retirar vhost anidado legacy (CF Universal SSL no lo cubre)
sudo rm -f /etc/nginx/sites-enabled/dev.esecurebroker.etsrv.site.conf
sudo nginx -t
sudo systemctl reload nginx
echo "OK https://${DOMAIN}/  → 127.0.0.1:8092"
