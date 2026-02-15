# I Was kubectl apply-ing Everything. Here's How I Stopped. (Part 1)

*Building MireCloud — the right way, from the ground up.*

---

I have a confession.

For months, my homelab was held together with notes, memory, and hope.

Keycloak was running. Grafana was up. GitLab was accessible. But if you asked me *why* something worked, half the time the honest answer was: "because I ran some commands six weeks ago and I haven't touched it since."

Passwords lived in a notes file. Certificates were generated once with OpenSSL and forgotten until they expired. Secrets were committed to Git — sometimes as plaintext, sometimes base64-encoded, which is the same thing with extra steps. Every rebuild started with 30 minutes of archaeology through old terminal sessions asking: *"What was that Keycloak admin password again? Which node has the CA key?"*

This is the story of how I fixed that. Not by being more careful. Not by taking better notes. By building infrastructure that doesn't need me to remember anything.

This is **Part 1** of the MireCloud series — the foundation. By the end of this article, you'll understand the secret and certificate pipeline that runs underneath everything else. In **Part 2**, I'll show you how Keycloak gets deployed on top of it: SSO, OIDC, database credentials from Vault, TLS from cert-manager — all GitOps-native, zero secrets in Git.

But you can't tell that story without telling this one first.

---

## What I Already Had

Before I started fixing things, I had a working multi-node Kubernetes cluster running at home. Four nodes, bare metal, Ubuntu. No cloud provider. No managed services. Everything from scratch.

The networking layer was already solid:

- **Cilium** as the CNI — running in full eBPF mode, kube-proxy completely replaced, no iptables anywhere
- **Cilium L2 announcements** handling LoadBalancer IPs natively via `CiliumLoadBalancerIPPool` and `CiliumL2AnnouncementPolicy` — no MetalLB needed
- **ArgoCD** managing deployments from Git

That last part is important. I had already committed to GitOps. Every service was supposed to be declarative. Every change was supposed to go through Git.

The problem was: I was cheating on secrets.

Everything *structural* was in Git. But every *credential* was applied manually — `kubectl create secret`, `helm install --set password=...`, copy-paste from a notes file. The GitOps principle was there in spirit. The execution had a gaping hole.

So I decided to close it properly.

---

## The Design Decision

Before writing a single line of YAML, I made one rule:

> **If this cluster burns down tomorrow, `git clone` + ArgoCD sync should give me everything back. No manual steps. No notes. No memory required.**

That rule forced three questions:
- Where do secrets live if not in Git? → **Vault**
- How do secrets get from Vault into Kubernetes? → **External Secrets Operator**
- Who signs and renews TLS certificates? → **cert-manager**

And a fourth question that most tutorials skip: how does all of this get deployed *itself* without manual `helm install` commands?

The answer is the same: ArgoCD. The infrastructure deploys the infrastructure.

---

## The Repo Structure

Everything lives in `github.com/mirecloud/home_lab`. The structure is a deliberate design, not an accident:

```
home_lab/
├── clusters/
│   └── home-lab/           ← one ArgoCD Application manifest per service
│       ├── vault-app.yaml
│       ├── external-secrets-app.yaml
│       ├── external-secrets-config-app.yaml
│       ├── cert-manager-app.yaml
│       └── ...
├── infrastructure/         ← Helm wrapper charts for platform components
│   ├── vault/
│   ├── external-secrets/
│   ├── external-secrets-config/
│   └── cert-manager/
└── apps/                   ← Helm wrapper charts for applications
    ├── keycloak/
    ├── gitlab/
    └── ...
```

The pattern is simple: every deployable unit is a **Helm wrapper chart** — a thin `Chart.yaml` that declares an upstream dependency, plus a `values.yaml` with your overrides. Nothing is deployed with `helm install`. ArgoCD reads the Application manifest in `clusters/home-lab/`, finds the chart, and deploys it.

For example, the Vault wrapper at `infrastructure/vault/Chart.yaml`:

