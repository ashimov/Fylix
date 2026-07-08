# Fylix Master-Key Rotation Runbook

## Overview

The master key (`secrets/master_key`) is a 32-byte AES-256 key that wraps
every per-transfer file key and every admin TOTP secret stored in the database
(RFC 3394 AES-KW). Rotating it means:

1. Generating a new 32-byte key.
2. Unwrapping each stored value with the **old** key.
3. Re-wrapping it with the **new** key.
4. Swapping the key file and restarting the api + worker containers.

The entire operation takes ~30 seconds of downtime for a typical instance
(< 10 000 transfers).

---

## Two rotation modes

Fylix supports two rotation procedures:

1. **Zero-downtime rotation (recommended)** — rolling restart + online rewrap
   via `POST /api/admin/crypto/rewrap`. Service stays up; the transition window
   lasts only as long as the rewrap job needs to finish (~30 seconds per
   10 000 transfers on modern hardware).

2. **Offline rotation (legacy)** — stop api + worker, run the rewrap script,
   swap the secret, restart. Documented further below; use only for
   disaster-recovery scenarios where the online path is unavailable (e.g. a
   standalone restored backup that has never been online).

---

## Zero-downtime rotation — 3-phase procedure

### Phase 1: Open the rotation window

Add the previous key alongside the new current key and roll-restart the
backend. During this phase the app reads with either key, writes with the
new one.

```bash
# 1. Safety-net backup (captures pre-rotation state).
./scripts/backup.sh

# 2. Generate the new 32-byte key.
openssl rand 32 > secrets/master_key.new
chmod 400 secrets/master_key.new

# 3. Record the new key hex on paper (last-resort recovery).
xxd -p -c 64 secrets/master_key.new
read -p "Press Enter once recorded on paper..."

# 4. Promote: old becomes "previous", new becomes "current".
mv secrets/master_key secrets/master_key.previous
mv secrets/master_key.new secrets/master_key
```

Add the previous-key path to the prod compose override:

```yaml
# docker-compose.prod.yml — api and worker services
environment:
  MASTER_KEY_PREVIOUS_PATH: /run/secrets/master_key_previous
secrets:
  - master_key
  - master_key_previous

secrets:
  master_key:
    file: ./secrets/master_key
  master_key_previous:
    file: ./secrets/master_key.previous
```

Roll-restart **sequentially** so one replica is always serving:

```bash
docker compose up -d --no-deps --force-recreate api
# wait until api is healthy before recreating worker:
curl -kf https://localhost/healthz
docker compose up -d --no-deps --force-recreate worker
```

At this point: old transfers decrypt via the previous-key fallback; new
transfers are wrapped with the new current key. No user-visible downtime.

### Phase 2: Online rewrap

Trigger the online rewrap endpoint (idempotent — re-run safely on partial
progress):

```bash
# Log in as admin (stores cookies + CSRF token in the jar).
curl -kc cookies.txt -b cookies.txt \
  -X POST https://localhost/api/admin/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@example.com","password":"...","totp_code":"123456"}'

# Run the rewrap. Returns {"ok": true, "transfers_rewrapped": N, "admins_rewrapped": M}.
CSRF=$(grep csrf cookies.txt | awk '{print $7}')
curl -kb cookies.txt \
  -X POST https://localhost/api/admin/crypto/rewrap \
  -H "X-CSRF-Token: $CSRF"
```

Progress is logged to the api container (`docker compose logs api`) as
`admin_crypto_rewrap: done transfers=N admins=M`. The
`action=crypto_rewrap` entry in the Admin Actions log captures the run for
audit.

Re-running the endpoint is safe: AES-KW is deterministic, so rows already
rewrapped produce byte-identical output on the second pass.

### Phase 3: Close the rotation window

Once rewrap reports zero remaining old-key rows (or after two consecutive
runs produce identical non-zero counts — i.e. nothing was migrated on the
second pass), remove the previous key:

```bash
# 1. Remove MASTER_KEY_PREVIOUS_PATH from docker-compose.prod.yml + secret mount.

# 2. Roll-restart.
docker compose up -d --no-deps --force-recreate api worker

# 3. Verify the app boots with current-only.
curl -kf https://localhost/healthz

# 4. Archive the previous key for 30 days in case an untested backup
#    still references it, then secure-delete.
mv secrets/master_key.previous secrets/master_key.old.$(date +%Y%m%d)
```

See "Old-key retention" below for the 30-day ceremony.

---

## Prerequisites (offline legacy procedure)

- Docker stack is up and healthy (`docker compose ps`).
- `openssl` and `xxd` are installed on the ops host.
- `secrets/age-backup.pub` exists (backup requires age — see `docs/BACKUP.md`).
- Off-hours window recommended; api and worker will be restarted at the end.

