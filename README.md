<p align="center">
  <img src="Fylix.png" alt="Fylix" width="320" />
</p>

<h3 align="center">Secure self-hosted file-exchange platform</h3>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.12-blue?logo=python&logoColor=white" alt="Python" />
  <a href="https://pypi.org/project/hawkapi/"><img src="https://img.shields.io/pypi/v/hawkapi.svg?label=hawkapi" alt="HawkAPI"></a>
  <img src="https://img.shields.io/badge/vue-3.5-4FC08D?logo=vue.js&logoColor=white" alt="Vue.js" />
  <img src="https://img.shields.io/badge/docker-compose-2496ED?logo=docker&logoColor=white" alt="Docker" />
  <img src="https://img.shields.io/badge/PostgreSQL-16-336791?logo=postgresql&logoColor=white" alt="PostgreSQL" />
  <img src="https://img.shields.io/badge/MinIO-S3-C72E49?logo=minio&logoColor=white" alt="MinIO" />
  <img src="https://img.shields.io/badge/Redis-7-DC382D?logo=redis&logoColor=white" alt="Redis" />
  <img src="https://img.shields.io/badge/AES--256--GCM-envelope-0369a1" alt="Crypto" />
  <a href="https://github.com/ashimov/Fylix/actions/workflows/ci.yml"><img src="https://github.com/ashimov/Fylix/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI" /></a>
  <a href="https://github.com/ashimov/Fylix/actions/workflows/security.yml"><img src="https://github.com/ashimov/Fylix/actions/workflows/security.yml/badge.svg?branch=main" alt="Security scans" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-yellow.svg" alt="MIT License" /></a>
</p>

---

## Overview

**Fylix** is a secure, self-hosted file-exchange platform. It lets employees of your organization and external partners exchange files through a branded web portal while a security team watches over every byte through a locked-down admin dashboard.

Every transfer is encrypted with a per-transfer AES-256-GCM key; the key itself is wrapped with a master key that lives only in process memory (Docker secret, never in the database). On expiry or manual delete, wiping the wrapped key turns the ciphertext into noise — **crypto-shredding** makes "deleted" actually mean unrecoverable.

### Why Fylix

- **Anonymous upload, full traceability** — partners don't need accounts; every upload writes IP, geo, email, file metadata, and Defender scan results into an immutable audit log.
- **Eight-layer defense in depth** — Nginx rate-limit → app rate-limit → blocklist → GeoIP → policy → hCaptcha → Microsoft Defender → AES-GCM-GCM with envelope wrap.
- **Zero trust at the storage layer** — MinIO holds only ciphertext; a database dump without the master key reveals nothing about file contents.
- **Corporate UX** — your organization's design system, RU/KZ/EN i18n, dark mode, transactional email flow with sender + recipient notifications.

---

## Quick start

```bash
git clone https://github.com/ashimov/Fylix.git
cd Fylix
./setup.sh
```

`setup.sh` checks prerequisites (Docker, Docker Compose v2, openssl), creates `.env` from
`.env.example`, generates the master encryption key and a dev TLS certificate, and brings the
stack up with `docker compose --profile dev up -d --build`.

> **Before your first real transfer:** the master key at `secrets/master_key` must exist and be
> 32 **raw** bytes (not base64) — `setup.sh` / `make master-key` generate it correctly. Every
> file's encryption key is wrapped with this key, and it is never stored in the database. **If
> `secrets/master_key` is lost, every stored transfer becomes permanently unrecoverable** — this
> is the same crypto-shredding mechanism used intentionally on delete/expire. Back up the
> generated hex value offline (see [docs/KEY_ROTATION.md](docs/KEY_ROTATION.md)) before relying on
> an instance for anything you can't afford to lose.

See [CLAUDE.md](CLAUDE.md) for the full command reference and architecture, and
[CONTRIBUTING.md](CONTRIBUTING.md) to set up a development environment.

---

## Key features

