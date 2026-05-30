#!/bin/bash
# Backup horario de la base de datos CTFd
# Guarda las últimas 48 horas (48 backups) y elimina los más antiguos
# Uso: bash backup.sh
# Crontab: 0 * * * * /home/jcenturion/web/ctf.hackl4bs.com/public_html/CTFd/backup.sh >> /home/jcenturion/backups/ctfd/backup.log 2>&1

BACKUP_DIR="/home/jcenturion/backups/ctfd"
DB_CONTAINER="ctfd-db-1"
DB_USER="ctfd"
DB_PASS="ctfd"
DB_NAME="ctfd"
KEEP_DAYS=2
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
FILE="$BACKUP_DIR/ctfd_$TIMESTAMP.sql.gz"

mkdir -p "$BACKUP_DIR"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Iniciando backup..."

if ! docker exec "$DB_CONTAINER" mysqldump -u"$DB_USER" -p"$DB_PASS" \
    --single-transaction \
    --routines \
    --triggers \
    "$DB_NAME" | gzip > "$FILE"; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: Backup fallido."
  exit 1
fi

SIZE=$(du -sh "$FILE" | cut -f1)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backup guardado: $FILE ($SIZE)"

find "$BACKUP_DIR" -name "ctfd_*.sql.gz" -mtime +$KEEP_DAYS -delete
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backups antiguos (>$KEEP_DAYS días) eliminados."
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backups disponibles:"
ls -lh "$BACKUP_DIR"/ctfd_*.sql.gz 2>/dev/null || echo "  (ninguno)"
