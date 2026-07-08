# Fylix

**Version:** 1.1.0 (frontend) / 0.1.0 (backend, admin-frontend) | **Port:** 443 (Nginx TLS) | **Stack:** Python 3.12 (uv, HawkAPI/FastAPI-style) + Vue 3 + PostgreSQL 16 + Redis 7 + MinIO

## What

Fylix is a secure, self-hosted file-exchange platform: anonymous partner uploads with full audit trail, per-transfer AES-256-GCM envelope encryption, crypto-shredding on delete, and an admin control plane with Argon2id + TOTP 2FA.

## Quick Start

```bash
./setup.sh                       # First-time setup (prereqs, .env, master key, certs, docker compose up)
make migrate                     # Apply DB migrations (run once after first `up`)
make admin-create email=admin@example.com pw='SomeStrongPassword!123'
make test                        # Run backend unit tests
```

## Commands

```bash
# Docker lifecycle
make up                          # docker compose up -d --build
make down                        # docker compose down
make logs                        # tail all service logs
make migrate                     # alembic upgrade head (inside api container)
make revision m="msg"            # new alembic revision
make clean                       # DESTRUCTIVE: teardown + wipe data/ volumes

# Backend (cd backend)
uv sync                          # install Python deps
uv run pytest tests/unit -v      # unit tests (no Docker needed; set dummy PG/MinIO env vars)
uv run pytest                    # full suite (make test) — needs stack context for integration markers
uv run ruff check . && uv run ruff format --check . && uv run mypy app   # make lint
uv run ruff format .             # make fmt

# Frontends (cd frontend or admin-frontend)
npm install
npm run dev                      # Vite dev server
npm run typecheck                # vue-tsc --noEmit
npm run build                    # vue-tsc --noEmit && vite build
npm run test                     # vitest (frontend/ only)

# Security / ops
make audit                       # pip-audit dependency CVE scan
make scan                        # bandit + trivy image scan
make backup / make restore file=<path>   # age-encrypted backup/restore
make rotate-key                  # master-key rotation ceremony
```

## Architecture

```text
backend/app/
├── crypto/     master-key loader, AES-KW envelope wrap, streaming AES-256-GCM
├── models/     SQLAlchemy ORM (11 tables: transfers, files, downloads, admins, audit...)
├── schemas/    Pydantic DTOs
├── services/   email, storage, auth, alerts, rate_limit, policy, geoip, blocklist, captcha
├── middleware/ rate_limit, csrf
├── routers/    public (upload/download/sender panel), admin (12 endpoint groups)
├── worker/     Redis-queue consumers + APScheduler (TTL cleanup, Defender poll)
└── tus/        minimal tus 1.0.0 PATCH/HEAD handler (resumable uploads)

frontend/          Public SPA (Vue 3 + Vite + TS) — upload, download, sender panel
admin-frontend/    Admin SPA (Vue 3 + Vite + TS + Chart.js) — 12 dashboard pages
nginx/             TLS termination, rate limiting, GeoIP, /admin CIDR allow-list
scripts/           host-side ops: gen_master_key, gen_dev_certs, backup, restore, rotate_master_key
docs/              DEPLOYMENT, SECURITY, THREAT_MODEL, KEY_ROTATION, BACKUP, SLO, CI, etc.
```

Nginx fronts everything over TLS and routes to the public SPA, admin SPA, and the API. Uploads land in a plaintext staging directory (bind-mounted so an on-host AV/EDR can scan them), then the worker AES-256-GCM-encrypts each file streaming into MinIO and wraps its key with the master key (AES-KW). PostgreSQL holds only metadata + wrapped keys; MinIO holds only ciphertext. Deleting/expiring a transfer sets `wrapped_key = NULL` (crypto-shredding) — the ciphertext becomes permanently unrecoverable.

## Key Files

```text
backend/app/crypto/                 master key load + envelope wrap/unwrap + streaming cipher
backend/app/routers/public.py       upload, download, sender-panel endpoints
backend/app/worker/tasks/           encrypt-on-ready, email queue, TTL cleanup, Defender poll
backend/alembic/versions/           6 schema migrations
backend/scripts/create_admin.py     bootstrap first admin (TOTP enrollment)
scripts/gen_master_key.sh           generates secrets/master_key (32 raw bytes, NOT base64)
docker-compose.yml                  dev composition (8 services + mailpit/jaeger in dev profile)
docker-compose.prod.yml             prod override (Dockerfile, APP_ENV=production)
Makefile                            all lifecycle/lint/test/ops targets
docs/SECURITY.md                    threat-model matrix + controls
docs/DEPLOYMENT.md                  full production bootstrap runbook
```

## Configuration

All configuration is via environment variables. See `.env.example`:

| Variable | Required | Description |
| -------- | -------- | ----------- |
| `APP_ENV` | yes | `development` or `production`; prod enforces strict checks below |
| `PUBLIC_URL` | yes | Public base URL (e.g. `https://localhost`) |
| `POSTGRES_DB/USER/PASSWORD` | yes | PostgreSQL credentials |
| `REDIS_URL` | yes | Redis connection string |
| `MINIO_ROOT_USER/PASSWORD` | yes | MinIO credentials |
| `MINIO_SECURE` | yes (prod) | Must be `true` in production |
| `MASTER_KEY_PATH` | yes | Path to 32 raw-byte master key (Docker secret) — see `make master-key` |
| `STAGING_DIR` | yes | Host bind-mount for pre-encryption AV scanning |
| `SMTP_*` | yes | Outbound mail relay for transfer notifications |
| `HCAPTCHA_SECRET/SITE_KEY` | yes (prod) | Mandatory in production |
| `MAXMIND_DB_PATH` | no | GeoLite2-Country.mmdb for country gating |
| `TELEGRAM_BOT_TOKEN/CHAT_ID` | no | Admin alerting |
| `SENTRY_DSN` / `VITE_SENTRY_DSN` | no | Error reporting |
| `GRAFANA_ADMIN_PASSWORD` | yes (if exposed) | Observability stack |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).
