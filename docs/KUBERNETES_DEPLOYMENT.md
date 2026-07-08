# Fylix — Kubernetes Blue-Green Deployment

Owner: Fylix SRE
Last updated: 2026-04-20
Related: `docs/DEPLOYMENT.md` (docker-compose / single-host), `docs/SLO.md`,
`docs/CHAOS_PLAN.md`, `docs/KEY_ROTATION.md`

This document covers running Fylix on Kubernetes with zero-downtime
blue-green releases. It assumes **stateful dependencies (Postgres,
MinIO, Redis) are operated externally** (managed service or dedicated
StatefulSets owned by the platform team) — only the stateless
api / worker / frontend / admin-frontend ship blue-green.

For small deployments you can keep docker-compose; use this doc when:

- You need **zero-downtime upgrades** (the compose upgrade path has a
  ~30 s gap — see `DEPLOYMENT.md §13`).
- You're running multiple replicas for capacity (`docs/CHAOS_PLAN.md`
  "Scale-up trigger").
- Your organization's platform policy is K8s-only.

---

## 1. Topology

```
                        ┌─────────────────────────────┐
                        │  Nginx Ingress Controller   │   (TLS termination,
                        │  (nginx-ingress / Traefik)  │    CIDR allowlist)
                        └──────────────┬──────────────┘
                                       │
                 ┌─────────────────────┼─────────────────────┐
                 │                     │                     │
          ┌──────▼──────┐       ┌──────▼──────┐       ┌──────▼──────┐
          │  svc-api    │       │  svc-admin  │       │  svc-public │
          │  (selector: │       │  (selector: │       │  (selector: │
          │  colour=??) │       │  colour=??) │       │  colour=??) │
          └──────┬──────┘       └──────┬──────┘       └──────┬──────┘
                 │                     │                     │
    ┌────────────┴────────┐   ┌────────┴──────┐   ┌──────────┴──────────┐
    │ Deployment: api-    │   │ Deployment:   │   │ Deployment:         │
    │   blue  or  green   │   │   admin-blue  │   │   frontend-blue     │
    │ (colour label)      │   │   or -green   │   │   or -green         │
    └────────────┬────────┘   └───────────────┘   └─────────────────────┘
                 │
         ┌───────┴───────┐         (worker has no Service; it consumes
         │  Deployment:  │          from Redis directly, so colour swap
         │  worker-blue  │          is independent — see §5 Worker)
         │  or -green    │
         └───────────────┘

Stateful deps (external to the release):
 ┌──────────┐   ┌──────────┐   ┌──────────┐
 │ Postgres │   │  Redis   │   │  MinIO   │
 │  (HA)    │   │  (HA)    │   │  (HA)    │
 └──────────┘   └──────────┘   └──────────┘
```

### The colour selector trick

Every Service has a selector that reads a `colour` label. The active
colour is stored in a single ConfigMap (`fylix-active-colour`) and
the traffic switch is one `kubectl patch svc …` that flips the
selector from `colour=blue` to `colour=green` (or vice-versa).

---

## 2. Namespace + RBAC

```yaml
# namespace.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: fylix-prod
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/warn: restricted
```

Restricted Pod Security Standard enforces non-root, read-only root
filesystem, no privilege escalation — matches the non-root `fylix`
uid 1001 in `backend/Dockerfile`.

---

## 3. Secrets

The master key **must** be a K8s `Secret` (not env var), mounted as
a file so lifespan's `load_master_key(...)` + the
`MASTER_KEY_PATH=/run/secrets/master_key` contract unchanged from
docker-compose.

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: fylix-master-key
  namespace: fylix-prod
type: Opaque
data:
  master_key: <base64 of the 32-byte key>
