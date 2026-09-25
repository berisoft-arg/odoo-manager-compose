#!/usr/bin/env bash
# Restore {{PROYECTO}} — 100% autoguiado (también acepta args para automatizar).
# Uso guiado: ./scripts/restore.sh
# Uso directo: ./scripts/restore.sh <nombre_bd> <full_backup.tgz|*.dump|carpeta> [--drive|--local]
#   --drive: baja el tgz de Google Drive (rclone) antes de restaurar.
#   --local: fuerza local aunque haya Drive (default: local primero).
# Acepta full_backup_*.tar.gz, *.dump sueltos (+ filestore*.tgz hermano)
# o carpeta con db.dump (+ filestore.tgz opcional).
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f .env ]; then
  set -a; . ./.env; set +a
fi
REMOTE="${RCLONE_REMOTE:-gdrive}"
RCFG="scripts/rclone.conf"; [ -s "$RCFG" ] || RCFG="$HOME/.config/rclone/rclone.conf"
SLUG=$(basename "$PWD" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9-_')
BD=""
SRC=""
DRIVE=0
for _a in "$@"; do
  case "$_a" in
    --drive) DRIVE=1 ;;
    --local) DRIVE=0 ;;
    --neutralizar|--sin-neutralizar) ;;  # los procesa el bloque final
    *) if [ -z "$BD" ]; then BD="$_a"; elif [ -z "$SRC" ]; then SRC="$_a"; fi ;;
  esac
done

elegir_archivo() {
  echo "Backups locales (full_backup_*.tar.gz, *.dump o carpeta con db.dump):"
  mapfile -t CANDS < <({ ls -t backups/full_backup_*.tar.gz backups/*.dump 2>/dev/null; for d in backups/*/; do [ -f "${d}db.dump" ] && echo "${d%/}"; done; } 2>/dev/null || true)
  echo "  0) Bajar de Drive ($REMOTE:{{PROYECTO}}/)"
  if [ "${#CANDS[@]}" -eq 0 ]; then echo "  (ninguno local)"; fi
  i=1; for f in "${CANDS[@]}"; do echo "  $i) $f"; i=$((i+1)); done
  read -rp "Elige [0-${#CANDS[@]}]: " N
  if [ "$N" = "0" ]; then DRIVE=1; return 0; fi
  SRC="${CANDS[$((N-1))]:-}"
  [ -n "$SRC" ] || { echo "Selección inválida."; exit 1; }
}

if [ -z "$SRC" ]; then
  [ -t 0 ] || { echo "Uso: $0 <nombre_bd> <full_backup.tgz|*.dump|carpeta> [--drive|--local]"; exit 1; }
  elegir_archivo
fi

if [ "$DRIVE" -eq 1 ]; then
  [ -t 0 ] || { echo "Drive requiere terminal para elegir."; exit 1; }
  echo "En Drive ($REMOTE:{{PROYECTO}}/):"
  RCLONE="docker compose --profile backup run --rm rclone"
  # shellcheck disable=SC2086
  mapfile -t REMOTOS < <($RCLONE lsf "$REMOTE:{{PROYECTO}}/" 2>/dev/null | grep "^full_backup_" || true)
  [ "${#REMOTOS[@]}" -eq 0 ] && { echo "Nada en Drive (¿remote/config?)."; exit 1; }
  i=1; for f in "${REMOTOS[@]}"; do echo "  $i) $f"; i=$((i+1)); done
  read -rp "Elige [1-${#REMOTOS[@]}]: " N
  AR="${REMOTOS[$((N-1))]:-}"
  [ -n "$AR" ] || { echo "Selección inválida."; exit 1; }
  # shellcheck disable=SC2086
  $RCLONE copy "$REMOTE:{{PROYECTO}}/$AR" backups/ || exit 1
  SRC="backups/$AR"
fi

