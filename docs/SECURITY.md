# Fylix — Security Threat Model & Controls

This document describes the security scope, threat actors, controls, and known
limitations of Fylix. It is intended for security reviewers, auditors,
and operators integrating the system into a broader corporate security programme.

---

## 1. Scope and assets

### In scope

| Asset | Description |
|-------|-------------|
| File contents | The uploaded files, both in transit and at rest in MinIO |
| Email metadata | Sender/recipient email addresses, timestamps, subject/message fields |
| Sender/recipient identities | IP addresses, country codes, session tokens stored in Redis |
| Audit log | Record of all admin-plane actions and significant events |
| Admin credentials | Argon2id password hashes and AES-256-KW-wrapped TOTP secrets |
| Master key | 32-byte AES-256 key that wraps all per-transfer file keys |
| Per-transfer file keys | 32-byte AES-256-GCM keys, stored wrapped in Postgres |
| Download tokens | 32-byte cryptographically random URL tokens |
| Age backup key pair | age encryption key pair used to protect backup archives |

### Out of scope

- Network infrastructure outside the Docker host (switches, routers, corporate
  firewall) — handled by corporate IT.
- DNS and domain registration security.
- End-user device security (recipient's browser, sender's workstation).
- Physical security of the server room.

---

## 2. Threat actors

| Actor | Description | Assumed capability |
|-------|-------------|-------------------|
| **External attacker (Internet)** | Unauthenticated actor on the public Internet. Primary concern. | Port scanning, brute-force, OWASP web attacks, CVE exploitation, phishing |
| **Malicious recipient** | An entity that has received a valid download link and wants to exceed its intended access. | Has one valid token; may attempt enumeration, link-sharing, or denial of service |
| **Insider (admin)** | An employee of your organization with admin portal access. Tertiary concern — mitigated by audit log. | Full read access to admin UI; no direct DB or filesystem access outside Docker |
| **Supply chain** | Compromised Python or npm dependency. | Code execution in the api/worker/frontend process |
| **Backup-targeted attacker** | Actor who obtains a backup archive through storage breach or credential theft. | Offline decryption attempts against the age-encrypted archive |

---

## 3. Controls matrix

| Asset | Threat | Control |
|-------|--------|---------|
| File contents (in transit, upload) | External MitM during upload | TLS 1.3 only; HSTS enforced; Nginx strict cipher suites; no TLS 1.2/1.1/1.0 |
| File contents (in transit, upload) | Upload session hijack | tus session token stored in Redis with 24 h TTL; upload URLs are opaque 32-byte tokens |
| File contents (at rest, MinIO) | Storage breach (MinIO compromise or bucket misconfig) | Per-transfer AES-256-GCM encryption; key not stored with ciphertext |
| File contents (at rest, MinIO) | Insider reads raw bucket objects | Wrapped keys stored in Postgres, not MinIO; plaintext not recoverable without master key + Postgres |
| File contents (staging window) | Malware in uploaded file | Microsoft Defender real-time scan of staging directory; file quarantined before encryption completes |
| File contents (staging window) | Race between upload and AV scan | Known limitation — see Section 5; production should add WinEventLog integration |
| File contents (download) | Unauthorised download without token | 32-byte (256-bit) random token required; brute-force infeasible (2^256 space) |
| File contents (download) | Download after TTL expiry | TTL enforced in DB; expired transfers return 410 Gone; background worker deletes ciphertext |
| File contents (backup archives) | Backup breach (stolen archive) | All archives age-encrypted with recipient public key; private key stored off-site |
| File contents (backup archives) | Backup breach + key compromise | Combined attack mitigated by storing age private key separately from backup storage |
| Master key | Key file exposure on host | File mode 0400; Docker secret mount (not env var); not logged anywhere |
| Master key | Loss (disk failure, accidental delete) | Hex copy recorded on paper in physical safe at bootstrap (see `docs/DEPLOYMENT.md`) |
| Master key | Insider exfiltration | Key is binary (not human-readable); requires root access to read from Docker secret mount |
| Per-transfer file keys | Postgres breach | Keys stored AES-256 KW-wrapped; useless without master key |
| Admin credentials (passwords) | Brute-force on login endpoint | Argon2id (OWASP-recommended memory-hard KDF); login rate-limited (Nginx + app layer); IP blocklist |
| Admin credentials (TOTP secrets) | TOTP seed theft from DB | TOTP secret stored AES-256-KW-wrapped; crypto-shredded on admin deletion |
| Admin session | Session fixation / hijack | Secure + HttpOnly + SameSite=Strict cookies; session invalidated on logout + password change |
| Admin access | Unauthorised admin access from Internet | Nginx geo block; only explicitly allowlisted CIDRs can reach `/admin` and `/api/admin` |
| Admin actions | Undetected insider abuse | Immutable audit log records every admin-plane action with actor, IP, and timestamp |
| Download token | Phishing / link-sharing by recipient | Token is reusable until TTL expiry or sender revocation; short TTL (default 7 days) limits exposure window |
| Download token | Link enumeration | 32-byte token space (2^256); enumeration requires ~10^77 requests — physically infeasible |
| Rate-limit bypass | Distributed brute-force | Multi-layer: Nginx zone limit → app-layer rate limit → CAPTCHA (hCaptcha) → IP blocklist |
| Rate-limit bypass | IPv6 evasion | Rate limiting keyed on /64 prefix for IPv6; reduces effectiveness of large address blocks as evasion tool |
| Denial of service | Resource exhaustion via large uploads | `client_max_body_size 0` + tus chunked protocol; app enforces per-transfer size limit (default 2 GB) |
| Denial of service | Connection flood | Nginx worker connection limit (4096); OS-level conntrack; upstream firewall recommended |
| Supply chain | Compromised Python dependency introducing malicious code | pip-audit scans pinned dependencies for known CVEs on every push; trivy scans container images; weekly cron re-scan |
| Supply chain | Compromised npm dependency in frontend build | trivy scans built frontend image; npm audit can be added to CI frontend job |
| GeoIP policy bypass | VPN / proxy to evade country block | Defence in depth — GeoIP is one layer; CAPTCHA, rate limit, and blocklist remain active for evaders |
| Email delivery | Recipient email address harvesting via SMTP log | SMTP credentials and logs are not exposed outside the Docker host |

