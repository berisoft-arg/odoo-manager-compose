#!/usr/bin/env bash
# Odoo Manager Compose — instalación nativa en VPS (venv aislado, sin Docker para omc).
# Uso:
#   git clone <tu-repo> /opt/odoo-manager-compose
#   cd /opt/odoo-manager-compose
#   OMC_HOME=/opt/omc OMC_PROJECTS=/opt ./deploy-vps.sh   (defaults; rara vez hace falta)
#
# Variables (todas opcionales, con defaults sensatos):
#   REPO_DIR=...       código (default: dir de este script)
#   VENV_DIR=...       entorno virtual (default: ~/.venv/omc; se crea si falta)
#   OMC_HOME=...       datos de usuario (default: /opt/omc; se deja escribible una vez)
#   OMC_PROJECTS=...   raíz de proyectos (default: /opt → /opt/<proyecto>)
#   MONITOR_PORT=...   puerto del monitor (default: 8765)
#   MONITOR_HOST=...   bind del monitor (default: 127.0.0.1; VPS público: reverse-proxy TLS)
#   ODOO_WEB_TOKEN=... token del monitor (default: se guarda en el servicio;
#   se consulta en omc opción 6, nunca se imprime acá)
#
# Idempotente: se puede correr de nuevo para actualizar (reinstala en el venv + reinicia).
set -euo pipefail

REPO_DIR="${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
VENV_DIR="${VENV_DIR:-$HOME/.venv/omc}"
OMC_HOME="${OMC_HOME:-/opt/omc}"
OMC_PROJECTS="${OMC_PROJECTS:-/opt}"
MONITOR_PORT="${MONITOR_PORT:-8765}"
MONITOR_HOST="${MONITOR_HOST:-127.0.0.1}"
UNIT_DIR="$HOME/.config/systemd/user"
BIN_DIR="$HOME/.local/bin"

log()  { printf '== %s\n' "$*"; }
fail() { printf 'XX %s\n' "$*" >&2; exit 1; }

# --- 0) Auto-limpieza experimento Docker -------------------------------------------
# Si quedó la función omc() del experimento omc-docker en ~/.bashrc, tapa al
# binario nativo: se borra solo ese bloque marcado (el resto no se toca).
BRC="$HOME/.bashrc"
if [ -f "$BRC" ] && grep -q "omc-docker" "$BRC" 2>/dev/null; then
  sed -i '/# >>> omc-docker >>>/,/# <<< omc-docker <<</d' "$BRC"
  log "Limpieza: bloque legacy omc-docker borrado de $BRC (abrí shell nuevo)"
fi

# --- 1) Prerrequisitos -------------------------------------------------------
log "Chequeando prerrequisitos..."
command -v python3 >/dev/null || fail "falta python3 (apt install python3)"
python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" \
  || fail "se necesita Python >= 3.10 ($(python3 --version 2>&1))"
python3 -c "import venv, ensurepip" 2>/dev/null \
  || fail "falta python3-venv (apt install python3-venv)"
command -v git >/dev/null || fail "falta git (apt install git)"
# Docker + compose OFICIAL (único origen válido): si ya responden, no se toca
# nada — jamás migrar un motor en uso ni mezclar con docker.io de Ubuntu.
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  log "Docker + compose OK — saltea instalación ($(docker --version 2>&1) / $(docker compose version 2>&1))"
elif command -v docker >/dev/null 2>&1; then
  fail "hay engine docker pero sin plugin compose: instalá el plugin oficial (https://docs.docker.com/engine/install/) y corre ./deploy-vps.sh de nuevo. No se auto-migra un motor en uso."