# Desempaquetar si es el tgz final
if [[ "$SRC" == *.tar.gz ]]; then
  WORK="backups/.restore-tmp"
  rm -rf "$WORK"; mkdir -p "$WORK"
  tar xzf "$SRC" -C "$WORK"
  DUMP=$(find "$WORK" -maxdepth 2 -name "*.dump" | head -n 1)
  FS=$(find "$WORK" -maxdepth 2 \( -name "filestore*.tgz" -o -name "filestore*.tar.gz" \) | head -n 1)
  [ -n "$DUMP" ] || { echo "El tgz no trae *.dump."; exit 1; }
elif [[ "$SRC" == *.dump ]]; then
  # dump suelto: va directo + filestore*.tgz hermano si hay
  DUMP="$SRC"
  FS=""
  for _cand in "$(dirname "$SRC")"/filestore*.tgz "$(dirname "$SRC")"/filestore*.tar.gz; do
    if [ -f "$_cand" ]; then FS="$_cand"; break; fi
  done
else
  DUMP="$SRC/db.dump"
  FS="$SRC/filestore.tgz"
  [ -f "$DUMP" ] || { echo "No existe $DUMP."; exit 1; }
fi

if [ -z "$BD" ]; then
  if [ -t 0 ]; then
    # sugerir por nombre: full_backup_<bd>_dayN.tar.gz, *.dump o carpeta
    SUG=$(basename "$SRC" | sed -E 's/^full_backup_//; s/_day[0-9].*//; s/\.dump$//; s/\.tar\.gz$//')
    read -rp "Base destino [$SUG]: " BD
    BD="${BD:-$SUG}"
  else
    echo "Uso: $0 <nombre_bd> <full_backup.tgz|*.dump|carpeta> [--drive|--local]"
    exit 1
  fi
fi

echo "Voy a BORRAR y recrear la base '$BD' con este backup."
read -rp "Escribe el nombre de la base para confirmar: " CONF
[ "$CONF" = "$BD" ] || { echo "No coincide. Abortado."; exit 1; }

echo "== Asegurando db arriba (sirve en servidor nuevo) =="
docker compose up -d db
echo "  esperando PostgreSQL..."
LISTO=0
for i in $(seq 1 30); do
  if docker compose exec -T db pg_isready -U odoo -d postgres >/dev/null 2>&1; then
    LISTO=1; break
  fi
  sleep 2
done
[ "$LISTO" = "1" ] || { echo "ERROR: db no responde."; exit 1; }

echo "== Parando odoo =="
docker compose stop odoo

echo "== Recreando BD $BD =="
docker compose exec -T db psql -U odoo -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$BD' AND pid <> pg_backend_pid();" || true
if docker compose exec -T db psql -U odoo -d postgres -c "DROP DATABASE IF EXISTS \"$BD\";" \
  && docker compose exec -T db psql -U odoo -d postgres -c "CREATE DATABASE \"$BD\" OWNER odoo;"; then
  LIMPIO=""
else
  # Sin DROP (ej backups de instalaciones desde fuente o sin permiso):
  # se restaura con --clean sobre la BD existente (se crea si falta).
  echo "  (sin DROP+CREATE: restauro con --clean --if-exists)"
  docker compose exec -T db psql -U odoo -d postgres -tAX \
    -c "SELECT 1 FROM pg_database WHERE datname='$BD';" | grep -q 1 \
    || docker compose exec -T db psql -U odoo -d postgres -c "CREATE DATABASE \"$BD\" OWNER odoo;"
  LIMPIO="--clean --if-exists"
fi
docker compose exec -T db env PGPASSWORD="${POSTGRES_PASSWORD:-odoo}" \
  pg_restore -U odoo -d "$BD" --no-owner $LIMPIO < "$DUMP"

