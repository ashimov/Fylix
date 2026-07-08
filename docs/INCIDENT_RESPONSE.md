# Fylix Incident Response Runbook

Owner: Fylix on-call
Last updated: 2026-04-20
Related: `docs/DEPLOYMENT.md §14`, `docs/SLO.md`, `docs/THREAT_MODEL.md`,
`docs/SECURITY.md`, `docs/KEY_ROTATION.md`

This runbook is the canonical per-playbook reference. It deepens the
brief incident-response section in `DEPLOYMENT.md` into step-by-step
procedures. Every playbook follows **Detect → Contain → Remediate →
Post-mortem**.

---

## Severity levels

| Sev | Impact | Response |
|---|---|---|
| **SEV-1** | Data exposure or total outage | Page oncall within 5 min. Bridge opened, exec informed. |
| **SEV-2** | Degraded service, one tenant affected, or integrity concern | Page oncall within 15 min. Written update every hour. |
| **SEV-3** | Elevated error rate, no user-visible impact | Slack ack within 1 h. Written summary next business day. |

---

## Playbooks

### 1. Suspected master-key compromise (SEV-1)

Symptom: key material observed outside the Docker secret path;
unauthorised `/run/secrets/master_key` access in host audit log;
crypto-shred audit shows wrong-key unwrap failures; operator error
(key committed to git / posted in chat).

**Detect:**
```bash
# Check host-level audit for access to the secret
sudo ausearch -f /run/secrets/master_key -ts today

# Verify wrapped-key / unwrap failures in app logs
docker compose logs api worker | grep -E "unwrap.*failed|master.*mismatch"
```

**Contain:**
1. Immediately run `backend/scripts/rotate_master_key.py` in **offline
   ceremony mode** (see `docs/KEY_ROTATION.md` §Offline). Generate a
   new 32-byte key, do NOT place the old one in the previous-key env.
2. Pause the worker: `docker compose stop worker` — prevents cleanup
   from shredding transfers before sender notification.
3. Revoke every active admin session: `docker compose exec redis redis-cli FLUSHDB`.

**Remediate:**
1. Rewrap all `wrapped_key` + `telegram_bot_token` blobs using the
   new master key (`rotate_master_key.py` rewrap phase).
2. Rewrap all admin TOTP secrets (`backend/scripts/wrap_totp_secrets.py`).
3. Force every admin to rotate their TOTP via `/admins/{id}/reset-totp`.
4. Audit: list all transfers created between leak window and
   remediation; consider whether to invalidate them (they were
   encrypted under the old key — the leaked key decrypts them if the
   ciphertext was also exfiltrated).
5. Restart worker + api: `docker compose up -d`.

**Post-mortem:** GDPR Art. 33 notification if any transfer covered
personal data. Written post-mortem within 72 h covering: leak vector,
time window, what the attacker could have decrypted, remediation
steps, recurrence prevention.

---

### 2. Crypto-shred SLA breach (SEV-2)

Symptom: `(time() - fylix_cleanup_last_run_timestamp) > 600` firing.
Expired transfers remain decryptable past TTL.

**Detect:** Grafana "Fylix — Crypto-shred SLA" dashboard heartbeat
panel is red. Alertmanager paged.

**Contain:**
```bash
docker compose ps worker                                  # worker running?
docker compose logs worker --tail 200 | grep cleanup       # last tick reason
docker compose exec redis redis-cli GET metrics:cleanup_last_run_ts
```

**Remediate:**
- If worker is down: `docker compose up -d worker` — should trigger
  a tick within 5 min; verify heartbeat recovers.
- If worker is up but cleanup throws: read the stacktrace, fix the
  underlying cause (most often Postgres connection exhaustion or
  MinIO credential rotation drift).