```

For rotation, see `docs/KEY_ROTATION.md` — the K8s variant is:

1. Create `fylix-master-key-next` with the new key.
2. Patch the Deployment to mount both (`/run/secrets/master_key` and
   `/run/secrets/master_key_prev`), set env
   `MASTER_KEY_PREVIOUS_PATH=/run/secrets/master_key_prev`.
3. Run `backend/scripts/rotate_master_key.py` rewrap phase.
4. Delete `fylix-master-key`, rename next → master.
5. Remove the `_prev` mount + env.

Other secrets: `smtp`, `telegram-bot`, `hcaptcha`, `postgres-dsn`,
`minio-creds`. Use [ExternalSecrets Operator](https://external-secrets.io/)
with HashiCorp Vault or AWS Secrets Manager — never commit them into
git as sealed-secret cipher blobs unless the operator is audited.

---

## 4. Deployments (api)

Blueprint for `api-blue`. Clone with `s/blue/green/` for green.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api-blue
  namespace: fylix-prod
  labels: { app: fylix-api, colour: blue }
spec:
  replicas: 3
  selector:
    matchLabels: { app: fylix-api, colour: blue }
  strategy:
    type: RollingUpdate
    rollingUpdate: { maxSurge: 1, maxUnavailable: 0 }
  template:
    metadata:
      labels: { app: fylix-api, colour: blue }
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 1001
        fsGroup: 1001
        seccompProfile: { type: RuntimeDefault }
      containers:
        - name: api
          image: registry.example.com/fylix/api:1.1.0      # pinned, NEVER :latest
          imagePullPolicy: IfNotPresent
          ports:
            - { name: http, containerPort: 8000 }
          env:
            - { name: APP_ENV, value: production }
            - { name: MASTER_KEY_PATH, value: /run/secrets/master_key }
            - { name: OTEL_EXPORTER_OTLP_ENDPOINT, value: http://jaeger-collector:4317 }
            - { name: OTEL_SERVICE_NAME, value: fylix-api }
          envFrom:
            - secretRef: { name: fylix-db-dsn }
            - secretRef: { name: fylix-smtp }
          volumeMounts:
            - { name: master-key, mountPath: /run/secrets, readOnly: true }
            - { name: staging, mountPath: /srv/fylix/staging }
            - { name: geoip, mountPath: /srv/fylix/geoip, readOnly: true }
          readinessProbe:
            httpGet: { path: /healthz, port: http }
            initialDelaySeconds: 5
            periodSeconds: 10
            failureThreshold: 2
          livenessProbe:
            httpGet: { path: /healthz, port: http }
            initialDelaySeconds: 30
            periodSeconds: 30
            failureThreshold: 3
          resources:
            requests: { cpu: "1",   memory: "512Mi" }
            limits:   { cpu: "2",   memory: "1Gi"   }
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities: { drop: ["ALL"] }
      volumes:
        - name: master-key
          secret:
            secretName: fylix-master-key
            defaultMode: 0400
        - name: staging
          emptyDir: { sizeLimit: 5Gi, medium: Memory }   # tmpfs for staging
        - name: geoip
          configMap: { name: fylix-geoip-db }
      topologySpreadConstraints:
        - maxSkew: 1
          topologyKey: kubernetes.io/hostname
          whenUnsatisfiable: ScheduleAnyway
          labelSelector:
            matchLabels: { app: fylix-api, colour: blue }
```

**Why each block matters:**

- `maxSurge: 1, maxUnavailable: 0` — during an in-colour rolling
  update (minor patches without a full blue-green swap), no pod is
  pulled until the replacement is ready. Keeps capacity.
- `readinessProbe` — the api's `/healthz` returns 200 only once
  `load_master_key(...)` completes in lifespan. Probe failure
  removes the pod from the Service endpoints — Kubernetes will NOT
  route traffic to a booting api.
- `emptyDir { medium: Memory }` for staging — keeps plaintext off
  node disk during the TUS PATCH → encrypt window (Threat A4 in
  `THREAT_MODEL.md`).
- `readOnlyRootFilesystem: true` — combined with the non-root
  userid, containment if the container is compromised.