# Valida el tgz de filestore y decide cómo aplicarlo (auto-ajuste con aviso).
# Escribe FS_MODO=directo (trae filestore/...) o anidado (trae <algo>/...).
# Retorna 1 si ilegible/vacío/inesperado: no tocar /data.
validar_filestore() {
  FS_MODO=""
  [ -f "$FS" ] || { echo "  ⚠ filestore no encontrado: $FS (se omite)."; return 1; }
  _listado=$(tar tzf "$FS" 2>/dev/null | grep -v '/$' | head -n 50 || true)
  [ -n "$_listado" ] || { echo "  ⚠ filestore ilegible o vacío: $FS (se omite, sin borrar nada)."; return 1; }
  if echo "$_listado" | grep -q '^filestore/'; then
    FS_MODO="directo"
    echo "  filestore con prefijo filestore/ OK."
  elif echo "$_listado" | head -n 1 | grep -q '/'; then
    FS_MODO="anidado"
    echo "  ⚠ filestore sin prefijo filestore/ (trae $(echo "$_listado" | head -n 1 | cut -d/ -f1)/...): se ubica en /data/filestore/$BD."
  else
    echo "  ⚠ filestore con estructura inesperada (se omite, sin borrar nada):"
    echo "$_listado" | head -n 5 | sed 's/^/    /'
    return 1
  fi
}

if [ -n "${FS:-}" ] && [ -f "$FS" ]; then
  echo "== Restaurando filestore =="
  if validar_filestore; then
    if [ "$FS_MODO" = "anidado" ]; then
      _dest="/data/filestore"
    else
      _dest="/data"
    fi
    docker run --rm -v "${SLUG}_odoo-data:/data" -v "$PWD/$(dirname "$FS"):/in" \
      alpine sh -c "rm -rf /data/filestore/$BD && mkdir -p /data/filestore && tar xzf /in/$(basename "$FS") -C $_dest"
    _n=$(docker run --rm -v "${SLUG}_odoo-data:/data" alpine sh -c "find /data/filestore/$BD -type f 2>/dev/null | wc -l")
    echo "  filestore/$BD: ${_n} archivos."
    [ "$_n" -gt 0 ] 2>/dev/null || echo "  ⚠ quedó vacío: revisá el tgz de origen."
  fi
else
  echo "(sin filestore, se omite)"
fi
rm -rf backups/.restore-tmp

docker compose start odoo
echo "== Verificación =="
docker compose exec -T db psql -U odoo -d "$BD" -tAX -c "SELECT count(*) FROM ir_module_module WHERE state='installed';" \
  && echo "(módulos instalados arriba)"
echo "✓ Restaurado. Revisa: docker compose logs -f odoo"
echo "  Ojo: si es otro servidor, ajusta web.base.url en Ajustes > Parámetros del sistema."

# --- Neutralizar (opcional, SOLO copias de desarrollo) ---
# Apaga crons y servidores de mail en la BD para que nada real se dispare
# (mails a clientes, webhooks). JAMÁS en producción.
NEUTRALIZAR=""
for _a in "$@"; do
  case "$_a" in
    --neutralizar) NEUTRALIZAR=si ;;
    --sin-neutralizar) NEUTRALIZAR=no ;;
  esac
done
if [ -z "$NEUTRALIZAR" ] && [ -t 0 ]; then
  read -rp "¿Neutralizar '$BD' (copia dev: apaga crons y mail)? [s/N]: " _n || true
  case "${_n:-}" in
    s|S|si|SI|y|Y|yes|YES) NEUTRALIZAR=si ;;
    *) NEUTRALIZAR=no ;;
  esac
fi
if [ "${NEUTRALIZAR:-no}" = "si" ]; then
  echo "== Neutralizando '$BD' (solo dev) =="
  docker compose exec -T odoo odoo neutralize -d "$BD" \
    && echo "(neutralizada: sin crons ni mails reales)" \
    || echo "AVISO: falló neutralize (a mano: docker compose exec odoo odoo neutralize -d $BD)."
fi
