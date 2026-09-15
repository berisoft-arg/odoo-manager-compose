# --- Rclone a demanda (perfil backup: NO levanta con up -d) ---
# Uso manual:  docker compose --profile backup run --rm rclone copy /data {{RCLONE_REMOTE}}:{{PROYECTO}}/ --progress
# El backup.sh lo usa solo si no hay rclone en el host.
  rclone:
    image: rclone/rclone
    profiles: ["backup"]
    volumes:
      - ./backups:/data
      - ./scripts/rclone.conf:/config/rclone/rclone.conf:ro
    command: version