---

## 5. Deployments (worker)

The worker has **no Service**; it pops jobs from Redis queues. Colour
matters only for the image version. Run **exactly one cleanup-ticker
pod** (avoid double-scheduling) — use a `StatefulSet` or set
`replicas: 1` on the worker Deployment AND set `strategy: Recreate`
(not rolling) so no two cleanups run concurrently.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: worker-blue
  namespace: fylix-prod
  labels: { app: fylix-worker, colour: blue }
spec:
  replicas: 1
  strategy: { type: Recreate }   # cleanup singleton
  selector:
    matchLabels: { app: fylix-worker, colour: blue }
  template:
    metadata:
      labels: { app: fylix-worker, colour: blue }
    spec:
      # same securityContext, env, volumes as api
      containers:
        - name: worker
          image: registry.example.com/fylix/worker:1.1.0
          command: ["/opt/venv/bin/python", "-m", "app.worker"]
          # no ports, no probes — worker has no HTTP surface
          resources:
            requests: { cpu: "1",   memory: "512Mi" }
            limits:   { cpu: "2",   memory: "1Gi"   }
```

Scale the worker horizontally by adding a **second** Deployment
`worker-encrypt-blue` that disables cleanup (add
`FYLIX_DISABLE_CLEANUP=1` env if you implement that flag) — otherwise
the scheduled `run_cleanup_once` fires from both and conflicts on the
Redis heartbeat key.

---

## 6. Services + blue-green switch

```yaml
apiVersion: v1
kind: Service
metadata: { name: svc-api, namespace: fylix-prod }
spec:
  selector: { app: fylix-api, colour: blue }    # <-- flipped at release
  ports: [{ port: 8000, targetPort: http }]
```

### Release sequence

```bash
ACTIVE=$(kubectl -n fylix-prod get cm fylix-active-colour -o jsonpath='{.data.colour}')
NEXT=$([ "$ACTIVE" = "blue" ] && echo green || echo blue)

# 1) Deploy NEXT side with the new image — zero traffic goes there yet
kubectl -n fylix-prod set image deploy/api-${NEXT}       api=registry.example.com/fylix/api:1.2.0
kubectl -n fylix-prod set image deploy/worker-${NEXT}    worker=registry.example.com/fylix/worker:1.2.0
kubectl -n fylix-prod set image deploy/admin-${NEXT}     admin-frontend=registry.example.com/fylix/admin-frontend:1.2.0
kubectl -n fylix-prod set image deploy/frontend-${NEXT}  frontend=registry.example.com/fylix/frontend:1.2.0
kubectl -n fylix-prod rollout status deploy/api-${NEXT}  --timeout=3m

# 2) Smoke-test NEXT via its internal DNS (bypass the Service selector)
kubectl -n fylix-prod run smoke --rm -it --image=curlimages/curl:8.10.0 -- \
  curl -sf http://api-${NEXT}.fylix-prod.svc.cluster.local:8000/healthz

# 3) Flip each Service selector (atomic, one per service)
for svc in svc-api svc-admin svc-public; do
  kubectl -n fylix-prod patch svc "$svc" --type merge -p "{\"spec\":{\"selector\":{\"colour\":\"${NEXT}\"}}}"
done

# 4) Record the new active colour
kubectl -n fylix-prod patch cm fylix-active-colour --type merge -p "{\"data\":{\"colour\":\"${NEXT}\"}}"

# 5) Keep OLD hot for fast rollback (10 min), then scale down to 0
sleep 600
kubectl -n fylix-prod scale deploy/api-${ACTIVE}      --replicas=0
kubectl -n fylix-prod scale deploy/worker-${ACTIVE}   --replicas=0
kubectl -n fylix-prod scale deploy/admin-${ACTIVE}    --replicas=0
kubectl -n fylix-prod scale deploy/frontend-${ACTIVE} --replicas=0
```

### Rollback (within the 10-min window)

```bash
kubectl -n fylix-prod patch cm fylix-active-colour --type merge -p "{\"data\":{\"colour\":\"${ACTIVE}\"}}"
for svc in svc-api svc-admin svc-public; do
  kubectl -n fylix-prod patch svc "$svc" --type merge -p "{\"spec\":{\"selector\":{\"colour\":\"${ACTIVE}\"}}}"