- Manual shred for individual transfers:
  ```bash
  docker compose exec api /opt/venv/bin/python -m scripts.force_shred <transfer_id>
  ```
  (add this script if it doesn't exist — see `app/worker/tasks/cleanup.py`).

**Post-mortem:** Attach the Grafana heartbeat screenshot + last-good
tick timestamp + worker logs. If the breach lasted > 1 h, classify
as SEV-1 data-exposure risk and follow §1.

---

### 3. Admin lockout (all admins locked) (SEV-2)

Symptom: no admin can log in — Argon2 failures cascading.

**Detect:** `docker compose exec postgres psql ... -c "SELECT email, failed_attempts, locked_until FROM admins"` shows all rows with `locked_until > NOW()`.

**Contain:** Immediately unlock the designated break-glass admin
account (bootstrapped as admin #1, email documented in vault):
```sql
UPDATE admins SET failed_attempts = 0, locked_until = NULL WHERE email = '<break-glass-email>';
```

**Remediate:** Log in with break-glass, unlock remaining admins via
UI. Investigate the brute-force source — check `audit_log` for
`event_type='admin_login_failed'` by IP and add to blocklist.

---

### 4. Storage corruption — MinIO object missing or altered (SEV-2)

Symptom: download returns 500 or a file's SHA-256 doesn't match
`transfer_files.sha256_cipher`.

**Detect:**
```sql
SELECT t.id, tf.filename, tf.sha256_cipher FROM transfers t
JOIN transfer_files tf ON tf.transfer_id = t.id
WHERE t.status = 'ready' AND t.deleted_at IS NULL
ORDER BY t.created_at DESC;
```
Compare each `sha256_cipher` to MinIO object via
`mc cat local/transfers/<transfer_id>/<file_id>.enc | sha256sum`.

**Contain:** Flip the affected transfer to `status='infected'` to
block further downloads while investigating.

**Remediate:** Restore from backup (see `docs/BACKUP.md`). Notify
the sender: the transfer cannot be delivered.

---

### 5. Rate-limit spike (DDoS / runaway client) (SEV-3)

Symptom: 429 rate spikes in nginx access log; legitimate users
complaining of throttling.

**Detect:** Grafana queue dashboard shows `upload:ready` depth
flat-lining at 0 while 429s climb in nginx logs.

**Contain:** Edge-ban the source IP at nginx:
```nginx
deny 198.51.100.42;
```
(Reload nginx: `docker compose exec nginx nginx -s reload`.)

**Remediate:** Add to `blocklist` table via `/api/admin/blocklist/ip`
for persistence. Investigate whether the client is a misbehaving
integration vs. attack.

---

### 6. Defender quarantine event (SEV-2)

Symptom: Worker audit log shows `event_type='defender_alert'`;
uploaded file disappeared from staging before encryption.

**Remediate:** Follow `docs/DEPLOYMENT.md §4 Defender integration`
verification steps. If repeated on different uploads from the same
sender, add sender email to blocklist.

---

### 7. Disk full (SEV-1 if staging, SEV-2 if MinIO)

**Detect:**
```bash
df -h /srv/fylix/staging   # tmpfs-style staging
docker compose exec minio df -h /data
```

**Contain — staging full:** stop new uploads at nginx:
```bash
docker compose exec nginx sh -c 'echo "return 503;" > /etc/nginx/conf.d/uploads-off.conf && nginx -s reload'
```
Remove orphaned staging dirs (transfers whose upload never completed
and are > 1 h old).

**Contain — MinIO full:** identify + shred expired transfers ahead
of schedule:
```sql
SELECT id FROM transfers WHERE expires_at < NOW() AND deleted_at IS NULL;
```
Run the cleanup tick manually; if bucket-level lifecycle rules not
configured, add them per `docs/DEPLOYMENT.md`.

---

## Drill schedule

Practice each playbook at least once per quarter in staging:

- **Q1:** Master-key compromise (rotate in offline mode, rewrap, verify)
- **Q2:** Crypto-shred SLA breach (pause worker, observe alert, recover)
- **Q3:** Admin lockout (break-glass path, unlock cascade)
- **Q4:** Storage corruption + restore-from-backup end-to-end

Record drill outcomes in `docs/DRILL_LOG.md` (create on first run).
Any playbook that produced an unexpected result → update this doc.

---

## Escalation contacts

Maintained in your organization's secure vault (outside this repo). Keys:

- Fylix oncall pager (24×7)
- Your security lead
- Your DPO (GDPR notification path)
- MinIO / Postgres / Redis vendor support (if commercial support is contracted)
- Legal (breach notification threshold decisions)

Do NOT put phone numbers or emails in this markdown file — they drift
and get committed to forks.
