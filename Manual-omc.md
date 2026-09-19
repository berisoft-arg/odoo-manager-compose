# Odoo Manager Compose — Manual completo

> `omc` (paquete `pip install odoo-manager-compose`) — Odoo Manager Compose: crea, opera y migra
> instancias Odoo con docker-compose. Versiones Odoo 17 / 18 / 19, entornos desarrollo / producción.
>
> **Uso diario: solo `omc`, sin argumentos.** Se abre el menú (opciones 1-10, `0` para salir)
> y todo se elige ahí: crear, descargar módulos, localizar, nginx, rclone, monitor, GitHub,
> backup, restore, migrar. Al terminar cada acción vuelve al menú.
> Los subcomandos directos (`omc crear --flags`, `omc addons ...`, etc.) existen como
> **atajos avanzados** (scripts, VPS sin tty); este manual los marca como tales.

## Índice

1. [Qué es y qué genera](#1-qué-es-y-qué-genera)
2. [Requisitos](#2-requisitos)
3. [Inicio rápido](#3-inicio-rápido)
4. [El asistente paso a paso](#4-el-asistente-paso-a-paso)
5. [Módulos: bundle, lista y terceros](#5-módulos-bundle-lista-y-terceros)
6. [`omc addons` (referencia avanzada)](#6-omc-addons-referencia-avanzada)
7. [Post-despliegue: sync y configuradores](#7-post-despliegue-sync-y-configuradores)
8. [Dependencias externas y Dockerfile](#8-dependencias-externas-y-dockerfile)
9. [Prod: nginx, HTTPS, backups y recursos](#9-prod-nginx-https-backups-y-recursos)
10. [Puertos y múltiples instancias](#10-puertos-y-múltiples-instancias)
11. [Docker útil](#11-docker-útil)
12. [Solución de problemas](#12-solución-de-problemas)
13. [Archivos del dir maestro](#13-archivos-del-dir-maestro)
14. [Monitor web](#14-monitor-web-flask-solo-lectura)
15. [Instalación (venv, sin Docker)](#15-instalación-venv-sin-docker)
16. [Migración entre versiones Odoo](#16-migración-entre-versiones-odoo-oca)
17. [VPS con deploy-vps.sh](#17-vps-con-deploy-vpssh)

---

## 1. Qué es y qué genera

Asistente interactivo (con modo automático por flags) que genera proyectos Odoo listos para
`docker compose`, más un helper que descarga **solo los módulos elegidos** de grandes monorepos
con `git sparse-checkout` (clones de pocos MB con `git pull` futuro).

### 1.1 Estructura de un proyecto generado

```text
mi-proyecto/
  docker-compose.yml        # db (postgres) + odoo (+ nginx/certbot en prod con dominio)
  .env                      # versiones, passwords, puertos, tuning PG, límites, dominio
  config/odoo.conf          # addons_path múltiple, workers, proxy_mode si hay nginx
  nginx/nginx.conf          # solo prod con dominio
  letsencrypt/ certbot-www/ # solo prod con dominio
  scripts/
    backup.sh               # dump Postgres + filestore (+ rclone a Drive)
    restore.sh              # recrea BD + filestore
    rclone.conf             # tu config rclone (la creas con `omc rclone`)
    rclone.conf.ejemplo     # plantilla
  backups/                  # destino local de backups
  addons/
    custom/                 # TUS módulos propios (a mano, nada del helper clona acá)
    extras/                 # sueltos de Odoo Apps (unzip en subcarpeta propia)
    <dueño>/               # cualquier otro origen (carpeta del dueño de la URL)
    oca/<repo>/             # clones sparse OCA
    adhoc/<repo>/           # clones sparse AdHoc
    cybrosys/<repo>/        # clones sparse Cybrosys
    mates/<repo>/           # clones sparse Odoo Mates
    codize/<repo>/          # clones sparse Codize
    repos.json              # estado: repos/módulos/ramas (para pull y export)
  odoo-addons.py            # stub que delega en `omc addons` (sparse-checkout)
  addons-bundle.json        # bundle con lo instalado (se genera solo; para clonar instancias)
  addons-bundle.ejemplo.json# plantilla para llenar
  requirements-odoo.txt      # deps Python detectadas (si hay)
  Dockerfile / .dockerignore# solo si hay dependencias Python
  README.md
```

Odoo ve cada repo por **`addons_path` múltiple** en `odoo.conf`, sin accesos directos:

```ini
addons_path = /mnt/extra-addons/custom,/mnt/extra-addons,/mnt/extra-addons/adhoc/odoo-argentina-ce
```

### 1.2 Dev vs prod

| Aspecto | desarrollo | producción |
|---|---|---|
| `restart` | `no` (no vuelve solo) | `always` |
| odoo | `--dev=all`, workers 0, 8072 expuesto | workers 4 + límites, `proxy_mode` si hay nginx |
| postgres | liviano (128MB shared_buffers, 50 conn) | tuneado (256MB, 100 conn, `command:`) |
| recursos | 1 CPU / 2G odoo | 2 CPU / 4G odoo (+ límites en db y nginx) |
| web | directa en `ODOO_PORT` | nginx + certbot opcional por dominio |
| backups | script local | script + rclone a Drive |

---

## 2. Requisitos

- Python 3.10+, Git y Docker con plugin compose (`docker compose version`).
- Para repos privados https: `export GITHUB_TOKEN=...` (nunca se guarda en archivos).
- Puertos libres en el host (el asistente los valida y sugiere libres).

---

## 3. Inicio rápido

```bash
cd ~/odoo-manager-compose
omc     # sin flags abre el menú:
#   1) Crear proyecto nuevo (docker-compose Odoo)
#   2) Descargar módulos y aplicar (bundle/lista + deps + rebuild)
#   3) Instalacion dependencias Localizacion Argentina
#   4) Configurar web nginx + certbot [prod]
#   5) Configurar rclone / Google Drive [prod]
#   6) Ver monitor web (pide puerto: localhost:PUERTO o IP:PUERTO en VPS)
#   7) Configurar GitHub (token + org)
#   8) Backup manual [prod]
#   9) Restaurar BD [prod] (guiado: local/Drive, doble confirmación)
#  10) Migrar proyecto a nueva versión Odoo (OCA: chequeo módulos + openupgrade)
#   0) Salir
# Opción 1 pide: 1) Nombre  2) Entorno  3) Versión  4) Puertos (validados)
# 5) Passwords  6) ¿Desplegar? Al terminar vuelve al menú: los módulos NO se
# descargan acá. Flujo habitual: 1 (crear) → 2 (descargar módulos con bundle o
# lista, rama X.0 automática) → 3 (localización AR si la necesitas: deja
# m2crypto/SECLEVEL + ofrece aplicar con Dockerfile + rebuild).
```

Abrir `http://localhost:PUERTO` y ver logs con `docker compose logs -f odoo`.

Limpieza para reprobar (conserva imágenes):

```bash
cd ~/odoo-manager-compose/mi-proyecto && docker compose down -v   # NO borra imágenes
docker ps            # vacío
rm -rf ~/odoo-manager-compose/mi-proyecto
```

> Nunca `docker rmi` ni `docker system prune -a` si quieres conservar las imágenes.

---

## 4. El asistente paso a paso

### 4.1 Entorno y versión

El entorno cambia restart, debug y workers (ver tabla §1.2). La versión define Postgres
vía `versions/*.env`: **17 → postgres:15; 18/19 → postgres:16**.

### 4.2 Puertos (validados antes de generar)

Se valida puerto HTTP y gevent contra socket local + `docker ps`. Si está ocupado, avisa y
sugiere el primer libre. Avanzado sin menú: `--puerto`, `--gevent-port`. En prod no se expone 8072.
Si el deploy choca igual (carrera), el error indica quién ocupa el puerto.

### 4.3 Módulos (rama automática, nunca se pregunta)

Rama = versión (`18` → `18.0`). Una sola puerta `¿Qué instalar?`:

- **Plantilla bundle** (todo junto, ver §5).
- **Elegir de lista**: origen `OCA/Ad Hoc/Cybrosys/Odoo Mates/Otro` → repo por número/nombre/URL →
  módulos por número/nombre/`todo` (`1,5` o `auditlog,sentry`). Lo inexistente en esa rama se omite.
- **Nada**.
- **Modo directo avanzado** (sin menú, para scripts): flags `--addon oca/server-tools:auditlog`,
  `--bundle mi.json`, `--sin-addons`.

### 4.4 Dependencias y Dockerfile

Detecta `external_dependencies`, genera `requirements-odoo.txt` y ofrece `Dockerfile`
(pip con `--break-system-packages`, git por apt) pasando el compose a `build`.

### 4.5 Despliegue final

Pregunta `¿Desplegar ahora? (docker compose up -d --build)` con progreso **en vivo**
(el primer build tarda minutos: pull + pip). Avanzado sin menú: `--deploy` / `--sin-deploy`.

### 4.6 Solo instalador (proyecto existente)

Avanzado sin menú (lo normal es la opción 2 del menú):

```bash
omc addons instalar --proyecto <ruta>   # bundle o lista, sin crear nada
```

---

## 5. Módulos: bundle, lista y terceros

### 5.1 Plantilla bundle (`addons-bundle.json`)

```json
{"modulos": [
  {"org": "oca", "repo": "server-tools", "modules": ["auditlog"]},
  {"org": "adhoc", "repo": "odoo-argentina-ce", "modules": ["l10n_ar_afipws"]},
  {"org": "mates", "repo": "odooapps", "modules": ["om_data_remove"]},
  {"org": "custom", "repo": "MiRepo", "url": "https://github.com/MiOrg/MiRepo",
   "branch": "18.0", "modules": ["mi_mod"]}
]}
```

Sin `branch` = rama automática. Hay `addons-bundle.ejemplo.json` de base en cada proyecto.
`"modules": ["*"]` baja el **repo entero** (a pedido explícito; los perfiles traen lista cerrada).

### 5.2 Terceros: Cybrosys y Mates (monorepos con ramas por versión)

Desde el menú opción 2 (Elegir de lista → origen cybrosys/mates). Avanzado sin menú:

```bash
omc addons add --repo CybroAddons --org cybrosys --odoo 18 <mod>
omc addons add --repo odooapps --org mates --odoo 19 om_data_remove
```

### 5.3 Pegar la URL directo (cualquier repo)

En la pregunta `Repo` (o en `add`/`list-modules`) puedes pegar la URL completa;
el programa infiere el origen, usa la rama de tu Odoo y lista los módulos numerados:

```text
Repo: https://github.com/ingadhoc/account-financial-tools
→ Listando adhoc/account-financial-tools rama 18.0 ...
```

Vale https y SSH. Si el repo no tiene la rama de tu Odoo, te muestra cuáles `X.0` sí
existen. Privados https requieren `GITHUB_TOKEN`.

> **Repo de un solo módulo** (ej `onlyone-odoo/dolares_arg`, con `models/`, `views/`,
> `__manifest__.py` en la raíz): el asistente lo detecta y lo clona entero en
> `addons/custom/<repo>` (ya cubierto por `addons_path`, sin elegir subcarpetas).

### 5.4 Otro repo y privados

Desde el menú opción 2 → Otro: pegás la URL y, si es un PR (rama de migración
ej `17.0-mig-web_dark_theme`), te lo pregunta y escribís la rama — lista e instala
desde ahí en vez de la `X.0` automática. El org queda como el dueño real
(ej `berisoft-arg`, que así sale en el bundle) y los clones existentes se actualizan
(`pull --ff-only`) antes de agregar, para que lo listado coincida con lo instalable.
Avanzado sin menú:

```bash
# Cargar tus enlaces al catálogo (quedan numerados en list-catalog y asistente):
omc addons catalog-add --org adhoc --repo account-financial-tools \
  --url https://github.com/ingadhoc/account-financial-tools --desc "Adhoc finanzas"
# O edita directo ~/odoo-manager-compose/addons-catalog.json (secciones oca/adhoc/cybrosys/mates/custom)
```

```bash
omc addons add --repo MiRepo --url https://github.com/MiOrg/MiRepo --branch 18.0 mi_mod
# SSH vale igual: --url git@github.com:MiOrg/MiRepo.git
export GITHUB_TOKEN=ghp_xxx   # privados https (solo memoria, jamás en archivos)
```

### 5.4bis GitHub: token + tu org/usuario (menú 7, o `omc github`)

Guarda token + org en `~/.config/omc/config.json` (0600, nunca en proyectos).
Da: **privados** (clone + API), **cuota** (5000 vs 60 req/h) y **búsqueda de dependencias
en tus repos** (`deps` revisa tu org primero). Token mínimo: classic PAT solo-lectura o
fine-grained Contents:read. Env `GITHUB_TOKEN`/`GITHUB_ORG` pisa lo guardado.

**Sin organización:** donde pide org poné tu **usuario** de GitHub (si el token valida,
se autocompleta solo). Tus repos van como `<usuario>/<repo>`. La contraseña no se usa
nunca (GitHub ya no acepta password para git: el token hace de password y OMC lo
inyecta por header sin guardarlo en el repo). El "name" y "company" del perfil son
fantasía: lo que vale es el **username** (dueño) + el **nombre corto** del repo
(`github.com/<username>/<repo>`).

### 5.5 Módulos propios

Directo en `addons/custom/` (tu git del proyecto los versiona, sin helper).

### 5.6 Localización AR AdHoc (menú 3, o `omc localizar --proyecto <ruta>`)

La opción 3 instala el bundle AdHoc en el proyecto elegido, guarda
`addons/localizacion.json` **con los requirements que trae el repo en esa rama**
(varían por versión de Odoo: se leen del clon descargado, no de una lista fija)
y ofrece correr `sync` (deps + Dockerfile con
m2crypto/SECLEVEL/cache + rebuild). Además genera `scripts/parametros_ar.sh`
(idempotente: crea `ir.config_parameter` si no existen, hoy `report.url`
→ `http://localhost:8069` y `afip.ws.env.type` → `homologation`) y ofrece fijarlos si ya hay BD creada.
En la creación ya no se pregunta localización:
ahí solo se crea el proyecto (los módulos van por opción 2/3 después).
Avanzado sin menú: `--localizacion argentina-adhoc` o `argentina-codize`. Tu flujo manual queda horneado en el Dockerfile:
`python3-m2crypto` por apt (M2Crypto fuera del pip), `SECLEVEL=2→1` y `cache`
de pyafipws con 777. No mezcles variantes AR en un proyecto
(mismo nombre de módulo en dos repos).

---

## 6. `omc addons` (referencia avanzada)

Todo lo de acá se usa desde el **menú opción 2** (bundle/lista + `sync`).
Esta sección es la referencia de los subcomandos directos (scripts, sin menú).

Dentro del proyecto (rama por defecto = la del `.env`), o desde afuera con `--proyecto`:

```bash
omc addons list-catalog [--org oca|adhoc|cybrosys|mates]
omc addons list-modules server-tools --odoo 18
omc addons add --repo server-tools --org oca --odoo 18 auditlog
omc addons bundle addons-bundle.json --odoo 18
omc addons status          # repos + presencia en odoo.conf
omc addons pull [--repo X] # git pull --ff-only de lo descargado
omc addons check-deps      # external_dependencies -> requirements-odoo.txt
omc addons quitar <mod>      # saca módulos (si no queda nada, borra el clon)
omc addons deps [--fix]    # depends entre módulos (ok/base/mismo-repo/falta)
omc addons sync [--bundle X] [--yes] [--no-deploy] [--skip-install]
omc addons export-bundle [--salida F] [--force]
omc addons fix-paths       # migra symlinks legacy a addons_path
omc addons instalar        # solo instalador (bundle o lista), sin crear nada
```

(Cada proyecto trae además un stub `odoo-addons.py` que delega en `omc addons`.)

Notas:

- `add`/`bundle` validan que cada módulo exista en la rama (lo inexistente se omite y no se
  guarda), avisan en el acto si pide otro módulo ausente (nativos como `l10n_ar` no avisan)
  y actualizan `addons_path`.
- `deps` cruza el `depends` con lo descargado + repos clonados + nativos de
  `github.com/odoo/odoo/tree/<ver>/addons` (caché 30 días; manda sobre contenedor/lista).
  Si no está ahí, **no es nativo**: `ok`, `base`, `mismo-repo` o `falta` con comando exacto.
  Nativos = unión de árbol GitHub + contenedor + lista estática (si el API rate-limitea,
  avisa y degrada).
  Estados: `ok`, `base`, `mismo-repo` (candidato a `--fix`) o `falta`.
  Con contenedor apagado lo no descargado sale `base?` sin confirmar (sin sugerencias falsas).
  Lo que falta se busca en el catálogo vía API GitHub (caché en `~.cache`, respeta `GITHUB_TOKEN`)
  y sugiere el comando exacto; `--fix` lo trae solo. `--fix` hace loop (cadenas A→B→C).
  Si no está ni en el catálogo, pregunta: 1) dónde está (OCA/Ad Hoc del catálogo con
  lista y filtro, u Otro por URL), 2) token/org por API, 3) omitir.
- En la opción 2 del menú, tras descargar corre `deps` y ofrece traer faltantes.
  El perfil AdHoc trae solo `odoo-argentina-ce` (FE + IVA); el resto como módulos normales.
- `sync` ordena el círculo: instala → ofrece traer faltantes → **re-escribe `requirements-odoo.txt`
  con lo nuevo** → Dockerfile → build. Sin cambios, no pregunta rebuild.
- Si un nombre existe en varios orgs (ej `account-financial-tools` en OCA y AdHoc),
  manda tu `--org`.
- Tras `sparse-checkout add` se hace `reapply` para materializar el árbol.

---

## 7. Post-despliegue: sync y configuradores

### 7.1 sync (Odoo ya corriendo)

Es la **opción 2 del menú**. Avanzado sin menú:

```bash
cd ~/odoo-manager-compose/mi-proyecto
omc addons sync                              # instalador + deps + rebuild
omc addons sync --bundle addons-bundle.json
omc addons sync --yes / --no-deploy / --skip-install
```

Ofrece el instalador del inicio (bundle o lista), reporte enfocado en lo nuevo,
y UN menú aplicar-todo (Dockerfile si hace falta, rebuild si cambió algo, si no restart).
Antes de aplicar, si `queue_job` (OCA) está descargado deja su config en `odoo.conf`
(`server_wide_modules` con queue_job + `[queue_job] channels = root:2`, fusionando
sin pisar; avisa si `workers = 0` porque el runner no arranca). Vale al instalar
por cualquier vía (opción 2, `add`, `bundle`, sync, crear con flags).
Auto-genera `addons-bundle.json` si falta y auto-actualiza el helper viejo del proyecto.
Si lo corres fuera del proyecto, te dice a cuál entrar (`cd <proyecto>` o `--proyecto`).

### 7.2 Configurar web después (nginx + certbot)

Es la **opción 4 del menú** (pide dominio/email). Avanzado sin menú:

```bash
omc web --proyecto . --dominio odoo.midominio.com --email yo@midominio.com [--staging]
# o interactivo: omc web --proyecto .   (pide dominio/email)
```

Escribe `nginx.conf` (día 1: solo HTTP + challenge certbot, sitio `odoo.conf`),
agrega nginx+certbot al compose (odoo → `expose`), pone
`proxy_mode = True` y guarda dominio/email en `.env`. Idempotente. Al final ofrece
**¿Obtener certificado y activar HTTPS ahora?**: levanta nginx, corre certonly para
dominio + www, reemplaza `nginx.conf` por la estructura final y recarga.

> Equivale a tu `certbot --nginx` manual, pero containerizado: en vez del plugin
> nginx del host se usa `certbot/certbot` con webroot (el nginx también corre en
> compose, no en el host). El certificado cubre **ambos nombres** (apex + www),
> igual que validás a mano, y `renew` los renueva juntos. A mano:

```bash
docker compose up -d
docker compose run --rm certbot certonly --webroot -w /var/www/certbot \
  --email YO --agree-tos --no-eff-email -d DOMINIO -d www.DOMINIO
# reemplazar nginx/nginx.conf por la estructura HTTPS (ver abajo) y:
docker compose exec nginx nginx -s reload
```

Estructura final (`nginx/nginx.conf` → sitio `odoo.conf`): 3 bloques —
HTTP→HTTPS (ambos dominios), www→apex en 443, y principal con HSTS,
`/web/database/manager` → 404, `/websocket` → `odoo:8072`,
`/` → `odoo:8069` (timeouts 36000s, `client_max_body_size 10240m`).
Compresión gzip en `nginx/gzip.conf` (se monta en `conf.d`, contexto http:
nivel 6, buffers 16 8k, tipos texto/json/js/xml/imágenes).

Sin dominio no hay certbot: queda prod directo (el asistente lo normaliza con aviso).

### 7.3 Configurar rclone después (Google Drive)

Es la **opción 5 del menú**. Avanzado sin menú:

```bash
omc rclone --proyecto . [--rclone-remote gdrive]
```

Crea `scripts/rclone.conf`, ofrece correr `rclone config` guiado y verifica el remote.
Sin rclone instalado indica cómo instalarlo. Guarda el remote en `.env`.

---

## 8. Dependencias externas y Dockerfile

`check-deps` lee `external_dependencies` (python/bin) de cada `__manifest__.py` +
`requirements.txt` de módulos y repos (alias `OpenSSL→pyOpenSSL`, match de URLs git).
Genera `requirements-odoo.txt` pineado (ej AdHoc: `pyOpenSSL`,
`git+https://github.com/filoquin/pyafipws.git@py3k`, `pysimplesoap~=1.8.22`).

Dockerfile resultante (pip con `--break-system-packages`, git por apt) y nombres PyPI
normalizados (`OpenSSL`→`pyOpenSSL`; URLs git intactas).

```dockerfile
FROM odoo:18
USER root
# Sistema SIEMPRE antes del pip: git (URLs git+https) + localización (ej python3-m2crypto)
RUN apt-get update && apt-get install -y --no-install-recommends git python3-m2crypto && rm -rf /var/lib/apt/lists/*
COPY requirements-odoo.txt /tmp/requirements-odoo.txt
RUN pip install --no-cache-dir --break-system-packages -r /tmp/requirements-odoo.txt
# + SECLEVEL=1 y cache pyafipws si hay localización
USER odoo
```

- `--break-system-packages`: exigido por Debian 12 (PEP 668).
- `git` por apt: necesario para dependencias `git+https`.
- Binarios de sistema se listan para agregar al `apt-get`.

---

## 9. Prod: nginx, HTTPS, backups y recursos

### 9.1 HTTPS (prod con dominio)

Ver §7.2. Renovar (cron mensual en host):

```bash
docker compose run --rm certbot renew && docker compose exec nginx nginx -s reload
```

### 9.2 Backups y restore (+ Drive) [solo prod: dev no lleva scripts]

```bash
./scripts/backup.sh <nombre_bd>   # dump -Fc + filestore, rotación day1..day7, validado
./scripts/restore.sh             # 100% guiado: local o Drive, doble confirmación, verifica
# Sin BD, backup.sh lista y eliges. Respalda rclone.conf en backups/.
# restore.sh levanta db solo si hace falta (sirve en servidor nuevo) y acepta
# backups de instalaciones desde fuente: si no puede DROP+CREATE, restaura con
# pg_restore --clean --if-exists sobre la BD existente.
# Sin BD, backup.sh lista y eliges. Respalda rclone.conf en backups/.
# Rclone: host si está, si no el servicio `rclone` del compose (perfil backup).
# Rclone sale del compose (servicio `rclone`, perfil `backup`): **nada que instalar en host**.
# Menú 5 lo configura (incluso dentro del servicio) y verifica el remote.
# Cron: 0 3 * * * cd /ruta/<proyecto> && ./scripts/backup.sh <bd> >> backups/cron.log 2>&1
```

### 9.3 Recursos y Postgres

Límites `deploy.resources` en compose (editables vía `ODOO_CPUS/MEM`, `DB_CPUS/MEM` en `.env`)
y tuning Postgres (`PG_*` en `.env`, aplicado como `command:` al contenedor db).
En prod pregunta **vCPUs y RAM del VPS** (sugiere lo local) y reparte: sistema+nginx fijos,
odoo ~70%CPU/62%RAM, db resto; PG 20%/50% (shared topado al 60% del límite del
contenedor db para no OOMear en VPS chicos) y workers `2CPU+1` (en `.env` queda `VPS_*`).
`odoo.conf` lleva los límites escalados: `limit_memory_soft` = RAM_odoo/workers
(piso 256MB), `limit_memory_hard` = soft×1.5 (antes fijos 2GB/2.5GB).
Avanzado sin menú: `--vcpus`, `--ram-gb`, `--odoo-cpus/mem`, `--db-cpus/mem`.

### 9.4 Duplicar instancia (módulos + datos)

Duplicar = **bundle** (qué código) + **backup/restore** (qué datos). Son dos piezas separadas:

**1) Extraer el bundle (código).** El `.json` con org/repo/módulos (+ `branch` si no
es la default, + `url` si es custom) se mantiene solo: cada descarga (opción 2) y
cada sync fusiona lo nuevo en `addons-bundle.json` **sin borrar tus entradas
manuales** (si no existe, lo crea). A mano (avanzado sin menú):
`omc addons export-bundle` (respeta `--salida F`, `--force` para sobrescribir).

**2) Backup (datos).** `./scripts/backup.sh <bd>` (o menú opción 8): dump `-Fc` +
filestore en `backups/full_backup_<bd>_dayN.tar.gz` (+ Drive si hay rclone).

**3) Instancia nueva.** Crear el proyecto (menú opción 1), copiarle el bundle y el tgz:

```bash
# código: menú opción 2 → Plantilla bundle (addons-bundle.json)
# o avanzado: omc addons bundle /ruta/al-bundle.json --odoo 17
# datos: cp full_backup_<bd>_dayN.tar.gz <nuevo>/backups/ && menú opción 9
```

**3bis) Llevar el bundle a otro servidor.** El json es texto plano y chico; desde
tu instancia local de pruebas al destino (VPS):

```bash
scp ~/odoo-manager-compose/mi-proyecto/addons-bundle.json usuario@vps:/opt/nuevo-proyecto/
# datos, si duplicas todo: scp backups/full_backup_<bd>_dayN.tar.gz usuario@vps:/opt/nuevo-proyecto/backups/
```

En el destino, menú opción 2 → Plantilla bundle: la pregunta de ruta acepta el
default (`addons-bundle.json` en la raíz del proyecto) o cualquier ruta absoluta
(ej. `~/bundles/tienda.json`) sin pisar nada. Si versionás el proyecto en git,
commitear el bundle es la vía más repetible.

**4) Restore (datos).** Menú opción 9 o `./scripts/restore.sh`: lista los tgz
(locales o Drive), doble confirmación, para odoo, recrea la BD (`DROP+CREATE`;
si no puede, `--clean --if-exists`, útil con backups de instalaciones desde fuente),
restaura filestore y levanta.

**Límites del bundle:** solo cubre repos de `addons/repos.json` (OCA/AdHoc/terceros/URLs).
Lo propio (`addons/custom/`, tu código) **no** va en el json: se copia por git o archivos.
Si la instancia es AR, aplicar opción 3 (localización) en la nueva también
(`localizacion.json` + Dockerfile + parámetros no viajan en el bundle).

---

## 10. Puertos y múltiples instancias

Cada proyecto dev usa dos puertos host configurables (`ODOO_PORT → 8069`,
`ODOO_GEVENT_PORT → 8072`), guardados en `.env`. Ver ocupados:

```bash
docker ps --format 'table {{.Names}}\t{{.Ports}}'
```

---

## 11. Docker útil

```bash
docker compose up -d --build
docker compose logs -f odoo
docker compose restart odoo
docker compose stop / down        # down -v BORRA la BD
docker compose exec db pg_dump -U odoo postgres > backup.sql
```

---

## 12. Solución de problemas

| Síntoma | Causa | Fix |
|---|---|---|
| `Bind 0.0.0.0:8072 failed: port is already allocated` | Otro proyecto dev usa ese puerto host | El asistente valida y asigna libres (`ODOO_GEVENT_PORT`); ver `docker ps` |
| `FATAL: database "odoo" does not exist` cada 10s | Healthcheck `pg_isready -U odoo` sin `-d` (conecta a BD `odoo`) | Ya lleva `-d postgres` en plantillas; `up -d` para aplicar |
| `ERROR: column "name" does not exist` en `ir_cron` | El monitor pedía `name`; en Odoo 18 es `cron_name` | Monitor detecta la columna (reinícialo para tomar el fix) |
| `externally-managed-environment` (PEP 668) | Imagen Odoo = Debian 12 | Dockerfile ya lleva `--break-system-packages` |
| `Cannot find command 'git'` en build | Dep con URL `git+https`, imagen sin git | Dockerfile ya instala git por apt |
| `couldn't write the config file` | `odoo.conf` montado `:ro` | Montar sin `:ro` (ya en plantillas) |
| `logfile reads 'False' ... skip` (Odoo 19) | `logfile` no acepta booleano | Sin línea `logfile` (= stdout, ya en plantillas) |
| `invalid addons directory '/mnt/extra-addons'` | `addons/` vacío | Inofensivo; desaparece al agregar módulos |
| `missing --http-interface` (Odoo 19) | Aviso, default cambia en 20.0 | `http_interface = 0.0.0.0` en plantilla |
| `pysimplesoap` 1.8.14 vs `pyafipws` (quiere `==1.8.22`) | Requirements de Codize pinean `stable_py3k` (viejo) | El asistente fuerza `pysimplesoap==1.8.22` si hay pyafipws; regenera con `check-deps` |
| `cron connection already closed` / `Unexpected indentation` | Arranque inicial / RST | Inofensivo si la web carga |
| `sync`: no estás en un proyecto | Se corrió desde `~/odoo-manager-compose` | `cd <proyecto>` o `--proyecto <ruta>` |
| git pide `Username/Password` en loop (o `Authentication failed`) | Privado sin token válido (o expirado/sin scope) | Menú 7 (validar token, scope `repo`/Contents, org = tu usuario) o `export GITHUB_TOKEN=...`; git ya no pregunta, falla rápido con el motivo |
| Módulo NO existe en repo@rama | Nombre mal o sin esa rama (u org equivocado) | Se omite sin guardar; re-listar (el `--org` manda) |
| Deploy "colgado" | Primer build tarda (pull + pip) sin salida | Progreso ahora en vivo; esperar o revisar `docker ps` |

---

## 13. Archivos del dir maestro (`~/odoo-manager-compose`)

```text
src/omc/                      # paquete (cli, core, tui, github, gitutils, manifest,
                              #          addonsops, addons_cli, compose, flows, migrate, webapp)
src/omc/templates/            # compose dev/prod/migrate, odoo.conf, nginx, Dockerfile, backup/restore, README
src/omc/versions/             # 17.env (pg15), 18.env / 19.env (pg16)
src/omc/data/                 # addons-catalog.json, localizaciones.json, addons-bundle.ejemplo.json
pyproject.toml                # pip install odoo-manager-compose -> comandos omc, omc-monitor
requirements.txt              # runtime (flask + gunicorn) para `pip install -r` en venv
deploy-vps.sh                 # instalación nativa en VPS (venv + systemd, idempotente)
tests/                        # suite pytest (29 tests)
src/omc/monitor/              # monitor Flask solo-lectura (lo sirve `omc-monitor`)
Manual-omc.md                 # este manual
<nombre>/                     # TUS proyectos viven aquí (~/odoo-manager-compose/<nombre> o $OMC_HOME)
```

> Los JSON de `src/omc/data/` son los defaults empaquetados. Si creas
> `~/odoo-manager-compose/addons-catalog.json` (o te lo genera `omc addons catalog-add`),
> esa copia manda: es tu capa editable y no se pisa al actualizar el paquete.

---

## 14. Monitor web (`src/omc/monitor/app.py`, Flask, SOLO lectura)

Desde el **menú opción 6** (frente/fondo/stop). Avanzado sin menú:

```bash
omc-monitor                                  # http://127.0.0.1:8765 (token en consola)
omc-monitor --port 8765 --token MI_TOKEN_LARGO
omc-monitor --port 8765 --fondo              # fondo, libera la terminal
omc-monitor --estado                         # ver si corre
omc-monitor --stop                           # detenerlo
# VPS: omc-monitor --host 0.0.0.0 --token MI_TOKEN_LARGO  (nunca sin token)
# o env: ODOO_WEB_TOKEN=... omc-monitor --host 0.0.0.0
```
El menú 6 del asistente (`omc` sin args) es la vía normal; lo de arriba son atajos directos.

- Pestañas: **Proyectos** (versión, puerto, dominio, `x/y en marcha` + visor de logs por
  servicio con auto-refresh) y **Contenedores** (`docker ps` global con auto-refresh).
- Una sola landing **Odoo Creator Compose — Monitor**: proyectos + contenedores + logs
  (sin pestañas). Tema claro/oscuro: marfil `#ECDFD2`/gris `#CCCACC`/negro y blanco,
  primario `#5F3475`, acento `#893172`.
- **Métricas** por proyecto (auto 20s, todo solo-lectura): conexiones PG vs `max_connections`,
  lentas >5s, bloqueos, tamaño por BD + crecimiento ~24h (historial local), cron activos por BD,
  CPU/RAM por contenedor (`docker stats`), disco + backups, último backup (fecha/tamaño/db.dump),
  días de SSL y 5xx recientes de nginx. La password de PG nunca sale del servidor.
- A propósito sin crear/editar/borrar nada: mantiene el espíritu del asistente de terminal.

---

## 15. Instalación (venv, sin Docker)

**Desde el repo (desarrollo):**

```bash
pip install -e .            # editable: los cambios en src/ aplican al acto
omc                # abre el menú: todo se elige ahí (crear, sync, localizar, ...,
                   # web, rclone, monitor, github, backup, restore, migrar; 0 = salir)
```

Diagnóstico directo (atajos sin menú):

```bash
omc list           # lista instancias en la raíz de proyectos ($OMC_PROJECTS, default /opt)
omc doctor         # valida compose/conf/addons/.env por instancia
omc doctor --fix   # repara addons_path si hace falta
```

**En venv aislado (recomendado fuera de desarrollo):**

```bash
python3 -m venv ~/.venv/omc
~/.venv/omc/bin/pip install -r requirements.txt   # runtime: flask + gunicorn
~/.venv/omc/bin/pip install --no-deps .           # registra el paquete
ln -sf ~/.venv/omc/bin/omc ~/.local/bin/omc
ln -sf ~/.venv/omc/bin/omc-monitor ~/.local/bin/omc-monitor
```

Los paquetes de migración OCA (`odoo-module-migrator`, `openupgradelib`) no se
preinstalan: `omc migrar` ofrece bajarlos con pip si faltan (con `--yes`, solos).

**Distribución:** `pip install odoo-manager-compose` (cuando se publique) o clon + venv.
Sin imagen Docker: `omc` corre nativo y controla el Docker del host para los proyectos.

---

## 16. Migración entre versiones Odoo (OCA)

Flujo autoguiado en dos etapas: primero el **código** de los módulos, después la **base de datos**.
Se usa desde el menú (opción 10) o directo:

```bash
omc migrar --proyecto ./mi-odoo --destino 19
omc migrar --proyecto ./mi-odoo --destino 19 --db mi_bd --sin-codigo
```

**Etapa 1 — módulos:** lee `repos.json` + `custom/`/`extras/` y para cada módulo verifica si ya
existe migrado a la versión destino (rama `X.0` en OCA/AdHoc/... vía `ls-remote`, sin clonar).
Clasifica: `✓` migrado upstream, `✗` sin migrar, `~` custom (código propio, sin upstream).
Para los sin migrar ofrece correr `odoo-module-migrator` (si falta, lo ofrece
instalar con pip en el momento; con `--yes` se instala solo)
sobre **copias** en `<proyecto>/migracion/<mod>/` — nunca muta el proyecto; revisa el diff antes de usar.

**Etapa 2 — BD:** clona `OCA/OpenUpgrade` en la rama destino (sparse: solo `openupgrade_framework`
+ `openupgrade_scripts`, se registra en `repos.json`), deja `openupgradelib` importable
(si falta, lo instala por pip; no reinstala si ya está), genera
`docker-compose.migrate.yml` (override con la **imagen Odoo destino** — sin esto la migración
correría con los binarios origen y no migraría nada) y `scripts/migrate_db.sh` (backup previo +
`docker compose -f docker-compose.yml -f docker-compose.migrate.yml run --rm odoo --
--database BD --update all --stop-after-init --load=base,web,openupgrade_framework`).

**Limitaciones:**
- OpenUpgrade exige pasar por cada versión intermedia: 17→19 se hace en dos corridas (17→18, 18→19);
  el asistente lo detecta y propone el primer salto.
- Siempre hay backup antes de migrar la BD (`scripts/backup.sh`).
- Los módulos custom requieren migración manual del código (el migrador ayuda, no hace magia).

---

## 17. VPS con deploy-vps.sh

**Instalación express en un VPS nuevo (tres pasos, un bloque por pegada):**

Paso 1 — base:

```bash
sudo apt update && sudo apt install -y python3 python3-venv git curl
```

Docker + compose (solo origen oficial): si ya responden, el deploy los respeta
tal cual; si faltan, el deploy instala el repo oficial solo. Nunca `docker.io`
junto a Docker oficial (chocan `containerd`/`containerd.io`). Tras el deploy:
re-login (o `newgrp docker`) por el grupo docker.

Paso 2 — omc (el deploy prepara /opt/omc + /opt con sudo único; uso diario sin sudo):

```bash
git clone https://github.com/berisoft-arg/odoo-manager-compose.git ~/odoo-manager-compose
cd ~/odoo-manager-compose && ./deploy-vps.sh
```

Raíces custom: `OMC_HOME=... OMC_PROJECTS=... ./deploy-vps.sh` (datos y proyectos).

Paso 3 — verificar:

```bash
omc --version && omc list   # `omc` pelado abre el menú 1-10
```

Instalación nativa (venv aislado + monitor como servicio, sin Docker para `omc`):

```bash
git clone <tu-repo> ~/odoo-manager-compose
cd ~/odoo-manager-compose
./deploy-vps.sh   # defaults: datos /opt/omc, proyectos /opt/<nombre>
# Raíces custom: OMC_HOME=... OMC_PROJECTS=... ./deploy-vps.sh
# (~/omc-data y ~/odoo-manager-compose existentes se respetan: migración)
```

El script es idempotente: verifica prerrequisitos (Python ≥3.10, `python3-venv`, git,
docker + plugin compose, systemd de usuario), deja escribibles `/opt/omc` (datos)
y `/opt` (proyectos) con sudo **una sola vez** (uso diario sin sudo), crea
`~/.venv/omc`, instala `requirements.txt` + el paquete, deja symlinks en
`~/.local/bin`, genera token si no le pasás `ODOO_WEB_TOKEN`, y habilita
`omc-monitor` (`systemctl --user`).

Raíz de proyectos (`list`/`doctor`/`elegir`/monitor la escanean):
`$OMC_PROJECTS` → `$OMC_HOME` (compat) → `~/odoo-manager-compose` existente →
`~/odoo-create` existente → `/opt`. Datos: `$OMC_HOME` → legados → `/opt/omc`.
`crear` genera en `<proyectos>/<nombre>` (pregunta `Carpeta del proyecto` en el
menú; `--salida` manda; sin permiso sale con la instrucción de sudo único).

Variables: `REPO_DIR`, `VENV_DIR`, `OMC_HOME`,
`MONITOR_PORT` (8765), `MONITOR_HOST` (127.0.0.1), `ODOO_WEB_TOKEN`.

```bash
sudo loginctl enable-linger $USER   # arrancar el monitor sin login
systemctl --user status omc-monitor # logs/estado
```

Prerrequisitos del host: solo Docker (para los proyectos Odoo que `omc` genera/despliega).
`omc` mismo corre nativo: se abre el menú y se elige (crear, sync, monitor, etc.);
`omc list` / `omc doctor` quedan como diagnóstico directo.
