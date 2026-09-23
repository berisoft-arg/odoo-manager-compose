# CHANGELOG — Odoo Manager Compose (OMC)

## [1.1.0] - 2026-09-22

- **AFIP WSAA (monitor)**: vencimiento por BD (alias/CUIT/tipo, notAfter/días, niveles ok/warn≤30/critical≤7/vencido, cache 20s) — §5.7/§14, `src/omc/monitor/app.py:366`. Incluye renew semanal certbot + `certbot delete`.
- **Desarrollo (IDE + navegador) — opción 13**: `.vscode/{settings,extensions,launch,tasks}.json` (generados desde `vscode-*.json.tpl`, merge no destructivo con `.bak`, soporte jsonc con `//`) + `opencode.json` (`$schema` `opencode.ai/config.json`, `instructions ["AGENTS.md"]`, `anomalyco.opencode` recomendado siempre, primero en `extensions.json`, Codium open-vsx), detección `codium>code>code-oss` (auto), `opencode` en terminal integrado (`Ctrl+Esc` split, `Ctrl+Shift+Esc` nueva) instala `anomalyco.opencode` auto, `omc dev|ide [--ide codium|vscode|auto] [--instalar|--solo-generar]`, `omc crear --ide`, menú 13 + submenú Dev (configurar/verificar/extensiones Chrome/regenerar AGENTS), `AGENTS.md` enriquecido con IDE/Navegador + **My Odoo Webkit** 1.3.0 `fdohfkgekkoehlofibieijojjcmlbdok` (Model inspector/Record viewer/Field explorer/ORM snippets/Shell) — §7.6, `src/omc/flows.py:2327`.
- **Proxy multinstancia (nginx compartido)**: nuevo proyecto central `proxy`
  (`omc proxy init`: compose + red externa `omc-proxy` + nginx único en 80/443),
  `omc web --proxy/--standalone`, sites por subdominio en `conf.d/` con TLS
  centralizado (certonly apex + www, reuso sin re-emitir, renew por cron),
  templates nginx parametrizados con `{{ODOO_HOST}}`; sites proxy sin
  `upstream`: `resolver 127.0.0.11` + `proxy_pass` con variable (un backend
  caído no voltea al resto). Opción 11 del menú.
- **Migrar a otro VPS**: `12) Migrar instancia a otro VPS` (paquete completo) —
  `stop odoo` (o `--consistente` con `stop db`), backup por BD, empaqueta
  `bundle+full_backup+env` en `migrar_<host>_<ts>.tar.gz` con `MANIFEST.json` (proxy excluido, solo prod).
- **Seguridad en restore**: `odoo neutralize -d` opt-in solo-dev
  (`--neutralizar`, pregunta default NO).
- **Agentes**: `AGENTS.md` por proyecto, `omc list/doctor --json` (doctor exit 2
  con errores), `omc logs/update/test`, resumen de omitidos y drift en `sync`,
  aviso de conflictos de versiones en requirements.
- **Reproducibilidad**: SHA fijado en `repos.json` (+ export en bundle),
  aviso de drift con `omc addons pull` para actualizar.
- **Mailpit en dev**: buzón local (`:8025`, SMTP interno 1025), `list_db = False`,
  `.env.example` sin secretos.

## [1.1.1] - 2026-09-22

- **Fix**: menú captura `assets/images/menu.png` 598x433 con 13) Desarrollo (banner 1.1.0), comentario `src/omc/flows.py:2567` 1..13 + 0 Salir (14 items), licencia SPDX string `AGPL-3.0-only`.
- **Docs**: `Manual §1.1` `.env` ignorado + `.env.ejemplo` sin `VPS_*` + `list_db=False` oculta `/web/database/manager`, `§5.7` `production` vs `ENTORNO=produccion`, `§7.3` snippet `resolver 127.0.0.11 valid=10s` dinámico vs clásico `upstream`.

## [1.1.2] - 2026-09-22

- **Dev prod-gating**: `opencode` siempre en dev (por proyecto, `.vscode` + `opencode.json` con `anomalyco.opencode`), nunca en prod VPS; en prod solo con `--force` genera `opencode.json` en modo terminal sin `.vscode`/IDE/extensión (advertencia).

## [1.1.3] - 2026-09-23

- **Docs: global + Dónde vive**: instalación global para root + cualquier usuario con `pipx` (`PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin --global`) y con `pip` (`sudo pip install --break` → `/usr/local/bin`), `§15.1` + verificación desde `/`, `/opt`, `/home`; `§13 Dónde vive` simplificado a proyectos en `/opt/<nombre>` por convención Odoo (`/opt/odoo`).

## [1.1.4] - 2026-09-23

- **Fix: `list_db = True` siempre** (dev y prod, manager por IP:puerto sin nginx; https sigue con `return 404`): `odoo.conf.tpl:12` + tests + `Manual §1.1/§3` (tras crear la BD pasar a `False` + restart).
- **Marca OMC**: `Generado por omc` → `OMC` en templates (`odoo.conf`, `docker-compose.*`, `env.ejemplo`, `agents-proyecto`, `vscode-settings`, `Dockerfile`, `compose-migrate`) + `flows.py` stub + `migrate.py`.

## [1.1.5] - 2026-09-24

- **Menú agrupado + proxy guiado**: menú por fases (Crear / Publicar / Operar) sin renumerar + pie con flujo habitual; `web --proxy` sin proxy inicializado ofrece `proxy init` en menú (antes abortaba al menú); pausa `Enter para volver` tras errores; staging/modo explícitos (`ENTER=no=real`). Tests + `Manual §3/§7.3/§12`.
- **Menú título plano + deps con checklist**: título sin fondo azul ni foco inicial (solo la opción con foco al navegar); `run_deps` y `elegir_repo_guiado` usan el mismo `checklist` paginado de repos/módulos (con fallback textual). Tests.

## [Sin publicar]

- **Deploy espera ESC**: tras el `pulling`/`build` muestra resumen (`ps` + URL/logs o hints de puertos/`429`) y espera `ESC` para volver al menú (`Enter` no vuelve); sin tty no espera. `Manual §4.5`.

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
