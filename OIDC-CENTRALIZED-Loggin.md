Here is the professionally rewritten guide in English:

---

# Operational Runbook: Kubernetes Security — OIDC Authentication & Centralized Audit Logging

**Cluster:** Mirecloud (Bare-Metal Kubernetes)
**Scope:** Elimination of static credential-based authentication and implementation of full API-level audit traceability.

---

## Overview

This runbook documents the complete architecture, configuration steps, and incident post-mortems for securing the Mirecloud Kubernetes cluster. It covers three pillars:

1. **Zero-Trust Authentication** — replacing static `admin.conf` credentials with SSO via Keycloak (OIDC).
2. **Audit Logging** — capturing a complete, tamper-evident record of every action performed against the cluster API.
3. **Log Centralization** — shipping and querying audit logs through a Promtail / Loki / Grafana observability stack.

---

## Phase 1 — OIDC Authentication (Zero Trust)

### 1.1 API Server Configuration (`node-4`)

The Kubernetes API Server is configured to delegate token validation to Keycloak. This means the cluster never manages user passwords directly.

**File:** `/etc/kubernetes/manifests/kube-apiserver.yaml`

Add the following flags to the `command` section:

```yaml
- command:
  - kube-apiserver
  - --oidc-issuer-url=https://keycloak.mirecloud.com/auth/realms/mirecloud
  - --oidc-client-id=kubernetes
  - --oidc-username-claim=email
  # Optional — required if Keycloak uses a private/internal CA:
  # - --oidc-ca-file=/etc/kubernetes/pki/ca.crt
```

> **Note:** Changes to a static Pod manifest are picked up automatically by the Kubelet. Monitor the Pod restart with `crictl ps` before proceeding.

---

### 1.2 Client Workstation Configuration (Windows / PowerShell)

End-user machines use the `kubelogin` plugin to perform browser-based SSO and exchange the resulting token with `kubectl`.

**Installation:**

```powershell
winget install Int128.kubelogin
```

**Kubeconfig setup:**

```powershell
kubectl config set-credentials oidc-user `
  --exec-api-version=client.authentication.k8s.io/v1beta1 `
  --exec-command=kubectl `
  --exec-arg=oidc-login `
  --exec-arg=get-token `
  --exec-arg=--oidc-issuer-url=https://keycloak.mirecloud.com/auth/realms/mirecloud `
  --exec-arg=--oidc-client-id=kubernetes `
  --exec-arg=--insecure-skip-tls-verify

kubectl config set-context oidc-context --cluster=kubernetes --user=oidc-user
kubectl config use-context oidc-context
```

> **Security note:** `--insecure-skip-tls-verify` should only be used in controlled lab environments. Replace with a proper CA bundle in production.

---

### 1.3 Authorization — RBAC Binding

Once Keycloak validates a user's identity, Kubernetes applies RBAC rules to determine what that identity is permitted to do. Identities are matched on the `email` claim as configured above.

**Example — granting cluster-admin to a specific user:**

```bash
kubectl create clusterrolebinding oidc-admin-binding \
  --clusterrole=cluster-admin \
  --user=info@mirecloud.com
```

Apply the principle of least privilege for non-administrative users. Use `ClusterRole` / `Role` scoped to specific namespaces and resources where possible.

---

## Phase 2 — Audit Logging

### 2.1 Audit Policy Definition

