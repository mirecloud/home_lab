Voilà le guide complet, directement ici :

---

```markdown
# Kubernetes OIDC Authentication via Keycloak — Complete Production Guide

> **Author:** Emmanuel Catin
> **Stack:** Kubernetes v1.34 · Keycloak (Quarkus) · Cilium Gateway API · kubelogin v1.35.2
> **Environment:** Bare-metal cluster · Realm `mirecloud`

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Authentication Flow](#2-authentication-flow)
3. [Keycloak Configuration](#3-keycloak-configuration)
4. [Kubernetes API Server Configuration](#4-kubernetes-api-server-configuration)
5. [kubectl & kubelogin Setup](#5-kubectl--kubelogin-setup)
6. [Headless Server — SSH Tunnel + Live Demo](#6-headless-server--ssh-tunnel--live-demo)
7. [Verification & Testing](#7-verification--testing)
8. [Troubleshooting Reference](#8-troubleshooting-reference)

---

## 1. Architecture Overview

<img width="1024" height="559" alt="image" src="https://github.com/user-attachments/assets/8bd9d73e-7298-4241-b754-43c6fcad8571" />


**Key principle:** The API server never handles passwords. It delegates identity
verification entirely to Keycloak via signed JWT tokens. RBAC then maps verified
identities to Kubernetes permissions.

---

## 2. Authentication Flow

### 2.1 Standard OIDC Authorization Code Flow

```
  kubectl           kubelogin          Keycloak        kube-apiserver
     │                  │                 │                   │
     │─ kubectl ────────►│                 │                   │
     │  get nodes        │                 │                   │
     │                  │── Open browser ─►│                   │
     │                  │  localhost:8000  │                   │
     │                  │                 │                   │
     │                  │  User enters    │                   │
     │                  │  credentials ──►│                   │
     │                  │                 │                   │
     │                  │◄── Auth Code ───│                   │
     │                  │                 │                   │
     │                  │── Exchange ─────►│                   │
     │                  │   code          │                   │
     │                  │◄── ID Token ────│                   │
     │                  │    (JWT signed) │                   │
     │◄─ Bearer Token ──│                 │                   │
     │                  │                 │                   │
     │────────── GET /api/v1/nodes  (Bearer: JWT) ────────────►│
     │                  │                 │                   │
     │                  │                 │◄── Verify JWT ────│
     │                  │                 │    via JWKS       │
     │                  │                 │                   │
     │                  │                 │  Extract claims:  │
     │                  │                 │  email → username │
     │                  │                 │  groups → groups  │
     │                  │                 │                   │
     │                  │                 │  RBAC check ──────│
     │                  │                 │  oidc-admin-      │
     │                  │                 │  binding          │
     │◄──────────────────────────── 200 OK + node list ───────│
```

### 2.2 JWT Token Anatomy

```
┌──────────────────────────────────────────────────────────┐
│                     ID Token (JWT)                        │
├───────────────┬──────────────────────────────────────────┤
│    HEADER     │  { "alg": "RS256", "typ": "JWT" }        │
├───────────────┼──────────────────────────────────────────┤
│               │  {                                        │
│               │    "iss": "https://keycloak.../mirecloud" │
│    PAYLOAD    │    "sub": "user-uuid",                    │
│   (Claims)    │    "email": "info@mirecloud.com",  ◄──────┼─ username
│               │    "groups": ["k8s-admin"],         ◄─────┼─ groups
│               │    "email_verified": true,          ◄─────┼─ REQUIRED
│               │    "exp": 1740000000                      │
│               │  }                                        │
├───────────────┼──────────────────────────────────────────┤
│   SIGNATURE   │  RSA256(header + payload, private_key)   │
│               │  ← Verified by API server via JWKS        │
└───────────────┴──────────────────────────────────────────┘
```

---

## 3. Keycloak Configuration

### 3.1 Realm & Client Setup

**Realm:** `mirecloud`

| Field                  | Value                               | Reason                                          |
|------------------------|-------------------------------------|-------------------------------------------------|
| Client type            | `OpenID Connect`                    | Standard OIDC protocol                          |
| Client ID              | `kubernetes`                        | Must match `--oidc-client-id` exactly           |
| Client authentication  | **`Off`** (Public client)           | Prevents `unauthorized_client` — no secret needed |
| Authentication flow    | `Standard flow` + `Direct access`   | Enables browser-based and headless flows        |

**Login settings:**

| Field               | Value                    |
|---------------------|--------------------------|
| Valid redirect URIs | `http://localhost:8000`  |
|                     | `http://localhost:8000/` |

