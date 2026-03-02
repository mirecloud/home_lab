$mdContent = @"
# 🔐 The Definitive Guide: Kubernetes OIDC Authentication via Keycloak (Bare-Metal)

This guide details the configuration of OpenID Connect (OIDC) authentication for a bare-metal Kubernetes cluster (v1.34) using Keycloak as the Identity Provider (IdP) and `kubelogin` for CLI access.

**Author:** Emmanuel Catin
**Stack:** K8s v1.34, Keycloak (Quarkus), Cilium Gateway API, kubelogin.

---

## 🏗️ 1. Keycloak Configuration (The Identity Provider)

To allow `kubectl` to authenticate without exposing secrets (Client Secret), the Keycloak client must be configured as "Public".

1. Create or select the Realm (e.g., `mirecloud`).
2. Create a new Client:
   - **Client type:** OpenID Connect
   - **Client ID:** `kubernetes` *(must EXACTLY match the API Server flag)*
3. Under **Capability config**:
   - **Client authentication:** `Off` *(Crucial: prevents the `unauthorized_client` error during token exchange by kubelogin)*.
   - **Authentication flow:** Check "Standard flow" and "Direct access grants".
4. Under **Login settings**:
   - **Valid redirect URIs:** Add **only** `http://localhost:8000` and `http://localhost:8000/`. (Enter each URL separately by pressing Enter. Keycloak does not accept spaces).
5. Under **Users**:
   - Ensure the admin user has an email address configured.
   - **Important:** The **Email verified** toggle must be set to `On`. Otherwise, the API Server will reject the token with the error `[invalid bearer token, oidc: email not verified]`.

---

## ⚙️ 2. `kube-apiserver` Configuration (The Relying Party)

The API Server must be configured to trust Keycloak and extract the correct information (claims) from the JWT token.

Edit the static manifest on the Control Plane (`/etc/kubernetes/manifests/kube-apiserver.yaml`).

> ⚠️ **Deadly YAML Pitfall:** **NEVER** use inline comments (`# comment`) next to arguments in the `command:` block. The Kubernetes parser will include the trailing spaces and the comment itself in the variable's value, causing silent 401 errors.

**Add the following flags cleanly:**

    - command:
      - kube-apiserver
      # ... other existing flags ...
      - --oidc-issuer-url=https://keycloak.mirecloud.com/auth/realms/mirecloud
      - --oidc-client-id=kubernetes
      - --oidc-username-claim=email
      - --oidc-groups-claim=groups
      - --oidc-ca-file=/etc/kubernetes/pki/keycloak-ca.crt

*Notes on flags:*
* `--oidc-issuer-url`: The exact discovery URL. **Pay attention to the `/auth/` path** if your Keycloak instance still uses it.
* `--oidc-ca-file`: The path to the Certificate Authority (CA) certificate that signed Keycloak's TLS certificate. If missing or invalid, the API Server will reject the token's signature.

*The API Server will automatically restart upon saving the file (takes ~60 seconds).*

---

## 💻 3. `kubectl` Configuration with `kubelogin`

The `kubelogin` plugin (also known as `oidc-login` for kubectl) manages the OAuth2 Authorization Code flow with the browser.

### Initial Cleanup (in case of previous tests)
kubectl oidc-login clean
*(Note: on a headless server, a dbus-launch error will appear; this is normal and harmless, the file cache is successfully deleted).*

### Defining the OIDC User
Run the following command to configure your local kubeconfig:

kubectl config set-credentials oidc-user \
  --exec-api-version=client.authentication.k8s.io/v1beta1 \
  --exec-command=kubectl \
  --exec-arg=oidc-login \
  --exec-arg=get-token \
  --exec-arg=--oidc-issuer-url=https://keycloak.mirecloud.com/auth/realms/mirecloud \
  --exec-arg=--oidc-client-id=kubernetes \
  --exec-arg=--insecure-skip-tls-verify

### Applying the Context
kubectl config set-context oidc-context --cluster=kubernetes --user=oidc-user
kubectl config use-context oidc-context

---

## 🚇 4. The Headless Server Trick (SSH Tunnel)

When running `kubectl get nodes` from a headless server (e.g., `node-4`), `kubelogin` cannot open a web browser for the callback (`localhost:8000`).

**The Solution: SSH Tunnel (Port Forwarding)**

1. Open a terminal on the client machine with a GUI (e.g., your Windows PC).
2. Create a tunnel binding the local port to the server's port:
   ssh -L 8000:localhost:8000 root@192.168.2.75
3. Leave this terminal running in the background.
4. On the K8s server (`node-4`), trigger the authentication:
   kubectl get nodes
5. The CLI server will output a manual link: `http://localhost:8000/?state=...`
6. Copy this link and paste it into the web browser on your Windows PC.
7. Authenticate via Keycloak. The browser will display **"Authenticated"** and the `kubectl` command on the server will unblock and display your nodes!

---

## 🩺 5. Troubleshooting

| Symptom / Error | Probable Cause | Solution |
| :--- | :--- | :--- |
| lookup keycloak... no such host | The headless node lacks access to the internal DNS resolver. | Add the Ingress/Gateway IP to /etc/hosts on the node. |
| Resource not found on the issuer URL | The Issuer path is incorrect. | Check the .well-known/openid-configuration URL in a browser and adjust accordingly. |
| A redirect URI is not a valid URI | Keycloak does not accept spaces in the Redirect URIs list. | Enter http://localhost:8000 and press Enter to create a distinct tag. |
| unauthorized_client | The Keycloak client demands a password (Client Secret). | Set **Client authentication** to Off in Keycloak. |
| state does not match | The local cache is corrupted by multiple attempts or background tabs. | Close all browser tabs and run kubectl oidc-login clean. |
| Silent 401 Unauthorized | The API Server cannot parse the Client ID or the keycloak-ca.crt CA is missing. | Remove inline comments from kube-apiserver.yaml. Verify the CA file. |
| email not verified | The --oidc-username-claim=email flag is strict and Keycloak reports the email is not verified. | Toggle the "Email verified" button to On in the user's profile within Keycloak. |
"@

Set-Content -Path "$env:USERPROFILE\Desktop\k8s-oidc-keycloak-guide-en.md" -Value $mdContent -Encoding UTF8
Write-Host "✅ The file k8s-oidc-keycloak-guide-en.md has been successfully created on your Desktop!" -ForegroundColor Green