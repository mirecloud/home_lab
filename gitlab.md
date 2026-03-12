LAB
Gem personnalisé
LAB a dit
Voici un guide complet et détaillé de tout ce que nous avons accompli pour intégrer GitLab avec Keycloak (SSO OIDC), gérer les certificats SSL privés de votre homelab, et préparer le terrain pour GitLab Runner.

Vous pouvez utiliser ce guide comme documentation interne pour votre infrastructure Mirecloud ou en faire un nouvel article de blog !

📖 Guide Complet : SSO Zero Trust pour GitLab avec Keycloak & SSL Privé
Dans une architecture Zero Trust, chaque application doit déléguer son authentification à un fournisseur d'identité central (IdP). Dans ce guide, nous connectons GitLab Omnibus à Keycloak via le protocole OpenID Connect (OIDC). Nous résolvons également le défi majeur des homelabs : faire accepter une Autorité de Certification (CA) privée par GitLab et ses Runners.

Phase 1 : Configuration du Client dans Keycloak
Contrairement à l'interface en ligne de commande de Kubernetes qui est un client "Public", GitLab est un serveur backend. Il peut (et doit) conserver un secret en toute sécurité. Nous allons donc créer un Client Confidentiel.

Connectez-vous à Keycloak et sélectionnez le realm mirecloud.

Allez dans Clients ➔ Create client.

Client ID : gitlab