---

## Pre-flight checks

```bash
# 1. Count active transfers (gives a rough estimate of rotation time)
docker compose exec postgres psql -U fylix -d fylix \
  -c "SELECT COUNT(*) FROM transfers WHERE wrapped_key IS NOT NULL;"

# 2. Count enrolled admins
docker compose exec postgres psql -U fylix -d fylix \
  -c "SELECT COUNT(*) FROM admins WHERE totp_secret IS NOT NULL;"

# 3. Confirm free disk space for backup (need ~2x current DB + MinIO size)
df -h .

# 4. Verify the stack is healthy
curl -k https://localhost/healthz
```

---

## Running the rotation

```bash
make rotate-key
# or: ./scripts/rotate_master_key.sh
```

The script walks through 8 steps:

| Step | Action |
|------|--------|
| 1 | Create an encrypted backup via `scripts/backup.sh` (safety net) |
| 2 | Generate a new 32-byte key with `openssl rand 32` |
| 3 | Copy the new key into the api container at `/tmp/new_master_key` |
| 4 | Run `scripts/rotate_master_key.py` inside the api container |
| 5 | Swap `secrets/master_key` ← `secrets/master_key.new` |
| 6 | Clean up `/tmp/new_master_key` inside the container |
| 7 | Restart api + worker (`docker compose restart api worker`) |
| 8 | Smoke-test `https://localhost/healthz` |

**Two confirmation prompts** prevent accidental runs:

- `Type 'ROTATE' to continue` — at the start.
- `Press Enter once recorded` — after the new key hex is displayed.

---

## Step 3: Stop api and worker

This prevents new transfers from being created with the OLD master key
during rotation. The script handles this automatically; if running steps
manually, execute:

```bash
docker compose stop api worker
```

Step 7 will restart them with the new master key in place.

---

## Paper ceremony for the new key

At step 2, the script prints the new key as a 64-character hex string:

```
new key hex: a3f7...  (64 hex chars)
(WRITE THIS DOWN — paper, safe)
Press Enter once recorded...
```

Write the hex string on paper and store it in a physical safe or equivalent
off-site secure location. This hex copy is a last-resort recovery tool if
both the `secrets/master_key` file **and** the backup archive are lost.

---

## Verification after rotation

```bash
# 1. Healthz
curl -k https://localhost/healthz

# 2. Download a transfer that existed before rotation
curl -k -O "https://localhost/t/<token>/files/<filename>"

# 3. Log in as an admin (uses TOTP — verify the TOTP code still works)
curl -k -X POST https://localhost/api/admin/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@example.com","password":"...","totp_code":"123456"}'
```

If either step 2 or 3 fails, execute the **Rollback** procedure immediately.

---

## Rollback: restore from pre-rotation backup

The backup created at step 1 of the rotation contains the **old** master key.
To fully revert:

```bash
# The backup file path was printed by rotate_master_key.sh — check the output.
./scripts/restore.sh backups/fylix-backup-<timestamp>.tar.age
```

This overwrites the DB, MinIO bucket, and `secrets/master_key` with the
pre-rotation snapshot, then restarts the stack. All data written between
the backup and the restore will be lost.

---

## Old-key retention

After a successful rotation, the old key is archived at:

```
secrets/master_key.old.<timestamp>
```

**Keep it for 30 days** (sealed envelope or secrets manager), then
secure-delete:

```bash
# macOS (no shred — use rm after overwriting)
dd if=/dev/urandom of=secrets/master_key.old.<timestamp> bs=32 count=1
rm secrets/master_key.old.<timestamp>

# Linux
shred -u secrets/master_key.old.<timestamp>
```

The 30-day window covers:
- Late-arriving backup tapes or snapshots that reference the old key.
- Rollback scenarios discovered after the initial smoke test.

---

## Rotation cadence

| Trigger | Action |
|---------|--------|
| Annual (at minimum) | Scheduled rotation |
| Suspected compromise (key leak, insider threat) | Immediate rotation |
| Staff departure (key had physical access) | Rotation within 24 hours |
| After a full restore from backup | Rotation recommended |

Schedule the annual rotation as a calendar reminder tied to your security
review cycle.

---

## Integration test

The rotation logic is covered by:

```
backend/tests/integration/test_key_rotation.py
```

Run it inside the api container:

```bash
docker compose exec -T api /opt/venv/bin/pytest \
  tests/integration/test_key_rotation.py -v -m integration
```

Expected: 1 passed.

Note: this test leaves the api container running with the **old** master key
loaded (because we cannot restart the container mid-test-session). The
autouse `_reset` fixture truncates all test data on the next run, so no
persistent inconsistency is introduced.
