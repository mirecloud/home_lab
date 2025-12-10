# Keycloak Deployment on MireCloud Kubernetes Lab

This guide documents the full installation of Keycloak in your MireCloud Kubernetes environment using an external PostgreSQL database and a custom wildcard TLS certificate.

---

##  Overview

I deployed Keycloak using:

- **CloudPirates Keycloak Helm chart**
- **External PostgreSQL** (existing Helm deployment)
- **Wildcard TLS certificate** signed by your internal CA
- **Ingress (NGINX)** exposed at:  
   `https://keycloak.mirecloud.com`

This guide consolidates your configuration into a clean, professional document.

---

##  Prerequisites

Before deploying Keycloak, ensure the following elements exist:

###  1. External PostgreSQL (already deployed)

I deployed PostgreSQL using helm:

```
Please refer to the Postgres.md file in the same repo
```

This chart outputs a secret with:

- **host:** `postgres.postgres.svc`
- **port:** `5432`
- **database:** `postgres`
- **username:** from secret key `db-username`
- **password:** from secret key `db-password`

###  2. Wildcard TLS Certificate

You created the certificate manually and created the Kubernetes TLS secret:

```bash
kubectl -n keycloak create secret tls wildcard-mirecloud   --cert=/home/asd/mirecloud-ca/wildcard.mirecloud.com.crt   --key=/home/asd/mirecloud-ca/wildcard.mirecloud.com.key
```

This secret is referenced by the Keycloak ingress.

---

##  Helm Values File (values.yaml)

Below is your exact, validated, deployment-ready Keycloak configuration.

```yaml
keycloak:
  adminUser: admin
  adminPassword: "admin"
  hostname: "keycloak.mirecloud.com"
  proxyHeaders: "xforwarded"
  production: true

database:
  type: postgres
  host: "postgres.postgres.svc"
  port: "5432"
  name: "postgres"
  existingSecret: "keycloak-db"
  secretKeys:
    usernameKey: "db-username"
    passwordKey: "db-password"

postgres:
  enabled: false

mariadb:
  enabled: false

ingress:
  enabled: true
  className: "nginx"
  annotations:
    nginx.ingress.kubernetes.io/backend-protocol: "HTTP"
  hosts:
    - host: keycloak.mirecloud.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: wildcard-mirecloud
      hosts:
        - keycloak.mirecloud.com

service:
  type: ClusterIP
```

---

##  Helm Deployment Command

Run the installation:

```bash
helm upgrade --install keycloak   oci://registry-1.docker.io/cloudpirates/keycloak   -n keycloak   -f values.yaml
```

Check installation status:

```bash
kubectl -n keycloak get pods
kubectl -n keycloak get ingress
kubectl -n keycloak logs deploy/keycloak
```

---

##  Final Access URL

Once deployed:

###  **https://keycloak.mirecloud.com**

This endpoint is protected by the wildcard certificate and routed through NGINX Ingress.

---

##  Deployment Complete

I now have a fully production-style Keycloak deployment with:

✔ External PostgreSQL  
✔ TLS termination  
✔ Wildcard domain  
✔ Ingress routing  
✔ Externalized credentials  

Perfect foundation for OAuth2 / OIDC integrations (Grafana, GitLab, ArgoCD, etc.).

---