> ⚠️ Enter each URI separately by pressing Enter. Do not separate with spaces.

### 3.2 User Requirements

```
┌─────────────────────────────────────────────┐
│           Keycloak User Checklist            │
├─────────────────────────────────────────────┤
│  ✅  Email address configured                │
│  ✅  Email verified → ON                    │
│       (if OFF → API server returns           │
│        "oidc: email not verified" 401)       │
│  ✅  Password configured                    │
└─────────────────────────────────────────────┘
```

> **Critical:** `--oidc-username-claim=email` strictly requires
> `email_verified: true` in the JWT. If `Off` in Keycloak, every
> authentication attempt silently returns 401.

---

## 4. Kubernetes API Server Configuration

### 4.1 Static Manifest Location

```
/etc/kubernetes/manifests/kube-apiserver.yaml
```

kubelet watches this file and auto-restarts the API server on save (~60s).

### 4.2 OIDC Flags

```yaml
- command:
  - kube-apiserver
  # ... existing flags ...
  - --oidc-issuer-url=https://keycloak.mirecloud.com/auth/realms/mirecloud
  - --oidc-client-id=kubernetes
  - --oidc-username-claim=email
  - --oidc-groups-claim=groups
  - --oidc-ca-file=/etc/kubernetes/pki/keycloak-ca.crt
```

### 4.3 Flag Reference

| Flag                    | Value                          | Purpose                                          |
|-------------------------|--------------------------------|--------------------------------------------------|
| `--oidc-issuer-url`     | `https://keycloak.../mirecloud`| Must match `issuer` in `/.well-known/openid-configuration` exactly |
| `--oidc-client-id`      | `kubernetes`                   | Must match Keycloak client ID exactly            |
| `--oidc-username-claim` | `email`                        | JWT claim mapped to Kubernetes username          |
| `--oidc-groups-claim`   | `groups`                       | JWT claim mapped to Kubernetes groups            |
| `--oidc-ca-file`        | `/etc/kubernetes/pki/...`      | CA that signed Keycloak's TLS certificate        |

### 4.4 ⚠️ Critical YAML Trap — Inline Comments

```yaml
# ❌ WRONG — inline comment corrupts the flag value
- --oidc-issuer-url=https://keycloak.mirecloud.com/auth/realms/mirecloud  # issuer

# ✅ CORRECT — comment on its own line
# Keycloak issuer URL
- --oidc-issuer-url=https://keycloak.mirecloud.com/auth/realms/mirecloud
```

Kubernetes includes trailing whitespace + comment text as part of the flag value,
causing silent 401 errors that are extremely hard to diagnose.

### 4.5 Verify the Issuer URL (with or without `/auth/`)

```bash
# Always verify before setting the flag:
wget --ca-certificate=/etc/kubernetes/pki/keycloak-ca.crt -qO- \
  https://keycloak.mirecloud.com/auth/realms/mirecloud/.well-known/openid-configuration \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['issuer'])"

# Output must be character-for-character identical to --oidc-issuer-url
```

---

## 5. kubectl & kubelogin Setup

### 5.1 Clean Previous Cache

```bash
kubectl oidc-login clean
# dbus-launch error on headless server = normal and harmless
```

### 5.2 Configure the OIDC Credential

```bash
kubectl config set-credentials oidc-user \
  --exec-api-version=client.authentication.k8s.io/v1beta1 \
  --exec-command=kubectl \
  --exec-arg=oidc-login \
  --exec-arg=get-token \
  --exec-arg=--oidc-issuer-url=https://keycloak.mirecloud.com/auth/realms/mirecloud \
  --exec-arg=--oidc-client-id=kubernetes \
  --exec-arg=--insecure-skip-tls-verify
```

### 5.3 Create and Activate the Context

```bash
kubectl config set-context oidc-context --cluster=kubernetes --user=oidc-user
kubectl config use-context oidc-context
```

### 5.4 Resulting kubeconfig Structure

```
~/.kube/config
├── clusters
│   └── kubernetes  (server: https://192.168.2.75:6443)
├── users
│   ├── kubernetes-admin  ← X.509 cert (emergency/admin access)
│   └── oidc-user         ← exec: kubectl oidc-login get-token
└── contexts
    ├── kubernetes-admin@kubernetes
    └── oidc-context  ◄── ACTIVE
```

