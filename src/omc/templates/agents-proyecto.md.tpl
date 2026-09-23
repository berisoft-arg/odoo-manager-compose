# {{PROYECTO}} — Odoo {{ODOO_VERSION}} (generado por OMC, para agentes)

## Comandos (correr desde la raíz del proyecto)

```bash
docker compose up -d && docker compose logs -f odoo   # levantar + logs
docker compose logs -f --tail=200 odoo                # solo logs
omc update <modulo> --db <bd>                         # actualizar 1 módulo
omc test <modulo> --db <bd>                           # test 1 módulo (--test-enable)
omc doctor --proyecto .        # valida compose/conf/addons/.env
omc list                       # ver todas las instancias
```

## IDE (VS Code / VSCodium)

- Abrir: `codium .` o `code .` — la carpeta ya trae `.vscode/` (settings, launch F5, tasks).
- Extensiones recomendadas: Python, Pylance, Ruff, Docker, Odoo (`ms-python.python`, `charliermarsh.ruff`, `trinhanhngoc.vscode-odoo`).
- Codium usa open-vsx equivalentes; el menú Dev (opción 13) puede instalarlas con `codium --install-extension`.
- Debug: `F5` → `Odoo {{ODOO_VERSION}}: attach` (debugpy 5678) o `shell`.

## Navegador (Chrome)

- **My Odoo Webkit** (principal, 76 usuarios, v1.3.0): https://chromewebstore.google.com/detail/my-odoo-webkit/fdohfkgekkoehlofibieijojjcmlbdok?hl=es
  Model inspector (modelo/ID/vista/action/XMLID/context/domain), record viewer (JSON-RPC), field explorer (type/label/relation), snippets ORM (browse/search/create/write/unlink), shell commands.
- Alternativas: Odoo Toolbox (Odoo.SH) y Odoo Debug (toggle `?debug=1` con `Ctrl+.`).

## Reglas (no romper en prod)

- Nunca `DROP DATABASE`, `down -v` ni `web --standalone` si hay proxy central.
- Secrets solo en `.env` (ignorado); commitear `.env.ejemplo`, jamás `.env`.
- Módulos propios en `addons/custom/` (van en tu git); terceros por `omc addons`.
- Backups en `backups/`; restore con doble confirmación (`scripts/restore.sh`).
- DB de pruebas restaurada: pasar `--neutralizar` (apaga crons y mail reales).
- En dev, los mails caen en Mailpit (`http://localhost:{{MAILPIT_PORT}}`, SMTP interno 1025).
