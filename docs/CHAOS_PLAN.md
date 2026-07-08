# Fylix Chaos Engineering Plan

Owner: Fylix SRE
Last updated: 2026-04-20
Scope: **staging only** — never run these scenarios against the
production deployment without an explicit change-management approval.

## Goals

Validate that Fylix fails **loud and correctly**, not silently:

1. Every dependency loss produces a visible alert (Grafana / pager).
2. No data loss — in-flight uploads either complete or fail cleanly;
   encrypted transfers are never left half-stored.
3. Recovery on the happy path is automatic once the dependency comes
   back; manual intervention is only required for corruption.
4. User-visible error messages remain crisp (no stack traces leaked,
   no infinite spinners).

---

## Experiment catalogue

Each experiment has: **hypothesis → procedure → expected observation →
acceptance criteria → cleanup**.

### 1. Postgres pause (connection starvation)

**Hypothesis:** api returns 503 within 5 s; existing admin sessions
continue to read cached settings; worker DLQs encrypt jobs rather
than busy-spinning.

**Procedure:**
```bash
docker compose pause postgres
# run for 60 seconds
sleep 60
docker compose unpause postgres
```

**Expected:**
- `GET /healthz` goes from 200 → 503 within 5 s.
- Any in-flight upload (TUS PATCH) returns 500 with `{"detail":"..."}`
  — NOT a hung connection.
- Worker logs "DB unreachable, deferring job" (retries via DLQ).
- On unpause, api recovers within 10 s, worker resumes.

**Acceptance:** No stuck connections reported by `pg_stat_activity`
after unpause. Grafana queue-depth returns to steady-state.

---

### 2. Redis kill (queue + session loss)

**Procedure:**
```bash
docker compose stop redis
# wait 30s
docker compose start redis
```

**Expected:**
- Admin session lookup fails → users bounced to login. Acceptable.
- Rate-limit middleware fails open (documented trade-off) — uploads
  continue to work.
- Worker paused (pop_job fails). When Redis returns, worker resumes
  polling.

**Acceptance:** No in-flight transfer stuck in `status='uploading'`
longer than the reconnect window. Grafana rate-limit spike dashboard
shows the outage window clearly.

---

### 3. MinIO disk-full simulation

**Procedure:**
```bash
# Fill MinIO to 99% and attempt an upload
docker compose exec minio sh -c 'dd if=/dev/zero of=/data/_filler bs=1M count=$(df -B1M /data | awk "NR==2 {print int(\$4*0.99)}")'
```

**Expected:** Worker encrypt task fails with MinIO "insufficient
space" error → transfer flipped to `status='infected'` and cleanup
attempts bucket-delete fallback.

**Cleanup:** `docker compose exec minio rm /data/_filler`.

---

### 4. Worker kill during encrypt

**Procedure:** Start a large (500MB) upload, wait for TUS PATCH to
complete all chunks + transition to `upload:ready` queue, then:
```bash
docker compose kill -s SIGKILL worker
sleep 5
docker compose up -d worker
```

**Expected:**
- Idempotency lock (`transfer:{id}:encrypting` in Redis, TTL 600s)
  expires after 10 min OR the new worker detects it.
- On next dequeue, encrypt runs cleanly — no duplicate MinIO
  objects, no wrapped_key overwrite.
- Audit log shows `upload_complete` exactly once.

**Acceptance:** `SELECT COUNT(*) FROM audit_log WHERE event_type='upload_complete' AND transfer_id=?` = 1.

---

### 5. Nginx upstream flap

**Procedure:** Repeatedly bring api down and up during a zip download:
```bash
for i in 1 2 3; do
  docker compose stop api; sleep 2; docker compose start api; sleep 8
done
```

**Expected:**
- tus client auto-resumes uploads (built-in).
- Download (non-resumable via HTTP/1.1) gets aborted; client sees
  `ERR_INCOMPLETE_CHUNKED_ENCODING` — documented behaviour.
- Nginx 502 during the window, 200 resumed within seconds.

---

### 6. OTel collector loss (Jaeger down)

**Procedure:** `docker compose stop jaeger`

**Expected:** api + worker continue serving normally. OTel BatchSpan
Processor buffers up to N spans in memory then drops oldest. No
crash, no latency regression on user-facing paths.

**Acceptance:** User-facing SLIs unaffected during the window. Logs
may show OTLP export failures — benign.

---

## Capacity planning scenarios

### Quarterly reporting peak

Partners submit quarterly reports over ~3 days at quarter-end:
- Expected: 10× normal upload volume, average 500MB per transfer,
  burst up to 50 concurrent uploads.
- Headroom check: run the Postgres pause + Redis kill experiments
  during a synthetic load of 50 concurrent 500MB uploads (use `k6`
  or `hey` against `/api/transfers` + TUS PATCH). Verify no SLO
  breach during the burst.

### Scale-up trigger

If any of these thresholds sustain > 30 min:
- `p99 upload POST latency > 500ms` → add an api replica behind nginx
  upstream (round-robin).
- `worker queue depth > 100` → start a second worker replica (set
  `WORKER_ID` env so only one runs cleanup).
- Postgres connections > 150 → raise `max_connections` to 400 and
  add PgBouncer in transaction-pooling mode.

---

## Drill cadence

- Run the catalogue quarterly in staging (aligns with
  `docs/INCIDENT_RESPONSE.md` drill schedule).
- One exploratory "game day" per year: pick an unexpected scenario
  (Postgres + MinIO simultaneously, DNS outage, Defender blocking
  legitimate files) and see where the runbooks break.
- Every chaos run → new row in `docs/DRILL_LOG.md`.

---

## Safety guardrails

- **Never run against production.** The `docker compose` commands
  here assume dev/staging. Production has different restart policies,
  real users, and audit-log consequences.
- **Capture metrics.** Grafana dashboards should show the experiment
  window cleanly; if the experiment is invisible in dashboards, our
  instrumentation is the bug.
- **Written hypothesis first.** Don't run a scenario without a
  prediction — otherwise you're breaking things, not learning.