```yaml
apiVersion: v2
name: vault
version: 1.0.0
dependencies:
  - name: vault
    version: 0.31.0
    repository: https://helm.releases.hashicorp.com
```

That's all. The upstream Vault chart is the dependency. Your `values.yaml` overrides what you need. ArgoCD deploys the wrapper on every push. No `helm upgrade`. No state drift. No "I deployed this manually last month and now it's different from Git."

The same pattern repeats for cert-manager, ESO, Keycloak, GitLab, Grafana — everything. One consistent mental model across the whole cluster.

---

## Layer 1 — Vault: The Single Source of Truth

The ArgoCD Application at `clusters/home-lab/vault-app.yaml` is what tells ArgoCD to deploy Vault:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: vault
  namespace: argocd
spec:
  project: default
  source:
    repoURL: "git@github.com:mirecloud/home_lab.git"
    targetRevision: HEAD
    path: infrastructure/vault
  destination:
    server: https://kubernetes.default.svc
    namespace: vault
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
  ignoreDifferences:
    - group: admissionregistration.k8s.io
      kind: MutatingWebhookConfiguration
      jsonPointers:
        - /webhooks/0/clientConfig/caBundle
```

That `ignoreDifferences` block stopped a lot of noise. Vault's injector auto-generates a webhook certificate that changes on every pod restart. Without it, ArgoCD shows Vault as `OutOfSync` forever and constantly tries to revert the certificate — which achieves nothing except making you think something is broken when it isn't.

The chart at `infrastructure/vault/values.yaml` configures HA mode with Raft consensus:

```yaml
vault:
  server:
    dev:
      enabled: false       # never dev mode
    ha:
      enabled: true
      replicas: 1
      raft:
        enabled: true
        config: |
          ui = true
          listener "tcp" {
            tls_disable = 1
            address = "[::]:8200"
          }
          storage "raft" {
            path = "/vault/data"
          }
          service_registration "kubernetes" {}
```

After ArgoCD deploys it, there is one manual step — the only one in the entire pipeline, and intentionally so:

```bash
kubectl -n vault exec -ti vault-0 -- vault operator init
# Save your unseal keys — a password manager, not Git

vault auth enable kubernetes

vault write auth/kubernetes/config \
    kubernetes_host="https://kubernetes.default.svc:443" \
    disable_iss_validation=true

vault policy write vault-backend - <<EOF
path "secret/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}
EOF

vault write auth/kubernetes/role/vault-backend \
  bound_service_account_names=external-secrets \
  bound_service_account_namespaces=external-secrets \
  policies=vault-backend \
  ttl=24h
```

That last command is the critical link. It tells Vault to trust the ESO ServiceAccount JWT as a valid authentication credential. No static tokens. No passwords. Kubernetes rotates the ServiceAccount token automatically — Vault authentication is always current, always zero-secret.

From this point on, storing a credential is one command and Git never touches it:

```bash
vault kv put secret/keycloak/admin  password='StrongAdminPassword'
vault kv put secret/keycloak/db     password='DbPassword'
vault kv put secret/grafana/sso     client_secret='OIDCClientSecret'
```

---

## Layer 2 — External Secrets Operator: The Bridge

ESO is the component that makes the pipeline GitOps-native. It watches for `ExternalSecret` CRDs in the cluster and materializes them into native Kubernetes `Secret` objects. The CRDs are safe to commit — they contain zero sensitive data, only references to paths in Vault.

I split this layer into two separate ArgoCD Applications on purpose. Here's why.

### Part A — The operator

`clusters/home-lab/external-secrets-app.yaml`:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: external-secrets
  namespace: argocd
spec:
  source:
    repoURL: "git@github.com:mirecloud/home_lab.git"
    targetRevision: HEAD
    path: infrastructure/external-secrets
  destination:
    server: https://kubernetes.default.svc
    namespace: external-secrets
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
      - ServerSideApply=true
      - Replace=true
```

