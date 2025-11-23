# 🔷 MireCloud Kubernetes Lab Infrastructure

Ce document décrit **mon infrastructure Kubernetes maison**, mes choix techniques, et les étapes de préparation que j’ai suivies pour construire un lab stable, proche d’un environnement pro DevOps/SRE.

---

## 📌 Objectifs du lab

- Simuler une **infrastructure entreprise** à petite échelle  
- Expérimenter Kubernetes + Cilium + MetalLB + NGINX Ingress  
- Tester l’intégration DNS avec mon domaine : `mirecloud.com`  
- Héberger Keycloak, GitLab, services internes, etc.

---

## 🧱 Architecture générale

### Vue réseau (LAN 192.168.2.0/24)

```text
                ┌────────────────────┐
                │ Box / Routeur ISP  │
                │ 192.168.2.1        │
                └─────────┬──────────┘
                          │
            ┌─────────────┴─────────────┐
            │                           │
  ┌───────────────┐           ┌────────────────┐
  │ DNS LOCAL     │           │ Control Plane  │
  │ 192.168.2.40  │           │ 192.168.2.22   │
  │ (BIND/Pi-hole │           │ Ubuntu Server  │
  └───────────────┘           └───────┬────────┘
                                        │
                     ┌──────────────────┼──────────────────┐
                     │                  │                  │
             ┌─────────────┐   ┌─────────────┐    ┌─────────────┐
             │ Worker Node │   │ Worker Node │    │ Worker Node │
             │ node-1      │   │ node-2      │    │ node-3      │
             │ .27         │   │ .28         │    │ .29         │
             └─────────────┘   └─────────────┘    └─────────────┘
