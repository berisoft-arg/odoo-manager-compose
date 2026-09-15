# {{PROYECTO}} — Odoo {{ODOO_VERSION}} ({{ENTORNO}})

Generado con `omc crear` (Odoo Manager Compose).

## Uso

```bash
docker compose up -d
docker compose logs -f odoo
```

Abrir http://localhost:{{ODOO_PORT}}

## Estructura

```
docker-compose.yml
.env
config/odoo.conf
odoo-addons.py       -> stub que delega en `omc addons` (sparse-checkout)
addons/
  custom/            -> TUS módulos propios (a mano, van en tu git)
  extras/            -> Sueltos de Odoo Apps (unzip en subcarpeta propia)
  oca/<repo>/        -> clones sparse OCA (solo módulos elegidos)
  adhoc/<repo>/      -> clones sparse AdHoc
  cybrosys/<repo>/   -> Cybrosys (ej CybroAddons)
  mates/<repo>/      -> Odoo Mates (ej odooapps)
  codize/<repo>/     -> Codize (ej odoo-argentina)
  repos.json         -> estado para `pull` futuro (URLs sin token)
Odoo ve cada repo vía addons_path múltiple en config/odoo.conf (sin accesos directos).
```

## Addons OCA / AdHoc / Cybrosys / Mates (solo elegidos + pull futuro)

```bash
# Ver catálogo curado
omc addons list-catalog
omc addons list-catalog --org mates

# Listar módulos de un repo/rama (usa la rama según tu Odoo)
omc addons list-modules server-tools --odoo {{ODOO_VERSION}}
omc addons list-modules odooapps --org mates --odoo {{ODOO_VERSION}}

# Descargar SOLO los que elijas (sparse-checkout, vale dev y prod)
omc addons add server-tools auditlog --org oca --odoo {{ODOO_VERSION}}
omc addons add odooapps om_account_asset --org mates --odoo {{ODOO_VERSION}}

# Cualquier otro repo (incl. privados): https o SSH
omc addons add MiRepo mi_modulo --url https://github.com/MiOrg/MiRepo --branch {{ODOO_VERSION}}.0
export GITHUB_TOKEN=ghp_xxx   # repos privados https (no se guarda en repos.json)
omc addons add Privado mod1 --url https://github.com/MiOrg/privado --branch {{ODOO_VERSION}}.0

# Tus módulos propios: cópialos directo en addons/custom/
cp -r /ruta/mi_modulo addons/custom/

# Ver estado / actualizar a futuro
omc addons status
omc addons pull
omc addons check-deps   # detecta external_dependencies

# Odoo YA desplegado y quieres agregar módulos de repos después:
omc addons sync                              # instalador + deps + rebuild + restart
omc addons sync --bundle addons-bundle.json  # primero instala todo el bundle
omc addons sync --yes                        # sin preguntas
omc addons sync --no-deploy                  # solo instala+deps, sin docker

# Exportar lo instalado para replicar la instancia en otro lado:
omc addons export-bundle                      # -> addons-bundle.export.json
omc addons export-bundle --salida mi-bundle.json --force

# Reiniciar Odoo para verlos
docker compose restart odoo
```

## Dependencias externas

Si un módulo declara `external_dependencies` (python/bin en su `__manifest__.py`),
el asistente genera `requirements-odoo.txt` + `Dockerfile` y pasa el compose a `build`.
El despliegue usa `docker compose up -d --build` automáticamente.

## Web pública HTTPS (prod con dominio)

Si el proyecto se creó sin dominio, se configura después:
```bash
omc web --proyecto .   # pide dominio/email
```

```bash
# 1) Levantar (nginx en 80 + odoo interno)
docker compose up -d
# 2) Certificado para dominio + www (cambia email/dominio según tu .env)
docker compose run --rm certbot certonly --webroot -w /var/www/certbot \
  --email {{CERTBOT_EMAIL}} --agree-tos --no-eff-email -d {{DOMINIO}} -d www.{{DOMINIO}}
# 3) Reemplazar nginx/nginx.conf por la estructura HTTPS y recargar
#    (el asistente lo hace solo con "¿Obtener certificado y activar HTTPS ahora?")
docker compose exec nginx nginx -s reload
# Renovar (cron mensual en el host):
docker compose run --rm certbot renew && docker compose exec nginx nginx -s reload
```

## Backups y restore (+ Google Drive)

```bash
./scripts/backup.sh <nombre_bd>              # dump + filestore en backups/<bd>_<fecha>/
./scripts/restore.sh <nombre_bd> <carpeta>   # recrea BD + filestore
# Drive: configura después con:
omc rclone --proyecto .
# (instala rclone, corre `rclone config` guiado y verifica el remote {{RCLONE_REMOTE}})
# Drive: instala rclone, configura scripts/rclone.conf (remote {{RCLONE_REMOTE}}) y el backup sube solo.
# Cron diario ejemplo (host): 0 2 * * * cd /ruta/{{PROYECTO}} && ./scripts/backup.sh <bd> >> backups/cron.log 2>&1
```

## Recursos (CPU/RAM) y Postgres

Límites en `docker-compose.yml` (`deploy.resources`, editables vía `ODOO_CPUS/MEM`, `DB_CPUS/MEM` en `.env`) y tuning Postgres (`PG_*` en `.env`, aplicado como `command:` al contenedor db).

## Comandos útiles

```bash
# Ver logs
docker compose logs -f

# Parar / borrar volúmenes (¡borra BD!)
docker compose down
docker compose down -v

# Backup BD
docker compose exec db pg_dump -U odoo postgres > backup.sql
```
