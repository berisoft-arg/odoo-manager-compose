# Proyecto: {{PROYECTO}} | Entorno: produccion | Odoo {{ODOO_VERSION}} | Generado por omc
services:
  db:
    image: {{POSTGRES_IMAGE}}
    restart: always
    command: >
      postgres
      -c shared_buffers={{PG_SHARED_BUFFERS}}
      -c effective_cache_size={{PG_EFFECTIVE_CACHE}}
      -c work_mem={{PG_WORK_MEM}}
      -c maintenance_work_mem={{PG_MAINT_MEM}}
      -c max_connections={{PG_MAX_CONN}}
    environment:
      - POSTGRES_DB=postgres
      - POSTGRES_USER=odoo
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
      - PGDATA=/var/lib/postgresql/data/pgdata
    volumes:
      - odoo-db-data:/var/lib/postgresql/data/pgdata
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U odoo -d postgres"]
      interval: 10s
      timeout: 5s
      retries: 5
{{DB_DEPLOY}}
  odoo:
    {{ODOO_BUILD_OR_IMAGE}}
    depends_on:
      db:
        condition: service_healthy
    restart: always
{{ODOO_PORTS}}
    environment:
      - HOST=db
      - USER=odoo
      - PASSWORD=${POSTGRES_PASSWORD}
    volumes:
      - ./addons:/mnt/extra-addons
      - ./config/odoo.conf:/etc/odoo/odoo.conf
      - odoo-data:/var/lib/odoo
{{ODOO_DEPLOY}}{{NGINX_SERVICES}}{{RCLONE_SERVICE}}volumes:
  odoo-db-data:
  odoo-data:
