# Fylix Threat Model (STRIDE)

Owner: Fylix security
Last updated: 2026-04-20
Methodology: [STRIDE](https://learn.microsoft.com/en-us/azure/security/develop/threat-modeling-tool-threats) per data flow. Paired with
`docs/SECURITY.md` (defense-in-depth control catalogue) and
`docs/INCIDENT_RESPONSE.md` (recovery playbooks).

This document covers the four highest-risk flows. Threats rated
**H/M/L** on (probability × impact). Every **H** must either be
mitigated by a current control or have a tracked follow-up ticket.

---

## Flow A — Anonymous upload (`POST /api/transfers` + TUS PATCH)

Actors: external internet client (no authentication).

| # | Category | Threat | Rating | Mitigation | Gap |
|---|---|---|---|---|---|
| A1 | **S**poofing | Attacker claims to be a trusted partner by setting `sender_email` to a fake address. | M | Captcha + blocklist + GeoIP; senders are never trusted to prove identity (the platform is "anonymous sender, traceable transfer"). | None — documented security model. |
| A2 | **T**ampering | Intermediary modifies staging file before encrypt. | L | Nginx TLS only; staging bind-mount under restrictive permissions; Defender integrity check. | Staging is not on tmpfs — host admin can tamper. |
| A3 | **R**epudiation | Sender denies uploading. | L | `audit_log` captures IP, UA, country, timestamp; Microsoft Defender records file-touch events. | OK. |
| A4 | **I**nformation disclosure | Plaintext leaks via staging file or memory. | **H** | Staging bind-mount on LUKS-encrypted host disk. Encrypt-in-memory via `SpooledTemporaryFile` (64 MiB threshold). Master key only in process memory. | Staging has plaintext between TUS PATCH and worker encrypt. If the host is imaged during that window, plaintext leaks. **Follow-up:** reduce window with faster worker pickup. |
| A5 | **D**enial of service | Resource exhaustion via huge file count / size. | M | Rate limit (hourly + daily per IP), 2 GB total size cap, 100-file cap, extension blacklist. | Single IP can chain many sessions with different domains before blocklist triggers. |
| A6 | **E**levation of privilege | Upload leads to RCE on worker. | **H** | MIME sniff via python-magic, Defender scan before encrypt, no server-side file execution, stream-zip pure-Python (no shell). | Python-magic wraps libmagic C — relies on lib CVE status. Track via SBOM. |

---

## Flow B — Anonymous download (`GET /t/{token}/file/{id}`)

Actors: external internet client holding the download token.

| # | Category | Threat | Rating | Mitigation | Gap |
|---|---|---|---|---|---|
| B1 | **S** | Token guess | L | 256-bit random token; Base64url encoded; validation constant-time. | None. |
| B2 | **T** | Ciphertext modified in MinIO out-of-band. | M | SHA-256 stored per-file; AES-GCM auth-tag check on stream. | Tamper detectable only at full-stream consumption, not partial. |
| B3 | **R** | Downloader claims they didn't receive. | L | `downloads` row per fetch with IP + UA + timestamp; email notification to sender. | OK. |
| B4 | **I** | Token leak via URL history / referer / proxy logs. | **H** (fixed) | **Tokens no longer in URL** post-upload (stashed in sessionStorage; UploadSuccessView consumes + removes). Download links emailed separately. | Still exposed in recipient email forwarding — operator education. |
| B5 | **D** | Bandwidth flood via repeated re-downloads. | M | Rate-limit on `/t/.../file/...` per IP; CDN in front (optional). | Not behind CDN in dev; prod should front with CloudFront or similar. |
| B6 | **E** | Server-side vuln via filename injection. | L | `Content-Disposition` filename percent-encoded + ASCII-fallback; no shell invocation. | OK. |

---

## Flow C — Admin login (`POST /api/admin/login`)

Actors: Admin on CIDR-allowed network.

| # | Category | Threat | Rating | Mitigation | Gap |
|---|---|---|---|---|---|
| C1 | **S** | Credential stuffing. | **H** | Argon2id (time=3, mem=64MB); constant-time dummy hash for unknown users; 5-strike lockout with 15-min window. | Relies on admin hygiene — add WebAuthn as a follow-up for passwordless. |
| C2 | **T** | Session cookie tampering. | L | Session ID is Redis lookup (server-side state), not JWT — cookie is an opaque handle. | OK. |
| C3 | **R** | Admin action not traced. | L | `admin_actions` table logs every mutating endpoint with IP + ctx.admin.id. | OK. |
| C4 | **I** | TOTP secret in DB leaks. | **H** | AES-KW wrap with master key (40→48 bytes). Wrapped-TOTP check + legacy-plaintext migration path. | Plaintext secrets may linger from pre-wrap migration. `wrap_totp_secrets.py` must run and ops must verify zero plaintext before any key rotation. |
| C5 | **D** | Lockout cascade — attacker locks all admins. | M | Break-glass admin account documented in `docs/INCIDENT_RESPONSE.md §3`. | Break-glass must be rotated annually. |
| C6 | **E** | RCE via login payload. | L | Pydantic validation; parameterised SQLAlchemy. | OK. |

---

## Flow D — Master-key rotation

Actors: Your security lead + operations.

| # | Category | Threat | Rating | Mitigation | Gap |
|---|---|---|---|---|---|
| D1 | **S** | Unauthorised operator triggers rotation. | M | Rotation runs a Python script on the host, not via the app. Host access is restricted; script logs to audit. | No MFA gate on the rotation script itself — relies on OS-level auth. |
| D2 | **T** | New key generated with weak entropy. | **H** | `secrets.token_bytes(32)` uses OS CSPRNG. | Document that `/dev/urandom` must be seeded (container start time). |
| D3 | **R** | Who rotated, when? | L | Script writes `audit_log: key_rotated` entry. | OK. |
| D4 | **I** | Both keys present briefly during rotation. | M | Zero-downtime rotation uses a `master_key_previous_path` env; both in memory during the rewrap window. Window is minutes at the scale of Fylix data. | Same as A4 — RAM is encrypted only at OS level. |
| D5 | **D** | Partial rewrap leaves some transfers undecryptable. | **H** | Script is transactional — either all transfers rewrap or none. | Failure in the middle today rolls back — verify in a staging drill. |
| D6 | **E** | Old key left readable on disk. | **H** | Offline ceremony shreds the old key file (`shred -u`); online mode moves it to encrypted off-host storage. | Relies on operator discipline — add a post-rotation checklist step that verifies the old key is no longer on disk. |

---

## Cross-cutting threats

| # | Threat | Mitigation |
|---|---|---|
| X1 | Dependency chain attack (pypi supply chain). | Lockfile `uv.lock` pinned; SBOM generated in CI (tracked follow-up); Dependabot on GitHub. |
| X2 | Container escape. | Non-root `fylix` uid 1001 in images; read-only volumes where possible; Docker secrets for master key (not env). |
| X3 | Timing side-channel in auth. | constant-time comparisons via `secrets.compare_digest` + `_auth.dummy_hash()` for unknown users. |
| X4 | GDPR Art. 33 breach notification. | See `docs/INCIDENT_RESPONSE.md §1`. |

---

## Workshop schedule

Repeat this STRIDE walk every 6 months with your security team. Agenda:

1. Review this document.
2. Pick one **H** gap and either fix it (PR merged within the sprint)
   or formally accept it with DPO sign-off.
3. Add new flows if the platform has grown (e.g., SFTP inbound,
   S3 cross-account).

Pen-testing: Scope an external pen-test every 6 months. Preferred
flows to test: Flow A (upload) and Flow C (admin login). Deliverables
feed back into this document as new rows.
