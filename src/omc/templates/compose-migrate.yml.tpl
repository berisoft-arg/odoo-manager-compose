# Override de migración OpenUpgrade — Proyecto: {{PROYECTO}} | Destino: Odoo {{ODOO_VERSION_DESTINO}}
# Generado por omc (se regenera en cada `migrar`, no tocar a mano).
# La migración DEBE correr con los binarios de la versión destino contra la BD origen:
#   docker compose -f docker-compose.yml -f docker-compose.migrate.yml run --rm odoo -- \
#     --database <BD> --update all --stop-after-init --load=base,web,openupgrade_framework
# `run` no publica puertos (no choca con la instancia en marcha). Volúmenes y odoo.conf
# se heredan del compose base (addons_path ya incluye addons/openupgrade).
services:
  odoo:
    image: {{ODOO_IMAGE_DESTINO}}
    restart: "no"