else
  log "Docker no encontrado — instalando desde el repo oficial..."
  if command -v apt-get >/dev/null 2>&1 && command -v sudo >/dev/null 2>&1; then
    # shellcheck disable=SC1091
    . /etc/os-release
    case "${ID:-debian} ${ID_LIKE:-}" in
      ubuntu* | *ubuntu*) REPO_OS=ubuntu ;; # Ubuntu + derivados (Mint, Pop!_OS)
      *) REPO_OS=debian ;;
    esac
    CODENAME="${VERSION_CODENAME:-stable}"
    ARCH="$(dpkg --print-architecture)"
    sudo apt-get update -qq
    sudo apt-get install -y ca-certificates curl gnupg
    sudo install -m 0755 -d /etc/apt/keyrings
    sudo curl -fsSL "https://download.docker.com/linux/${REPO_OS}/gpg" -o /etc/apt/keyrings/docker.asc
    sudo chmod a+r /etc/apt/keyrings/docker.asc
    echo "deb [arch=${ARCH} signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/${REPO_OS} ${CODENAME} stable" \
      | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
    sudo apt-get update -qq
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin \
      || fail "no se pudo instalar docker oficial (instalalo manual: https://docs.docker.com/engine/install/)"
    sudo systemctl enable --now docker 2>/dev/null || true
    if ! id -nG "$USER" 2>/dev/null | grep -qw docker; then
      sudo usermod -aG docker "$USER"
      echo "AVISO: te agregué al grupo docker — re-logueate o hacé 'newgrp docker' y corre ./deploy-vps.sh de nuevo"
    fi
    docker compose version >/dev/null 2>&1 || fail "docker compose sigue sin estar disponible tras la instalación"
    log "Docker + compose instalado ($(docker --version 2>&1) / $(docker compose version 2>&1))"
  else
    fail "falta docker / compose y no hay apt/sudo para instalarlo. Instalá manual: https://docs.docker.com/engine/install/"
  fi
fi
docker ps >/dev/null 2>&1 || fail "docker no accesible: sudo usermod -aG docker $USER y re-logueate"
command -v systemctl >/dev/null || fail "falta systemctl (se necesita systemd)"
systemctl --user status >/dev/null 2>&1 || fail "sin sesión systemd de usuario (conectate por SSH normal)"

# --- 2) venv + install ---------------------------------------------------------
if [ ! -x "$VENV_DIR/bin/python" ]; then
  log "Creando venv en $VENV_DIR..."
  python3 -m venv "$VENV_DIR" || fail "no se pudo crear el venv"
else
  log "venv existente en $VENV_DIR."
fi
log "Instalando requirements (requirements.txt) en el venv..."
"$VENV_DIR/bin/pip" install -q -r "$REPO_DIR/requirements.txt" || fail "pip install requirements falló"
log "Registrando odoo-manager-compose (sin re-resolver deps)..."
"$VENV_DIR/bin/pip" install -q --no-deps "$REPO_DIR" || fail "pip install falló"
[ -x "$VENV_DIR/bin/omc" ] || fail "omc no quedó instalado en el venv"

# --- 3) Symlinks para uso comodo ------------------------------------------------
mkdir -p "$BIN_DIR"
ln -sf "$VENV_DIR/bin/omc" "$BIN_DIR/omc"
ln -sf "$VENV_DIR/bin/omc-monitor" "$BIN_DIR/omc-monitor"
log "Symlinks: $BIN_DIR/omc -> $VENV_DIR/bin/omc"
PATH_MARK="# omc en PATH (deploy-vps.sh)"
case ":$PATH:" in
  *":$BIN_DIR:"*)
    log "$BIN_DIR ya está en tu PATH."
    ;;
  *)
    if ! grep -qF "$PATH_MARK" "$BRC" 2>/dev/null; then
      [ -f "$BRC" ] || touch "$BRC"
      printf '\n%s\nexport PATH="$HOME/.local/bin:$PATH"\n' "$PATH_MARK" >> "$BRC"
    fi
    log "Agregado $BIN_DIR a tu PATH en $BRC (abrí shell nuevo o corre: export PATH=\"\$HOME/.local/bin:\$PATH\")"
    ;;
esac

# --- 4) Datos + raíz de proyectos -------------------------------------------------
# Sudo único: se dejan escribibles una vez; el uso diario no necesita sudo.
asegurar_dir() {
  local d="$1" rol="$2"
  if [ -d "$d" ] && [ -w "$d" ]; then
    log "$rol: $d (ya escribible)"
    return 0
  fi
  if command -v sudo >/dev/null 2>&1; then
    sudo mkdir -p "$d" && sudo chown "$(id -u):$(id -g)" "$d" \
      || fail "sudo no pudo preparar $d"
  else
    fail "$d no es escribible y no hay sudo: sudo mkdir -p $d && sudo chown $(id -u):$(id -g) $d"
  fi
}
asegurar_dir "$OMC_HOME" "OMC_HOME (datos)"
asegurar_dir "$OMC_PROJECTS" "OMC_PROJECTS (proyectos)"
log "OMC_HOME=$OMC_HOME OMC_PROJECTS=$OMC_PROJECTS"