done
```

Single kubectl patch ≈ instant traffic revert. The OLD deployment
is still running at full capacity because step 5 hadn't fired yet.

### Rollback after the 10-min window

If step 5 already scaled OLD to 0, `kubectl scale deploy/api-${ACTIVE}
--replicas=3` restores it — then re-run the flip. Add 30-60 s for
pods to pass readiness probes.

---

## 7. Schema migrations

Migrations are the hard part of blue-green. The rule:

**Every schema change must be forward-compatible with the PREVIOUS
release for at least one deploy cycle.**

Split destructive changes into two releases:

1. Release N: add new column, dual-write (app writes both old + new).
2. Release N+1: remove old column / code reading the old column.

For this project `alembic upgrade head` runs as a **one-shot Job**,
not as part of the api init container:

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: fylix-migrate-1.2.0
  namespace: fylix-prod
spec:
  backoffLimit: 0
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: alembic
          image: registry.example.com/fylix/api:1.2.0
          command: ["/opt/venv/bin/alembic", "upgrade", "head"]
          envFrom:
            - secretRef: { name: fylix-db-dsn }
```

Run the Job **before** flipping the Service selector (step 3 above).

---

## 8. Ingress + TLS

Replace the docker-compose Nginx with an Ingress + cert-manager:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: fylix
  namespace: fylix-prod
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
    nginx.ingress.kubernetes.io/whitelist-source-range: "10.0.0.0/8,192.0.2.0/24"  # /admin CIDR
    nginx.ingress.kubernetes.io/proxy-body-size: "2g"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "600"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "600"
spec:
  tls:
    - hosts: [fylix.example.com]
      secretName: fylix-tls
  rules:
    - host: fylix.example.com
      http:
        paths:
          - path: /api/admin
            pathType: Prefix
            backend: { service: { name: svc-admin, port: { number: 8000 } } }
          - path: /admin
            pathType: Prefix
            backend: { service: { name: svc-admin, port: { number: 80 } } }
          - path: /(healthz|api/|t/|s/)
            pathType: ImplementationSpecific
            backend: { service: { name: svc-api, port: { number: 8000 } } }
          - path: /
            pathType: Prefix
            backend: { service: { name: svc-public, port: { number: 80 } } }
```

The `whitelist-source-range` annotation replaces the CIDR-gate in
`nginx/nginx.conf` for the `/admin` + `/api/admin` paths. Keep only
`/healthz` + `/api/public-config` publicly reachable; everything
else goes through the admin CIDR list.

---

## 9. NetworkPolicy — block east-west

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: { name: fylix-api-egress, namespace: fylix-prod }
spec:
  podSelector: { matchLabels: { app: fylix-api } }
  policyTypes: [Egress]
  egress:
    - to: [{ podSelector: { matchLabels: { app: fylix-postgres } } }]
      ports: [{ port: 5432, protocol: TCP }]
    - to: [{ podSelector: { matchLabels: { app: fylix-redis } } }]
      ports: [{ port: 6379, protocol: TCP }]
    - to: [{ podSelector: { matchLabels: { app: fylix-minio } } }]
      ports: [{ port: 9000, protocol: TCP }]
    - to: [{ namespaceSelector: { matchLabels: { name: kube-system } } }]  # DNS
      ports: [{ port: 53, protocol: UDP }]
    # outbound to internet (hCaptcha, SMTP, Telegram) — scope via
    # corp egress proxy or explicit egressCIDRs
```

The `data` network isolation we have in compose (`internal: true`)
becomes a NetworkPolicy here.

