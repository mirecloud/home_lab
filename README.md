# MireCloud Home Lab

<div align="center">

![Kubernetes](https://img.shields.io/badge/Kubernetes-v1.36.x-326CE5?style=flat-square&logo=kubernetes&logoColor=white)
![Ubuntu](https://img.shields.io/badge/Ubuntu-24.04_LTS-E95420?style=flat-square&logo=ubuntu&logoColor=white)
![ArgoCD](https://img.shields.io/badge/ArgoCD-GitOps-EF7B4D?style=flat-square&logo=argo&logoColor=white)
![Vault](https://img.shields.io/badge/HashiCorp_Vault-0.31.0-FFEC6E?style=flat-square&logo=vault&logoColor=black)
![Cilium](https://img.shields.io/badge/Cilium-eBPF-F8C517?style=flat-square&logo=cilium&logoColor=black)
![Keycloak](https://img.shields.io/badge/Keycloak-7.1.5-4D4D4D?style=flat-square&logo=keycloak&logoColor=white)

**Production-grade bare-metal Kubernetes homelab — zero secrets in Git, full GitOps, SSO everywhere.**

[Articles](#-article-series) · [Architecture](#️-architecture) · [Stack](#-stack) · [Nodes](#-node-topology) · [Deployment](#-deployment-order)

</div>

---

## Overview
<img width="1257" height="825" alt="image" src="https://github.com/user-attachments/assets/95098546-7395-485b-826c-5bc4775889d6" />

MireCloud is a multi-node Kubernetes homelab running across bare-metal and Proxmox-hosted nodes, built with production-oriented practices. Every in-repository service is deployed declaratively via ArgoCD. Credentials live in HashiCorp Vault — never in Git. TLS certificates are issued and renewed automatically. DNS entries are managed programmatically.

The lab serves as a hands-on environment for SRE/DevOps workflows, identity federation, observability, GitOps automation, and CKA/CKS preparation.

**Core principles:**
- **Zero secrets in Git** — Vault is the single source of truth for all credentials
- **GitOps-native** — every resource is declared in code, ArgoCD enforces convergence
- **Automated everything** — DNS, TLS, secret rotation, service restarts

---

## 📖 Article Series

This infrastructure is documented in a technical blog series published on Medium and Google Blogger:

| Part | Title | Status |
|------|-------|--------|
| **1** | [I Was kubectl apply-ing Everything. Here's How I Stopped.](Articles/part-1.md) | ✅ Published |
| **2** | [SSO the Hard Way: Deploying Keycloak on Bare-Metal Kubernetes](Articles/mirecloud-part2-keycloak.md) | ✅ Published |
| **3** | [Integrating Grafana with Keycloak via OIDC](Articles/mirecloud-part3-grafana-oidc.md) | ✅ Published |
| **4** | ExternalDNS — Sync automatique avec BIND via RFC2136 | ✅ Published |
| **5** | GitLab SSO with Keycloak — `discovery: false` and Internal CAs | 🚧 Coming soon |

> *Emmanuel Catin — Senior Platform Engineer · CKA (90%) · CKS in preparation · Montréal, QC*

---

##  Architecture

<img width="1428" height="796" alt="image" src="https://github.com/user-attachments/assets/44eca1ba-b86c-4be8-b02e-984f8735ed6d" />


See [`Articles/architecture-diagram.svg`](Articles/architecture-diagram.svg) for the full visual diagram.

---

##  Node Topology

### Virtualization and GPU layer

| Host | Platform | Hardware role | Key capabilities |
|------|----------|---------------|------------------|
| **Proxmox host** | Proxmox VE 9 | Ryzen 5 7600X + NVIDIA RTX 5060 Ti 16 GB | VM lifecycle, IOMMU and GPU passthrough |
| **node-gpu** | Kubernetes worker VM | Dedicated NVIDIA GPU passthrough | vLLM inference, CUDA workloads and local LLM serving |

### Kubernetes nodes

| Node | IP | Role | Key Workloads |
|------|----|------|---------------|
| **node-4** | `192.168.2.75` | Control Plane + NFS | kube-apiserver, etcd, ArgoCD, Vault, NFS server (`/mnt/k8s-volumes`) |
| **node-1** | `192.168.2.29` | General Worker | GitLab, Keycloak, PgAdmin, n8n, MLflow, PostgreSQL |
| **node-2** | `192.168.2.46` | Monitoring Worker | Prometheus, Alertmanager, Grafana, Loki, Promtail, cert-manager, ESO |
| **node-3** | `192.168.2.74` | Infrastructure Worker | BIND DNS (`:53`), OpenLDAP, MinIO S3 (`:9000`) |
| **node-gpu** | Internal | GPU Worker | vLLM, Qwen2.5-14B-Instruct-AWQ and NVIDIA device workloads |

**Kubernetes:** v1.36.x · **OS:** Ubuntu 24.04 LTS · **LAN:** `192.168.2.0/24`

**LoadBalancer IP pool:** `192.168.2.200–240` (Cilium L2 announcements, node-4 only)

| Service | IP |
|---------|----|
| ArgoCD | `192.168.2.201` |
| PgAdmin | `192.168.2.202` |
| Keycloak | `192.168.2.204` |
| Grafana | `192.168.2.205` |

---

##  Stack

### Platform & GitOps

| Component | Version | Role |
|-----------|---------|------|
| **Kubernetes** | v1.36.x | Container orchestration |
| **ArgoCD** | Externally managed | GitOps controller — `selfHeal: true`, `prune: true` |
| **Cilium** | Externally managed | CNI, eBPF networking, Gateway API, kube-proxy replacement |
| **Reloader** | v1.4.12 | Auto-restart pods on Secret/ConfigMap changes |

### Secrets & PKI

| Component | Version | Role |
|-----------|---------|------|
| **HashiCorp Vault** | 0.31.0 | Secret store — KV v2, HA Raft, Kubernetes auth |
| **External Secrets Operator** | 1.2.0 | Vault → K8s Secret sync, `ClusterSecretStore: vault-backend`, refresh 1m |
| **cert-manager** | v1.16.2 | TLS lifecycle — `ClusterIssuer: mirecloud-ca-issuer`, internal CA from Vault |

### Networking & DNS

| Component | Version | Role |
|-----------|---------|------|
| **Cilium Gateway API** | — | L4/L7 ingress, TLS termination, `gatewayClassName: cilium` |
| **ExternalDNS** | v0.20.0 | Auto-sync DNS from Gateway HTTPRoutes → BIND via RFC2136/TSIG |
| **BIND** | — | Authoritative DNS server, zone `mirecloud.com` (node-3) |

### Identity & SSO

| Component | Version | Role |
|-----------|---------|------|
| **Keycloak** | keycloakx chart 7.2.0 | IdP — realm `mirecloud`, 2 replicas, Infinispan session cluster |
| **OpenLDAP** | — | User directory, `dc=mirecloud,dc=com` (node-3) |

### Observability

| Component | Version | Role |
|-----------|---------|------|
| **kube-prometheus-stack** | 80.4.2 | Prometheus + Alertmanager + Grafana, retention 15d |
| **Loki** | 6.49.0 | Log aggregation, SingleBinary, S3 backend → MinIO |
| **Promtail** | 6.16.0 | DaemonSet log shipper → Loki |
| **Hubble + Tetragon** | — | eBPF network visibility + runtime security (Sigkill policies) |
| **MinIO** | — | S3-compatible object storage for Loki (node-3, chunks/ruler/admin) |

### Applications

| Component | Version | Role |
|-----------|---------|------|
| **PostgreSQL** | — | Shared DB for Keycloak, GitLab, n8n, MLflow (StatefulSet, NFS PVC) |
| **GitLab CE** | 9.7.0 | Self-hosted Git + CI, OIDC via Keycloak, NGINX Ingress |
| **PgAdmin 4** | 1.32.0 | PostgreSQL web UI, Cilium Gateway, admin creds from Vault |
| **MLflow** | 1.8.1 | ML experiment tracking, Basic Auth, NGINX Ingress |
| **n8n** | 1.16.15 | Workflow automation, queue mode, 2 workers, Redis broker |
| **vLLM Production Stack** | chart 0.1.11 / engine 0.11.0 | OpenAI-compatible local inference on `node-gpu` |
| **Open WebUI** | chart 14.8.0 | Multi-user LLM interface with Keycloak OIDC |
| **Qwen2.5-14B-Instruct-AWQ** | AWQ 4-bit | Primary local model, 8192-token context and prefix caching |

---

##  Repository Structure

```
home_lab/
├── clusters/
│   └── home-lab/               # ArgoCD Application manifests (one per service)
│       ├── vault-app.yaml
│       ├── external-secrets-app.yaml
│       ├── external-secrets-config-app.yaml
│       ├── cert-manager-app.yaml
│       ├── keycloak-app.yaml
│       ├── prometheus-stack-app.yaml
│       ├── loki-app.yaml
│       ├── grafana-stack-app.yaml
│       ├── external-dns-app.yaml
│       ├── reloader-app.yaml
│       ├── gitlab-app.yaml
│       ├── pgadmin-app.yaml
│       ├── n8n-app.yaml
│       ├── mlflow-app.yaml
│       ├── vllm-app.yaml
│       └── openwebui-app.yaml
│
├── infrastructure/             # Platform Helm wrapper charts
│   ├── vault/
│   ├── external-secrets/
│   ├── external-secrets-config/    # ClusterSecretStore
│   ├── cert-manager/
│   ├── external-dns/
│   ├── reloader/
│   └── monitoring/
│       ├── prometheus-stack/
│       └── loki-stack/
│
├── apps/                       # Application Helm wrapper charts
│   ├── keycloak/
│   ├── gitlab/
│   ├── pgadmin/
│   ├── n8n/
│   ├── mlflow/
│   ├── vllm/                    # vLLM Production Stack + Qwen model
│   └── openwebui/               # Open WebUI + Keycloak OIDC
│
├── cilium/                     # Cilium-specific manifests
│   ├── cilium-pool.yaml            # CiliumLoadBalancerIPPool
│   ├── cilium-l2-policy.yaml       # L2 announcement policy
│   ├── hubble-to-loki.yaml         # Hubble flow logger
│   └── secure-loki.yaml            # CiliumNetworkPolicy for Loki
│
├── tetragon/
│   └── kill-curl.yaml              # TracingPolicy — runtime security
│
└── Articles/                   # Published blog content + diagrams
    ├── architecture-diagram.svg
    ├── oidc-flow-diagram.svg
    ├── part-1.md
    ├── mirecloud-part2-keycloak.md
    ├── mirecloud-part3-grafana-oidc.md
    └── external-dns-bind-rfc2136.{md,html}
```

Every service follows the same pattern: a thin Helm wrapper chart (`Chart.yaml` + `values.yaml`) declared as an ArgoCD Application. No `helm install` commands — only `git push`.

### Version policy

All Helm dependencies managed by this repository use explicit versions in their wrapper `Chart.yaml` files. ArgoCD and Cilium are currently managed outside this repository, so the README identifies them as externally managed instead of falsely claiming a floating `latest` version. ArgoCD Applications follow the repository branch through `HEAD` or `main`; those Git revisions are separate from application package versions.

---

##  Secrets Pipeline

```
Vault KV v2
    │  (Kubernetes JWT auth, ServiceAccount: external-secrets)
    ▼
External Secrets Operator
    │  ClusterSecretStore: vault-backend
    │  refreshInterval: 1m · creationPolicy: Owner
    ▼
Kubernetes Secrets  ←──  consumed by  ──►  Pods / cert-manager
```

**Vault secret paths:**

| Path | Contents |
|------|----------|
| `secret/keycloak/admin` | Keycloak admin password |
| `secret/keycloak/db` | Keycloak DB password |
| `secret/grafana/sso` | Grafana OIDC client secret |
| `secret/dns/rfc2136` | ExternalDNS TSIG key |
| `secret/gitlab/oidc` | GitLab OmniAuth OIDC config |
| `secret/gitlab/db` | GitLab DB password |
| `secret/pgadmin/admin` | PgAdmin admin password |
| `secret/n8n/db` | n8n DB password |
| `mirecloud/ca` | Internal CA keypair (`tls.crt`, `tls.key`) |

---

##  Deployment Order

```
1. vault-app              → Initialize, unseal, configure K8s auth (manual once)
        ↓  (Vault: Healthy)
2. external-secrets-app   → ESO operator + CRDs
        ↓  (ESO: Healthy)
3. external-secrets-config-app  → ClusterSecretStore (STATUS: Valid)
        ↓  (Store: Valid)
4. cert-manager-app       → cert-manager + CA ExternalSecret + ClusterIssuer
        ↓  (Issuer: Ready)
5. keycloak-app           → PostgreSQL must be running first
6. prometheus-stack-app   → Grafana OIDC connects to Keycloak
7. loki-app               → Connects to MinIO on node-3
8. external-dns-app       → TSIG key from Vault via ESO
9. reloader-app
10. gitlab-app / pgadmin-app / n8n-app / mlflow-app
```

---

##  Security Posture

| Area | Implementation |
|------|----------------|
| **Secrets** | HashiCorp Vault KV v2 — zero credentials in Git |
| **Secret injection** | ESO `ClusterSecretStore`, refresh every 60s |
| **TLS** | cert-manager + internal CA, auto-renew |
| **Network policies** | `CiliumNetworkPolicy` — Loki accessible only from `monitoring` namespace |
| **Runtime security** | Tetragon `TracingPolicy` — `sys_execve` kprobe, Sigkill on policy violation |
| **DNS updates** | TSIG HMAC-SHA256 authenticated RFC2136 updates only |
| **GitOps drift** | ArgoCD `selfHeal: true` — cluster continuously converges to Git state |
| **OIDC** | Keycloak as central IdP for Grafana, GitLab (no local password DBs) |

---

## 📡 OIDC Integration Map

```
Keycloak (realm: mirecloud)
    │
    ├── Grafana     back-channel token_url: keycloakx-http.keycloak.svc.cluster.local
    │               role_attribute_path: realm_access.roles → Admin|Viewer
    │
    └── GitLab      discovery: false (internal CA constraint)
                    explicit endpoints · ssl_verify: false
                    OmniAuth config ← Vault (secret/gitlab/oidc)
```

---

##  Infrastructure Notes

**Why two ESO Applications?**
The `ClusterSecretStore` CRD is installed by the operator. Bundling both in one Application causes ArgoCD to try creating the store object before the CRD exists. Splitting them ensures the operator is healthy before the configuration is applied.

**`fullnameOverride: "external-secrets"` in ESO values**
Controls the ServiceAccount name. Must exactly match the `bound_service_account_names` in the Vault Kubernetes auth role. A mismatch causes silent 403 failures on every secret sync.

**cert-manager webhook with `hostNetwork: true`**
Required in this bare-metal environment to avoid CNI timing issues during webhook initialization.

**Vault `ignoreDifferences` for MutatingWebhookConfiguration**
The Vault injector regenerates its webhook certificate on every pod restart. Without this block, ArgoCD perpetually shows Vault as `OutOfSync`.

**Keycloak `--proxy-headers=xforwarded` + `KC_PROXY=edge`**
Both flags are required when TLS is terminated at the Cilium Gateway. Without `xforwarded`, Keycloak builds redirect URIs using `http://` instead of `https://`, breaking the OIDC callback flow.

**Local AI serving on the GPU worker**
vLLM runs on `node-gpu` with NVIDIA GPU passthrough from Proxmox. It serves `Qwen/Qwen2.5-14B-Instruct-AWQ` through an OpenAI-compatible API. Open WebUI uses that endpoint and delegates authentication to Keycloak. CUDA JIT caches and model weights persist on PVC storage to avoid recompilation and repeated downloads.

**Loki back-channel URLs in Grafana config**
`token_url` and `api_url` use internal cluster DNS (`keycloak-keycloakx-http.keycloak.svc.cluster.local`) — not the public hostname. Avoids DNS resolution issues from inside pods in a homelab environment.

---

##  DNS Zone (`mirecloud.com`)

Managed automatically by ExternalDNS. Records are created/deleted as Gateway HTTPRoutes appear or disappear. BIND on node-3 receives RFC2136 dynamic updates authenticated with TSIG/HMAC-SHA256.

```dns
keycloak        A   192.168.2.204
grafana         A   192.168.2.205
argocd          A   192.168.2.201
pgadmin         A   192.168.2.202
gitlab          A   <assigned>
mlflow          A   <assigned>
n8n             A   <assigned>
```

---

##  Observability

**Metrics:** kube-prometheus-stack scrapes the full cluster via ServiceMonitors, including GitLab webservice, sidekiq, and shell exporters.

**Logs:** Promtail DaemonSet ships all pod logs to Loki. Hubble flow logger (`hubble observe -f -o json`) feeds network flow data through Promtail into Loki, visible in Grafana via the *Cilium Flows — Hubble Observer* dashboard.

**Network security:** Tetragon enforces runtime policies at the kernel level (kprobe on `sys_execve`). CiliumNetworkPolicy restricts Loki ingress to the `monitoring` namespace only.

---

## Storage

NFS server on node-4 (`/mnt/k8s-volumes`) provides `ReadWriteMany` PersistentVolumes for stateful workloads. MinIO on node-3 (`192.168.2.74:9000`) provides S3-compatible object storage for Loki (buckets: `chunks`, `ruler`, `admin`).

---

*MireCloud — My own personal cloud.*  
*[github.com/mirecloud/home_lab](https://github.com/mirecloud/home_lab)*
