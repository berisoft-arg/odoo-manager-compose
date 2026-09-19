# Odoo Manager Compose (`omc`)

Crea, opera y migra instancias **Odoo 17 / 18 / 19** con docker-compose.
Asistente interactivo + CLI + monitor web + migración OCA entre versiones.

> Documentación completa en [Manual-omc.md](Manual-omc.md).

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
  (contenedores, cron, colas), tema claro/oscuro, token de acceso.
- **Migración OCA** (`omc migrar`): etapa 1 código (`odoo-module-migrator`,
  clasifica migrado/sin-migrar/custom sin mutar el proyecto), etapa 2 BD
  (OpenUpgrade + `docker-compose.migrate.yml`), con backup previo siempre.
- **Backup/restore**: dump PostgreSQL + filestore, local o Drive, con doble
  confirmación al restaurar.
- **Multi-instancia**: puertos validados y sugeridos libres, `ODOO_GEVENT_PORT`,
  `omc list` / `omc doctor [--fix]`.

## Requisitos

Python 3.10+, Git, Docker con plugin compose. Para repos privados en https:
`export GITHUB_TOKEN=...` (solo memoria, nunca se guarda).

## Instalación

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

**En Debian / Ubuntu — cualquier entorno (desde cero):**

```bash
# 1) Sistema base
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git curl

# 2) Docker oficial (si ya tenés docker compose, deploy-vps.sh lo saltea y lo respeta)
#    Si no está, deploy-vps.sh instala el repo oficial solo (nunca docker.io).
#    Manual alternativo (repo oficial): https://docs.docker.com/engine/install/ubuntu/
#    Luego: re-login o `newgrp docker` por el grupo docker.

# 3) Bajar OMC (no clonar dentro de odoo-manager-compose)
git clone https://github.com/berisoft-arg/odoo-manager-compose.git ~/odoo-manager-compose
cd ~/odoo-manager-compose

# 4) Instalar (venv aislado + monitor systemd) — idempotente, se puede re-ejecutar para actualizar
./deploy-vps.sh
# Opcionales: OMC_PROJECTS=... OMC_HOME=... MONITOR_PORT=8765 ./deploy-vps.sh
#            ODOO_WEB_TOKEN=... ./deploy-vps.sh  # si no, se genera uno y se muestra una vez

# 5) Verificar
~/.local/bin/omc --version   # lee src/omc/__init__.py
omc                          # abre el menú interactivo (1-10, 0 salir)
systemctl --user status omc-monitor
# Para que arranque sin login: sudo loginctl enable-linger $USER
# Actualizar: cd ~/odoo-manager-compose && git pull && ./deploy-vps.sh
```

**Desde Git (pip, recomendado en otro venv):**

```bash
pip install "git+https://github.com/berisoft-arg/odoo-manager-compose.git"
```

Los paquetes de migración OCA se instalan a demanda: `omc migrar` los ofrece
bajar con pip si faltan (sin flags extra en la instalación).

**En venv aislado (manual, sin deploy-vps.sh):**

```bash
python3 -m venv ~/.venv/omc
~/.venv/omc/bin/pip install -r requirements.txt   # runtime: flask + gunicorn
~/.venv/omc/bin/pip install --no-deps .
ln -sf ~/.venv/omc/bin/omc ~/.local/bin/omc
ln -sf ~/.venv/omc/bin/omc-monitor ~/.local/bin/omc-monitor
```

**En VPS (producción):** clonar y correr `./deploy-vps.sh` — crea el venv,
instala, deja symlinks, genera token y habilita `omc-monitor` como servicio
systemd de usuario. Si `docker compose` ya está instalado lo respeta; si falta
lo instala del repo oficial (Debian/Ubuntu con `apt` + `sudo`, nunca `docker.io`). Ver [Manual §17](Manual-omc.md#17-vps-con-deploy-vpssh).

**Desarrollo:**

```bash
pip install -e .
omc       # abre el menú interactivo
```

## Uso rápido

```bash
omc                 # menú: crear, localizar, addons, nginx, rclone, monitor,
                    #        github, backup, restore, migrar
omc crear --nombre mi-tienda --version 18 --entorno prod
omc addons add --repo server-tools --org oca --odoo 18 auditlog
omc addons bundle addons-bundle.json --odoo 18
omc addons sync
omc localizar --proyecto /opt/mi-tienda
omc monitor --puerto 8765
omc doctor --fix
omc migrar
```

## Estructura del repo

```text
src/omc/            # paquete (cli, core, tui, github, gitutils, manifest,
                    #          addonsops, addons_cli, compose, flows, migrate, webapp)
src/omc/templates/  # compose dev/prod/migrate, odoo.conf, nginx, Dockerfile, backup/restore
src/omc/versions/   # 17.env (pg15), 18.env / 19.env (pg16)
src/omc/data/       # catálogo de addons, localizaciones, bundle ejemplo
src/omc/monitor/    # monitor Flask solo-lectura (lo sirve `omc-monitor`)
tests/              # suite pytest
requirements*.txt   # runtime (+migración) para pip install en venv
deploy-vps.sh       # instalación nativa en VPS (venv + systemd)
Manual-omc.md       # documentación completa
```

## Licencia

AGPL-3.0 — ver [LICENSE](LICENSE).