### Public file-exchange flow
- **Drag-and-drop upload** up to 2 GB (configurable), with resumable [tus.io](https://tus.io) chunks — 5 MB each, survives flaky connections.
- **Server-rendered download page** at `/t/{token}` — works without JavaScript, tiny CSP, `Content-Disposition: attachment` prevents XSS via HTML files.
- **Streaming ZIP download** for multi-file transfers — decrypted chunk-by-chunk without ever touching disk.
- **Sender management panel** at `/s/{manage_token}` — view every download (IP, geo, timestamp, bytes), delete transfer early (crypto-shred), revoke link (keep for forensics).
- **Transactional email flow** — recipient gets download link, sender gets confirmation + download notifications, all localised RU/KZ/EN.

### Security controls (spec §7)
- **Per-transfer AES-256-GCM** encryption, streaming Cipher API (O(chunk_size) memory, ~250 KB peak for 10 MB files).
- **Envelope wrapping** via AES-KW (RFC 3394); master key stored as Docker secret, never in DB or logs.
- **Crypto-shredding** on delete/expire — `wrapped_key = NULL` permanently locks ciphertext.
- **TOTP secrets wrapped** with the same master key — DB leak doesn't bypass 2FA.
- **Microsoft Defender** integration via staging-dir watch; file disappearance auto-flips transfer to `infected` + critical Telegram alert.
- **Rate-limit** (Redis Lua atomic): 10 uploads/hour, 100/day, 30 downloads/hour per IP. Configurable via admin.
- **GeoIP** country gate (MaxMind GeoLite2-Country) — configurable allow-list.
- **Blocklist** — IP/CIDR via PostgreSQL `<<=`, email domain and exact email via citext. Expiry-aware.
- **Extension blacklist** — `.exe .bat .scr .vbs .js .msi .ps1 .hta .lnk .iso` by default.
- **hCaptcha** — mandatory when `HCAPTCHA_SECRET` is configured.
- **Nginx edge** — `limit_req zone=upload rate=10r/m burst=3` as defense-in-depth above app-level rate-limit.

### Admin control plane
- **Argon2id + TOTP 2FA** with lockout (5 failures → 15 min).
- **Redis sessions** with 30-min sliding TTL, HttpOnly/Secure/SameSite=Strict cookies.
- **CSRF** double-submit cookie protection on all mutating endpoints.
- **IP allow-list** at Nginx level for `/admin` and `/api/admin` — CIDR-based, prod corp-network only.
- **11 admin pages**: Dashboard (KPIs + 4 live charts), Transfers (filters + drawer + delete/revoke), Search (trigram across emails/filenames/IPs), Blocklist (3-tab CRUD), Limits, Extensions, Analytics (6 charts, day-range), Audit log (filters + CSV export), Admin Actions, Admins CRUD, Telegram config.
- **Role-based access** — `admin` (mutations) vs `viewer` (read-only).
- **Admin actions log** — immutable trail of every admin mutation (FK `SET NULL` on delete so history survives).

### Operations
- **Encrypted backup/restore** — pg_dump + MinIO mirror + master key in a single age-encrypted archive.
- **Master-key rotation** — unwrap/rewrap every transfer and TOTP in DB chunks, paper ceremony for old key.
- **GitHub Actions CI** — ruff + mypy strict + unit + integration + bandit + pip-audit + semgrep + trivy.
- **Prod Docker image** — multi-stage, `--no-dev`, non-root, 270 MB.
- **Telegram alerts** — infected file, rate-limit spike, admin login spike, storage high, Defender event.

---

## Architecture

```
                          ┌──────────────────────┐
                          │     Internet         │
                          └──────────┬───────────┘
                                     │
                          ┌──────────▼───────────┐
                          │   Nginx (:443 TLS)   │
                          │ - TLS 1.3 + HSTS     │
                          │ - limit_req zones    │
                          │ - GeoIP (MaxMind)    │
                          │ - /admin CIDR gate   │
                          └──────────┬───────────┘
                                     │
          ┌──────────────┬───────────┼──────────────┬──────────────┐
          │              │           │              │              │
   ┌──────▼──────┐ ┌─────▼────┐ ┌────▼─────┐ ┌─────▼──────┐ ┌─────▼──────┐
   │  frontend   │ │  admin-  │ │   api    │ │  /t/{tok}  │ │  /s/{mtok} │
   │  Vue 3 SPA  │ │  frontend│ │  HawkAPI │ │ server-rd  │ │ sender     │
   │  (public)   │ │ Vue 3 SPA│ │          │ │ HTML       │ │ panel      │
   └─────────────┘ └──────────┘ └─┬──┬──┬──┘ └────────────┘ └────────────┘
                                  │  │  │
                      ┌───────────┘  │  └───────────────────┐
                      │              │                      │
                ┌─────▼─────┐  ┌─────▼─────┐         ┌──────▼──────┐
                │ PostgreSQL│  │   Redis   │         │    MinIO    │
                │    16     │  │  7 Lua    │         │  (S3 API)   │
                │ - transfer│  │ - sessions│         │ ciphertext  │
                │   metadata│  │ - queues  │         │    only     │
                │ - audit   │  │ - rate-lim│         │             │
                │ - wrapped │  │ - cache   │         │             │
                │   keys    │  │           │         │             │
                └───────────┘  └─────┬─────┘         └──────▲──────┘
                                     │                      │
                              ┌──────▼──────────────────────┴──────┐
                              │            Worker                  │
                              │ - BRPOP upload:ready → encrypt     │
                              │ - BRPOP email:queue  → aiosmtplib  │
                              │ - BRPOP tg:queue     → aiohttp     │
                              │ - APScheduler: TTL cleanup 5min    │
                              │              Defender poll 30sec   │
                              └────────────────────┬───────────────┘
                                                   │
                                       ┌───────────▼───────────┐
                                       │  Host bind-mounts     │
                                       │  /srv/fylix/staging   │  ← Defender watch
                                       │  /srv/fylix/geoip     │
                                       └───────────────────────┘

         Networks:  web (public-facing)   ·   data (internal, no egress)
         Secrets:   master_key (Docker secret, 32 bytes, in-memory only)
```

### Transfer lifecycle

```
POST /api/transfers         ─┐
                             ├─► 7 guards: captcha → rate-limit → blocklist → GeoIP → policy
                             │   → TransferService.create (DB rows + tokens + staging dir)
PATCH /api/transfers/{t}/   │
       files/{f}  × N chunks ─┘  (tus.io resumable, 5 MB each, writes to /staging)
                             │
                             ▼
                    [Microsoft Defender real-time watch on /staging]
                             │
                             ▼
Redis LPUSH upload:ready  ──► Worker BRPOP
                             │
                             ▼
           python-magic → MIME sniff → AES-256-GCM encrypt stream →
           MinIO put_object → wrap file_key (AES-KW) → status='ready'
                             │
                             ▼
          LPUSH email:queue for each recipient + sender_confirm
                             │
                             ▼
GET /t/{token}              ─┐
GET /t/{token}/file/{f}      ├─► stream-decrypt from MinIO → HTTP response
GET /t/{token}/zip           │   + Download row + sender download-notice email
                             │
                             ▼
[APScheduler every 5 min]    ─► expired transfers → crypto-shred (wrapped_key=NULL,
                                                    delete MinIO objects, audit)
```

---

## Manual setup (step-by-step)

Prefer running these steps yourself instead of `./setup.sh`? Here's exactly what it does under the hood.

### Prerequisites
- Docker 24+ and Docker Compose v2
- [`uv`](https://github.com/astral-sh/uv) for Python dep management (optional — only for host-side test runs)
- Node.js 22+ (optional — only if editing the SPAs outside the container)

### Bring up the stack

```bash
# Generate the 32-byte master key (one-off; record the hex on paper)
make master-key

# Self-signed TLS cert for https://localhost
make certs

# Optional: generate the age key for encrypted backups
make age-key

# Copy env template and tweak if needed
cp .env.example .env

# Bring up all services (dev profile includes mailpit for email capture)
docker compose --profile dev up -d --build

# Apply database migrations
make migrate

# Verify
curl -k https://localhost/healthz
# → {"status":"ok","app":"Fylix"}
```

### Create the first admin

```bash
make admin-create email=admin@example.com pw='SomeStrongPassword!123'
# Scans the printed otpauth:// URI with Google Authenticator
```

Visit:
- **https://localhost/** — public upload portal
- **https://localhost/admin/** — admin panel (login with email + password + TOTP)
- **http://localhost:8025/** — mailpit web UI (dev-only email capture)

---

## Development

### Common Make targets

| Target | Purpose |
|---|---|
| `make up` / `make down` | Start / stop docker-compose stack |
| `make logs` | Tail all service logs |
| `make migrate` | Run Alembic migrations |
| `make revision m="msg"` | Generate a new Alembic revision |
| `make test` | Backend unit tests (host-side via `uv`) |
| `make lint` | ruff check + ruff format --check + mypy strict |
| `make fmt` | Auto-format Python sources |
| `make audit` | `pip-audit` dependency CVE scan |
| `make scan` | bandit source + trivy container-image scan |
| `make backup` | Encrypted backup via age |
| `make rotate-key` | Master-key rotation ceremony |
| `make clean` | **Destructive**: teardown + wipe all volumes |

### Repository layout

```
Fylix/
├── backend/                      HawkAPI + worker
│   ├── app/
│   │   ├── crypto/               master-key loader, AES-KW envelope, streaming AES-GCM
│   │   ├── models/               SQLAlchemy ORM (11 tables)
│   │   ├── schemas/              Pydantic DTOs
│   │   ├── services/             email, storage, auth, alerts, rate_limit, policy, geoip, blocklist, captcha
│   │   ├── middleware/           rate_limit, csrf
│   │   ├── routers/              public (upload/download/sender panel), admin (12 endpoints)
│   │   ├── worker/               Redis-queue consumers + APScheduler tasks
│   │   └── tus/                  minimal tus 1.0.0 PATCH/HEAD handler
│   ├── alembic/versions/         6 schema migrations
│   ├── scripts/                  create_admin, wrap_totp_secrets, rotate_master_key
│   ├── tests/
│   │   ├── unit/                 221 tests (crypto, services, schemas)
│   │   └── integration/          130 tests (full stack via docker compose)
│   ├── Dockerfile                multi-stage prod (270 MB, --no-dev)
│   └── Dockerfile.dev            dev image with pytest + deps for in-container tests
│
├── frontend/                     Public SPA — Vue 3 + Vite + TS
│   ├── src/
│   │   ├── api/                  typed client + CSRF
│   │   ├── components/           TopBar, AppFooter (animated Hawk), ChipInput, FileDropZone, ProgressBar, CopyButton, CookieBanner
│   │   ├── views/                Upload, UploadSuccess, SenderPanel, Legal, NotFound
│   │   ├── stores/               settings (theme, cookie-consent)
│   │   ├── composables/          useTusUpload
│   │   ├── i18n/                 ru.json, kk.json, en.json
│   │   └── styles/               tokens.css (design tokens — navy/blue theme), reset.css
│   └── Dockerfile                multi-stage → nginx:alpine SPA host
│
├── admin-frontend/               Admin SPA — Vue 3 + Vite + TS + Chart.js
│   └── src/views/                12 pages: Login, Dashboard, Transfers, Search, Blocklist, Limits,
│                                 Extensions, Analytics, Audit, AdminActions, Admins, Telegram
│
├── nginx/                        TLS termination + routing + IP allow-list
├── scripts/                      host-side ops: master-key gen, dev-certs, backup/restore, key-rotation
├── docs/                         Deployment, Security, Backup, Key Rotation, CI docs
├── data/                         Runtime bind-mounts (gitignored): postgres, redis, minio, staging, geoip, backups
├── secrets/                      Master key + age key + TLS certs (gitignored)
├── docker-compose.yml            Dev composition (uses Dockerfile.dev)
├── docker-compose.prod.yml       Prod override (uses Dockerfile, sets APP_ENV=production)
└── Makefile                      Lifecycle + CI + ops targets
```

### Testing

**Host-side** (unit only — no Docker needed):

```bash
cd backend
POSTGRES_DB=x POSTGRES_USER=x POSTGRES_PASSWORD=x \
  MINIO_ROOT_USER=x MINIO_ROOT_PASSWORD=x \
  uv run pytest tests/unit -v
```

**In-container** (integration — requires stack up):

```bash
docker compose exec api /opt/venv/bin/pytest tests/integration -v -m integration
```

**TLS-specific** tests (opt-in, host-side):

```bash
cd backend
TLS_URL=https://localhost uv run pytest tests/integration/test_healthz.py -v -m integration
```

Full suite summary:
- **221 unit tests** (crypto, services, schemas, middleware, HTTP helpers, pagination cursors, settings validation, DLQ, metrics, envelope wrap for TOTP + Telegram)
- **130 integration tests** (end-to-end via HawkAPI + Postgres + Redis + MinIO + mailpit; 122 pass + 8 skipped for external SMTP/TLS infra)
- **3 skipped** (TLS tests needing `TLS_URL`), **1 skipped** (cookie-toggle requires container restart)

---

## Technology stack

### Backend
- **Python 3.12** + HawkAPI 0.1.4 + Pydantic 2 + SQLAlchemy 2 (async) + Alembic
- **PostgreSQL 16** (citext, pg_trgm, gen_random_uuid)
- **Redis 7** (Lua-atomic rate-limit, session store, queues)
- **MinIO** (S3-compatible object storage)
- **cryptography** 43 (AES-KW + AES-256-GCM low-level Cipher)
- **argon2-cffi** (password hashing) + **pyotp** (TOTP) + **geoip2** (MaxMind) + **aiosmtplib** (SMTP)
- **APScheduler** + **aiohttp** + **python-magic** + **stream-zip**

### Frontend
- **Vue 3.5** + Vite 5 + TypeScript 5 + Pinia 2 + vue-router 4 + vue-i18n 10
- **tus-js-client** 4 (resumable uploads)
- **Chart.js 4** + vue-chartjs 5 (admin analytics)
- Hand-rolled components using the project's design tokens (navy `#272666`, blue `#94BDE5`, Inter) — customise in `frontend/src/styles/tokens.css` to match your own brand

### Infrastructure
- **Docker Compose v2** (8 services: nginx, api, worker, frontend, admin-frontend, postgres, redis, minio + mailpit in dev profile)
- **Nginx 1.27** (TLS 1.3, HSTS, limit_req, geo allow-list, SPA fallback)
- **age** for encrypted backups

---

## Security posture

Fylix is designed to survive full compromise of any single layer:

- **DB leak**: ciphertext is unreadable without the master key (Docker secret, never in DB).
- **MinIO leak**: ciphertext is unreadable without wrapped per-transfer keys (in DB).
- **Master key leak without DB**: no ciphertext to decrypt.
- **Backup leak**: age-encrypted, recipient-only decryptable.
- **Admin session leak**: HttpOnly + Secure + SameSite=Strict + CSRF double-submit + 30-min sliding TTL.
- **Admin password leak**: Argon2id + TOTP + lockout; TOTP secret is itself wrapped with master key.
- **Rate-limit bypass**: 2-layer (Nginx `limit_req` + app Redis Lua atomic).
- **Malware upload**: Microsoft Defender on staging + extension blacklist + MIME sniff via `python-magic`.

See [docs/SECURITY.md](docs/SECURITY.md) for the full threat-model matrix (20+ rows).

---

## Documentation

| Document | Purpose |
|---|---|
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Full production deployment runbook — TLS, MaxMind, Defender, SMTP relay, CIDR allow-list, bootstrap sequence, health checks, upgrade path, observability stack |
| [docs/KUBERNETES_DEPLOYMENT.md](docs/KUBERNETES_DEPLOYMENT.md) | Kubernetes blue-green deployment — colour-selector pattern, manifests, traffic flip, rollback window, schema-migration Job, Ingress + NetworkPolicy, observability wiring |
| [docs/SECURITY.md](docs/SECURITY.md) | Threat model + controls matrix + known limitations + compliance posture (GDPR, ISO 27001) |
| [docs/BACKUP.md](docs/BACKUP.md) | Backup and restore procedures via `age` — one-time key setup, scheduled backups, retention policy, off-site upload, restore drill |
| [docs/KEY_ROTATION.md](docs/KEY_ROTATION.md) | Master-key rotation ceremony — pre-flight, rotation, paper ceremony for old key, rollback, cadence |
| [docs/CI.md](docs/CI.md) | CI/CD pipeline + local security scan guide (bandit, pip-audit, semgrep, trivy) |
| [docs/MIGRATION.md](docs/MIGRATION.md) | FastAPI → HawkAPI 0.1.5 migration notes — shim catalogue + known follow-ups |
| [docs/SLO.md](docs/SLO.md) | Service Level Objectives, error budgets, alert rules (Prometheus) |
| [docs/INCIDENT_RESPONSE.md](docs/INCIDENT_RESPONSE.md) | Playbooks per failure mode (master-key compromise, crypto-shred breach, admin lockout, storage corruption) |
| [docs/CHAOS_PLAN.md](docs/CHAOS_PLAN.md) | Chaos-engineering experiment catalogue (staging-only) + capacity-planning triggers |
| [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) | STRIDE threat model for the 4 critical flows (upload, download, admin login, key rotation) |

---

## Using with Claude Code

This project includes a [CLAUDE.md](CLAUDE.md) that gives Claude Code full context — commands,
architecture, key files, and configuration.

```bash
claude    # Start Claude Code — reads CLAUDE.md automatically
```

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for dev environment setup,
test/lint commands, and PR conventions.

## License

MIT — see [LICENSE](LICENSE).

## Credits

Built with [HawkAPI](https://github.com/ashimov/HawkAPI). Developed by [Berik Ashimov](https://linkedin.com/in/berik-ashimov).
