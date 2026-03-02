$mdContent = @"
#  Guide Definitif : Authentification OIDC Kubernetes via Keycloak (Bare-Metal)

Ce guide détaille la configuration de l'authentification OpenID Connect (OIDC) pour un cluster Kubernetes bare-metal (v1.34) utilisant Keycloak comme fournisseur d'identité (IdP) et `kubelogin` pour l'accès CLI.

**Auteur :** Emmanuel Catin
**Stack :** K8s v1.34, Keycloak (Quarkus), Cilium Gateway API, kubelogin.

---

##  1. Configuration de Keycloak (L'Identity Provider)

Pour que `kubectl` puisse s'authentifier sans exposer de secrets (Client Secret), le client Keycloak doit être configuré comme "Public".

1. Créer ou sélectionner le Realm (ex: `mirecloud`).
2. Créer un nouveau Client :
   - **Client type:** OpenID Connect
   - **Client ID:** `kubernetes` *(doit correspondre EXACTEMENT au flag de l'API Server)*
3. Dans **Capability config** :
   - **Client authentication:** `Off` *(Crucial : empêche l'erreur `unauthorized_client` lors de l'échange de jeton par kubelogin)*.
   - **Authentication flow:** Cocher "Standard flow" et "Direct access grants".
4. Dans **Login settings** :
   - **Valid redirect URIs:** Ajouter **uniquement** `http://localhost:8000` et `http://localhost:8000/`. (Entrer chaque URL séparément en appuyant sur Entrée. Keycloak n'accepte pas les espaces).
5. Dans **Users** :
   - Assurez-vous que l'utilisateur administrateur a une adresse e-mail configurée.
   - **Important :** L'option **Email verified** doit être sur `On`. Sinon, l'API Server rejettera le jeton avec l'erreur `[invalid bearer token, oidc: email not verified]`.

---

##  2. Configuration du `kube-apiserver` (Le Relying Party)

L'API Server doit être configuré pour faire confiance à Keycloak et extraire les bonnes informations (claims) du jeton JWT.

Éditer le manifeste statique sur le Control Plane (`/etc/kubernetes/manifests/kube-apiserver.yaml`).

>  **Piège YAML Mortel :** Ne **JAMAIS** mettre de commentaires en ligne (`# commentaire`) à côté des arguments dans le bloc `command:`. Le parser Kubernetes inclura les espaces et le commentaire dans la valeur de la variable, causant des erreurs 401 silencieuses.

**Ajouter les flags suivants proprement :**

    - command:
      - kube-apiserver
      # ... autres flags existants ...
      - --oidc-issuer-url=https://keycloak.mirecloud.com/auth/realms/mirecloud
      - --oidc-client-id=kubernetes
      - --oidc-username-claim=email
      - --oidc-groups-claim=groups
      - --oidc-ca-file=/etc/kubernetes/pki/keycloak-ca.crt

*Notes sur les flags :*
* `--oidc-issuer-url` : L'URL exacte de découverte. **Attention au `/auth/`** si votre instance Keycloak l'utilise encore.
* `--oidc-ca-file` : Le chemin vers le certificat de l'autorité de certification (CA) qui a signé le certificat TLS de Keycloak. S'il est manquant ou invalide, l'API Server rejettera la signature du jeton.

*L'API Server redémarrera automatiquement à la sauvegarde du fichier (compter ~60 secondes).*

---

##  3. Configuration de `kubectl` avec `kubelogin`

Le plugin `kubelogin` (plugin `oidc-login` pour kubectl) gère le flux OAuth2 Authorization Code avec le navigateur.

### Nettoyage préalable (en cas de tests antérieurs)
kubectl oidc-login clean
*(Note : sur un serveur sans interface graphique, une erreur dbus-launch apparaîtra ; elle est normale et inoffensive, le cache de fichiers est bien supprimé).*

### Définition de l'utilisateur OIDC
Exécuter la commande suivante pour configurer le kubeconfig local :

kubectl config set-credentials oidc-user \
  --exec-api-version=client.authentication.k8s.io/v1beta1 \
  --exec-command=kubectl \
  --exec-arg=oidc-login \
  --exec-arg=get-token \
  --exec-arg=--oidc-issuer-url=https://keycloak.mirecloud.com/auth/realms/mirecloud \
  --exec-arg=--oidc-client-id=kubernetes \
  --exec-arg=--insecure-skip-tls-verify

### Application du contexte
kubectl config set-context oidc-context --cluster=kubernetes --user=oidc-user
kubectl config use-context oidc-context

---

##  4. L'Astuce du Serveur Headless (Tunnel SSH)

Lorsqu'on exécute `kubectl get nodes` depuis un serveur sans interface graphique (ex: `node-4`), `kubelogin` ne peut pas ouvrir de navigateur web pour le callback (`localhost:8000`).

**La solution : Le Tunnel SSH (Port Forwarding)**

1. Ouvrir un terminal sur la machine cliente avec interface graphique (ex: PC Windows).
2. Créer un tunnel bindant le port local au port du serveur :
   ssh -L 8000:localhost:8000 root@192.168.2.75
3. Laisser ce terminal en arrière-plan.
4. Sur le serveur K8s (`node-4`), lancer l'authentification :
   kubectl get nodes
5. Le serveur CLI affichera un lien manuel : `http://localhost:8000/?state=...`
6. Copier ce lien et le coller dans le navigateur du PC Windows.
7. S'authentifier sur Keycloak. Le navigateur affichera **"Authenticated"** et la commande `kubectl` sur le serveur se débloquera et affichera les nœuds !

---

##  5. Résolution des problèmes (Troubleshooting)

| Symptôme / Erreur | Cause probable | Solution |
| :--- | :--- | :--- |
| lookup keycloak... no such host | Le nœud headless n'a pas accès au résolveur DNS interne. | Ajouter l'IP de l'Ingress/Gateway dans /etc/hosts sur le nœud. |
| Resource not found sur l'URL issuer | Le chemin de l'Issuer est incorrect. | Vérifier l'URL .well-known/openid-configuration dans un navigateur et l'ajuster. |
| A redirect URI is not a valid URI | Keycloak n'accepte pas les espaces dans la liste des Redirect URIs. | Entrer http://localhost:8000 et appuyer sur Entrée. |
| unauthorized_client | Le client Keycloak exige un mot de passe (Client Secret). | Mettre **Client authentication** sur Off dans Keycloak. |
| state does not match | Le cache local est corrompu par de multiples tentatives ou onglets ouverts. | Fermer les onglets du navigateur et exécuter kubectl oidc-login clean. |
| 401 Unauthorized silencieux | L'API Server ne trouve pas le Client ID ou le CA keycloak-ca.crt est manquant. | Nettoyer le kube-apiserver.yaml des commentaires inline. Vérifier le fichier CA. |
| email not verified | Le flag oidc-username-claim=email est strict et Keycloak indique que l'email n'est pas vérifié. | Passer le bouton "Email verified" sur On dans la fiche de l'utilisateur sur Keycloak. |
"@

Set-Content -Path "$env:USERPROFILE\Desktop\k8s-oidc-keycloak-guide.md" -Value $mdContent -Encoding UTF8
Write-Host "✅ Fichier k8s-oidc-keycloak-guide.md créé avec succès sur ton Bureau !" -ForegroundColor Green