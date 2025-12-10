
#  MireCloud PKI & Wildcard Certificate Guide

This document provides a fully professional, production‑grade workflow to build your own **Certificate Authority (CA)** and generate a **wildcard TLS certificate** for `*.mirecloud.com`.

---

#  PART 1 — Create Your Certification Authority (CA)

##  Workspace
```bash
mkdir -p ~/mirecloud-ca
cd ~/mirecloud-ca
```

##  1. Generate the CA Private Key
```bash
openssl genrsa -out mirecloud-ca.key 4096
```

## 🏛️ 2. Generate the Root CA Certificate
```bash
openssl req -x509 -new -nodes   -key mirecloud-ca.key   -sha256   -days 3650   -subj "/C=CA/ST=Quebec/L=Terrebonne/O=MireCloud/OU=CA/CN=MireCloud Root CA"   -out mirecloud-ca.crt
```

Your CA is valid for **10 years**.

---

#  PART 2 — Create the Wildcard Certificate `*.mirecloud.com`

We will generate:

- a private key  
- a Certificate Signing Request (CSR)  
- a certificate signed by your local CA  
- SAN (Subject Alternative Name) support

---

##  1. Generate the Wildcard Private Key
```bash
openssl genrsa -out wildcard.mirecloud.com.key 4096
```

---

##  2. Create the SAN Extension File

Create a file named **`wildcard.ext`**:

```
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage=serverAuth,clientAuth
subjectAltName = @alt_names

[alt_names]
DNS.1 = *.mirecloud.com
DNS.2 = mirecloud.com
```

---

##  3. Generate the Wildcard CSR
```bash
openssl req -new   -key wildcard.mirecloud.com.key   -subj "/C=CA/ST=Quebec/L=Terrebonne/O=MireCloud/OU=IT/CN=*.mirecloud.com"   -out wildcard.mirecloud.com.csr
```

---

##  4. Sign the Certificate With Your CA
```bash
openssl x509 -req   -in wildcard.mirecloud.com.csr   -CA mirecloud-ca.crt -CAkey mirecloud-ca.key -CAcreateserial   -out wildcard.mirecloud.com.crt   -days 825 -sha256   -extfile wildcard.ext
```

 Your wildcard certificate is valid for **825 days**, the maximum allowed by Chrome.

---

#  PART 3 — Folder Structure Summary

Your folder should now look like this:

```
~/mirecloud-ca/
│
├── mirecloud-ca.key               # CA private key (KEEP SECRET)
├── mirecloud-ca.crt               # CA certificate (distribute this)
├── mirecloud-ca.srl               # Serial number tracking
│
├── wildcard.mirecloud.com.key     # Wildcard private key
├── wildcard.mirecloud.com.csr     # Wildcard CSR
├── wildcard.mirecloud.com.crt     # Signed wildcard certificate
├── wildcard.ext                   # SAN extension file
```

---

#  I AM Now Running Your Own PKI

This PKI enables:

- Kubernetes TLS secrets  
- NGINX Ingress TLS  
- Keycloak HTTPS  
- Grafana HTTPS  
- GitLab HTTPS  
- Internal microservices authentication  



---

##  MireCloud — Secure Everything. Everywhere.
