#!/usr/bin/env bash
# Fylix backup smoke-restore.
#
# Purpose: weekly verification that the most-recent Postgres backup in
# $BACKUP_DIR can actually be restored into a throwaway database, and
# that the row counts look sane (admins / audit_log / settings / FK integrity).
#
# A backup file that lands on disk is NOT the same as a backup you can
# actually use in an incident — this script closes the gap.
#
# Env:
#   BACKUP_DIR        — path on staging where nightly dumps land
#                       (produced by scripts/backup.sh per BACKUP.md)
#   PGHOST, PGPORT,
#   PGUSER, PGPASSWORD — Postgres connection (read-write: creates +
#                       drops a scratch DB named ${TEST_DB})
#   TEST_DB           — scratch DB name (default: fylix_smoke_$(date +%s))
#   ALERT_URL         — Slack/Telegram webhook to POST failure to
#                       (optional; if unset, script just exits non-zero)
#
# Cron:
#   0 4 * * 1 /srv/fylix/backend/scripts/backup_smoke_restore.sh \
#             >> /var/log/fylix-backup-smoke.log 2>&1
#   # Mondays 04:00 — after Sunday night's backup, before business hours.
set -euo pipefail

: "${BACKUP_DIR:?BACKUP_DIR is required}"
: "${PGHOST:?PGHOST is required}"
: "${PGPORT:=5432}"
: "${PGUSER:?PGUSER is required}"
TEST_DB="${TEST_DB:-fylix_smoke_$(date +%s)}"

log() {
  printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

fail() {
  log "FAIL: $*"
  if [[ -n "${ALERT_URL:-}" ]]; then
    curl -fsS -X POST -H "Content-Type: application/json" \
         -d "{\"text\":\"Fylix backup smoke-restore failed: $*\"}" \
         "$ALERT_URL" || true
  fi
  exit 1
}

latest_backup=$(ls -1t "${BACKUP_DIR}"/*.dump 2>/dev/null | head -n 1 || true)
if [[ -z "${latest_backup}" ]]; then
  fail "No .dump file in ${BACKUP_DIR}"
fi
log "Using latest backup: ${latest_backup}"

# Age check — a stale backup means the nightly job is silently broken.
age_hours=$(( ( $(date +%s) - $(stat -c %Y "${latest_backup}") ) / 3600 ))
if (( age_hours > 36 )); then
  fail "Latest backup is ${age_hours}h old (> 36h threshold)"
fi

# Create throwaway DB
log "Creating scratch DB ${TEST_DB}"
createdb -h "${PGHOST}" -p "${PGPORT}" -U "${PGUSER}" "${TEST_DB}" || \
  fail "createdb ${TEST_DB} failed"

cleanup() {
  log "Dropping scratch DB ${TEST_DB}"
  dropdb -h "${PGHOST}" -p "${PGPORT}" -U "${PGUSER}" --if-exists "${TEST_DB}" || true
}
trap cleanup EXIT

# Restore
log "Restoring ${latest_backup} into ${TEST_DB}"
pg_restore -h "${PGHOST}" -p "${PGPORT}" -U "${PGUSER}" -d "${TEST_DB}" \
           --no-owner --no-privileges --single-transaction \
           "${latest_backup}" || fail "pg_restore failed"

# Sanity checks — counts within reasonable ranges. Thresholds kept
# loose so the test fires only on catastrophic regressions, not on
# real business changes.
check_count() {
  local table="$1" min="$2"
  local n
  n=$(psql -h "${PGHOST}" -p "${PGPORT}" -U "${PGUSER}" -d "${TEST_DB}" \
          -tAc "SELECT count(*) FROM ${table}")
  if (( n < min )); then
    fail "${table}: ${n} rows (< ${min} minimum)"
  fi
  log "  ${table}: ${n} rows (>= ${min})"
}

log "Row-count sanity checks"
check_count admins 1
check_count transfers 0          # could be 0 in fresh staging — just ensure the table exists + query succeeds
check_count audit_log 1
check_count settings 1           # seeded on first migration

# Foreign-key check — SET NULL cascades from 0007+0008 migrations.
log "FK integrity spot check"
orphan=$(psql -h "${PGHOST}" -p "${PGPORT}" -U "${PGUSER}" -d "${TEST_DB}" \
             -tAc "SELECT count(*) FROM audit_log WHERE transfer_id IS NOT NULL
                   AND transfer_id NOT IN (SELECT id FROM transfers)")
if (( orphan > 0 )); then
  fail "audit_log has ${orphan} orphan transfer_id references"
fi

# Migration head matches
log "Alembic head check"
head=$(psql -h "${PGHOST}" -p "${PGPORT}" -U "${PGUSER}" -d "${TEST_DB}" \
            -tAc "SELECT version_num FROM alembic_version")
log "  alembic head: ${head}"
if [[ -z "${head}" ]]; then
  fail "alembic_version table is empty"
fi

log "OK: backup restore succeeded, counts sane, FK clean, migration head=${head}"
