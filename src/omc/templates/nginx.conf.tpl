# Nginx para {{PROYECTO}} -> odoo:8069 (dominio {{DOMINIO}} + www)
# Día 1 funciona solo con HTTP (puerto 80): sirve el challenge de certbot.
# Tras obtener el cert, este archivo se reemplaza por la estructura HTTPS
# (nginx-https.conf.tpl: 80->443, www->apex, bloque principal) y se recarga.

upstream odoo {
    server odoo:8069;
}

server {
    listen 80;
    server_name {{DOMINIO}} www.{{DOMINIO}};

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        proxy_pass http://odoo;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 600s;
        client_max_body_size 200m;
    }
}