> **Critical prerequisite:** The audit policy file **must exist on the host** before the API Server flags are applied. Failure to do so will crash the control plane (see [Incident 2](#incident-2--control-plane-crash-on-audit-activation)).

Create the policy file on the control plane node (`node-4`):

```bash
cat <<EOF > /etc/kubernetes/audit-policy.yaml
apiVersion: audit.k8s.io/v1
kind: Policy
omitStages:
  - "RequestReceived"
rules:
  # Suppress high-frequency internal system noise
  - level: None
    users: ["system:kubelet", "system:kube-proxy"]

  # Capture full request and response body for sensitive resources
  - level: RequestResponse
    resources:
      - group: ""
        resources: ["secrets", "configmaps"]

  # Capture metadata only (who, what, when) for all other resources
  - level: Metadata
EOF
```

**Policy rationale:**

| Level | Data Captured | Use Case |
|---|---|---|
| `None` | Nothing | Suppress noise from trusted internal components |
| `Metadata` | User, verb, resource, timestamp | General activity tracking |
| `RequestResponse` | Full payload | Sensitive resources requiring deep forensic capability |

---

### 2.2 API Server — Enabling Audit Logging

**File:** `/etc/kubernetes/manifests/kube-apiserver.yaml`

Three sections must be modified: startup arguments, volume mounts, and host volume declarations.

**A. Startup arguments:**

```yaml
- --audit-policy-file=/etc/kubernetes/audit-policy.yaml
- --audit-log-path=/var/log/kubernetes/audit/audit.log
- --audit-log-maxage=30
- --audit-log-maxbackup=10
- --audit-log-maxsize=100
```

**B. Volume mounts** (under `containers[].volumeMounts`):

```yaml
volumeMounts:
  - mountPath: /etc/kubernetes/audit-policy.yaml
    name: audit-policy
    readOnly: true
  - mountPath: /var/log/kubernetes/audit
    name: audit-logs
    readOnly: false
```

**C. Host volumes** (under `spec.volumes`):

```yaml
volumes:
  - hostPath:
      path: /etc/kubernetes/audit-policy.yaml
      type: FileOrCreate
    name: audit-policy
  - hostPath:
      path: /var/log/kubernetes/audit
      type: DirectoryOrCreate
    name: audit-logs
```

---

## Phase 3 — Log Centralization (Promtail → Loki)

Promtail is deployed as a DaemonSet and configured to tail the audit log file on `node-4`, parse the JSON entries, and forward structured log streams to Loki (backed by S3/MinIO).

**Relevant section of `values.yaml` (Promtail Helm chart):**

```yaml
promtail:
  enabled: true

  # Mount the host audit log directory into the Promtail pod
  extraVolumes:
    - name: audit-logs
      hostPath:
        path: /var/log/kubernetes/audit

  extraVolumeMounts:
    - name: audit-logs
      mountPath: /var/log/kubernetes/audit
      readOnly: true

  config:
    snippets:
      extraScrapeConfigs: |
        - job_name: kubernetes-audit
          static_configs:
            - targets:
                - localhost
              labels:
                job: kubernetes-audit
                __path__: /var/log/kubernetes/audit/*.log

          pipeline_stages:
            # Parse the JSON audit log entry
            - json:
                expressions:
                  audit_user: user.username
                  audit_verb: verb
                  audit_namespace: objectRef.namespace
                  audit_resource: objectRef.resource
            # Promote extracted values to Loki labels for efficient filtering
            - labels:
                audit_user:
                audit_verb:
                audit_namespace:
                audit_resource:
```

> **Label cardinality warning:** Only promote fields with bounded cardinality (verb, resource, namespace) to Loki labels. High-cardinality fields like `resourceName` should be queried via `| json` at read time, not indexed as labels.

---

## Phase 4 — Querying Audit Logs in Grafana (LogQL)

Kubernetes audit logs record **API server operations**, not raw terminal commands. The table below maps common `kubectl` commands to their API-level equivalents as they appear in the audit log.

### kubectl → Audit Log Translation Matrix

| `kubectl` Command | `audit_verb` | `audit_resource` |
|---|---|---|
| `kubectl get nodes` | `list` | `nodes` |
| `kubectl get namespaces` | `list` | `namespaces` |
| `kubectl apply -f app.yaml` | `patch` / `update` | *(depends on resource in manifest)* |
| `kubectl delete pod <name>` | `delete` | `pods` |
| `kubectl exec -it <pod>` | `create` | `pods/exec` |

---

### Useful LogQL Queries (Grafana → Explore)

**All actions by a specific user, formatted as a human-readable summary:**

```logql
{job="kubernetes-audit", audit_user="info@mirecloud.com"}
| json
| line_format "User [ {{.audit_user}} ] performed [ {{.audit_verb}} ] on [ {{.audit_resource}} ]"
```

**Isolate a specific operation (e.g., `kubectl get nodes`):**

```logql
{job="kubernetes-audit", audit_user="info@mirecloud.com", audit_resource="nodes", audit_verb="list"}
```

**Detect any access to Secrets across the cluster:**

```logql
{job="kubernetes-audit", audit_resource="secrets"}
| json
| line_format "{{.audit_user}} | {{.audit_verb}} | {{.objectRef_namespace}}/{{.objectRef_name}}"
```

---

## Troubleshooting & Post-Mortems

### Incident 1 — `state does not match` (OIDC Login Failure)

| Field | Detail |
|---|---|
| **Symptom** | Browser returns `authcode-browser error: state does not match` during login. |
| **Root Cause** | Stale `localhost:8000` browser tabs from previous failed login attempts held conflicting CSRF state cookies. The state token sent by the terminal no longer matched the state expected by the browser session. |
| **Resolution** | 1. Close all browser tabs. 2. Clear the local token cache: `kubectl oidc-login clean`. 3. Retry the login flow. |
| **Prevention** | Always clear the kubelogin cache before debugging OIDC issues. Treat each login attempt as a fresh session. |

---

### Incident 2 — Control Plane Crash on Audit Activation

| Field | Detail |
|---|---|
| **Symptom** | `kubectl get nodes` returns `connection refused`. The API Server Pod is not running. |
| **Diagnostic Command** | `crictl ps -a` to find the container ID, then `crictl logs <container_id>` |
| **Error Observed** | `err="loading audit policy file: failed to read file path \"/etc/kubernetes/audit-policy.yaml\": no such file or directory"` |
| **Root Cause** | The API Server is strict: if `--audit-policy-file` is specified, the file must exist **and be accessible inside the container** at startup. The failure was caused by either (a) the file not yet being created on the host, or (b) the `volumeMounts` not being correctly configured to project the host path into the static Pod. |
| **Resolution** | 1. Verify `/etc/kubernetes/audit-policy.yaml` exists on the host. 2. Ensure both `volumes` and `volumeMounts` are correctly declared in the manifest (see [Phase 2.2](#22-api-server--enabling-audit-logging)). 3. The Kubelet will automatically detect the corrected manifest and restart the container. |
| **Prevention** | Always create the audit policy file and verify `volumeMounts` **before** adding the `--audit-policy-file` flag to the manifest. Use a staged rollout: write the file, update volumes, then add the flag. |

---

## Quick Reference

| Component | Configuration File | Key Flag / Field |
|---|---|---|
| API Server | `/etc/kubernetes/manifests/kube-apiserver.yaml` | `--oidc-issuer-url`, `--audit-policy-file` |
| Audit Policy | `/etc/kubernetes/audit-policy.yaml` | `level`, `resources`, `users` |
| Audit Logs | `/var/log/kubernetes/audit/audit.log` | JSON, one entry per line |
| Promtail | Helm `values.yaml` | `extraVolumes`, `pipeline_stages` |
| RBAC Binding | Applied via `kubectl` | `--clusterrole`, `--user` |