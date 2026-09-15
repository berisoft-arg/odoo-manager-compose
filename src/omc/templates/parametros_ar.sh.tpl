#!/usr/bin/env bash
# Parámetros AR {{PROYECTO}} — crea ir.config_parameter si no existen (idempotente).
# Uso: ./scripts/parametros_ar.sh [nombre_bd]   (ej: ./scripts/parametros_ar.sh midb)
# Sin argumento y con terminal: lista las bases y eliges.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f .env ]; then
  # shellcheck disable=SC1091
  set -a; . ./.env; set +a
fi

BD="${1:-}"
if [ -z "$BD" ]; then
  if [ -t 0 ]; then
    echo "Bases disponibles:"
    mapfile -t BDS < <(docker compose exec -T db env PGPASSWORD="${POSTGRES_PASSWORD:-odoo}" \
      psql -U odoo -d postgres -tAX \
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

PSQL="docker compose exec -T db env PGPASSWORD=\"${POSTGRES_PASSWORD:-odoo}\" psql -U odoo -d $BD -v ON_ERROR_STOP=1"
{{PARAMS_SQL}}
echo "✓ Parámetros AR verificados en $BD."
