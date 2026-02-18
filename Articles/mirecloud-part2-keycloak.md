# SSO the Hard Way: Deploying Keycloak on Bare-Metal Kubernetes (Part 2)

*MireCloud Series — Production-grade identity infrastructure: Vault secrets, clustered Keycloak, Gateway API, and zero credentials in Git.*

---

## Overview

Part 1 established the foundation: HashiCorp Vault as the single source of truth for credentials, External Secrets Operator bridging Vault into Kubernetes-native Secrets, cert-manager automating TLS certificate lifecycle, and ArgoCD deploying everything declaratively from Git.

Part 2 builds the identity layer on top of that foundation: **Keycloak** — an open-source identity and access management solution deployed as a production-grade, 2-replica cluster with PostgreSQL persistence, every credential sourced from Vault, and exposed via the Cilium Gateway API with automatic TLS.

By the end of this article, you will have:
- A highly available Keycloak cluster with distributed session state via Infinispan
- PostgreSQL backend for persistent storage
- Admin and database credentials managed entirely through Vault
- TLS certificates issued and renewed automatically by cert-manager
- External access via Cilium Gateway API with proper proxy header handling
- Zero secrets visible in Git — complete GitOps compliance

The architecture:

```
┌─────────────────────────────────────────────────────────────┐
│                        Git Repository                        │
│              apps/keycloak/ (no secrets)                     │
└──────────────────────────┬──────────────────────────────────┘
                           │ ArgoCD syncs
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    Kubernetes Cluster                        │
│                                                             │
│  ┌─────────┐   pulls    ┌──────────────────────────────┐   │
│  │  Vault  │ ◄──────── │  External Secrets Operator   │   │
│  │  KV v2  │           │  (materializes K8s Secrets)   │   │
│  └─────────┘           └──────────┬───────────────────┘   │
│                                   │                         │
│                         ┌─────────▼──────────┐             │
│                         │  Keycloak (×2)     │             │
│                         │  Infinispan cluster│             │
│                         │  ← postgres        │             │
│                         └────────────────────┘             │
│                                   ▲                         │
│                         ┌─────────┴──────────┐             │
│                         │  Cilium Gateway    │             │
│                         │  192.168.2.204     │             │
│                         │  TLS terminated    │             │
│                         └────────────────────┘             │
└─────────────────────────────────────────────────────────────┘
                                   ▲
                                   │ HTTPS
                            User Browser
```

---

## Why Keycloak?

Keycloak provides enterprise-grade identity and access management with support for:
- **OpenID Connect (OIDC)** and SAML 2.0 protocols
- **User Federation** with LDAP, Active Directory, Kerberos
- **Social Login** (Google, GitHub, etc.)
- **Multi-factor Authentication** (TOTP, WebAuthn)
- **Fine-grained Authorization** with role-based and attribute-based access control
- **Centralized Session Management** across multiple applications

In a homelab or small enterprise environment, Keycloak eliminates the need to manage separate user databases in every application. Every service delegates authentication to Keycloak. Add a user once, grant them access to multiple services through realm roles. Revoke access in one place when they leave.

---

## Prerequisites

The following components must be operational before proceeding:

- Vault initialized, unsealed, and Kubernetes auth configured
- `ClusterSecretStore` named `vault-backend` in `Valid` state
- cert-manager operational with `ClusterIssuer` `mirecloud-ca-issuer` in `Ready` state
- ArgoCD connected to the repository

Verify:

```bash
kubectl get clustersecretstore vault-backend
# NAME            AGE   STATUS   CAPABILITIES   READY
# vault-backend   2d    Valid    ReadWrite      True

kubectl get clusterissuer mirecloud-ca-issuer
# NAME                   READY   AGE
# mirecloud-ca-issuer    True    2d
```

If either of these is not ready, return to Part 1.

---

## Layer 0 — PostgreSQL

Keycloak requires a relational database for persistent storage of realms, users, sessions, and configuration. The embedded H2 database is explicitly unsupported in clustered deployments and should never be used outside of local development.

