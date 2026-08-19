#!/usr/bin/env bash
# Restore a dump into a target database.
#
# Destructive by nature, so it refuses to run without an explicit confirmation
# and prints exactly what it is about to overwrite.

set -euo pipefail

DUMP="${1:?usage: restore.sh <dump-file> [target-database-url]}"
TARGET="${2:-${DATABASE_URL:?set DATABASE_URL or pass a target}}"

echo "About to restore:"
echo "  dump   : ${DUMP}"
echo "  target : ${TARGET%%\?*}"
echo
echo "This REPLACES the contents of the target database."
read -r -p "Type the word RESTORE to continue: " confirm
[ "$confirm" = "RESTORE" ] || { echo "aborted"; exit 1; }

pg_restore --clean --if-exists --no-owner --no-privileges --dbname="$TARGET" "$DUMP"

echo
echo "Restored. Verifying the audit chain:"
psql "$TARGET" -tAc "SELECT count(*) FROM audit_logs;" | xargs echo "  audit rows:"
echo "  Now run: GET /api/v1/admin/audit/verify — it must report ok=true."