---

## 6. Headless Server — SSH Tunnel + Live Demo

### 6.1 The Problem

```
  node-4 (headless server)       Keycloak
         │                           │
         │── kubelogin ──────────────►│
         │◄── redirect to ───────────│
         │    localhost:8000         │
         │                           │
         │   ❌ No browser!           │
         │   Cannot complete flow    │
```

### 6.2 The Solution — SSH Port Forwarding

```
Windows PC (browser)      node-4 (server)         Keycloak
        │                       │                      │
        │  ssh -L 8000:localhost:8000 root@192.168.2.75 │
        │◄──────────────────────┤                      │
        │   (tunnel established)│                      │
        │                       │                      │
        │                       │─ kubectl get nodes ──►│
        │                       │                      │
        │◄── Manual URL printed │                      │
        │    http://localhost:8000/?state=...           │
        │                       │                      │
        │─ Open in browser ─────────────────────────────►
        │                       │                      │
        │  ┌───────────────────────────────────────┐   │
        │  │        MIRECLOUD                      │   │
        │  │  ┌─────────────────────────────────┐  │   │
        │  │  │  Sign in to your account        │  │   │
        │  │  │                                 │  │   │
        │  │  │  Username or email: [_________] │  │   │
        │  │  │  Password:          [_________] │  │   │
        │  │  │                                 │  │   │
        │  │  │         [ Sign In ]             │  │   │
        │  └──┴─────────────────────────────────┴──┘   │
        │                       │                      │
        │── ✅ Authenticated ──►│                      │
        │   (callback via       │                      │
        │    SSH tunnel)        │◄── JWT token ────────│
        │                       │                      │
        │                       │─── 200 OK ───────────►
```

### 6.3 Step-by-Step Procedure

**Step 1 — On your Windows PC, open a terminal:**

```bash
ssh -L 8000:localhost:8000 root@192.168.2.75
# Leave this terminal open in the background
```

**Step 2 — On node-4, run:**

```bash
kubectl get nodes
```

**Step 3 — The terminal on node-4 prints:**

```
error: could not open the browser: exec: "xdg-open,x-www-browser,www-browser":
       executable file not found in $PATH
Please visit the following URL in your browser manually: http://localhost:8000/
```

> The browser error is **expected and harmless** on a headless server.
> The command is now waiting for you to authenticate.

**Step 4 — Copy the URL and paste it in your Windows PC browser.**

You will land on the Keycloak login page:

```
┌──────────────────────────────────────────┐
│             MIRECLOUD                    │
│                                          │
│   Sign in to your account               │
│                                          │
│   Username or email  [ info@mirecloud ] │
│   Password           [ ************** ] │
│                                          │
│              [ Sign In ]                 │
└──────────────────────────────────────────┘
```

**Step 5 — Enter your Keycloak credentials and click Sign In.**

The browser will show `Authenticated` and the terminal on node-4 immediately
unblocks and displays the result:

```
root@node-4:~# kubectl get nodes
error: could not open the browser: exec: "xdg-open,x-www-browser,www-browser":
       executable file not found in $PATH
Please visit the following URL in your browser manually: http://localhost:8000/

NAME     STATUS   ROLES           AGE   VERSION
node-2   Ready    <none>          23d   v1.34.2
node-3   Ready    <none>          23d   v1.34.2
node-4   Ready    control-plane   23d   v1.34.2

root@node-4:~#
```

> 🔐 **This is SSO in action.** Maximum security in the background,
> seamless experience for the user. The token is cached locally —
> subsequent `kubectl` commands will not prompt for login until the
> token expires.

---

## 7. Verification & Testing

### 7.1 API Server OIDC Flags

```bash
kubectl get pod -n kube-system kube-apiserver-node-4 -o yaml | grep '\-\-oidc'
```

Expected:
```
- --oidc-issuer-url=https://keycloak.mirecloud.com/auth/realms/mirecloud
- --oidc-client-id=kubernetes
- --oidc-username-claim=email
- --oidc-groups-claim=groups
- --oidc-ca-file=/etc/kubernetes/pki/keycloak-ca.crt
```

### 7.2 Keycloak TLS Certificate

