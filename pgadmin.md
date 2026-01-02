# PgAdmin Integration Guide (Secure)

This document describes the **secure deployment of PgAdmin** in the HomeLab, fully integrated with Vault for secret management and protected by HTTPS using cert-manager.

This guide confirms a successful end-to-end setup:
- Vault delivers the admin secret
- External Secrets injects it into Kubernetes
- PgAdmin authenticates correctly
- Ingress and networking operate as expected

---

## 1. Vault Secret Creation

The PgAdmin web interface password is stored in Vault.

> Note:  
> This password also acts as the **Master Password** used by PgAdmin to encrypt stored server connections.

```bash
# Execute from node-4 or directly from the Vault pod
kubectl -n vault exec -ti vault-0 -- sh -c   "vault kv put secret/pgadmin/admin password='REPLACE_WITH_STRONG_PASSWORD'"
```

---

## 2. External Secret Configuration

**File**
```
apps/pgadmin/templates/external-secrets.yaml
```

External Secrets Operator retrieves the Vault secret (`secret/pgadmin/admin`)
and generates a native Kubernetes Secret named `pgadmin-admin-password`.

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: pgadmin-admin-es
  namespace: pgadmin
spec:
  refreshInterval: 1m
  secretStoreRef:
    name: vault-backend
    kind: ClusterSecretStore
  target:
    name: pgadmin-admin-password
  data:
    - secretKey: password
      remoteRef:
        key: secret/pgadmin/admin
        property: password
```

---

## 3. Helm Configuration (`values.yaml`)

**File**
```
apps/pgadmin/values.yaml
```

PgAdmin is explicitly configured to consume the password managed by Vault.
No credentials are defined inline.

```yaml
pgadmin4:
  env:
    email: "info@mirecloud.com"
    contextPath: ""   # Must be empty for root access (/)

  existingSecret: "pgadmin-admin-password"
  secretKeys:
    pgadmin-password: "password"

  extraEnv: []

  ingress:
    enabled: true
    annotations:
      cert-manager.io/cluster-issuer: "mirecloud-ca-issuer"
    hosts:
      - host: pgadmin.mirecloud.com
        paths:
          - path: /
            pathType: Prefix
    tls:
      - secretName: pgadmin-tls
        hosts:
          - pgadmin.mirecloud.com
```

⚠️ Important:
- Do not define passwords directly in `values.yaml`
- Do not create manual `Secret` objects
- Vault remains the single source of truth

---

## 4. TLS Trust (Client-Side)

If the browser shows **“Not Secure”**, this is expected until the internal CA
is trusted by the client system.

### Fix (Windows)

1. Locate `mirecloud-ca.crt`
2. Double-click → **Install Certificate**
3. Select **Local Machine**
4. Choose **Trusted Root Certification Authorities**
5. Restart Chrome / Edge

Once installed, the HTTPS lock icon will appear as secure.

---

## 5. Quick Troubleshooting

### 404 at startup
- Normal during initial container startup
- Normal when accessing `/` before authentication
- After login, PgAdmin redirects to `/browser/`

### Password not updating
PgAdmin stores state in a persistent SQLite database:
```
/var/lib/pgadmin/pgadmin4.db
```

To force a full reset:

```bash
kubectl -n pgadmin delete pvc pgadmin-pgadmin4
kubectl -n pgadmin delete pod -l app.kubernetes.io/name=pgadmin4
```

A fresh PVC will be created on the next deployment.

---

## 6. Validation Checklist

```bash
kubectl -n pgadmin get pods
kubectl -n pgadmin get secrets
kubectl -n pgadmin get ingress
```

Expected:
- PgAdmin pod: `Running`
- Secret: `pgadmin-admin-password`
- TLS secret: `pgadmin-tls`
- UI accessible at: `https://pgadmin.mirecloud.com`

---

## Security Outcome

- No credentials in Git
- Vault-backed secret lifecycle
- Automated synchronization via External Secrets
- TLS enforced with internal CA
- Fully GitOps-compatible

This PgAdmin deployment matches the same security standards as Keycloak
and is suitable for advanced homelab or enterprise-style environments.
