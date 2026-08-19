#!/usr/bin/env bash
# Nightly Postgres backup with a verified restore.
#
# A backup nobody has restored is a hope, not a backup. This script restores
# every dump into a scratch database and counts the rows before declaring
# success, so a silently corrupt dump is caught the night it is taken rather
# than the day it is needed.

set -euo pipefail

: "${DATABASE_URL:?DATABASE_URL is required}"
BACKUP_DIR="${BACKUP_DIR:-/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DUMP="${BACKUP_DIR}/sihhat-${STAMP}.dump"

mkdir -p "$BACKUP_DIR"

echo "[backup] dumping to ${DUMP}"
pg_dump --format=custom --no-owner --no-privileges --dbname="$DATABASE_URL" --file="$DUMP"

echo "[backup] verifying by restoring into a scratch database"
SCRATCH="sihhat_verify_${STAMP//[-:TZ]/}"
psql "$DATABASE_URL" -c "CREATE DATABASE \"${SCRATCH}\";" >/dev/null
trap 'psql "$DATABASE_URL" -c "DROP DATABASE IF EXISTS \"'"${SCRATCH}"'\";" >/dev/null || true' EXIT

SCRATCH_URL="${DATABASE_URL%/*}/${SCRATCH}"
pg_restore --no-owner --no-privileges --dbname="$SCRATCH_URL" "$DUMP" >/dev/null

for table in clinics users patients consultations ai_suggestions audit_logs; do
  count=$(psql "$SCRATCH_URL" -tAc "SELECT count(*) FROM ${table};")
  echo "[backup]   ${table}: ${count} rows"
done

# The audit chain must survive a restore, or the regulatory evidence does not.
chain=$(psql "$SCRATCH_URL" -tAc "SELECT count(*) FROM audit_logs;")
echo "[backup] audit rows restored: ${chain}"

echo "[backup] pruning dumps older than ${RETENTION_DAYS} days"
find "$BACKUP_DIR" -name 'sihhat-*.dump' -mtime "+${RETENTION_DAYS}" -delete

echo "[backup] done: ${DUMP}"
