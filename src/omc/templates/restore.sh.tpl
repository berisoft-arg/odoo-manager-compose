#!/usr/bin/env bash
# Restore {{PROYECTO}} — 100% autoguiado (también acepta args para automatizar).
# Uso guiado: ./scripts/restore.sh
# Uso directo: ./scripts/restore.sh <nombre_bd> <full_backup.tgz|carpeta> [--drive]
#   --drive: baja el tgz de Google Drive (rclone) antes de restaurar.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f .env ]; then
  set -a; . ./.env; set +a
fi
REMOTE="${RCLONE_REMOTE:-gdrive}"
RCFG="scripts/rclone.conf"; [ -s "$RCFG" ] || RCFG="$HOME/.config/rclone/rclone.conf"
SLUG=$(basename "$PWD" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9-_')
BD="${1:-}"
SRC="${2:-}"
DRIVE=0
[ "${3:-}" = "--drive" ] && DRIVE=1

elegir_archivo() {
  echo "Backups locales (backups/full_backup_*.tar.gz):"
  mapfile -t FILES < <(ls -t backups/full_backup_*.tar.gz 2>/dev/null || true)
  echo "  0) Bajar de Drive ($REMOTE:{{PROYECTO}}/)"
  if [ "${#FILES[@]}" -eq 0 ]; then echo "  (ninguno local)"; fi
  i=1; for f in "${FILES[@]}"; do echo "  $i) $f"; i=$((i+1)); done
  read -rp "Elige [0-${#FILES[@]}]: " N
  if [ "$N" = "0" ]; then DRIVE=1; return 0; fi
  SRC="${FILES[$((N-1))]:-}"
  [ -n "$SRC" ] || { echo "Selección inválida."; exit 1; }
}

if [ -z "$SRC" ]; then
  [ -t 0 ] || { echo "Uso: $0 <nombre_bd> <full_backup.tgz|carpeta> [--drive]"; exit 1; }
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
else
  DUMP="$SRC/db.dump"
  FS="$SRC/filestore.tgz"
  [ -f "$DUMP" ] || { echo "No existe $DUMP."; exit 1; }
fi

if [ -z "$BD" ]; then
  if [ -t 0 ]; then
    # sugerir por nombre del archivo: full_backup_<bd>_dayN.tar.gz
    SUG=$(basename "$SRC" | sed -E 's/^full_backup_//; s/_day[0-9].*//')
    read -rp "Base destino [$SUG]: " BD
    BD="${BD:-$SUG}"
  else
    echo "Uso: $0 <nombre_bd> <full_backup.tgz|carpeta> [--drive]"
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

if [ -n "${FS:-}" ] && [ -f "$FS" ]; then
  echo "== Restaurando filestore =="
  docker run --rm -v "${SLUG}_odoo-data:/data" -v "$PWD/$(dirname "$FS"):/in" \
    alpine sh -c "rm -rf /data/filestore/$BD && mkdir -p /data/filestore && tar xzf /in/$(basename "$FS") -C /data"
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