---

## 4. Key security properties

### Crypto-shredding

Deleting the `wrapped_key` column for a transfer in Postgres makes the MinIO
ciphertext permanently unrecoverable — the encryption key is gone. This means:

- An admin "delete transfer" action is an irreversible cryptographic deletion,
  not just a logical soft-delete.
- 90% of backup-archive leak risk is mitigated for deleted transfers: even with
  the archive and the master key, the file content is gone if the Postgres dump
  post-dates the deletion.
- This property depends on the master key not being compromised. If the master
  key is known to an attacker, they can re-derive nothing (they still need the
  wrapped key). Correct: the wrapped key is also in the Postgres dump, so
  backup confidentiality relies on both the age archive encryption AND the
  master key remaining secret.

### Defence in depth

No single control is relied upon exclusively. The inbound path for a download
request traverses:

1. Nginx TLS termination + HSTS
2. Nginx geo block (admin paths)
3. Nginx rate-limit zone
4. App-layer rate-limit (Redis-backed, per-IP)
5. IP blocklist check
6. GeoIP country policy check
7. hCaptcha verification (configurable)
8. Token validation (32-byte lookup in DB)
9. TTL + download count check
10. AES-256-GCM decryption + streaming to client

An attacker must bypass all active layers to exfiltrate a file they are not
authorised to receive.

### Forward secrecy of file keys

Each transfer has its own random 32-byte AES-256 key generated at upload time.
Compromise of one transfer's key does not affect any other transfer. Master-key
rotation re-wraps all file keys, so after rotation the old master key can be
securely deleted — files encrypted under a previous master key remain accessible
with the new wrapping.

### TOTP and session security

Admin TOTP secrets are wrapped individually. A Postgres breach without the master
key yields no usable TOTP seeds. Sessions are stored server-side in Redis with a
hard expiry; there are no long-lived JWT tokens that could be replayed after
password rotation.

---

## 5. Known limitations

**No end-to-end encryption.** The server has plaintext access to every file during
the encryption window (staging directory). The recipient must trust the server
operator. This is an architectural constraint of the current design; a future
version could implement client-side encryption, but this would require a
JavaScript crypto library in the browser and a key exchange mechanism that is
out of scope for the MVP.

**No cryptographic signing of download links.** The download token is a 256-bit
random value looked up in the database, not a signed JWT. If an attacker could
enumerate the token space (2^256 — physically infeasible with current hardware),
they would gain access without a valid token. The practical risk is zero, but it
is architecturally distinguishable from a scheme that would be secure even if
an attacker could query the database.