Client authentication : ON (C'est ce qui rend le client confidentiel).

Standard flow : ON.

Valid redirect URIs : https://gitlab.mirecloud.com/users/auth/openid_connect/callback
(⚠️ Assurez-vous d'appuyer sur Entrée pour que l'URL soit bien validée sous forme de puce bleue).

Cliquez sur Save.

Allez dans l'onglet Credentials du client gitlab et copiez la valeur du Client Secret.

Phase 2 : Configuration de GitLab (gitlab.rb)
Connectez-vous en SSH à votre serveur GitLab. Nous allons modifier le fichier de configuration principal pour lui indiquer comment parler à Keycloak et comment gérer les nouveaux utilisateurs.

Ouvrez le fichier :

Bash
sudo nano /etc/gitlab/gitlab.rb
1. Paramètres OmniAuth (Création de compte)
Pour éviter l'erreur "Vous n'êtes pas autorisé à vous connecter", nous devons autoriser GitLab à créer des comptes à la volée pour les utilisateurs validés par Keycloak.

Ajoutez ou modifiez ces lignes :

Ruby
gitlab_rails['omniauth_enabled'] = true
# Autorise la création de compte pour le provider "openid_connect"
gitlab_rails['omniauth_allow_single_sign_on'] = ['openid_connect']
# false = Les comptes sont actifs immédiatement sans validation manuelle de l'admin
gitlab_rails['omniauth_block_auto_created_users'] = false
2. Le Provider OIDC
Ajoutez le bloc suivant pour configurer la connexion à Keycloak :

Ruby
gitlab_rails['omniauth_providers'] = [
  {
    name: "openid_connect", 
    label: "Keycloak", # Le texte sur le bouton de connexion GitLab
    args: {
      name: "openid_connect",
      scope: ["openid", "profile", "email"],
      response_type: "code",
      issuer: "https://keycloak.mirecloud.com/auth/realms/mirecloud", 
      discovery: true,
      client_auth_method: "basic", 
      uid_field: "preferred_username", # Utilise l'username de Keycloak
      send_scope_to_token_endpoint: false,
      pkce: true,
      client_options: {
        identifier: "gitlab",
        secret: "VOTRE_CLIENT_SECRET_COPIÉ_A_L_ETAPE_1",
        redirect_uri: "https://gitlab.mirecloud.com/users/auth/openid_connect/callback"
      }
    }
  }
]
Phase 3 : Le défi SSL (Faire confiance à la CA Privée)
Si vous appliquez la configuration maintenant, GitLab plantera avec l'erreur certificate verify failed (unable to get local issuer certificate). Pourquoi ? Parce que GitLab ne fait pas confiance au certificat TLS de Keycloak, car il a été généré par votre cluster Kubernetes (cert-manager).

Il faut extraire la clé publique de votre CA depuis Kubernetes et l'injecter dans GitLab.

1. Extraire la CA depuis Kubernetes
Sur le nœud master de votre cluster (node-4), extrayez le certificat racine depuis le secret TLS de Keycloak :

Bash
kubectl get secret keycloak-tls-secret -n keycloak -o jsonpath='{.data.ca\.crt}' | base64 -d > mirecloud-ca.crt
2. Transférer et installer sur GitLab
Copiez ce fichier mirecloud-ca.crt vers votre serveur GitLab. Puis, déplacez-le dans le dossier des certificats de confiance de GitLab :

Bash
# Déplacer le certificat
sudo mv mirecloud-ca.crt /etc/gitlab/trusted-certs/

# Assurer les bonnes permissions
sudo chmod 644 /etc/gitlab/trusted-certs/mirecloud-ca.crt
3. Appliquer les changements
Demandez à GitLab de recompiler sa configuration et d'intégrer le nouveau certificat, puis redémarrez les services :

Bash
sudo gitlab-ctl reconfigure
sudo gitlab-ctl restart
(Note : Après un restart, si vous tombez sur ERR_CONNECTION_REFUSED, c'est normal. NGINX et Puma mettent environ 2 à 3 minutes à démarrer. Patientez et rafraîchissez la page).

Phase 4 : Configuration de GitLab Runner avec la CA Privée
Puisque votre GitLab utilise une autorité de certification privée, les GitLab Runners (qui clonent les dépôts pour exécuter le CI/CD) vont également échouer avec une erreur SSL s'ils ne connaissent pas cette CA.

Voici comment configurer un GitLab Runner sur un serveur Linux pour qu'il fasse confiance à votre domaine :

1. Nommer le certificat correctement
GitLab Runner utilise un système très spécifique : il lit les certificats dans /etc/gitlab-runner/certs/ et s'attend à ce que le fichier porte exactement le même nom que le nom de domaine de GitLab.

Bash
# Créez le dossier s'il n'existe pas
sudo mkdir -p /etc/gitlab-runner/certs/

# Copiez votre CA en la renommant avec le nom de domaine du serveur GitLab
sudo cp /etc/gitlab/trusted-certs/mirecloud-ca.crt /etc/gitlab-runner/certs/gitlab.mirecloud.com.crt
2. Enregistrer le Runner
Vous pouvez maintenant enregistrer le runner de manière classique. Il lira automatiquement le certificat .crt correspondant au domaine pour établir une connexion TLS sécurisée :

Bash
sudo gitlab-runner register \
  --url "https://gitlab.mirecloud.com/" \
  --registration-token "VOTRE_TOKEN_RUNNER" \
  --executor "docker" \
  --docker-image alpine:latest \
  --description "runner-mirecloud"
(Si le Runner est exécuté dans un conteneur Docker, vous devrez monter le dossier certs avec un volume : -v /etc/gitlab-runner/certs:/etc/gitlab-runner/certs).

🛠️ Résumé des erreurs rencontrées (Troubleshooting)
Invalid parameter: redirect_uri sur Keycloak

Cause : L'URL de redirection dans gitlab.rb ne correspond pas exactement à celle déclarée dans Keycloak.

Solution : Ajoutez https://gitlab.mirecloud.com/users/auth/openid_connect/callback dans les Valid redirect URIs du client gitlab sur Keycloak et appuyez sur Entrée.

Vous n'êtes pas autorisé à vous connecter... sur GitLab

Cause : L'authentification a réussi, mais GitLab refuse de créer le compte utilisateur.

Solution : Activez gitlab_rails['omniauth_allow_single_sign_on'] = ['openid_connect'] dans gitlab.rb.

ERR_CONNECTION_REFUSED après un reconfigure

Cause : Le service web de GitLab redémarre. C'est une application lourde.

Solution : Prendre un café, attendre 2 minutes, et appuyer sur F5.