`ServerSideApply=true` is required. ESO installs large CRDs — without server-side apply, ArgoCD hits annotation size limits and fails with a cryptic error that has nothing to do with the real cause.

The chart at `infrastructure/external-secrets/values.yaml`:

```yaml
external-secrets:
  fullnameOverride: "external-secrets"
  installCRDs: true
  webhook:
    create: true
    certManager:
      enabled: false
```

> **`fullnameOverride` is not optional.** It controls the ServiceAccount name ESO creates. If it doesn't exactly match `external-secrets` — the name you bound in the Vault role — every secret sync silently fails with a 403. This one cost me a few hours of staring at logs before I found it.

### Part B — The configuration

`clusters/home-lab/external-secrets-config-app.yaml`:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: external-secrets-config
  namespace: argocd
spec:
  source:
    repoURL: "git@github.com:mirecloud/home_lab.git"
    targetRevision: HEAD
    path: infrastructure/external-secrets-config
  destination:
    server: https://kubernetes.default.svc
    namespace: external-secrets
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

This Application deploys only one thing — the `ClusterSecretStore` at `infrastructure/external-secrets-config/secret-store.yaml`:

```yaml
apiVersion: external-secrets.io/v1
kind: ClusterSecretStore
metadata:
  name: vault-backend
spec:
  provider:
    vault:
      server: http://vault.vault.svc.cluster.local:8200
      path: secret
      version: v2
      auth:
        kubernetes:
          mountPath: kubernetes
          role: vault-backend
          serviceAccountRef:
            name: external-secrets
            namespace: external-secrets
```

**Why split into two Applications?** The `ClusterSecretStore` CRD is installed by Part A. If you bundle both in the same Application, ArgoCD tries to create the `ClusterSecretStore` object before the CRD exists — and it fails. Permanently. Splitting them means you sync Part A, wait for the operator to be `Healthy`, then sync Part B. Clean, predictable, no surprises.

One more thing: always use `vault.vault.svc.cluster.local` as the server address, never `vault-active`. During Raft leader elections, the active endpoint briefly disappears. The stable service never does.

Verify the bridge:

```bash
kubectl get clustersecretstore vault-backend
# STATUS: Valid ✓
```

---

## Layer 3 — cert-manager: Certificates on Autopilot

`clusters/home-lab/cert-manager-app.yaml`:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: cert-manager
  namespace: argocd
spec:
  source:
    repoURL: "git@github.com:mirecloud/home_lab.git"
    targetRevision: HEAD
    path: infrastructure/cert-manager
  destination:
    server: https://kubernetes.default.svc
    namespace: cert-manager
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
      - ServerSideApply=true
```

The chart wraps the upstream at `infrastructure/cert-manager/Chart.yaml`:

```yaml
apiVersion: v2
name: cert-manager-wrapper
dependencies:
  - name: cert-manager
    version: "v1.16.2"
    repository: "https://charts.jetstack.io"
```

The CA private key and certificate live in Vault. ESO injects them into cert-manager's namespace via an `ExternalSecret` at `infrastructure/cert-manager/templates/ca-secret.yaml`:

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: mirecloud-ca-es
  namespace: cert-manager
  annotations:
    argocd.argoproj.io/sync-wave: "-2"
spec:
  refreshInterval: "1m"
  secretStoreRef:
    name: vault-backend
    kind: ClusterSecretStore
  target:
    name: mirecloud-ca-key-pair
    creationPolicy: Owner
    template:
      type: kubernetes.io/tls
  data:
    - secretKey: tls.crt
      remoteRef:
        key: mirecloud/ca
        property: tls.crt
    - secretKey: tls.key
      remoteRef:
        key: mirecloud/ca
        property: tls.key
```

The `sync-wave: "-2"` annotation is essential. It tells ArgoCD to apply this ExternalSecret *before* anything else in the Application — ensuring the CA secret exists in Kubernetes before the ClusterIssuer tries to reference it. Without it, cert-manager boots, the issuer looks for the secret, finds nothing, enters a failed state, and stays there until you manually resync.

