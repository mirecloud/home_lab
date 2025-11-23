# Keycloak sur Kubernetes – Lab complet (mirecloud)

Ce dossier documente mon déploiement de **Keycloak (17.0.1-legacy)** sur mon cluster Kubernetes *mirecloud* avec :

- PostgreSQL externe  
- Ingress NGINX + MetalLB  
- TLS via secret Kubernetes  
- DNS interne via BIND (`mirecloud.com`)  

---

## 1. Architecture

### Composants

| Composant | Description |
|---------|-------------|
| PostgreSQL | DB externe pour Keycloak |
| Keycloak | Identity provider (SSO / IAM) |
| NGINX Ingress | Reverse proxy HTTP/HTTPS |
| MetalLB | Fournit l’IP externe |
| BIND | DNS interne du domaine mirecloud.com |

### Services internes

| Service | Adresse |
|--------|--------|
| PostgreSQL | `postgres.postgres.svc.cluster.local:5432` |
| Keycloak | `keycloak-http.keycloak.svc.cluster.local:8080` |
| Ingress | `keycloak.mirecloud.com → 192.168.2.100` |

---

## 2. DNS BIND

Sur ton serveur DNS `192.168.2.40`, édite :

```bash
sudo nano /etc/bind/db.mirecloud.com
