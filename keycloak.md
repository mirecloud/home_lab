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

---

## 4. Secret PostgreSQL
Keycloak utilise une DB PostgreSQL externe.

Créer le secret :
```bash
kubectl create secret generic keycloak-db-creds \
  -n keycloak \
  --from-literal=user=admin \
  --from-literal=password=admin
---

## 3 values
# ---------------------------------------------------------
# BASIC SETTINGS
# ---------------------------------------------------------
replicas: 1

image:
  repository: quay.io/keycloak/keycloak
  tag: "17.0.1-legacy"
  pullPolicy: IfNotPresent

# ---------------------------------------------------------
# DISABLE INTERNAL POSTGRES
# ---------------------------------------------------------
postgresql:
  enabled: false

# ---------------------------------------------------------
# DATABASE CONFIG (EXTERNAL POSTGRES)
# ---------------------------------------------------------
extraEnv: |
  - name: KEYCLOAK_USER
    valueFrom:
      secretKeyRef:
        name: keycloak-admin
        key: KEYCLOAK_USER

  - name: KEYCLOAK_PASSWORD
    valueFrom:
      secretKeyRef:
        name: keycloak-admin
        key: KEYCLOAK_PASSWORD

  - name: DB_VENDOR
    value: postgres

  - name: DB_ADDR
    value: "postgres.postgres.svc"

  - name: DB_PORT
    value: "5432"

  - name: DB_DATABASE
    value: "postgres"

  - name: DB_USER
    valueFrom:
      secretKeyRef:
        name: postgres-external
        key: username

  - name: DB_PASSWORD
    valueFrom:
      secretKeyRef:
        name: postgres-external
        key: password

  - name: PROXY_ADDRESS_FORWARDING
    value: "true"

  # Mode "behind reverse proxy" (ingress-nginx)
  - name: KEYCLOAK_FRONTEND_URL
    value: "https://keycloak.mirecloud.com/auth"

# ---------------------------------------------------------
# SECRET LOCATION FOR DB CREDS
# ---------------------------------------------------------
extraVolumes: |
  - name: external-ca
    secret:
      secretName: mirecloud-ca

extraVolumeMounts: |
  - name: external-ca
    mountPath: /usr/local/share/ca-certificates/mirecloud-ca.crt
    subPath: mirecloud-ca.crt
    readOnly: true

# ---------------------------------------------------------
# INGRESS CONFIG
# ---------------------------------------------------------
ingress:
  enabled: true
  ingressClassName: "nginx"

  annotations:
    nginx.ingress.kubernetes.io/proxy-buffer-size: "128k"
    nginx.ingress.kubernetes.io/proxy-body-size: "50m"
    nginx.ingress.kubernetes.io/backend-protocol: "HTTP"

  rules:
    - host: keycloak.mirecloud.com
      paths:
        - path: /
          pathType: Prefix

  tls:
    - hosts:
        - keycloak.mirecloud.com
      secretName: wildcard-mirecloud

# ---------------------------------------------------------
# SERVICE CONFIG
# ---------------------------------------------------------
service:
  type: ClusterIP
  httpPort: 80
  httpsPort: 8443

# ---------------------------------------------------------
# RESOURCES (OPTIONAL)
# ---------------------------------------------------------
resources:
  requests:
    cpu: "500m"
    memory: "1Gi"
  limits:
    cpu: "1"
    memory: "2Gi"


---

## indication

🧱 Étape 1 — Créer le secret Postgres externe

Comme ton chart CloudPirates a généré un secret avec des clés encodées base64, mais Keycloak veut des clés en clair.

Donc on crée un secret propre :

kubectl -n keycloak create secret generic postgres-external \
  --from-literal=username=postgres \
  --from-literal=password=7lsoGvNqCuoqxVLxqL0hC0yL3WzQGQ26

🧱 Étape 2 — Ajouter ta CA interne (facultatif mais utile)
kubectl -n keycloak create secret generic mirecloud-ca \
  --from-file=mirecloud-ca.crt

🧱 Étape 3 — Ajouter le certificat wildcard
kubectl -n keycloak create secret tls wildcard-mirecloud \
  --cert=wildcard.mirecloud.com.crt \
  --key=wildcard.mirecloud.com.key

🧱 Étape 4 — Installer Keycloak
helm repo add codecentric https://codecentric.github.io/helm-charts
helm repo update

helm install keycloak codecentric/keycloak \
  -n keycloak \
  -f keycloak-values.yaml

🧱 Étape 5 — Créer l’admin user
kubectl -n keycloak create secret generic keycloak-admin \
  --from-literal=KEYCLOAK_USER=admin \
  --from-literal=KEYCLOAK_PASSWORD=admin


Puis ajoute dans extraEnv (déjà dans notre values.yaml si tu veux) :

  - name: KEYCLOAK_USER
    valueFrom:
      secretKeyRef:
        name: keycloak-admin
        key: KEYCLOAK_USER

  - name: KEYCLOAK_PASSWORD
    valueFrom:
      secretKeyRef:
        name: keycloak-admin
        key: KEYCLOAK_PASSWORD


Si ajouté, fais :

helm upgrade keycloak codecentric/keycloak -n keycloak -f keycloak-values.yaml
