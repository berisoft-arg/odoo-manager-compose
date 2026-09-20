# {{PROYECTO}} — Odoo {{ODOO_VERSION}} (generado por omc, para agentes)

## Comandos (correr desde la raíz del proyecto)

```bash
docker compose up -d && docker compose logs -f odoo   # levantar + logs
docker compose logs -f --tail=200 odoo                # solo logs
omc update <modulo> --db <bd>                         # actualizar 1 módulo
omc test <modulo> --db <bd>                           # test 1 módulo (--test-enable)
omc doctor --proyecto .        # valida compose/conf/addons/.env
omc list                       # ver todas las instancias
```

## Reglas (no romper en prod)

- Nunca `DROP DATABASE`, `down -v` ni `web --standalone` si hay proxy central.
- Secrets solo en `.env` (ignorado); commitear `.env.ejemplo`, jamás `.env`.
- Módulos propios en `addons/custom/` (van en tu git); terceros por `omc addons`.
- Backups en `backups/`; restore con doble confirmación (`scripts/restore.sh`).
- DB de pruebas restaurada: pasar `--neutralizar` (apaga crons y mail reales).
- En dev, los mails caen en Mailpit (`http://localhost:{{MAILPIT_PORT}}`, SMTP interno 1025).
