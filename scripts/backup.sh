#!/bin/bash
# PostgreSQL backup script for Docker container

set -e

# Configuration
BACKUP_DIR="/backup"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="telegram_analysis_backup_${TIMESTAMP}.sql"
BACKUP_PATH="${BACKUP_DIR}/${BACKUP_FILE}"

# Database connection details (from environment)
DB_HOST="postgres"
DB_NAME="telegram_analysis"
DB_USER="telegram_user"

echo "Starting backup at $(date)"
echo "Backup file: ${BACKUP_FILE}"

# Create backup directory if it doesn't exist
mkdir -p "${BACKUP_DIR}"

# Create the backup
PGPASSWORD="${POSTGRES_PASSWORD}" pg_dump \
    -h "${DB_HOST}" \
    -U "${DB_USER}" \
    -d "${DB_NAME}" \
    --verbose \
    --clean \
    --no-owner \
    --no-privileges \
    > "${BACKUP_PATH}"

# Compress the backup
gzip "${BACKUP_PATH}"
COMPRESSED_BACKUP="${BACKUP_PATH}.gz"

echo "Backup completed: ${COMPRESSED_BACKUP}"
echo "Backup size: $(du -h "${COMPRESSED_BACKUP}" | cut -f1)"

# Optional: Remove old backups (keep last 7 days)
find "${BACKUP_DIR}" -name "telegram_analysis_backup_*.sql.gz" -mtime +7 -delete

echo "Backup process finished at $(date)"