PostgreSQL is deployed as a StatefulSet in a dedicated namespace:

```bash
helm install postgres oci://registry-1.docker.io/cloudpirates/postgres \
  -n postgres --create-namespace
```

The chart generates a random password on first install and stores it in a Kubernetes Secret. This is the one time this credential is handled manually:

```bash
# Retrieve the generated password
kubectl -n postgres get secret postgres \
  -o jsonpath='{.data.postgres-password}' | base64 -d

# Store it in Vault immediately — this is the last time you see this value
kubectl -n vault exec -ti vault-0 -- vault kv put secret/keycloak/db \
    password='<retrieved-password>'
```

The internal service endpoint used throughout this deployment: `postgres.postgres.svc:5432`.

Runtime confirmation:

```bash
kubectl get pods -n postgres
# NAME         READY   STATUS    RESTARTS   AGE
# postgres-0   1/1     Running   0          79m
```

---

## Layer 1 — Secrets in Vault

Every sensitive value is stored in Vault before any Kubernetes manifest is applied. This is the contract the entire pipeline depends on.

```bash
# Keycloak admin account
kubectl -n vault exec -ti vault-0 -- vault kv put secret/keycloak/admin \
    password='StrongAdminPassword'

# Keycloak database credentials (already stored in Layer 0)
kubectl -n vault exec -ti vault-0 -- vault kv put secret/keycloak/db \
    password='DbPassword'
```

Verification:

```bash
kubectl -n vault exec -ti vault-0 -- vault kv list secret/keycloak
# Keys
# ----
# admin
# db
```

Two paths. Two credentials. Zero Git commits.

---

## Layer 2 — External Secrets: Materializing Vault Credentials

The `ClusterSecretStore` from Part 1 is already in place. Two `ExternalSecret` resources declare which Vault paths to sync and what Kubernetes `Secret` objects to create.

**`apps/keycloak/templates/external-secrets.yaml`**:

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: keycloak-admin-es
  namespace: keycloak
spec:
  refreshInterval: 1m
  secretStoreRef:
    name: vault-backend
    kind: ClusterSecretStore
  target:
    name: keycloak-admin-password
    creationPolicy: Owner
  data:
  - secretKey: password
    remoteRef:
      key: secret/keycloak/admin   # Vault KV v2 path — no /data/ prefix
      property: password
---
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: keycloak-db-es
  namespace: keycloak
spec:
  refreshInterval: 1m
  secretStoreRef:
    name: vault-backend
    kind: ClusterSecretStore
  target:
    name: byo-db-creds             # Must match existingSecret in values.yaml exactly
    creationPolicy: Owner
  data:
  - secretKey: password
    remoteRef:
      key: secret/keycloak/db
      property: password
```

> **Critical: The `remoteRef.key` path.** ESO handles KV v2 path construction internally — it appends `/data/` to the path when calling the Vault API. If you include `/data/` in the key yourself, the resulting path becomes `/data/data/secret/keycloak/admin`, which returns a 404. ESO reports this as `SecretSyncedError` without making the root cause obvious. The key should be the logical Vault path: `secret/keycloak/admin`.

> **`creationPolicy: Owner`** means ESO manages the full lifecycle of the resulting Secret. Deleting the ExternalSecret also deletes the Secret. This prevents orphaned credentials from persisting after a component is removed.

Verify:

```bash
kubectl get externalsecret -n keycloak
# NAME                STATUS         READY
# keycloak-admin-es   SecretSynced   True
# keycloak-db-es      SecretSynced   True

kubectl get secret -n keycloak
# NAME                     TYPE     DATA   AGE
# byo-db-creds             Opaque   1      2m
# keycloak-admin-password  Opaque   1      2m
```

If status is not `SecretSynced`, debug the ESO controller logs:

```bash
kubectl logs -n external-secrets deployment/external-secrets
```

The issue is always upstream of Keycloak at this stage — either the Vault path is wrong, the ClusterSecretStore authentication is broken, or the Vault policy does not grant read access to the path.

---

## Layer 3 — Keycloak Helm Chart

**`apps/keycloak/Chart.yaml`**:

```yaml
apiVersion: v2
name: keycloak-wrapper
type: application
version: 1.0.0
dependencies:
  - name: keycloakx
    repository: "oci://ghcr.io/codecentric/helm-charts"
    version: "7.1.5"
