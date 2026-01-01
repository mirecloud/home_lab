# Guide d'Intégration : Vault & External Secrets (GitOps)

Ce guide documente l'architecture de gestion des secrets mise en place dans le HomeLab.

**Objectif :** Zéro secret dans Git. Vault stocke les secrets, External Secrets (ESO) les injecte dynamiquement dans Kubernetes.

---

## 1. Architecture des dossiers

Pour éviter les problèmes de *race condition* (l'œuf et la poule) dans ArgoCD, l'infrastructure est séparée en **trois couches distinctes** :

```text
infrastructure/
├── vault/                      # Le coffre-fort (logiciel Vault)
├── external-secrets/           # L'opérateur ESO (CRDs + contrôleur)
│   ├── Chart.yaml
│   └── values.yaml
└── external-secrets-config/    # La configuration (le pont vers Vault)
    └── secret-store.yaml       # ClusterSecretStore
```

---

## 2. Déploiement ArgoCD

### Ordre de déploiement (strict)

1. **Vault**
   - `infrastructure/vault`

2. **External Secrets Operator**
   - `infrastructure/external-secrets`

3. **External Secrets Config**
   - `infrastructure/external-secrets-config`

⚠️ **Important :**
Attendre que l'opérateur ESO soit **Healthy** avant de déployer la configuration.
Les CRDs (`ClusterSecretStore`) doivent exister.

---

### Astuce ArgoCD – Vault Injector

Pour éviter que l'application Vault reste en `OutOfSync` à cause du certificat auto‑généré par l'injector, ajouter ceci dans l'Application ArgoCD de Vault :

```yaml
spec:
  ignoreDifferences:
    - group: admissionregistration.k8s.io
      kind: MutatingWebhookConfiguration
      jsonPointers:
        - /webhooks/0/clientConfig/caBundle
```

---

## 3. Configuration du pont : ClusterSecretStore

**Fichier :**
`infrastructure/external-secrets-config/secret-store.yaml`

Ce fichier permet à External Secrets de s'authentifier auprès de Vault.

⚠️ **Point critique :**
Toujours utiliser le **service stable** `vault`, jamais `vault-active`.

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

---

## 4. Initialisation de Vault (procédure unique)

Après l'installation, Vault est **vide et scellé**.
Cette procédure est à faire **une seule fois**.

---

### A. Initialisation & Unseal

```bash
# Entrer dans le pod
kubectl -n vault exec -ti vault-0 -- sh

# Générer les clés (À FAIRE UNE SEULE FOIS ET SAUVEGARDER LE RÉSULTAT)
vault operator init
```

Déverrouiller Vault (répéter sur chaque pod si HA) :

```bash
vault operator unseal <CLE_1>
vault operator unseal <CLE_2>
vault operator unseal <CLE_3>
```

---

### B. Configuration de l'authentification Kubernetes

Toujours dans `vault-0`, avec le **Root Token** :

```bash
vault login <ROOT_TOKEN>
```

1. Activer l'auth Kubernetes :

```bash
vault auth enable kubernetes
```

2. Configurer l'API Kubernetes :

```bash
vault write auth/kubernetes/config \
  kubernetes_host="https://$KUBERNETES_PORT_443_TCP_ADDR:443"
```

3. Créer la policy :

```bash
vault policy write vault-backend - <<EOF
path "secret/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}
EOF
```

4. Créer le rôle lié à ESO :

```bash
vault write auth/kubernetes/role/vault-backend \
  bound_service_account_names=external-secrets \
  bound_service_account_namespaces=external-secrets \
  policies=vault-backend \
  ttl=24h
```

---

## 5. Mode d'emploi (Day‑to‑Day)

### Exemple : ajouter un secret pour Keycloak

---

### Étape 1 – Créer le secret dans Vault

```bash
vault kv put secret/keycloak admin-password="MonSuperMotDePasse"
```

---

### Étape 2 – Créer l'ExternalSecret

**Fichier :**
`apps/keycloak/templates/external-secret.yaml`

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: keycloak-secrets
  namespace: keycloak
spec:
  refreshInterval: 1m
  secretStoreRef:
    name: vault-backend
    kind: ClusterSecretStore
  target:
    name: keycloak-admin-secret
  data:
    - secretKey: password
      remoteRef:
        key: secret/keycloak
        property: admin-password
```

---

### Étape 3 – Consommer le secret dans Helm

```yaml
auth:
  existingSecret: keycloak-admin-secret
  passwordSecretKey: password
```

---

## 6. Vérification

```bash
kubectl get clustersecretstore vault-backend
```

Résultat attendu :

```
STATUS:   Valid
```

---

## 7. Versioning Git

```bash
git add VAULT_INTEGRATION.md
git commit -m "Docs: add Vault & External Secrets integration guide"
git push
```

---

✔️ Architecture saine  
✔️ Aucun secret dans Git  
✔️ Compatible GitOps / ArgoCD  

Prêt à brancher la prochaine application.
