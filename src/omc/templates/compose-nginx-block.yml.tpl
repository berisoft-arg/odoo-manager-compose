# --- Nginx + Certbot (solo si el asistente configuró dominio) ---
# Flujo: 1) docker compose up -d nginx  2) obtener cert (ver README)
# 3) nginx.conf se reemplaza por la estructura HTTPS y se recarga
  nginx:
    image: nginx:alpine
    restart: always
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/conf.d/odoo.conf:ro
      - ./nginx/gzip.conf:/etc/nginx/conf.d/gzip.conf:ro
      - ./letsencrypt:/etc/letsencrypt:ro
      - ./certbot-www:/var/www/certbot:ro
    depends_on:
      - odoo
    deploy:
      resources:
        limits: {cpus: '0.50', memory: 512M}
        reservations: {cpus: '0.25', memory: 128M}

  certbot:
    image: certbot/certbot
    volumes:
      - ./letsencrypt:/etc/letsencrypt
      - ./certbot-www:/var/www/certbot
    # Se usa a demanda, no queda corriendo:
    #   docker compose run --rm certbot certonly --webroot -w /var/www/certbot \
    #     --email {{CERTBOT_EMAIL}} --agree-tos --no-eff-email -d {{DOMINIO}} -d www.{{DOMINIO}}{{CERTBOT_STAGING}}
    # Luego nginx.conf se reemplaza por la estructura HTTPS y se recarga.
    # Renovar (cron en host): docker compose run --rm certbot renew && docker compose exec nginx nginx -s reload
    command: sleep infinity
