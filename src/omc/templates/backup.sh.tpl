#!/usr/bin/env bash
# Backup {{PROYECTO}} — rotación day1..day7 + copia dominical + validaciones + rclone a Drive.
# Uso: ./scripts/backup.sh [nombre_bd]   (ej: ./scripts/backup.sh midb)
# Sin argumento y con terminal: lista las bases y eliges.
# Crontab sugerido: 0 3 * * * cd /ruta/{{PROYECTO}} && ./scripts/backup.sh <bd> >> backups/cron.log 2>&1
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f .env ]; then
  # shellcheck disable=SC1091
  set -a; . ./.env; set +a
fi
REMOTE="${RCLONE_REMOTE:-gdrive}"
RCFG="scripts/rclone.conf"
[ -f "$RCFG" ] || RCFG="$HOME/.config/rclone/rclone.conf"

# --- 0. Nombre de la BD ---
BD="${1:-}"
if [ -z "$BD" ]; then
  if [ -t 0 ]; then
    echo "Bases disponibles:"
    mapfile -t BDS < <(docker compose exec -T db psql -U odoo -d postgres -tAX \
      -c "SELECT datname FROM pg_database WHERE datistemplate=false AND datname NOT IN ('postgres');" 2>/dev/null)
    [ "${#BDS[@]}" -eq 0 ] && { echo "No hay bases (¿Odoo sin crear BD?)."; exit 1; }
    i=1; for b in "${BDS[@]}"; do echo "  $i) $b"; i=$((i+1)); done
    read -rp "Elige [1-${#BDS[@]}]: " N
    BD="${BDS[$((N-1))]:-}"
    [ -z "$BD" ] && { echo "Selección inválida."; exit 1; }
  else
    echo "Uso: $0 <nombre_bd_odoo>" >&2
    exit 1
  fi
fi

DIA=$(date +%u)  # 1 (lunes) a 7 (domingo): 7 generaciones rotando
DEST="backups"
WEEK=""  # ruta de la copia dominical (solo DIA=7)
mkdir -p "$DEST"
SLUG=$(basename "$PWD" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9-_')
DB_DUMP="$DEST/${BD}_db_day${DIA}.dump"
FS_TAR="$DEST/filestore_${BD}_day${DIA}.tar.gz"
FULL="$DEST/full_backup_${BD}_day${DIA}.tar.gz"

echo "--- Backup {{PROYECTO}} / $BD --- [$(date)]"

# --- 1. Dump Postgres (falla rápido) ---
if ! docker compose exec -T db env PGPASSWORD="${POSTGRES_PASSWORD:-odoo}" \
    pg_dump -U odoo -Fc "$BD" > "$DB_DUMP"; then
  echo "ERROR CRÍTICO: falló pg_dump de $BD." >&2
  rm -f "$DB_DUMP"
  exit 1
fi

# --- 2. Validar dump no vacío ---
if [ ! -s "$DB_DUMP" ]; then
  echo "ERROR CRÍTICO: dump de $BD vacío (0 bytes)." >&2
  rm -f "$DB_DUMP"
  exit 1
fi

# --- 3. Filestore (con validación previa) ---
if docker run --rm -v "${SLUG}_odoo-data:/data:ro" alpine test -d "/data/filestore/$BD"; then
  docker run --rm -v "${SLUG}_odoo-data:/data:ro" -v "$PWD/$DEST:/out" \
    alpine tar czf "/out/$(basename "$FS_TAR")" -C /data "filestore/$BD"
else
  echo "AVISO: sin filestore para $BD todavía. Tar vacío."
  tar -czf "$FS_TAR" --files-from /dev/null
fi

# --- 4. Empaquetado final + limpieza de temporales ---
tar -czf "$FULL" -C "$DEST" "$(basename "$DB_DUMP")" "$(basename "$FS_TAR")"
rm -f "$DB_DUMP" "$FS_TAR"

# --- 4b. Copia dominical (red más allá de day1..day7: se conservan 4 domingos) ---
if [ "$DIA" = "7" ]; then
  WEEK="$DEST/full_backup_${BD}_week$((10#$(date +%V) % 4)).tar.gz"
  cp "$FULL" "$WEEK"
  echo "(copia dominical en $WEEK: se conservan 4 domingos)"
fi

# --- 5. Respaldo de la config de rclone (para descargarla/reponerla) ---
# Copia ~/.config/rclone/rclone.conf — sin esto no hay restore desde Drive en otra máquina.
if [ -f "$HOME/.config/rclone/rclone.conf" ]; then
  cp "$HOME/.config/rclone/rclone.conf" "$DEST/rclone.conf.bak"
  echo "(rclone.conf respaldado en $DEST/rclone.conf.bak)"
elif [ -f scripts/rclone.conf ]; then
  cp scripts/rclone.conf "$DEST/rclone.conf.bak"
  echo "(rclone.conf del proyecto respaldado en $DEST/rclone.conf.bak)"
else
  echo "(sin rclone.conf: configúralo para subir a Drive)"
fi

# --- 6. Subida a Google Drive (servicio rclone del compose: nada que instalar en host) ---
echo "--- Subiendo a Drive ($REMOTE) ---"
if ! grep -q "^\[" scripts/rclone.conf 2>/dev/null && [ -f "$HOME/.config/rclone/rclone.conf" ]; then
  echo "(uso tu ~/.config/rclone/rclone.conf)"
  cp "$HOME/.config/rclone/rclone.conf" scripts/rclone.conf
fi
RCLONE="docker compose --profile backup run --rm rclone"
if $RCLONE copy /data "$REMOTE:{{PROYECTO}}/" \
    --include "full_backup_${BD}_day${DIA}.tar.gz" --no-check-dest; then
  echo "Subida OK."
  if [ -n "${WEEK:-}" ] && [ -f "$WEEK" ]; then
    $RCLONE copy /data "$REMOTE:{{PROYECTO}}/" \
      --include "$(basename "$WEEK")" --no-check-dest \
      && echo "Subida dominical OK." \
      || echo "AVISO: falló la subida dominical (el local quedó bien)."
  fi
else
  echo "ERROR: falló la subida a Drive (el local quedó bien; revisa rclone.conf)." >&2
  exit 1
fi
du -sh "$FULL"
echo "✓ Backup en $FULL"
