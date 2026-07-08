# Fylix Backup & Restore Runbook

## Prerequisites

Install [`age`](https://age-encryption.org) on the host that runs backups:

```bash
# macOS
brew install age

# Debian / Ubuntu
apt-get install age

# Manual (all platforms)
# https://github.com/FiloSottile/age/releases
```

Verify with `age --version` and `age-keygen --version`.  
The scripts will exit with a clear error if either binary is missing.

---

## One-time setup

Generate the age key pair used to encrypt all backup archives:

```bash
make age-key
# or: ./scripts/age-keygen.sh
```

This creates:

| File | Permissions | Purpose |
|------|-------------|---------|
| `secrets/age-backup.key` | 0o400 | **Private key** — required for restore. Store off-site. |
| `secrets/age-backup.pub` | 0o444 | Public recipient — used by `backup.sh` at every run. |

**Safe storage for the private key:**

- Copy `secrets/age-backup.key` to at least two separate locations:
  a password manager vault, an encrypted USB stored off-site, and/or a
  secrets manager (AWS Secrets Manager, Vault, etc.).
- The private key is never needed during normal operation — only during restore.
- For multi-operator setups, append additional `-r <recipient>` lines to
  `backup.sh` after generating separate age key pairs for each operator.

---

## Running a backup

```bash
make backup
# or: ./scripts/backup.sh [output-dir]
```

The default output directory is `backups/` in the repo root.  
Each run produces a single timestamped file:

```
backups/fylix-backup-20260413-120000Z.tar.age
```

**What's inside (encrypted):**

| File | Contents |
|------|----------|
| `pgdump-<ts>.sql` | Full pg_dump in custom format (`-Fc`) |
| `minio-<ts>.tar` | All objects from the `transfers` bucket |
| `master_key` | Copy of `secrets/master_key` |

**Expected file sizes:**

- Baseline (empty DB): ~50–200 KB overhead
- Per transfer: ~30 MB for a typical 25 MB upload (ciphertext + Postgres metadata)
- MinIO data dominates for busy instances

Intermediate files are written to a `mktemp -d` staging directory and
shredded (via `shred -u` if available) before the temp dir is removed.

---

## Restore drill

**Run this quarterly on a staging environment — never on production during business hours.**

```bash
# On staging host with a copy of the backup file and the private key:
./scripts/restore.sh /path/to/fylix-backup-20260413-120000Z.tar.age
# or:
make restore file=/path/to/fylix-backup-20260413-120000Z.tar.age
```

The script will:

1. Prompt `Type 'RESTORE' to continue` — this is a safety gate.
2. Decrypt the archive with `secrets/age-backup.key`.
3. Restore `master_key` to `secrets/master_key`.
4. Drop and recreate the Postgres database, then `pg_restore`.
5. Wipe and repopulate the MinIO `transfers` bucket.
6. Restart `api` and `worker` containers.
7. Print a smoke-test command.

---

## Retention policy

Suggested rotation (implement as a host cron or CI job):

| Frequency | Count |
|-----------|-------|
| Daily | keep 7 |
| Weekly (Sunday) | keep 4 |
| Monthly (1st) | keep 12 |

Example shell snippet for `crontab -e`:

```bash
# Prune backups older than 7 days, keeping at most 7 daily files
0 3 * * * find /srv/backups -name "fylix-backup-*.tar.age" -mtime +7 -delete
```

For a more complete GFS (Grandfather-Father-Son) rotation, use a tool such as
`tmpreaper`, `logrotate` (with a custom stateref), or your cloud provider's
object lifecycle policies.

---

## Off-site upload

Copy each new archive to a remote location immediately after creation.
Examples:

```bash
# rclone to S3
rclone copy backups/ s3:my-bucket/fylix-backups/

# rclone to Backblaze B2
rclone copy backups/ b2:my-bucket/fylix-backups/

# AWS CLI
aws s3 cp backups/fylix-backup-*.tar.age s3://my-bucket/fylix-backups/

# scp to a bastion
scp backups/fylix-backup-*.tar.age ops@offsite-host:/backups/
```

Because every archive is age-encrypted, it is safe to store in any
cloud bucket — the private key never leaves `secrets/`.

---

## Disaster recovery runbook

Full rebuild from scratch when the host is lost:

1. **Provision a new host** with Docker, Docker Compose, and `age` installed.
2. **Clone the repo** and set up `.env` (copy from `.env.example`).
3. **Restore the age private key** from your off-site store into `secrets/age-backup.key`
   and `chmod 400 secrets/age-backup.key`.
4. **Download the latest backup archive** from off-site storage.
5. **Bring up infrastructure** (DB + MinIO only — api/worker not needed yet):
   ```bash
   docker compose up -d postgres minio redis
   sleep 10
   docker compose exec postgres createdb -U fylix fylix 2>/dev/null || true
   ```
6. **Run restore**:
   ```bash
   ./scripts/restore.sh /path/to/fylix-backup-LATEST.tar.age
   ```
7. **Verify** by visiting `https://<host>/healthz` and attempting a download.
8. **Rotate certificates** if the TLS cert was not included in the backup
   (it is not by default — regenerate with `make certs`).

For key rotation after a compromise, see [`docs/KEY_ROTATION.md`](KEY_ROTATION.md).