```

The upstream chart is declared as a dependency. ArgoCD deploys the wrapper. No direct `helm install` calls — everything is declarative.

**`apps/keycloak/values.yaml`**:

```yaml
keycloakx:
  command:
    - "/opt/keycloak/bin/kc.sh"
    - "start"
    - "--http-enabled=true"
    - "--http-port=8080"
    - "--hostname-strict=false"
    - "--proxy-headers=xforwarded"

  replicas: 2

  extraEnv: |
    - name: KEYCLOAK_ADMIN
      value: admin
    - name: KEYCLOAK_ADMIN_PASSWORD
      valueFrom:
        secretKeyRef:
          name: keycloak-admin-password
          key: password
    - name: KC_PROXY
      value: edge

  dbchecker:
    enabled: true

  database:
    vendor: postgres
    hostname: postgres.postgres.svc
    port: 5432
    database: postgres
    username: postgres
    existingSecret: byo-db-creds

  service:
    type: LoadBalancer
```

**Configuration rationale:**

**`--proxy-headers=xforwarded`** instructs Keycloak to respect `X-Forwarded-For` and `X-Forwarded-Proto` headers injected by the upstream Gateway. Without this flag, Keycloak ignores the forwarded headers and constructs redirect URIs based on what it sees directly — which is plain HTTP on port 8080. The resulting OIDC redirect URIs use `http://` instead of `https://`, causing the authorization code callback to fail at the browser.

**`KC_PROXY=edge`** is the complementary setting. It tells Keycloak it operates behind a TLS-terminating reverse proxy and should accept forwarded headers as authoritative. These two flags are paired — neither is sufficient without the other when TLS is terminated at the Gateway.

**`dbchecker.enabled: true`** adds an init container that waits for PostgreSQL to respond before Keycloak starts. Without it, a PostgreSQL restart during cluster initialization causes Keycloak to enter `CrashLoopBackOff`. The init container eliminates the race condition.

**`existingSecret: byo-db-creds`** references the Secret created by ESO. The name must match the `target.name` in the ExternalSecret exactly. No password is written anywhere in this values file.

---

## Layer 4 — Cilium Gateway API and TLS

This deployment uses the Kubernetes Gateway API rather than the legacy Ingress resource. Gateway API provides cleaner separation between infrastructure concerns (Gateway, GatewayClass) and application routing concerns (HTTPRoute), and is the direction the Kubernetes ecosystem is moving toward.

Three objects are required:

**`apps/keycloak/templates/ingress.yaml`**:

```yaml
# ── 1. Certificate ────────────────────────────────────────────────
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: keycloak-tls-cert
  namespace: keycloak
spec:
  secretName: keycloak-tls-secret
  issuerRef:
    name: mirecloud-ca-issuer
    kind: ClusterIssuer
  commonName: keycloak.mirecloud.com
  dnsNames:
  - keycloak.mirecloud.com

---
# ── 2. Gateway ────────────────────────────────────────────────────
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: mirecloud-gateway
  namespace: keycloak
spec:
  gatewayClassName: cilium
  listeners:
  - name: http
    protocol: HTTP
    port: 80
    allowedRoutes:
      namespaces:
        from: Same
  - name: https
    protocol: HTTPS
    port: 443
    tls:
      mode: Terminate
      certificateRefs:
      - kind: Secret
        name: keycloak-tls-secret
    allowedRoutes:
      namespaces:
        from: Same

---
# ── 3. HTTPRoute ──────────────────────────────────────────────────
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: keycloak-route
  namespace: keycloak
spec:
  parentRefs:
  - name: mirecloud-gateway
  hostnames:
  - "keycloak.mirecloud.com"
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /
    backendRefs:
    - name: keycloak-keycloakx-http
      port: 80
```

