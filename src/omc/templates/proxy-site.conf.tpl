# Site {{DOMINIO}} (+ www) de {{PROYECTO}} en el proxy central.
# Día 1 HTTP: sirve el challenge de certbot. Tras el cert se reemplaza por
# proxy-site-https.conf.tpl y se recarga.
# Upstream por variable con resolver Docker (uno por server: si este odoo
# está caído, solo este site falla y el reload nunca voltea al resto).
# Sin upstream estático a propósito.

server {
    listen 80;
    server_name {{DOMINIO}} www.{{DOMINIO}};

    resolver 127.0.0.11 valid=10s;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    set $up {{ODOO_HOST}}:8069;

    location / {
        proxy_pass http://$up;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 600s;
        client_max_body_size 200m;
    }
}
