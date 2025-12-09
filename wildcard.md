🚀 PARTIE 1 — Créer ton CA (Autorité de Certification)
📌 Dossier de travail
mkdir -p ~/mirecloud-ca
cd ~/mirecloud-ca

📌 1. Générer la clé privée de ta CA
openssl genrsa -out mirecloud-ca.key 4096

📌 2. Générer le certificat Root CA
openssl req -x509 -new -nodes -key mirecloud-ca.key \
  -sha256 -days 3650 \
  -subj "/C=CA/ST=Quebec/L=Terrebonne/O=MireCloud/OU=CA/CN=MireCloud Root CA" \
  -out mirecloud-ca.crt


Ton CA valide 10 ans.

🚀 PARTIE 2 — Créer le wildcard *.mirecloud.com

On va créer :

une clé privée

une CSR

un certificat signé par ta CA

avec SAN wildcard

📌 1. Créer la clé privée du wildcard
openssl genrsa -out wildcard.mirecloud.com.key 4096

📌 2. Créer le fichier d’extension SAN

Crée wildcard.ext :

authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage=serverAuth,clientAuth
subjectAltName = @alt_names

[alt_names]
DNS.1 = *.mirecloud.com
DNS.2 = mirecloud.com

📌 3. Générer la CSR
openssl req -new -key wildcard.mirecloud.com.key \
  -subj "/C=CA/ST=Quebec/L=Terrebonne/O=MireCloud/OU=IT/CN=*.mirecloud.com" \
  -out wildcard.mirecloud.com.csr

📌 4. Signer le certificat avec ta CA
openssl x509 -req \
  -in wildcard.mirecloud.com.csr \
  -CA mirecloud-ca.crt -CAkey mirecloud-ca.key -CAcreateserial \
  -out wildcard.mirecloud.com.crt \
  -days 825 -sha256 -extfile wildcard.ext


Ton wildcard est valide 2 ans (825 jours, limite Chrome).

🚀 PARTIE 3 — Structure finale des fichiers
~/mirecloud-ca/
│
├── mirecloud-ca.key                    # clé privée CA (garder secrète)
├── mirecloud-ca.crt                    # certificat CA (à distribuer)
├── mirecloud-ca.srl
│
├── wildcard.mirecloud.com.key          # clé privée du wildcard
├── wildcard.mirecloud.com.csr
├── wildcard.mirecloud.com.crt          # cert wildcard signé
├── wildcard.ext

