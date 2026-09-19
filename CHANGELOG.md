# CHANGELOG — Odoo Manager Compose (OMC)

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
