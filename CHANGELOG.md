# CHANGELOG — Odoo Manager Compose (OMC)

## [Sin publicar]

- **Proxy multinstancia (nginx compartido)**: nuevo proyecto central `proxy`
  (`omc proxy init`: compose + red externa `omc-proxy` + nginx único en 80/443),
  `omc web --proxy/--standalone`, sites por subdominio en `conf.d/` con TLS
  centralizado (certonly apex + www, reuso sin re-emitir, renew por cron),
  templates nginx parametrizados con `{{ODOO_HOST}}`; sites proxy sin
  `upstream`: `resolver 127.0.0.11` + `proxy_pass` con variable (un backend
  caído no voltea al resto). Opción 11 del menú.

## [1.0.0]

Primera versión documentada: asistente + menú en loop, creación/operación de
instancias Odoo 17/18/19 con docker-compose, monitor web solo-lectura,
migración OCA, proyectos en `/opt` por default (`OMC_PROJECTS`/`OMC_HOME`).

### Ya resueltos (salieron de Solución de problemas)

- Healthcheck Postgres: `pg_isready` con `-d postgres` en plantillas.
- Monitor Odoo 18: detecta columna `cron_name` (antes pedía `name`).
- Imagen Odoo = Debian 12 (PEP 668): Dockerfile con `--break-system-packages`.
- Deps con URL `git+https`: Dockerfile instala git por apt.
- `odoo.conf` montado sin `:ro` en plantillas (evita `couldn't write the config file`).
- Odoo 19: sin línea `logfile` (= stdout).