**Object responsibilities:**

| Object | Managed By | Responsibility |
|--------|-----------|----------------|
| `Certificate` | cert-manager | Issues and renews TLS certificate from internal CA |
| `Gateway` | Cilium | Binds a LoadBalancer IP, terminates TLS, forwards HTTP internally |
| `HTTPRoute` | Cilium | Maps `keycloak.mirecloud.com` to the Keycloak service |

The traffic path is: `Client → HTTPS:443 (Cilium Gateway, IP 192.168.2.204) → HTTP:80 (keycloak-keycloakx-http) → HTTP:8080 (pod)`.

TLS is terminated at the Gateway. Keycloak receives plain HTTP, which is why `--http-enabled=true` and `KC_PROXY=edge` are required in the pod configuration.

Verify:

```bash
kubectl get gateway -n keycloak
# NAME                CLASS    ADDRESS          PROGRAMMED   AGE
# mirecloud-gateway   cilium   192.168.2.204    True         5m

kubectl get certificate -n keycloak
# NAME                 READY   SECRET               AGE
# keycloak-tls-cert    True    keycloak-tls-secret  5m

kubectl get httproute -n keycloak
# NAME             HOSTNAMES                     AGE
# keycloak-route   ["keycloak.mirecloud.com"]    5m
```

---

## Distributed Sessions: What Infinispan Provides

With `replicas: 2`, the keycloakx chart automatically configures Keycloak nodes to form a distributed Infinispan cache cluster. Pod discovery uses the headless Kubernetes service, which exposes individual pod addresses directly rather than load-balancing across them.

The clustering lifecycle is visible in the Keycloak logs:

```
ISPN100002: Starting rebalance with members
             [keycloak-keycloakx-0-35812, keycloak-keycloakx-1-53189],
             phase READ_OLD_WRITE_ALL, topology id 2
ISPN100010: Finished rebalance with members
             [keycloak-keycloakx-0-35812, keycloak-keycloakx-1-53189],
             topology id 5
```

This rebalance occurs for each cache (sessions, work, authenticationSessions, clientSessions, etc.) as the second pod joins. Once complete, both nodes share distributed session state. A user authenticated through pod-0 can have their request served by pod-1 without being prompted to log in again.

Without this clustering, running two replicas with a standard LoadBalancer — which distributes requests round-robin — causes intermittent authentication failures whenever a request lands on a different pod from the one that created the session. The fix is not sticky sessions; it is proper distributed state, which Infinispan provides automatically.

Runtime confirmation:

```bash
kubectl get pods -n keycloak
# NAME                   READY   STATUS    RESTARTS   AGE
# keycloak-keycloakx-0   1/1     Running   0          10m
# keycloak-keycloakx-1   1/1     Running   0          10m

kubectl logs -n keycloak keycloak-keycloakx-0 | grep ISPN100010
# ISPN100010: Finished rebalance with members [keycloak-keycloakx-0-35812, keycloak-keycloakx-1-53189], topology id 5
```

---

## Deployment

**ArgoCD Application manifest:**

**`clusters/home-lab/keycloak-app.yaml`**:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: keycloak
  namespace: argocd
spec:
  project: default
  source:
    repoURL: "git@github.com:mirecloud/home_lab.git"
    targetRevision: HEAD
    path: apps/keycloak
  destination:
    server: https://kubernetes.default.svc
    namespace: keycloak
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

Deployment order:

```
1. Prerequisites verified (Vault, ESO, cert-manager)
         ↓
2. vault kv put secret/keycloak/admin
   vault kv put secret/keycloak/db
         ↓
3. git push apps/keycloak/
   ArgoCD sync: keycloak
         ↓  (ESO creates Secrets, cert-manager issues cert)
4. Keycloak starts → connects to postgres
   2-node Infinispan cluster forms
         ↓
5. Gateway IP assigned: 192.168.2.204
   TLS certificate issued: keycloak.mirecloud.com
         ↓
6. Access: https://keycloak.mirecloud.com
   Login with admin / <vault-password>
```

