# Sitio odoo para {{PROYECTO}} (dominio {{DOMINIO}})
# Estructura final tras validar certbot: HTTP->HTTPS, www->apex, bloque principal.
# Odoo detrás: odoo:8069 (HTTP) + odoo:8072 (websocket/longpolling, requiere workers).

# 1. Redirección HTTP (puerto 80) a HTTPS para ambos dominios
server {
    listen 80;
    server_name {{DOMINIO}} www.{{DOMINIO}};

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    return 301 https://{{DOMINIO}}$request_uri;
}

# 2. Redirección HTTPS de www a sin www
server {
    listen 443 ssl;
    server_name www.{{DOMINIO}};

    ssl_certificate /etc/letsencrypt/live/{{DOMINIO}}/fullchain.pem; # certbot webroot
    ssl_certificate_key /etc/letsencrypt/live/{{DOMINIO}}/privkey.pem; # certbot webroot
    # TLS seguro inline (sin depender de options-ssl-nginx.conf del plugin nginx,
    # que certonly --webroot no crea). Equivalente al perfil intermedio de Mozilla.
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    return 301 https://{{DOMINIO}}$request_uri;
}

# 3. Bloque Principal HTTPS
server {
    listen 443 ssl;
    server_name {{DOMINIO}};

    ssl_certificate /etc/letsencrypt/live/{{DOMINIO}}/fullchain.pem; # certbot webroot
    ssl_certificate_key /etc/letsencrypt/live/{{DOMINIO}}/privkey.pem; # certbot webroot
    # TLS seguro inline (ver bloque www: certonly --webroot no crea los .conf del plugin nginx).
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    add_header Strict-Transport-Security "max-age=2592000; includeSubDomains" always;

    # Bloqueo del gestor de bases de datos
    location /web/database/manager {
        return 404;
    }

    # Odoo WebSocket (longpolling; requiere workers en odoo.conf)
    location /websocket {
        proxy_pass http://odoo:8072;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }

    # Proxy Principal Odoo (upstream = servicio odoo del compose)
    location / {
        proxy_pass http://odoo:8069/;
        proxy_next_upstream error timeout invalid_header http_500 http_502 http_503 http_504;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-NginX-Proxy true;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-Host $host;

        proxy_redirect off;
        proxy_request_buffering off;

        proxy_connect_timeout 36000s;
        proxy_read_timeout 36000s;
        proxy_send_timeout 36000s;
        send_timeout 36000s;

        client_max_body_size 10240m;
    }
}
