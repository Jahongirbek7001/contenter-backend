#!/usr/bin/env bash
# Daily Postgres dump, kept 14 days on the server. Cron (as the deploy user):
#   30 3 * * * /opt/contentor/backend/deploy/backup.sh >> /opt/contentor/backups/backup.log 2>&1
# Copying the dumps off the server (rclone to cloud storage) is set up separately: a backup
# that lives only on the same VPS is lost together with it.
set -euo pipefail

BACKEND_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKUP_DIR="${BACKUP_DIR:-/opt/contentor/backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"
STAMP="$(date -u +%Y%m%d-%H%M%S)"

mkdir -p "$BACKUP_DIR"
cd "$BACKEND_DIR"
docker compose -f compose.prod.yml exec -T postgres \
  pg_dump -U contentor --format=custom contentor > "$BACKUP_DIR/contentor-$STAMP.dump"
find "$BACKUP_DIR" -name 'contentor-*.dump' -mtime "+$KEEP_DAYS" -delete
echo "$(date -u +%FT%TZ) backup ok: contentor-$STAMP.dump"
