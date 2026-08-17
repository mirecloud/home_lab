# Installation LibreChat

Déploiement GitOps (ArgoCD) de LibreChat sur le homelab MireCloud.
Chart : `oci://ghcr.io/danny-avila/librechat-chart/librechat` **v2.0.8** (wrapper `apps/librechat`).

Deux prérequis **manuels** avant le premier sync ArgoCD :

1. Peupler le secret Vault `secret/librechat/env`
2. Créer le client `librechat` dans Keycloak (realm `mirecloud`)

---

## 1. Secrets Vault

L'`ExternalSecret` (`templates/external-secrets.yaml`) synchronise Vault → le Secret
Kubernetes `librechat-credentials-env`. La racine de clé suit **exactement** la même
convention que openwebui (`key: secret/<app>/...` sur le `ClusterSecretStore`
`vault-backend`, mount KVv2 `secret`).

> ⚠️ Vérifie d'abord que ta convention openwebui répond bien :
> ```bash
> vault kv get secret/openwebui/secret
> ```
> Si le chemin réel chez toi porte un préfixe différent (ex. double `secret/`),
> applique **le même** décalage à la commande ci-dessous.

### Génération + écriture des valeurs

LibreChat exige : `CREDS_KEY` (32o hex), `CREDS_IV` (16o hex), `JWT_SECRET`,
`JWT_REFRESH_SECRET`, `MEILI_MASTER_KEY`. On ajoute les secrets OIDC
(`OPENID_SESSION_SECRET` + `OPENID_CLIENT_SECRET`, ce dernier vient de Keycloak — voir §2).

```bash
# Génère les secrets d'un coup et les écrit dans Vault (KVv2 mount "secret")
vault kv put secret/librechat/env \
  CREDS_KEY="$(openssl rand -hex 32)" \
  CREDS_IV="$(openssl rand -hex 16)" \
  JWT_SECRET="$(openssl rand -hex 32)" \
  JWT_REFRESH_SECRET="$(openssl rand -hex 32)" \
  MEILI_MASTER_KEY="$(openssl rand -hex 32)" \
  OPENID_SESSION_SECRET="$(openssl rand -hex 32)" \
  OPENID_CLIENT_SECRET="REMPLACER_PAR_LE_SECRET_KEYCLOAK"
```

> Le `OPENID_CLIENT_SECRET` sera connu après la création du client Keycloak (§2).
> Tu peux relancer un `vault kv patch` pour ne mettre à jour que cette clé :
> ```bash
> vault kv patch secret/librechat/env OPENID_CLIENT_SECRET="<secret-du-client>"
> ```

### Vérification

```bash
vault kv get secret/librechat/env
# puis, après sync ArgoCD :
kubectl -n librechat get externalsecret
kubectl -n librechat get secret librechat-credentials-env -o jsonpath='{.data}' | tr ',' '\n'
```

La CA interne (`mirecloud-ca-cert`) est synchronisée par le 2ᵉ ExternalSecret
depuis `secret/mirecloud/ca` (déjà en place, identique à openwebui).

---

## 2. Client Keycloak (realm `mirecloud`)

Aucun realm-import GitOps dans ce repo → création manuelle, comme les autres clients
(`openwebui`, etc.). Via `kcadm.sh` depuis le pod Keycloak, ou l'UI admin.

### Option A — kcadm.sh (depuis le pod Keycloak)

```bash
# Ouvre un shell dans le pod keycloak
kubectl -n keycloak exec -it deploy/keycloak-keycloakx -- bash

# Auth admin (adapte le mot de passe / master realm)
/opt/keycloak/bin/kcadm.sh config credentials \
  --server http://localhost:8080/auth \
  --realm master --user admin --password "$KEYCLOAK_ADMIN_PASSWORD"

# Crée le client confidentiel "librechat"
/opt/keycloak/bin/kcadm.sh create clients -r mirecloud \
  -s clientId=librechat \
  -s enabled=true \
  -s protocol=openid-connect \
  -s publicClient=false \
  -s standardFlowEnabled=true \
  -s directAccessGrantsEnabled=false \
  -s 'redirectUris=["https://librechat.mirecloud.com/oauth/openid/callback"]' \
  -s 'webOrigins=["https://librechat.mirecloud.com"]' \
  -s 'attributes={"post.logout.redirect.uris":"https://librechat.mirecloud.com/*"}'

# Récupère l'ID interne puis le secret
CID=$(/opt/keycloak/bin/kcadm.sh get clients -r mirecloud -q clientId=librechat --fields id --format csv --noquotes | tail -n1)
/opt/keycloak/bin/kcadm.sh get clients/$CID/client-secret -r mirecloud
```

Copie la valeur `value` retournée → c'est le `OPENID_CLIENT_SECRET` du §1
(`vault kv patch ...`).

### Option B — UI admin Keycloak

1. Realm `mirecloud` → **Clients** → **Create client**
2. Client ID : `librechat` — Client authentication : **On** (confidentiel)
3. Standard flow : **On** ; Direct access grants : Off
4. **Valid redirect URIs** : `https://librechat.mirecloud.com/oauth/openid/callback`
5. **Web origins** : `https://librechat.mirecloud.com`
6. Onglet **Credentials** → copier le *Client secret*

### (Optionnel) Claim `groups` pour du contrôle d'accès par rôle

LibreChat sait restreindre l'accès via un rôle OIDC (`OPENID_REQUIRED_ROLE*`).
Si tu veux réutiliser tes groupes Keycloak (comme openwebui), ajoute un mapper
**Group Membership** (Token Claim Name = `groups`) au client, puis renseigne dans
`values.yaml → librechat.configEnv` :

```yaml
OPENID_REQUIRED_ROLE_SOURCE: "id"      # ou "access"
OPENID_REQUIRED_ROLE_PARAMETER_PATH: "groups"
OPENID_REQUIRED_ROLE: "/librechat-users"
```

---

## 3. Sync ArgoCD

```bash
# Le manifeste Application est dans clusters/home-lab/librechat-app.yaml
kubectl apply -f clusters/home-lab/librechat-app.yaml   # si non auto-découvert
argocd app sync librechat                                # ou via l'UI
```

Vérifs post-déploiement :

```bash
kubectl -n librechat get pods
kubectl -n librechat get svc                # confirme le nom du service backend (HTTPRoute)
kubectl -n librechat get gateway,httproute
kubectl -n librechat get certificate        # librechat-tls-cert doit passer Ready=True
```

---

## Points à valider

- **Nom du service backend** dans `templates/gateway.yaml` : `librechat:3080`
  (release ArgoCD = `librechat`, fullname collapsé). Si 503 sur la route,
  `kubectl -n librechat get svc` et ajuster `backendRefs.name`.
- **Modèle RAG** dans `configYamlContent` : `default: ["rag"]` → mettre le nom réel
  exposé par `http://rag-api.rag.svc.cluster.local:8000/v1/models`.
- **DNS** : `librechat.mirecloud.com` (géré par external-dns si annoté comme les autres).

## Désinstallation

```bash
argocd app delete librechat            # + supprimer clusters/home-lab/librechat-app.yaml du repo
# Nettoyage éventuel des PVC (Mongo/Meili/images) et du secret Vault si voulu :
kubectl -n librechat delete pvc --all
vault kv delete secret/librechat/env
```
