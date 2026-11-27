#!/usr/bin/env bash
# Daily Postgres dump, kept 14 days on the server and copied off it with rclone when
# BACKUP_REMOTE is set (e.g. "gdrive:contentor-backups"). Cron, as root:
#   30 3 * * * /opt/contentor/backend/deploy/backup.sh >> /opt/contentor/backups/backup.log 2>&1
# A backup that lives only on this VPS is lost together with it: configure the remote.
set -euo pipefail

BACKEND_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKUP_DIR="${BACKUP_DIR:-/opt/contentor/backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"
REMOTE_KEEP_DAYS="${REMOTE_KEEP_DAYS:-60}"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
FILE="$BACKUP_DIR/contentor-$STAMP.dump"

# The remote name lives in backend/.env next to the other settings.
if [ -z "${BACKUP_REMOTE:-}" ] && [ -f "$BACKEND_DIR/.env" ]; then
  BACKUP_REMOTE="$(grep -E '^BACKUP_REMOTE=' "$BACKEND_DIR/.env" | cut -d= -f2- || true)"
fi

mkdir -p "$BACKUP_DIR"
cd "$BACKEND_DIR"
docker compose -f compose.prod.yml exec -T postgres \
  pg_dump -U contentor --format=custom contentor > "$FILE"
find "$BACKUP_DIR" -name 'contentor-*.dump' -mtime "+$KEEP_DAYS" -delete
echo "$(date -u +%FT%TZ) backup ok: $(basename "$FILE")"

if [ -n "${BACKUP_REMOTE:-}" ]; then
  rclone copy "$FILE" "$BACKUP_REMOTE"
  rclone delete --min-age "${REMOTE_KEEP_DAYS}d" "$BACKUP_REMOTE"
  echo "$(date -u +%FT%TZ) copied to $BACKUP_REMOTE"
else
  echo "$(date -u +%FT%TZ) WARNING: BACKUP_REMOTE is not set; the dump stays on this server only"
fi