# --- 5) Token del monitor ---------------------------------------------------------
# Orden: exportado > reutilizado del servicio existente > generado (solo re-deploy
# no rota el token: si querés uno nuevo, exportá ODOO_WEB_TOKEN antes de correr).
if [ -n "${ODOO_WEB_TOKEN:-}" ]; then
  GENERADO=0
  ORIGEN_TOKEN="provisto por vos"
else
  PREVIO="$(grep -E '^Environment=ODOO_WEB_TOKEN=' "$UNIT_DIR/omc-monitor.service" 2>/dev/null | cut -d= -f3- || true)"
  if [ -n "$PREVIO" ]; then
    ODOO_WEB_TOKEN="$PREVIO"
    GENERADO=0
    ORIGEN_TOKEN="reutilizado del servicio existente"
  else
    ODOO_WEB_TOKEN="$("$VENV_DIR/bin/python" -c 'import secrets; print(secrets.token_urlsafe(32))')"
    GENERADO=1
    ORIGEN_TOKEN="generado y guardado en el servicio"
  fi
fi

# --- 6) Servicio systemd de usuario -------------------------------------------------
mkdir -p "$UNIT_DIR"
UNIT="$UNIT_DIR/omc-monitor.service"
log "Escribiendo $UNIT..."
cat > "$UNIT" <<EOF
[Unit]
Description=Odoo Manager Compose - Monitor web (solo lectura)
After=network.target

[Service]
Type=simple
Environment=OMC_HOME=$OMC_HOME
Environment=OMC_PROJECTS=$OMC_PROJECTS
Environment=ODOO_WEB_TOKEN=$ODOO_WEB_TOKEN
ExecStart=$VENV_DIR/bin/omc-monitor --host $MONITOR_HOST --port $MONITOR_PORT
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF
chmod 600 "$UNIT"  # el token vive acá: solo lectura del dueño
systemctl --user daemon-reload
systemctl --user enable --now omc-monitor >/dev/null
sleep 2
if systemctl --user is-active --quiet omc-monitor; then
  log "Monitor activo."
else
  fail "el servicio no arrancó: systemctl --user status omc-monitor / journalctl --user -u omc-monitor"
fi

# --- 6b) Linger (monitor sin login) --------------------------------------------------
# Se intenta activar (como root o con sudo no-interactivo sale solo); si no,
# queda la instrucción manual en el resumen.
if loginctl enable-linger "$USER" 2>/dev/null || sudo -n loginctl enable-linger "$USER" 2>/dev/null; then
  log "Linger activado (el monitor sobrevive sin login)."
  LINGER_OK=1
else
  LINGER_OK=0
fi

# --- 7) Resumen ----------------------------------------------------------------------
echo ""
echo "Odoo Manager Compose listo."
echo "  omc:        $($VENV_DIR/bin/omc --version) ($BIN_DIR/omc -> venv)"
echo "  OMC_HOME:   $OMC_HOME (datos)"
echo "  Proyectos:  $OMC_PROJECTS/<nombre> (ej. $OMC_PROJECTS/mi-odoo)"
echo "  Monitor:    http://$MONITOR_HOST:$MONITOR_PORT"
if [ "$GENERADO" = "1" ]; then
  echo "  Token:      (generado y guardado en el servicio; verlo en omc → opción 6)"
else
  echo "  Token:      ($ORIGEN_TOKEN)"
fi
echo "  Token en:   $UNIT (grep ODOO_WEB_TOKEN; permiso 600)"
echo ""
if [ "${LINGER_OK:-0}" = "1" ]; then
  echo "  Linger:       activado (el monitor sobrevive sin login)"
else
  echo "  Para que arranque sin login:  sudo loginctl enable-linger $USER"
fi
echo "  Logs:                         systemctl --user status omc-monitor"
echo "  Actualizar:                   cd $REPO_DIR && git pull && ./deploy-vps.sh"
echo "  Repos privados GitHub:        export GITHUB_TOKEN=...  (memoria, no se guarda)"
echo ""
echo "  Agregá a tu ~/.bashrc si OMC_HOME/OMC_PROJECTS no persisten entre sesiones:"
echo "    export OMC_HOME=$OMC_HOME OMC_PROJECTS=$OMC_PROJECTS"
