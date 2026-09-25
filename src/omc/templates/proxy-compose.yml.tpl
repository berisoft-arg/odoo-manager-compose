# Proxy multinstancia OMC ({{PROYECTO}}) — único publicador 80/443 del host.
# Generado por `omc proxy init`. Los sitios viven en ./conf.d/<dominio>.conf
# (un archivo por proyecto, generados con `omc web --proxy`).
# Red omc-proxy: externa, creada por `omc proxy init`; los odoo se suman a ella.
services:
  nginx:
    image: nginx:alpine
    restart: always
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./conf.d:/etc/nginx/conf.d/:ro
      - ./letsencrypt:/etc/letsencrypt:ro
      - ./certbot-www:/var/www/certbot:ro
    networks:
      - omc-proxy
    deploy:
      resources:
        limits: {cpus: '0.50', memory: 512M}
        reservations: {cpus: '0.25', memory: 128M}
  certbot:
    image: certbot/certbot
    # Solo a demanda (up -d no lo levanta; run explícito sí):
    profiles: ["certbot"]
    volumes:
      - ./letsencrypt:/etc/letsencrypt
      - ./certbot-www:/var/www/certbot
    # Se usa a demanda, no queda corriendo:
    #   docker compose run --rm certbot certonly --webroot -w /var/www/certbot \
    #     --email <email> --agree-tos --no-eff-email -d <dominio> -d www.<dominio>
    # Renovar todo (cron en host): ver README del proxy.
networks:
  omc-proxy:
    external: true
