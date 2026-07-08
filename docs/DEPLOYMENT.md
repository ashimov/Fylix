# Fylix — Production Deployment Runbook

This document is the authoritative guide for deploying and operating Fylix
in production. Read it end-to-end before touching a production host.

---

## Table of contents

1. [Prerequisites](#1-prerequisites)
2. [TLS setup](#2-tls-setup)
3. [MaxMind GeoLite2](#3-maxmind-geolite2)
4. [Microsoft Defender integration](#4-microsoft-defender-integration)
5. [SMTP relay](#5-smtp-relay)
6. [Admin CIDR allowlist](#6-admin-cidr-allowlist)
7. [Initial bootstrap](#7-initial-bootstrap)
8. [Health checks](#8-health-checks)
9. [Log locations](#9-log-locations)
10. [Observability stack](#10-observability-stack)
11. [Backup schedule](#11-backup-schedule)
12. [Key rotation schedule](#12-key-rotation-schedule)
13. [Upgrade procedure](#13-upgrade-procedure)
14. [Incident response](#14-incident-response)
15. [Troubleshooting](#15-troubleshooting)

---

## 1. Prerequisites

### Host requirements

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| CPU | 2 vCPU | 4 vCPU |
| RAM | 2 GB | 4 GB |
| Disk | 20 GB | 100 GB+ (depends on transfer volume) |
| OS | Ubuntu 22.04 LTS / Debian 12 / RHEL 9 | Ubuntu 22.04 LTS |

### Required software

```bash
# Docker Engine 24+
docker --version    # must be >= 24.0.0

# Docker Compose v2 (plugin, not standalone)
docker compose version   # must be >= 2.20.0

# age (for backup encryption)
age --version        # https://age-encryption.org

# openssl (for cert generation, key inspection)
openssl version

# Optional but recommended
curl jq xxd
```

Install Docker on Ubuntu:

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# Log out and back in so group membership takes effect.
```

### Firewall / network

Open inbound TCP ports 80 and 443 only. All other ports (5432, 6379, 9000) must
be reachable only from within the Docker bridge network. Do not expose them to
the host's public interface.

---

## 2. TLS setup

### Option A — Let's Encrypt (certbot, recommended for internet-facing hosts)

```bash
# Install certbot
apt-get install certbot

# Obtain cert (standalone mode — stop nginx first if already running)
certbot certonly --standalone -d transfer.yourorg.com

# Certs are written to:
#   /etc/letsencrypt/live/transfer.yourorg.com/fullchain.pem
#   /etc/letsencrypt/live/transfer.yourorg.com/privkey.pem

# Copy into the repo layout:
mkdir -p nginx/certs
cp /etc/letsencrypt/live/transfer.yourorg.com/fullchain.pem nginx/certs/fullchain.pem
cp /etc/letsencrypt/live/transfer.yourorg.com/privkey.pem   nginx/certs/privkey.pem
chmod 400 nginx/certs/privkey.pem
chmod 444 nginx/certs/fullchain.pem
```

Set up auto-renewal. Add to root crontab (`crontab -e`):

```
0 3 1 * * certbot renew --quiet && \
  cp /etc/letsencrypt/live/transfer.yourorg.com/fullchain.pem /srv/fylix/nginx/certs/fullchain.pem && \
  cp /etc/letsencrypt/live/transfer.yourorg.com/privkey.pem   /srv/fylix/nginx/certs/privkey.pem && \
  chmod 400 /srv/fylix/nginx/certs/privkey.pem && \
  docker compose -f /srv/fylix/docker-compose.yml exec nginx nginx -s reload
```

### Option B — Internal CA / self-signed (air-gapped or intranet deployments)

```bash
# Generate a 4096-bit RSA cert valid 1 year, with SAN for your hostname:
make certs
# or manually:
openssl req -x509 -newkey rsa:4096 -sha256 -days 365 -nodes \
  -keyout nginx/certs/privkey.pem \
  -out nginx/certs/fullchain.pem \
  -subj "/CN=transfer.yourorg.com/O=YourOrg" \
  -addext "subjectAltName=DNS:transfer.yourorg.com,IP:10.0.0.50"
chmod 400 nginx/certs/privkey.pem
chmod 444 nginx/certs/fullchain.pem
```

Distribute the `fullchain.pem` to client machines as a trusted CA certificate so
browsers do not show cert warnings.

### Expected `nginx/certs/` layout

```
nginx/certs/
├── fullchain.pem   (0444 — public cert; includes any intermediate chain)
└── privkey.pem     (0400 — private key; owned by root)
```

The Nginx container bind-mounts this directory read-only at `/etc/nginx/certs`.

---

## 3. MaxMind GeoLite2

GeoIP country detection gates transfers by the sender's country and powers
the analytics dashboard.

### One-time account setup

1. Register a free account at https://dev.maxmind.com/geoip/geolite2-free-geolocation-data
2. Generate a licence key under **My Account → Manage Licence Keys**.
3. Download `GeoLite2-Country.mmdb`:

```bash
mkdir -p /srv/fylix/geoip
curl -sL "https://download.maxmind.com/app/geoip_download?edition_id=GeoLite2-Country&license_key=YOUR_KEY&suffix=tar.gz" \
  | tar -xzC /srv/fylix/geoip --strip-components=1 '*.mmdb'
# Result: /srv/fylix/geoip/GeoLite2-Country.mmdb
```

Set in `.env`:

```
MAXMIND_DB_PATH=/srv/fylix/geoip/GeoLite2-Country.mmdb
```

The docker-compose mounts this path read-only into the api/worker containers.

### Monthly refresh (cron)

MaxMind updates GeoLite2 databases on the first and third Tuesday of each month.
Add to root crontab:

```
0 4 1,15 * * \
  curl -sL "https://download.maxmind.com/app/geoip_download?edition_id=GeoLite2-Country&license_key=YOUR_KEY&suffix=tar.gz" \
  | tar -xzC /srv/fylix/geoip --strip-components=1 '*.mmdb' && \
  docker compose -f /srv/fylix/docker-compose.yml restart api worker
```

If GeoLite2 is absent or unreadable, the api logs a warning and country detection
falls back to `null` — transfers proceed but the country-block policy cannot fire.

---

## 4. Microsoft Defender integration

The staging directory (`/srv/fylix/staging` by default, set in `.env` as
`STAGING_DIR`) is the plaintext write landing zone. Every uploaded file chunk lands
here before being encrypted and moved to MinIO. This is the only window where
Defender can scan file contents.

### Linux host — Microsoft Defender for Endpoint (MDE / mdatp)

```bash
# Install the mdatp agent (Ubuntu 22.04):
curl -o microsoft.list https://packages.microsoft.com/config/ubuntu/22.04/prod.list
mv microsoft.list /etc/apt/sources.list.d/microsoft-prod.list
curl -sSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor > microsoft.gpg
mv microsoft.gpg /etc/apt/trusted.gpg.d/microsoft.gpg
apt-get update && apt-get install mdatp

# Onboard the device (download onboarding package from M365 Defender portal):
python3 MicrosoftDefenderATPOnboardingLinuxServer.py

# Verify real-time protection is on:
mdatp health --field real_time_protection_enabled
# Expected: true
```

Configure the monitored path explicitly to ensure staging is covered:

```bash
mdatp exclusion folder remove --path /srv/fylix/staging
# (Remove any mistaken exclusion — staging must be scanned, not excluded.)
```

### Windows Server host

1. Enable Real-time Protection in **Windows Security → Virus & threat protection**.
2. Ensure the staging bind-mount path is on an NTFS volume (not a RAM disk or
   network share without Defender coverage).
3. No additional configuration needed — Defender scans all NTFS writes by default.

### Verification — EICAR test

After installation, place the EICAR test string in a file inside staging and
confirm Defender quarantines it within a few seconds:

```bash
# Linux:
echo 'X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*' \
  > /srv/fylix/staging/eicar-test.txt

sleep 5
ls /srv/fylix/staging/eicar-test.txt
# Expected: file absent (quarantined) or permission denied
```

If the file persists after 10 seconds, real-time protection is not covering
the staging path. Investigate before going live.

### Important caveat

Defender quarantine is asynchronous — there is a race condition window between
the file landing in staging and the scan completing. This window is typically
under 1 second for small files but can be longer for large files on busy hosts.
The api does not block on scan completion; it proceeds to encrypt and remove the
staging file after the upload completes. This is a known limitation documented in
`docs/SECURITY.md`.

---

## 5. SMTP relay

Fylix sends notification emails for:
- Download link delivery to recipients
- Upload confirmation to senders
- Admin alerts (on configurable event types)

### Option A — Corporate Exchange relay

```
SMTP_HOST=mail.yourorg.com
SMTP_PORT=587
SMTP_USER=fylix@yourorg.com
SMTP_PASSWORD=<service-account-password>
SMTP_FROM=no-reply@yourorg.com
```

Request a dedicated service account from IT with:
- SMTP AUTH permission on port 587 (STARTTLS)
- A send-as alias `no-reply@yourorg.com` (or equivalent)
- Rate limit: ≥ 100 messages/hour

### Option B — Amazon SES

```
SMTP_HOST=email-smtp.eu-central-1.amazonaws.com
SMTP_PORT=587
SMTP_USER=<SMTP_credentials_access_key_id>
SMTP_PASSWORD=<SMTP_credentials_secret_access_key>
SMTP_FROM=no-reply@verified-domain.com
```

Verify the sender domain in SES first (`aws sesv2 create-email-identity`).
Move out of sandbox mode to send to arbitrary recipients.

### Option C — Mailgun

```
SMTP_HOST=smtp.mailgun.org
SMTP_PORT=587
SMTP_USER=postmaster@mg.yourorg.com
SMTP_PASSWORD=<mailgun-smtp-password>
SMTP_FROM=no-reply@mg.yourorg.com
```

### Comparison

| | Exchange | SES | Mailgun |
|---|---|---|---|
| Cost | Internal (no extra cost) | ~$0.10/1000 emails | ~$35/month (50k emails) |
| Deliverability | Good (corp domain) | Excellent | Excellent |
| Setup complexity | Low (IT request) | Medium | Low |
| GDPR residency | Within org | AWS region choice | EU region available |

### Self-signed certificate on the SMTP relay

If your corporate SMTP relay presents a self-signed or internally-signed TLS
certificate that does not match its hostname, add the following to `.env`:

```env
SMTP_VERIFY_CERT=false
```

This disables certificate verification for the SMTP connection only. Do **not**
set this against public relays (SES, Mailgun) where certificate validation is
always valid.

### Testing email delivery

```bash
# From inside the api container:
docker compose exec api python3 -c "
import asyncio, aiosmtplib
from email.mime.text import MIMEText
msg = MIMEText('Test from Fylix')
msg['Subject'] = 'SMTP test'
msg['From'] = 'no-reply@yourorg.com'
msg['To'] = 'admin@yourorg.com'
asyncio.run(aiosmtplib.send(msg, hostname='your-smtp-host', port=587, username='user', password='pass', start_tls=True))
print('OK')
"
```

---

## 6. Admin CIDR allowlist

Access to `/admin/*` and `/api/admin/*` is gated by a `geo` block in
`nginx/nginx.conf`. Only clients whose IP falls within a listed CIDR may
reach those paths; all others receive HTTP 403.

### Current default ranges

| CIDR | Purpose |
|------|---------|
| `127.0.0.0/8` | Loopback — always allowed |
| `172.16.0.0/12` | Docker bridge networks — required for the dev/CI stack |
| `10.0.0.0/8` | Corporate VPN / intranet example — **replace with your actual CIDR** |
| `192.168.0.0/16` | Alternate RFC-1918 example — remove if not needed |

### How to update CIDRs

1. Edit `nginx/nginx.conf` — find the `geo $admin_allowed { … }` block.
2. Add a line `<cidr> 1;` for each allowed network; remove lines to tighten access.
3. Reload Nginx without downtime:

```bash
docker compose exec nginx nginx -s reload
```

4. Verify from an allowed host:

```bash
curl -k -s -o /dev/null -w "%{http_code}\n" \
  -X POST https://transfer.yourorg.com/api/admin/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"x@y.co","password":"x","totp_code":"000000"}'
# Expected: 401 (auth fails — NOT 403 which means geo block is hitting)
```

**In production:** restrict to VPN egress IPs or jump-host CIDR only. Remove
`10.0.0.0/8` and `192.168.0.0/16` if those are not exclusively your org's ranges.

---

## 7. Initial bootstrap

Run these steps once on a fresh host. Steps are idempotent where noted.

```bash
# 1. Clone the repo
git clone https://github.com/yourorg/fylix.git /srv/fylix
cd /srv/fylix

# 2. Generate the master encryption key (IRREVERSIBLE — back this up before anything else)
make master-key
#    Output: secrets/master_key (32 random bytes, mode 0400)
#    IMMEDIATELY record the hex on paper and store in a physical safe:
xxd -p secrets/master_key | tr -d '\n'
#    Keep this paper copy in a sealed envelope in a secure location.

# 3. Generate TLS certificates (choose A or B from Section 2 above)
make certs   # generates a dev self-signed cert — replace with real cert for prod

# 4. Generate the age backup key pair (idempotent, run once)
make age-key
#    Output: secrets/age-backup.key (0400) + secrets/age-backup.pub (0444)
#    Store age-backup.key off-site (same safe as master key hex or a password manager).

# 5. Configure environment
cp .env.example .env
# Edit .env — at minimum change:
#   POSTGRES_PASSWORD=<strong random password>
#   MINIO_ROOT_PASSWORD=<strong random password>
#   SMTP_HOST / SMTP_USER / SMTP_PASSWORD
#   TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID  (optional)
#   HCAPTCHA_SECRET / HCAPTCHA_SITE_KEY    (optional but recommended)
#   MAXMIND_DB_PATH                         (see Section 3)
#   PUBLIC_URL=https://transfer.yourorg.com

# 6. Create GeoIP directory
mkdir -p /srv/fylix/data/geoip
# Download the MaxMind DB here (see Section 3).

# 7. Start the production stack
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

# 8. Wait for services to become healthy
docker compose ps
# All services should show "healthy" or "running".

# 9. Run database migrations
make migrate
# or: docker compose exec api alembic upgrade head

# 10. Create the first admin user
make admin-create email=admin@yourorg.com pw='SomeStrongPassw0rd!'
# The command prints an otpauth:// URI — scan it with an authenticator app
# (Google Authenticator, Authy, 1Password, etc.) immediately.
# This URI is shown only once. If lost, re-run with a new password to regenerate.

# 11. Smoke test
curl -k https://transfer.yourorg.com/healthz
# Expected: {"status":"ok"}
```

---

## 8. Health checks

### Endpoint

```
GET https://<host>/healthz
```

Returns `{"status":"ok"}` with HTTP 200 when the api is up and can reach
Postgres and Redis. Returns HTTP 500 if any dependency is unavailable.

### Container status

```bash
docker compose ps
# All containers should be "Up" or "Up (healthy)".
# The api and worker containers have health checks configured.
```

### Expected services

| Container | Purpose | Port (internal) |
|-----------|---------|-----------------|
| `nginx` | TLS termination + reverse proxy | 80, 443 (host) |
| `api` | HawkAPI application server | 8000 (internal) |
| `worker` | Background job processor | — |
| `postgres` | Primary database | 5432 (internal) |
| `redis` | Session store + rate-limit state | 6379 (internal) |
| `minio` | Object storage (encrypted files) | 9000 (internal) |

### Monitoring

Recommended: point an uptime monitor (UptimeRobot, Checkly, your corporate Nagios)
at `https://transfer.yourorg.com/healthz`. Alert threshold: 2 consecutive failures.

---

## 9. Log locations

All containers write to stdout/stderr. Docker captures these via its logging driver.

### Reading logs

```bash
# All services, live:
make logs
# or:
docker compose logs -f

# Single service:
docker compose logs -f api
docker compose logs -f worker
docker compose logs -f nginx

# Last 500 lines of api:
docker compose logs --tail 500 api
```

### Log format

Logs are emitted via Python's standard `logging` module to stdout (captured by Docker).
For JSON-formatted logs in production, configure `python-json-logger` via
`logging.dictConfig` — not yet wired in v1.0.0.

### Persistent log shipping (recommended)

For long-term retention and alerting, configure Docker's logging driver or a
log shipper:

```yaml
# Add to each service in docker-compose.prod.yml:
logging:
  driver: "json-file"
  options:
    max-size: "100m"
    max-file: "10"
```

Or use Filebeat / Fluentd / Promtail to ship to Elasticsearch / Loki.

### Nginx access log

Nginx writes to `/var/log/nginx/access.log` inside its container in the combined
`main` format (see `nginx/nginx.conf`). Include it in your log shipper or collect
with `docker compose logs nginx`.

### Audit log (database)

Admin-plane actions (login, download, delete, settings change) are recorded in the
`audit_log` table in Postgres. Export via:

```bash
docker compose exec postgres psql -U fylix -d fylix \
  -c "SELECT created_at, admin_email, action, detail FROM audit_log ORDER BY created_at DESC LIMIT 100;"
```

---

## 10. Observability stack

Bundled with `docker-compose.yml`: **Jaeger** (distributed tracing),
**Prometheus** (metrics scraping), **Grafana** (dashboards + alerting).

### Services

| Service | Port (dev) | Purpose |
|---|---|---|
| `jaeger` | `:16686` | All-in-one — OTLP gRPC receiver (`:4317`, internal) + UI |
| `prometheus` | `:9090` (internal) | Scrapes `api:8000/metrics` every 15s, 30-day retention, 2GB cap |
| `grafana` | `:3000` | UI; reads Prometheus via internal network |

Dashboards auto-provisioned from `observability/grafana/dashboards/`:
1. **Fylix — Worker queues & DLQ** — live queue depth, DLQ thresholds
2. **Fylix — Crypto-shred SLA** — cleanup-heartbeat age (alert > 600s)
3. **Fylix — Upload throughput & tracing** — queue-arrival derivative + Jaeger deep-link

### Production gating

All three UIs must be CIDR-gated at Nginx in prod, same pattern as
`/admin` and `/metrics`. Add to `nginx/nginx.conf`:

```nginx
location /jaeger/  { if ($admin_allowed = 0) { return 403; } proxy_pass http://jaeger:16686/; }
location /grafana/ { if ($admin_allowed = 0) { return 403; } proxy_pass http://grafana:3000/;  }
```

### OpenTelemetry

Traces export via OTLP gRPC to Jaeger. Control via env:

| Variable | Default | Meaning |
|---|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://jaeger:4317` | Set empty to disable |
| `OTEL_SERVICE_NAME` | `fylix-api` / `fylix-worker` | Per service |
| `OTEL_TRACES_SAMPLER_ARG` | `1.0` | 0..1 sampling ratio; lower in high-traffic |

Auto-instrumented: SQLAlchemy, Redis, httpx. MinIO uses urllib3 directly —
planned manual spans in encrypt.py / download handlers.

Bootstrap lives in `backend/app/observability.py`. No-op when
`OTEL_EXPORTER_OTLP_ENDPOINT` is unset (tests, offline dev).

### Metrics we expose today

From `backend/app/routers/metrics.py`:

- `fylix_worker_queue_depth{queue="..."}` — Redis LLEN per queue
- `fylix_cleanup_last_run_timestamp` — unix ts of last cleanup tick

Alert rule candidates (Phase 3 SLO.md):

```promql
# Cleanup heartbeat stale (crypto-shred SLA violation)
(time() - fylix_cleanup_last_run_timestamp) > 600

# DLQ backlog
sum(fylix_worker_queue_depth{queue=~".*:dlq"}) > 50
```

### Postgres tuning

For the 1GB / 1 CPU container profile, `postgres` runs with:

```
shared_buffers=256MB           # 25% of container RAM
effective_cache_size=768MB     # 75% of container RAM
max_connections=200            # api pool + worker pool + admin + headroom
work_mem=16MB
maintenance_work_mem=64MB
wal_buffers=16MB
random_page_cost=1.1           # SSD
log_min_duration_statement=500 # log slow queries
```

Bump `shared_buffers` proportionally if the host is scaled to larger
`mem_limit` — the rest of the knobs stay. See the `command:` block in
`docker-compose.yml` for the authoritative list.

---

## 11. Backup schedule

See [`docs/BACKUP.md`](BACKUP.md) for the full backup and restore runbook.

### Recommended cron

```
# Nightly backup at 02:00 local time
0 2 * * * cd /srv/fylix && ./scripts/backup.sh >> /var/log/fylix-backup.log 2>&1

# Upload to S3 immediately after
5 2 * * * rclone copy /srv/fylix/backups/ s3:your-bucket/fylix-backups/ >> /var/log/fylix-backup.log 2>&1

# Prune local backups older than 7 days
10 2 * * * find /srv/fylix/backups -name "fylix-backup-*.tar.age" -mtime +7 -delete
```

### Retention recommendation

| Period | Copies to keep |
|--------|---------------|
| Daily | 7 |
| Weekly (last Sunday) | 4 |
| Monthly (1st) | 12 |

Off-site archives are age-encrypted; store them in any cloud bucket.

---

## 12. Key rotation schedule

See [`docs/KEY_ROTATION.md`](KEY_ROTATION.md) for the full key rotation runbook.

### When to rotate

| Trigger | Action |
|---------|--------|
| Annually (minimum) | Scheduled rotation during a maintenance window |
| Suspected key exposure | Immediate rotation; rotate within the hour |
| Staff departure (had key access) | Rotation within 24 hours |
| After a full restore from backup | Rotation recommended to close the old key |

After rotation, keep `secrets/master_key.old.<timestamp>` for 30 days, then
secure-delete it.

---

## 13. Upgrade procedure

### Standard upgrade (30-second downtime)

```bash
cd /srv/fylix

# 1. Pull new code
git fetch origin
git checkout <new-version-tag>

# 2. Take a backup before any schema changes
make backup

# 3. Rebuild images
docker compose -f docker-compose.yml -f docker-compose.prod.yml build

# 4. Apply database migrations (while old containers are still running)
#    For backwards-compatible migrations this is safe with the old code.
docker compose exec api alembic upgrade head

# 5. Swap containers (brief downtime here)
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# 6. Verify health
curl -k https://transfer.yourorg.com/healthz
docker compose ps
```

### Zero-downtime upgrade (advanced)

Zero-downtime requires two active instances behind a load balancer. The MVP
architecture does not include this. Accept the ~30-second downtime window during
`docker compose up -d` for now. Schedule upgrades during low-traffic hours.

### Rollback

If the new version is broken:

```bash
git checkout <previous-version-tag>
docker compose -f docker-compose.yml -f docker-compose.prod.yml build
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
# If migrations were applied and are not backwards-compatible:
docker compose exec api alembic downgrade -1
```

---

## 14. Incident response

### Suspected compromise

Follow these steps in order — speed matters but do not skip verification steps.

1. **Isolate** — block public access immediately:

    ```bash
    docker compose stop nginx
    # Or add a blanket deny to the firewall:
    ufw insert 1 deny in on eth0 to any port 443
    ```

2. **Preserve evidence** — dump logs before any destructive action:

    ```bash
    docker compose logs --tail 10000 > /tmp/incident-logs-$(date +%Y%m%d%H%M%S).txt
    docker compose exec postgres pg_dump -U fylix fylix -Fc > /tmp/incident-pgdump.dump
    ```

3. **Rotate all secrets** — assume every secret is compromised:

    ```bash
    make rotate-key          # master key
    # Also rotate: POSTGRES_PASSWORD, MINIO_ROOT_PASSWORD, SMTP_PASSWORD
    # Revoke and reissue all admin TOTP secrets via the admin panel or DB.
    # Regenerate TLS certificate if private key may be exposed.
    ```

4. **Review audit log**:

    ```bash
    docker compose exec postgres psql -U fylix -d fylix \
      -c "SELECT * FROM audit_log WHERE created_at > NOW() - INTERVAL '7 days' ORDER BY created_at DESC;"
    ```

    Look for: unexpected admin logins, mass downloads, settings changes, login failures.

5. **Assess scope** — determine which transfers may have been accessed. Generate a
   list of affected transfer IDs from the audit log.

6. **Notify** — coordinate with legal / DPO:
    - GDPR Article 33: notify supervisory authority within 72 hours of becoming
      aware of a personal data breach.
    - Notify affected senders and recipients per your data breach notification policy.

7. **Consider full restore from pre-compromise backup** if the database integrity
   is in doubt. See `docs/BACKUP.md`.

8. **Post-incident review** — document the timeline, root cause, and remediation
   within 5 business days.

---

## 15. Troubleshooting

### Nginx shows cert mismatch

```
SSL_ERROR_RX_RECORD_TOO_LONG  (or similar)
```

Cause: Nginx started before `nginx/certs/fullchain.pem` and `privkey.pem` existed.

Fix:

```bash
ls -la nginx/certs/   # verify both files exist and have correct permissions
docker compose restart nginx
```

### Master key permission denied

```
PermissionError: [Errno 13] Permission denied: '/run/secrets/master_key'
```

Cause: `secrets/master_key` has wrong permissions or is owned by a different user.

Fix:

```bash
ls -la secrets/master_key   # should be -r-------- (0400), owned by root or current user
chmod 400 secrets/master_key
docker compose restart api worker
```

### Redis connection refused

```
redis.exceptions.ConnectionError: Error 111 connecting to redis:6379
```

Cause: Redis container not healthy, or networking issue.

Fix:

```bash
docker compose ps redis         # check status
docker compose logs redis       # check for OOM or config errors
docker compose restart redis
docker compose restart api worker
```

### Migration failure — relation already exists

```
sqlalchemy.exc.ProgrammingError: (asyncpg.exceptions.DuplicateTableError)
```

Cause: Alembic version table out of sync, or migrations applied manually.

Fix:

```bash
docker compose exec postgres psql -U fylix -d fylix \
  -c "SELECT version_num FROM alembic_version;"
# Compare against the head revision:
docker compose exec api alembic heads
# If mismatched, stamp to current state and re-run:
docker compose exec api alembic stamp head
docker compose exec api alembic upgrade head
```

### Upload stuck / tus session not resuming

Cause: Redis session key expired, or MinIO unreachable.

Fix:

```bash
docker compose logs api | grep -i tus   # look for error context
docker compose ps minio                 # check MinIO is healthy
docker compose exec redis redis-cli ping
```

### Container exits immediately after startup

```bash
docker compose logs api | tail -30
```

Common causes:
- Missing or malformed `.env` — check all required variables are set.
- `MASTER_KEY_PATH` points to a non-existent or unreadable file.
- Postgres not yet ready — the api has a `depends_on: condition: service_healthy`
  guard, but this can race on slow machines. Re-run `docker compose up -d api`.

### GeoIP always returns null

Cause: `MAXMIND_DB_PATH` is set but the file is absent or zero-length.

Fix:

```bash
docker compose exec api ls -lh /srv/fylix/geoip/GeoLite2-Country.mmdb
# Re-download if missing (see Section 3).
docker compose restart api worker
```