---

## 10. Observability

The Jaeger / Prometheus / Grafana stack from
`observability/` translates cleanly:

- **Jaeger collector** as a separate Deployment + Service
  (`jaeger-collector:4317` OTLP endpoint referenced by `api`/`worker` env).
- **Prometheus** — deploy via
  [kube-prometheus-stack Helm chart](https://github.com/prometheus-community/helm-charts/tree/main/charts/kube-prometheus-stack);
  add a `ServiceMonitor` targeting the api Service `/metrics` path.
- **Grafana** — Helm `grafana.adminUser` + `grafana.persistence`. Load
  our dashboards via
  `grafana.dashboardsConfigMaps` pointing to a ConfigMap that mirrors
  `observability/grafana/dashboards/`.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata: { name: fylix-api, namespace: fylix-prod }
spec:
  selector: { matchLabels: { app: fylix-api } }
  endpoints:
    - port: http
      path: /metrics
      interval: 15s
      relabelings:
        - sourceLabels: [__meta_kubernetes_pod_label_colour]
          targetLabel: colour
```

The `colour` relabeling lets you split blue vs green metrics in
Grafana — crucial for comparing new-release SLIs to the old one
during a canary phase.

---

## 11. HPA

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata: { name: api-blue, namespace: fylix-prod }
spec:
  scaleTargetRef: { apiVersion: apps/v1, kind: Deployment, name: api-blue }
  minReplicas: 3
  maxReplicas: 12
  metrics:
    - type: Resource
      resource: { name: cpu, target: { type: Utilization, averageUtilization: 60 } }
    - type: Pods
      pods:
        metric: { name: upload_concurrent }      # custom, via prometheus-adapter
        target: { type: AverageValue, averageValue: "20" }
```

Repeat for green. During the release window, keep both HPAs active —
after the 10-min hold, scale down the old colour.

---

## 12. Pre-flight checklist

Before first prod rollout on Kubernetes:

- [ ] Master key is a `Secret`, mounted at `/run/secrets/master_key` with mode 0400.
- [ ] `fylix-active-colour` ConfigMap exists and matches reality.
- [ ] All 4 Deployments × 2 colours (8 total) have `app=fylix-*, colour=(blue|green)` labels.
- [ ] All 3 Services have `selector.colour` matching the ConfigMap.
- [ ] NetworkPolicies deny east-west by default; whitelist Postgres / Redis / MinIO only.
- [ ] Ingress `whitelist-source-range` on `/admin` matches the corp CIDR list from `docs/DEPLOYMENT.md §6`.
- [ ] `alembic upgrade head` Job succeeds on staging cluster before any prod flip.
- [ ] Backup smoke-restore CronJob scheduled (`scripts/backup_smoke_restore.sh`).
- [ ] Rollback window (10 min) matches the error-budget per `docs/SLO.md`.

---

## 13. Follow-ups (known gaps)

- **Helm chart**: this doc shows raw manifests for readability. A proper
  Helm chart (or Kustomize overlay) that parameterises
  `colour`/`imageTag`/`replicas` belongs in `ops/helm/fylix/`.
- **Canary support**: current model is pure blue-green (100% traffic
  switch). For gradual rollout (1% → 10% → 100%), introduce
  [Argo Rollouts](https://argo-rollouts.readthedocs.io/) — the
  `colour` label generalises to canary weights.
- **StatefulSet for Postgres / MinIO / Redis**: out of scope here —
  document expects managed or platform-team-owned deps. If you must
  self-host, use [CloudNativePG](https://cloudnative-pg.io/) (Postgres),
  [MinIO Operator](https://min.io/docs/minio/kubernetes/upstream/),
  and a Redis Operator (Bitnami / OT Container Kit).
- **External Secrets Operator**: swap the raw `Secret` with ExternalSecret
  pointing at Vault / AWS SM once the corp vault path is decided.
