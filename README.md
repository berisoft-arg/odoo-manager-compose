# Odoo Manager Compose (`omc`)

Crea, opera y migra instancias **Odoo 17 / 18 / 19** con docker-compose.
Asistente interactivo + CLI + monitor web + migración OCA entre versiones.

> Documentación completa en [Manual-OMC.md](Manual-OMC.md).

## Qué hace

- **Crear proyectos**: genera `docker-compose.yml` (Odoo + PostgreSQL, + nginx/certbot
  con dominio en prod), `.env`, `config/odoo.conf`, scripts de backup/restore.
  Entornos **dev** (debug, sin restart) y **prod** (workers, tuning PG, límites,
  backups a Google Drive vía rclone).
- **Módulos (`omc addons`)**: descarga **solo los módulos elegidos** de grandes
  monorepos con `git sparse-checkout` (OCA, AdHoc, Cybrosys, Odoo Mates, Codize,
  repos propios o privados). Bundle exportable para clonar instancias,
  resolución de dependencias (`deps`), `sync`, `pull`, `status`, `check-deps`.
- **Localización Argentina**: bundle AdHoc (factura electrónica + IVA),
  `python3-m2crypto` por apt, `SECLEVEL=1`, cache de pyafipws.
- **Monitor web** (`omc-monitor`): Flask solo-lectura del estado de instancias
  (contenedores, cron, colas, disco, SSL, **AFIP WSAA por BD con alertas 30/7 días**),
  tema claro/oscuro, token de acceso (URL y token solo visibles en la opción 6 del menú).
- **Migración OCA** (`omc migrar`): etapa 1 código (`odoo-module-migrator`,
  clasifica migrado/sin-migrar/custom sin mutar el proyecto), etapa 2 BD
  (OpenUpgrade + `docker-compose.migrate.yml`), con backup previo siempre.
- **Backup/restore**: dump PostgreSQL + filestore, local o Drive (+ copia dominical),
  con doble confirmación al restaurar.
- **Desarrollo (IDE + navegador)**: `.vscode/` para VS Code/VSCodium (settings, launch, tasks, extensiones `anomalyco.opencode`/Python/Ruff/Docker/Odoo), `opencode.json` (`$schema` + `instructions ["AGENTS.md"]`), `AGENTS.md` por proyecto, **My Odoo Webkit** Chrome (model/field/record) y **opencode** CLI/TUI.
- **Multi-instancia**: puertos validados y sugeridos libres, `ODOO_GEVENT_PORT`,
  `omc list` / `omc doctor [--fix]`. Con dominio en un solo host: **proxy
  nginx compartido** (`omc proxy init` + `omc web --proxy`), un site por
  subdominio con TLS centralizado.

## Requisitos

Python 3.10+, Git, Docker con plugin compose. Para repos privados en https:
`export GITHUB_TOKEN=...` (por env nunca se guarda; el menú 7 puede guardarlo en `~/.config`, jamás en proyectos).

## Instalación

```bash
pipx install odoo-manager-compose
# o
pip install odoo-manager-compose --break-system-packages
omc --version  # abre el menú 1-13
```

> Manual completo: [Manual-OMC §15](Manual-OMC.md#15-instalación-venv-sin-docker) y [§17 VPS](Manual-OMC.md#17-vps-producción).

## Uso rápido: el menú básico (1-13, 0 sale)

```bash
omc                 # abre el menú
```

![Menú principal OMC — opciones 1-13 y 0 Salir](assets/images/menu.png)

*Flujo habitual: `1` crear → `2` módulos → `3` localizar → `8` backup → `13` dev (VS Code/Codium + My Odoo Webkit + opencode).*

```bash
# Desarrollo (opcional, recomendado siempre — solo dev; en prod VPS solo con --force para opencode terminal sin IDE)
# VS Code / VSCodium + opencode
codium .  # o code . → .vscode/ + opencode.json ya vienen (Ctrl+Esc split, Ctrl+Shift+Esc nueva)
opencode  # TUI: en terminal integrado instala extensión anomalyco.opencode auto; fallback: Marketplace buscar "OpenCode"
# En VPS (prod): omc dev --proyecto . --force  # solo opencode.json terminal, sin .vscode ni extensión
```

Menú avanzado (subcomandos directos como `omc crear --flags`,
`omc doctor --fix`): ver [Manual-OMC](Manual-OMC.md). Para agentes/CI:
`omc list/doctor --json`, `omc logs/update/test` y `AGENTS.md` + `opencode.json` (instrucciones para agentes).

## Estructura del repo

```text
src/omc/            # paquete (cli, core, tui, github, gitutils, manifest,
                    #          addonsops, addons_cli, compose, flows, migrate, webapp)
src/omc/templates/  # compose dev/prod/migrate, odoo.conf, nginx, Dockerfile, backup/restore, vscode-*.json.tpl, opencode.json.tpl, agents-proyecto.md.tpl
src/omc/versions/   # 17.env (pg15), 18.env / 19.env (pg16)
src/omc/data/       # catálogo de addons, localizaciones, bundle ejemplo
src/omc/monitor/    # monitor Flask solo-lectura (lo sirve `omc-monitor`)
tests/              # suite pytest
requirements*.txt   # runtime
Manual-OMC.md        # documentación completa
CHANGELOG.md         # historial
```

### Dónde vive (estándar VPS)

```text
pipx venv (~/.local/pipx/venvs/odoo-manager-compose)  # código OMC (con git: /opt/odoo-manager-compose)
~/.local/bin/omc                                      # comando
~/.config/systemd/user/     # servicio omc-monitor (con el token, permiso 600)
/opt/omc                    # datos OMC: OMC_HOME (catálogos editables, estado)
/opt/<nombre>               # proyectos: OMC_PROJECTS (ej. /opt/mi-proyecto)
~/.config/omc/              # GitHub (token opcional 0600, jamás en proyectos)
```

## Licencia

AGPL-3.0 — ver [LICENSE](LICENSE).
