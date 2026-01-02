# HomeLab Integration Guide: GitLab, Keycloak & Vault

This document describes the **validated and functional reference architecture** used to deploy the MireCloud application stack on Kubernetes.

**Status:**  Operational  
**Domain:** `*.mirecloud.com`  
**Core Components:** GitLab (CE), Keycloak (SSO/OIDC), Vault (Secrets), Grafana (Monitoring)

---

## 1. Architecture Overview & Data Flows

### Secrets Management
- **Vault** is the single source of truth for sensitive configuration (OIDC, database credentials).
- **External Secrets Operator (ESO)** synchronizes Vault secrets into Kubernetes-native `Secret` objects.

### Identity & Access Management
- **Keycloak** acts as the central Identity Provider (IdP).
- **OIDC** is used for authentication and SSO across applications.

### Database Layer
- External **PostgreSQL** cluster (CNPG) shared by platform services.
- GitLab uses PostgreSQL exclusively in external mode.

### Networking & TLS
- **NGINX Ingress Controller** handles north-south traffic.
- **cert-manager** issues TLS certificates using an internal Certificate Authority.
- TLS is terminated at the ingress level.

---

## 2. Keycloak Configuration (Identity Provider)

### Base URL
The detected base URL for this deployment is:

```
https://keycloak.mirecloud.com/auth/
```

> Note: This deployment uses the **legacy `/auth` path**.

---

### GitLab OIDC Client Configuration

| Setting | Value |
|------|------|
| Client ID | `gitlab` |
| Client Authentication | Enabled |
| Client Type | Confidential |

#### Enabled Authentication Flows
-  **Standard Flow** (mandatory for web login)
-  **Direct Access Grants**

#### Valid Redirect URI
```
https://gitlab.mirecloud.com/users/auth/openid_connect/callback
```

---

## 3. Vault Configuration (Secrets Backend)

Complex configuration data (multi-line YAML) is stored in Vault using a **copy-and-load** approach to prevent formatting errors.

### GitLab OIDC Secret

- **Vault Path:** `secret/gitlab/oidc`
- **Key:** `provider`

This secret defines the complete OmniAuth OIDC configuration consumed by GitLab.

> Design choice:
> - OIDC discovery is explicitly disabled (`discovery: false`)
> - Explicit endpoints are defined to avoid internal DNS and SSL trust issues
> - `/auth` paths are required for Keycloak compatibility
> - SSL verification is disabled for internal CA constraints

#### Stored YAML Configuration

```yaml
name: openid_connect
label: Keycloak
icon: https://www.keycloak.org/resources/images/keycloak_logo_480x108.png
args:
  name: openid_connect
  scope:
    - openid
    - profile
    - email
  response_type: code
  issuer: https://keycloak.mirecloud.com/auth/realms/mirecloud
  discovery: false
  client_auth_method: query
  uid_field: preferred_username
  send_scope_to_token_endpoint: "false"
  client_options:
    identifier: gitlab
    secret: <KEYCLOAK_CLIENT_SECRET>
    redirect_uri: https://gitlab.mirecloud.com/users/auth/openid_connect/callback
    authorization_endpoint: https://keycloak.mirecloud.com/auth/realms/mirecloud/protocol/openid-connect/auth
    token_endpoint: https://keycloak.mirecloud.com/auth/realms/mirecloud/protocol/openid-connect/token
    userinfo_endpoint: https://keycloak.mirecloud.com/auth/realms/mirecloud/protocol/openid-connect/userinfo
    jwks_uri: https://keycloak.mirecloud.com/auth/realms/mirecloud/protocol/openid-connect/certs
    connection_opts:
      ssl:
        verify: false
```

---

## 4. GitLab Deployment Configuration (`values.yaml`)

The following configuration reflects a **HomeLab-optimized GitLab deployment**, with unnecessary embedded services disabled and external dependencies enforced.

```yaml
gitlab:
  upgradeCheck:
    enabled: false

  global:
    common:
      check: false
    edition: ce

    hosts:
      domain: mirecloud.com
      https: true

    appConfig:
      omniauth:
        enabled: true
        autoLinkUser:
          - openid_connect
        allowSingleSignOn:
          - openid_connect
        blockAutoCreatedUsers: false
        providers:
          - secret: gitlab-oidc-config
            key: provider

    ingress:
      configureCertmanager: false
      class: nginx
      annotations:
        cert-manager.io/cluster-issuer: mirecloud-ca-issuer
      tls:
        enabled: true
        secretName: gitlab-tls

    psql:
      host: postgres.postgres.svc
      port: 5432
      username: postgres
      database: gitlab
      password:
        useSecret: true
        secret: gitlab-postgresql-password
        key: postgres-password

  postgresql:
    install: false

  gitlab-runner:
    install: false
```

---

## 5. Resulting Platform State

- GitLab authenticates users exclusively through Keycloak (OIDC).
- Secrets are never committed to Git.
- Vault acts as the single source of truth.
- TLS is enforced end-to-end.
- The architecture is reproducible, GitOps-compliant, and suitable for advanced HomeLab or small enterprise environments.

---

## 6. Summary

This configuration represents a **stable and validated reference implementation** for:
- Secure GitLab deployments on Kubernetes
- Centralized identity management with Keycloak
- Secret lifecycle management using Vault
- Internal PKI-backed TLS with cert-manager

The platform is production-grade in design, despite operating in a HomeLab context.
