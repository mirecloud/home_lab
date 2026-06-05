# GitLab + Vault PKI + VS Code Integration Guide

## Overview

This guide documents the complete process used to replace a self-signed GitLab certificate with a Vault PKI certificate, trust the CA on Windows, and connect GitLab successfully to VS Code.

---

## Initial Problem

GitLab was serving a self-signed certificate:

```bash
issuer=CN = gitlab.mirecloud.com
subject=CN = gitlab.mirecloud.com
```

Resulting errors:

```text
self signed certificate
SEC_E_UNTRUSTED_ROOT
```

---

## Verify Current GitLab Certificate

```bash
openssl s_client -connect localhost:443 -servername gitlab.mirecloud.com -showcerts
```

If you see:

```text
Verification error: self-signed certificate
issuer=CN = gitlab.mirecloud.com
```

the certificate is not signed by Vault.

---

## Enable Vault PKI

```bash
kubectl -n vault exec -it vault-0 -- sh
vault login
```

Check secret engines:

```bash
vault secrets list
```

Enable PKI:

```bash
vault secrets enable -path=pki_int pki
vault secrets tune -max-lease-ttl=8760h pki_int
```

Create Root CA:

```bash
vault write pki_int/root/generate/internal \
  common_name="MireCloud Root CA" \
  ttl=8760h
```

---

## Create PKI Role

```bash
vault write pki_int/roles/mirecloud-dot-com \
  allowed_domains="mirecloud.com" \
  allow_subdomains=true \
  max_ttl="720h"
```

Generate GitLab Certificate:

```bash
vault write pki_int/issue/mirecloud-dot-com \
  common_name="gitlab.mirecloud.com" \
  alt_names="gitlab.mirecloud.com" \
  ttl="720h"
```

Vault returns:

- certificate
- private_key
- issuing_ca

---

## Backup Existing GitLab Certificates

```bash
sudo cp /etc/gitlab/ssl/gitlab.mirecloud.com.crt \
  /etc/gitlab/ssl/gitlab.mirecloud.com.crt.bak

sudo cp /etc/gitlab/ssl/gitlab.mirecloud.com.key \
  /etc/gitlab/ssl/gitlab.mirecloud.com.key.bak
```

---

## Install Vault Certificate

### Certificate File

`/etc/gitlab/ssl/gitlab.mirecloud.com.crt`

Must contain:

```text
-----BEGIN CERTIFICATE-----
GitLab Certificate
-----END CERTIFICATE-----

-----BEGIN CERTIFICATE-----
Vault Issuing CA
-----END CERTIFICATE-----
```

### Private Key

`/etc/gitlab/ssl/gitlab.mirecloud.com.key`

```text
-----BEGIN RSA PRIVATE KEY-----
...
-----END RSA PRIVATE KEY-----
```

---

## Fix PEM Formatting Errors

If GitLab reports:

```text
PEM_read_bio_X509: no start line
```

Remove leading spaces:

```bash
sudo sed -i 's/^[[:space:]]*-----BEGIN CERTIFICATE-----/-----BEGIN CERTIFICATE-----/' \
/etc/gitlab/ssl/gitlab.mirecloud.com.crt

sudo sed -i 's/^[[:space:]]*-----END CERTIFICATE-----/-----END CERTIFICATE-----/' \
/etc/gitlab/ssl/gitlab.mirecloud.com.crt
```

---

## Permissions

```bash
sudo chmod 644 /etc/gitlab/ssl/gitlab.mirecloud.com.crt
sudo chmod 600 /etc/gitlab/ssl/gitlab.mirecloud.com.key
sudo chown root:root /etc/gitlab/ssl/gitlab.mirecloud.com.*
```

---

## Reconfigure GitLab

```bash
sudo gitlab-ctl reconfigure
sudo gitlab-ctl restart nginx
```

Validate:

```bash
openssl s_client \
-connect localhost:443 \
-servername gitlab.mirecloud.com \
</dev/null 2>/dev/null \
| openssl x509 -noout -issuer -subject
```

Expected:

```text
issuer=CN = MireCloud Root CA
subject=CN = gitlab.mirecloud.com
```

---

## Export Vault Root CA

```bash
vault read -field=certificate pki_int/cert/ca > mirecloud-ca.crt
```

---

## Install CA on Windows

PowerShell (Administrator):

```powershell
Import-Certificate `
-FilePath "C:\Users\emman\OneDrive\Bureau\mirecloud-ca.crt" `
-CertStoreLocation Cert:\LocalMachine\Root
```

Verify:

```powershell
Get-ChildItem Cert:\LocalMachine\Root |
Where-Object {$_.Subject -match "MireCloud"}
```

---

## Test TLS Connectivity

```powershell
curl.exe --ssl-no-revoke https://gitlab.mirecloud.com/api/v4/version
```

Expected:

```json
{"message":"401 Unauthorized"}
```

This confirms:

- DNS works
- TLS works
- Certificate is trusted
- GitLab is responding

---

## Configure CRL / AIA in Vault

```bash
vault write pki_int/config/urls \
  issuing_certificates="https://vault.mirecloud.com/v1/pki_int/ca" \
  crl_distribution_points="https://vault.mirecloud.com/v1/pki_int/crl"
```

Regenerate certificates afterward.

---

## Connect VS Code GitLab Workflow

Add account:

```text
GitLab: Add Account
```

Use:

```text
https://gitlab.mirecloud.com
```

Do NOT use:

```text
https://gitlab.mirecloud.com/admin1/test.git
```

---

## Create Personal Access Token

GitLab:

```text
Avatar
→ Preferences
→ Access Tokens
```

Scopes:

```text
api
read_user
read_repository
write_repository
```

Use:

```text
Username: admin1
Token: Personal Access Token
```

---

## Git Authentication Issues

If push fails:

```text
HTTP Basic: Access denied
```

Remove cached credentials:

```powershell
cmdkey /list | findstr gitlab
cmdkey /delete:git:https://gitlab.mirecloud.com
```

Retry:

```powershell
git push origin main
```

Use:

```text
Username: admin1
Password: Personal Access Token
```

---

## Final State

✅ GitLab certificate signed by Vault PKI

✅ Windows trusts MireCloud Root CA

✅ GitLab API reachable over HTTPS

✅ VS Code GitLab Workflow connected

✅ Git push/pull working with tokens

### Next Improvement

Deploy Vault Agent on the GitLab VM to automate certificate renewal.