Verification:

```bash
kubectl get application -n argocd keycloak
# NAME       SYNC STATUS   HEALTH
# keycloak   Synced        Healthy

kubectl get all -n keycloak
# NAME                       READY   STATUS    RESTARTS   AGE
# pod/keycloak-keycloakx-0   1/1     Running   0          15m
# pod/keycloak-keycloakx-1   1/1     Running   0          15m

# NAME                              TYPE           CLUSTER-IP       EXTERNAL-IP     PORT(S)
# service/keycloak-keycloakx-http   LoadBalancer   10.43.x.x        192.168.2.203   80:xxxxx/TCP
```

Access the Keycloak admin console at `https://keycloak.mirecloud.com`. Login with username `admin` and the password stored in Vault.

---

## Known Issues and Workarounds

### cert-manager OutOfSync in ArgoCD

The cert-manager application may show `OutOfSync` in ArgoCD. This is a known and intentional state. The `Certificate` CRD triggers cert-manager to create and manage a `Secret` containing the TLS keypair. ArgoCD observes a `Secret` in the namespace that was not declared in Git and flags a diff.

The resolution is to add an `ignoreDifferences` block to the cert-manager ArgoCD Application:

```yaml
spec:
  ignoreDifferences:
    - group: ""
      kind: Secret
      name: keycloak-tls-secret
      namespace: keycloak
      jsonPointers:
        - /data
```

The service continues to operate correctly regardless of the ArgoCD sync status.

### Keycloak Generates HTTP Redirect URIs

If Keycloak redirects users to `http://` URLs instead of `https://`, verify that both `--proxy-headers=xforwarded` and `KC_PROXY=edge` are present in the `command` and `extraEnv` sections respectively. One without the other is insufficient.

### Database Connection Failures During Startup

If Keycloak enters `CrashLoopBackOff` with database connection errors, verify:

1. PostgreSQL is running: `kubectl get pods -n postgres`
2. The database password in Vault matches the actual PostgreSQL password
3. ESO has successfully created the `byo-db-creds` Secret: `kubectl get secret -n keycloak byo-db-creds -o yaml`
4. The `dbchecker` init container is enabled in values.yaml

---

## Security Posture

At the completion of this deployment:

- No credential appears in Git in any form — no base64, no Helm `--set` flags, no inline `stringData`
- Vault is the authoritative source for every sensitive value in the cluster
- TLS is enforced on all external endpoints, certificates issued and renewed automatically by cert-manager
- ExternalSecrets refresh every 60 seconds — a rotated Vault secret propagates to Kubernetes within one minute
- Session state is distributed across Keycloak replicas — no single point of failure
- PostgreSQL credentials are isolated to the Keycloak namespace and managed through ESO

---

## What's Next: Part 3

Keycloak is now operational as a standalone identity server. The next step is integrating it with an actual application to provide SSO.

**Part 3** will cover the complete OIDC integration with Grafana, including:
- The OpenID Connect Authorization Code Flow (with diagram)
- Front-channel vs. back-channel URL configuration
- Client secret management via Vault and ESO
- Role mapping from Keycloak realm roles to Grafana permissions
- Eliminating the Grafana native login form entirely

Follow me on Medium to be notified when it publishes.

The complete repository is available at [github.com/mirecloud/home_lab](https://github.com/mirecloud/home_lab).

---

*Emmanuel Catin — Senior Platform Engineer | Kubernetes, GitOps, Zero Trust*
*CKA (90%) | CKS in preparation | Montréal, QC*

---

*#Kubernetes #Keycloak #GitOps #Vault #ExternalSecrets #CiliumGateway #GatewayAPI #PostgreSQL #Infinispan #DevSecOps #HomeLab #PlatformEngineering #ZeroTrust*