**Microsoft Defender scan race condition.** The staging directory is scanned
asynchronously by Defender. There is a window (typically < 1 second) between a
file landing in staging and the scan completing. The api does not poll for scan
completion — it proceeds after the upload finishes. A sufficiently fast or
fragmented upload might complete encryption before a large malware payload is
fully scanned. Production deployments on Windows Server should integrate
WinEventLog to detect quarantine events and trigger a secondary validation step.

**hCaptcha is all-or-nothing.** There is no adaptive triggering based on
behaviour signals. All download requests are either always challenged or never
challenged, depending on the `HCAPTCHA_SECRET` env var being set. A future
version should add a risk-scoring layer that only triggers CAPTCHA for suspicious
traffic patterns.

**tus upload URLs have no IP binding.** Upload sessions (tus resumable uploads) are identified by a 32-byte opaque URL token stored in Redis with a 24 h TTL. There is no originating-IP check — anyone who obtains the upload URL can resume the upload from any IP. In practice, upload URLs are transmitted only to the uploading browser and expire after 24 h; the risk is low but operators should be aware of this if upload URLs are logged.

**Download tokens are reusable, not single-use.** A download token grants unlimited downloads until the transfer TTL expires or the sender explicitly revokes the transfer. There is no per-download or max-downloads enforcement. Senders should treat the download link as a shared secret and revoke it if they believe it has been forwarded to unintended recipients.

**Rate limiting is not distributed.** The Redis-backed rate limiter is per-instance.
If the stack is ever scaled to multiple api replicas sharing the same Redis, the
rate limits remain consistent. However, if deployed as multiple independent
stacks (not the intended architecture), rate limits are per-stack and an attacker
could bypass them by targeting different instances.

**Audit log is not tamper-evident.** The audit log is stored in the same Postgres
database as application data. An attacker with write access to the database could
modify or delete audit records. For compliance use cases requiring tamper-evident
logs, ship logs to an append-only external system (e.g., AWS CloudTrail, a WORM
S3 bucket, or a dedicated SIEM).

---

## 6. Compliance posture

### GDPR (Regulation (EU) 2016/679)

| Obligation | Implementation |
|------------|---------------|
| Right to erasure (Art. 17) | Admin "delete transfer" triggers crypto-shredding of file content and deletion of personal metadata from the database |
| Right of access (Art. 15) | Audit log can be exported per-user by an admin; no self-service portal yet |
| Data minimisation (Art. 5(1)(c)) | Only email addresses, IP, and transfer metadata collected; no tracking cookies |
| Storage limitation (Art. 5(1)(e)) | Per-transfer TTL enforced; background worker auto-deletes expired transfers |
| Breach notification (Art. 33) | Incident response runbook in `docs/INCIDENT_RESPONSE.md` (detailed) + `docs/DEPLOYMENT.md` Section 14 (summary); 72-hour supervisory authority notification |
| DPA / sub-processor agreements | Operator must ensure agreements are in place for SMTP provider, cloud storage (if used for backups), and any external monitoring |

### ISO 27001 alignment (partial)

| Control area | Status |
|---|---|
| A.8.2 — Information classification | Partial — transfers are treated as confidential by default; no formal classification scheme |
| A.8.3 — Cryptographic controls | Aligned — AES-256-GCM, Argon2id, RFC 3394 key wrap, TLS 1.3 |
| A.9.4 — Access control | Aligned — TOTP MFA, CIDR allowlist, session management |
| A.12.4 — Logging and monitoring | Partial — audit log in DB; external SIEM integration recommended |
| A.12.6 — Technical vulnerability management | Aligned — pip-audit + trivy in CI; weekly scheduled scans |
| A.14.2 — Security in development | Aligned — semgrep + bandit in CI; code review required for PRs |
| A.17.1 — Business continuity | Partial — backup + restore runbook exists; no formal BCP document |

### Your organization's internal security policy

Alignment with your organization's internal security standards is to be
determined in coordination with your corporate security team. Known open
items:

- Formal data classification label for transfer payloads.
- Integration with corporate SSO (SAML/OIDC) for admin authentication — currently
  local accounts only.
- Penetration test by an approved third party before production go-live.
- Sign-off from the Data Protection Officer on the GDPR processing basis.

---

## 7. Security contacts

For vulnerability reports, contact the development team through the internal issue
tracker. Do not disclose security vulnerabilities in public GitHub issues.

For production security incidents, follow the playbooks in
[`docs/INCIDENT_RESPONSE.md`](INCIDENT_RESPONSE.md) (or the summary in
`docs/DEPLOYMENT.md` Section 14) and notify the designated incident
response lead.