```bash
openssl s_client -connect keycloak.mirecloud.com:443 \
  -CAfile /etc/kubernetes/pki/keycloak-ca.crt </dev/null 2>&1 \
  | grep 'Verify return code'
# Expected: Verify return code: 0 (ok)
```

### 7.3 Keycloak Discovery Endpoint

```bash
wget --ca-certificate=/etc/kubernetes/pki/keycloak-ca.crt -qO- \
  https://keycloak.mirecloud.com/auth/realms/mirecloud/.well-known/openid-configuration \
  | python3 -m json.tool | grep '"issuer"'
```

### 7.4 RBAC Binding

```bash
kubectl get clusterrolebinding oidc-admin-binding -o yaml
```

Expected:
```yaml
subjects:
- kind: User
  name: info@mirecloud.com   # matches --oidc-username-claim=email
roleRef:
  kind: ClusterRole
  name: cluster-admin
```

### 7.5 API Server Logs

```bash
kubectl logs -n kube-system kube-apiserver-node-4 --tail=50 \
  | grep -iE 'oidc|email|401|unauthorized'
# Healthy state → no output
```

### 7.6 End-to-End Checklist

```
┌──────────────────────────────────────────────────────────────┐
│                  OIDC End-to-End Checklist                    │
├──────────────────────────────────────────────────────────────┤
│  [ ] keycloak-ca.crt present at /etc/kubernetes/pki/         │
│  [ ] TLS verify returns code 0 (ok)                          │
│  [ ] /.well-known/openid-configuration reachable             │
│  [ ] issuer URL identical in discovery doc & apiserver flag  │
│  [ ] No inline YAML comments on OIDC flags                   │
│  [ ] Keycloak client: Public (Client authentication Off)     │
│  [ ] Redirect URI: http://localhost:8000 (no spaces)         │
│  [ ] User Email verified: On                                 │
│  [ ] ClusterRoleBinding exists for OIDC user                 │
│  [ ] kubelogin installed (kubectl oidc-login version)        │
│  [ ] SSH tunnel open on port 8000 (headless server only)     │
│  [ ] kubectl get nodes → returns list  ✅                    │
└──────────────────────────────────────────────────────────────┘
```

---

## 8. Troubleshooting Reference

| Symptom / Error | Root Cause | Fix |
|:---|:---|:---|
| `lookup keycloak... no such host` | Node cannot resolve `keycloak.mirecloud.com` | Add `192.168.2.204 keycloak.mirecloud.com` to `/etc/hosts` |
| `Resource not found` on issuer URL | Wrong path — missing or extra `/auth/` | Check `/.well-known/openid-configuration` and align with `--oidc-issuer-url` |
| `A redirect URI is not a valid URI` | Spaces between URIs in Keycloak | Enter `http://localhost:8000` and press Enter for each URI |
| `unauthorized_client` | Client has a secret (confidential mode) | Set **Client authentication → Off** in Keycloak |
| `state does not match` | Corrupted token cache from multiple attempts | Close all browser tabs and run `kubectl oidc-login clean` |
| Silent 401 Unauthorized | Inline comment in `kube-apiserver.yaml` corrupts flag, or CA file missing | Remove all inline comments. Verify CA file path. |
| `oidc: email not verified` | `email_verified: false` in JWT | Set **Email verified → On** in the Keycloak user profile |
| `xdg-open: not found` | Headless server — no graphical environment | Expected and harmless — use the SSH tunnel method (Section 6) |
| Token works once then 401 | Token expired, not refreshing | Ensure `interactiveMode: IfAvailable` in kubeconfig exec block |

---

## Appendix — DNS on Cluster Nodes

```bash
# Add static entry on each node
echo "192.168.2.204 keycloak.mirecloud.com" >> /etc/hosts

# Verify
nc -zv keycloak.mirecloud.com 443
# Expected: Connection to keycloak.mirecloud.com 443 port succeeded!
```

---

*Validated on cluster `mirecloud` — Kubernetes v1.34.2 · Keycloak Quarkus · kubelogin v1.35.2*
```

---

Voilà ! La section **6 (Headless Server)** montre maintenant le flow complet avec :
- Le tunnel SSH
- La page de login Keycloak en ASCII (`MIRECLOUD / Sign in to your account`)
- L'exact output terminal que tu as eu, avec le message `xdg-open not found` suivi du résultat des nodes
- La note sur le **token cache** (pas besoin de se re-logger avant l'expiration)

Tu veux que je le sauvegarde quelque part sur le cluster ?
