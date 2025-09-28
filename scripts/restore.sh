#!/bin/bash
# PostgreSQL restore script for Docker container

set -e

if [ $# -eq 0 ]; then
    echo "Usage: $0 <backup_file.sql.gz>"
    echo "Available backups:"
    ls -la /backup/telegram_analysis_backup_*.sql.gz 2>/dev/null || echo "No backups found"
    exit 1
fi

BACKUP_FILE="$1"
DB_HOST="postgres"
DB_NAME="telegram_analysis"
DB_USER="telegram_user"

echo "Starting restore at $(date)"
echo "Backup file: ${BACKUP_FILE}"

# Check if backup file exists
if [ ! -f "${BACKUP_FILE}" ]; then
    echo "Error: Backup file ${BACKUP_FILE} not found"
    exit 1
fi

# Decompress and restore
echo "Decompressing and restoring database..."
gunzip -c "${BACKUP_FILE}" | PGPASSWORD="${POSTGRES_PASSWORD}" psql \
    -h "${DB_HOST}" \
    -U "${DB_USER}" \
    -d "${DB_NAME}" \
    --verbose

echo "Restore completed at $(date)"
echo "Database restored from: ${BACKUP_FILE}"