The `ClusterIssuer` at `infrastructure/cert-manager/templates/cluster-issuer.yaml`:

```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: mirecloud-ca-issuer
spec:
  ca:
    secretName: mirecloud-ca-key-pair
```

One issuer for the whole cluster. Any namespace can now request a signed, auto-renewing certificate with a few lines of YAML. No OpenSSL. No manual copy-paste. No calendar reminder.

---

## The Deployment Order

Here's the complete picture — all the Applications in `clusters/home-lab/`, in the order they need to be synced:

```
1.  vault-app.yaml                     ← sync, then run manual bootstrap once
         ↓  (wait: Vault Healthy)
2.  external-secrets-app.yaml          ← ESO operator + CRDs
         ↓  (wait: ESO Healthy)
3.  external-secrets-config-app.yaml   ← ClusterSecretStore → STATUS: Valid
         ↓  (wait: Store Valid)
4.  cert-manager-app.yaml              ← cert-manager + CA secret + ClusterIssuer
         ↓
5.  your-app.yaml                      ← ExternalSecrets and Certificates work
```

Once step 4 is green, the foundation is complete. Every `ExternalSecret` you commit to Git will resolve. Every `Certificate` you request will be signed. ArgoCD's `selfHeal: true` means the cluster continuously converges back to what Git says — if someone manually changes something in the cluster, it gets reverted.

---

## What This Feels Like Now

Adding a new service today:

```bash
# 1. Store the credential in Vault — one command, Git never sees it
vault kv put secret/newapp/db password='Value'

# 2. Create the wrapper chart
# infrastructure/newapp/Chart.yaml
# infrastructure/newapp/values.yaml

# 3. Declare what secrets to inject — no sensitive data
# apps/newapp/templates/external-secret.yaml

# 4. Request a certificate — three lines
# apps/newapp/templates/certificate.yaml

# 5. Register the Application with ArgoCD
# clusters/home-lab/newapp-app.yaml

# 6. Push. Done.
git push
```

No `kubectl create secret`. No `helm install`. No OpenSSL. No notes. No archaeology.

The cluster knows what to do.

---

## The Honest Part

The initial setup takes time. Vault initialization is intentionally manual — you should be present for it, save the unseal keys in a real password manager, and run the Kubernetes auth config yourself. That's appropriate for something that holds every credential in your cluster.

The `fullnameOverride` quirk, the `ServerSideApply` requirement, the sync wave on cert-manager, the `ignoreDifferences` on Vault — none of these are in the official docs. They're the things you find by staring at a 403 or a permanently stuck ArgoCD sync. I'm writing them down so you don't have to find them the hard way.

But they're one-time costs.

Every service I've added since — and there are several — follows the same pattern. The infrastructure layer stops being something I think about. It just works.

---

## What's Coming in Part 2

Now that the foundation is solid — Vault running, ESO bridging secrets into Kubernetes, cert-manager signing certificates automatically — it's time to deploy the first real application on top of it.

**Part 2: Keycloak — SSO the Right Way.**

I'll show you how Keycloak gets deployed as a GitOps-native service on MireCloud: admin password from Vault, database credentials from Vault, TLS certificate from cert-manager, exposed via the Cilium Gateway API. And how Keycloak becomes the identity provider for every other service in the cluster.

If you want to be notified when it drops, follow me here on LinkedIn.

The full repo is at [github.com/mirecloud/home_lab](https://github.com/mirecloud/home_lab). Questions, feedback, or war stories about your own secrets setup — drop them in the comments.

---

*Emmanuel Catin — Senior Platform Engineer | Kubernetes, GitOps, Zero Trust*  
*CKA (90%) | CKS in preparation | Montreal, QC*

*#Kubernetes #GitOps #Vault #ExternalSecrets #CertManager #ArgoCD #DevSecOps #HomeLab #PlatformEngineering*