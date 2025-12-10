# 🚀 MireCloud Kubernetes Home Lab

## 🧱 Overview

This document describes the complete architecture of my MireCloud Kubernetes Home Lab — a production‑style cluster designed for training DevOps/SRE workflows, identity management, observability, networking, and automation.

The lab includes:
- A fully functional multi‑node Kubernetes cluster
- Cilium CNI for advanced networking
- MetalLB for bare‑metal LoadBalancing
- NGINX Ingress controller
- Centralized DNS + LDAP using BIND & OpenLDAP
- NFS server for persistent storage
- Services such as Keycloak, Grafana, GitLab, Kafka, PostgreSQL, etc.

---

## 🌐 Network Topology (LAN 192.168.2.0/24)

```
                    ┌────────────────────┐
                    │   Control Node      │
                    │   192.168.2.75      │
                    │   NFS Server        │
                    └──────────┬──────────┘
                               │
      ┌────────────────────────┼────────────────────────┐
      │                        │                        │
┌──────────────┐      ┌──────────────┐        ┌────────────────┐
│  node‑1       │      │  node‑2       │        │  node‑3        │
│  192.168.2.29 │      │  192.168.2.46 │        │  192.168.2.74  │
│               │      │               │        │ DNS + LDAP     │
└──────────────┘      └──────────────┘        └────────────────┘
```

---

## 🏗️ Cluster Components

### **Control Plane (192.168.2.75)**
- Ubuntu Server
- Kubernetes Control Plane
- NFS Server (persistent volumes for apps)
- Hosts cluster certificates, CA, and PKI tooling

### **Worker Nodes**
| Node | IP | Role |
|------|------|------|
| **node‑1** | 192.168.2.29 | General workloads |
| **node‑2** | 192.168.2.46 | Services, monitoring stack |
| **node‑3** | 192.168.2.74 | DNS Server (BIND), OpenLDAP |

---

## 🧩 Core Services Installed

### **Networking**
- **Cilium** – eBPF networking, ClusterMesh ready
- **MetalLB** – exposes LoadBalancers for bare‑metal
- **NGINX Ingress Controller** – public entrypoint via DNS

### **Identity**
- **Keycloak** running on the cluster  
- Integrated with:
  - Grafana
  - GitLab
  - Internal apps
  - Future cloud services (OIDC/SAML)

### **Observability**
- **Prometheus**
- **Alertmanager**
- **Grafana**
- **Loki**
- **Tempo (planned)**

### **Databases**
- **PostgreSQL** (external cluster via Helm)
- **Redis** for caching and real‑time services
- Possible integration with **Kafka + Spark**

---

## 🗄️ Storage Layout

### **NFS Server (Control Node)**
Used by:
- GitLab
- Keycloak
- Postgres PVs
- Grafana dashboards
- Custom apps and microservices

A StorageClass points to:
```
/mnt/k8s-volumes
```

---

## 🌍 DNS & Domain Integration

Your internal DNS zone:

```
mirecloud.com
```

Example records:
```
keycloak.mirecloud.com → 192.168.2.200 (MetalLB)
grafana.mirecloud.com  → 192.168.2.200
```

DNS server also hosts:
- Forward lookup zone
- Reverse lookup zone
- LDAP domain (mirecloud.com)

---

## 🔐 PKI, TLS & Certificates

You maintain:
- Wildcard cert: `*.mirecloud.com`
- Internal CA
- Certificates for:
  - Keycloak
  - Grafana
  - GitLab
  - MLFlow
  - Postgres
  - NGINX Ingress

---

## 📦 Applications Planned / Installed

- Keycloak OIDC SSO
- Grafana + Prometheus
- GitLab CE with CI Runners
- Kafka / Spark Streaming stack
- MLFlow
- FastAPI microservices
- Custom MireCloud automation tools

---

## 🧪 Purpose of the Lab

This lab gives you hands‑on experience with:
- Realistic multi‑node Kubernetes admin
- CI/CD pipelines
- Identity federation (Keycloak)
- TLS & certificate management
- Observability & logging stacks
- Distributed storage (NFS)
- Bare‑metal networking (MetalLB)
- Secrets management
- Helm + ArgoCD GitOps workflows

It simulates a **production‑grade environment** for:
- SRE
- DevOps engineering
- Kubernetes administration
- Cloud‑native development
- Security & networking (CKA / CKS preparation)

---

## 📸 Architecture Diagram

(Insert PNG generated earlier into your repo)
`mirecloud-k8s-diagram.png`

---

## 🧑‍💻 Final Notes

Your lab is not “just a home lab” —  
it’s a **full cloud‑native platform**, structured like a real SaaS company stack.

Great foundation for:
- Freelancing
- Portfolio projects
- Cloud certification
- Automation & experimentation
- Developing real microservice architectures

---

## ✔️ Next recommended additions

- ArgoCD full GitOps
- HashiCorp Vault
- External‑DNS
- Service Mesh (Istio or Cilium Mesh)
- Kafka Connect + Debezium
- Backups via Velero

---

### 🚀 Welcome to MireCloud — your own personal cloud.

