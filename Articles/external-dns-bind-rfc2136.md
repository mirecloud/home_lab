# ExternalDNS sur Kubernetes Homelab — Synchronisation automatique avec BIND via RFC2136

> **Stack :** Kubernetes v1.34 · ExternalDNS v0.20.0 · BIND · RFC2136 · HMAC-SHA256 · Cilium Gateway API · HashiCorp Vault · External Secrets Operator · ArgoCD
> **Date :** 22 février 2026
> **Lab :** MireCloud Home Lab · `*.mirecloud.com`

---

## Le problème

Quand tu gères un homelab Kubernetes avec plusieurs services exposés — Grafana, Keycloak, ArgoCD, PgAdmin — tu te retrouves vite à maintenir manuellement des entrées DNS dans BIND. C'est répétitif, source d'erreurs, et ça ne scale pas.

La solution : **ExternalDNS**. Ce controller Kubernetes surveille tes Services, Ingress et HTTPRoutes en temps réel, et met à jour automatiquement ton serveur DNS dès qu'un nouveau service est exposé. Fini les entrées oubliées.

---

## Architecture du lab

```
┌─────────────────────────────────────────────────────────┐
│                  Kubernetes Cluster                     │
│                                                         │
│   Cilium Gateway API                                    │
│   (grafana, keycloak, pgadmin, argocd...)               │
│           │                                             │
│           ▼                                             │
│   ExternalDNS v0.20.0  (namespace: external-dns)        │
│   sources: service · ingress · gateway-httproute        │
│           │                                             │
│           │  RFC2136 Dynamic DNS Update                 │
│           │  TSIG / HMAC-SHA256                         │
└───────────┼─────────────────────────────────────────────┘
            │
            ▼
  ┌─────────────────────┐
  │  BIND (node-3)      │
  │  192.168.2.74:53    │
  │  zone: mirecloud.com│
  └─────────────────────┘
```

**Nodes du cluster :**

| Node | IP | Rôle |
|------|----|------|
| node-4 | 192.168.2.75 | Control Plane + NFS |
| node-2 | 192.168.2.46 | Worker — Monitoring |
| node-3 | 192.168.2.74 | Worker — **BIND DNS** |

---

## Étape 1 — Configurer BIND pour accepter les Dynamic DNS Updates

Sur `node-3`, BIND doit accepter les mises à jour dynamiques signées avec une clé TSIG.

### Générer la clé TSIG

```bash
tsig-keygen -a hmac-sha256 externaldns-key
```

Résultat :

```
key "externaldns-key" {
    algorithm hmac-sha256;
    secret "VotreCleBase64IciTresLongue==";
};
```

### Configurer named.conf

```
key "externaldns-key" {
    algorithm hmac-sha256;
    secret "VotreCleBase64IciTresLongue==";
};

zone "mirecloud.com" {
    type master;
    file "/var/lib/bind/db.mirecloud.com";
    allow-update { key "externaldns-key"; };
};
```

```bash
systemctl reload named
```

---

## Étape 2 — Stocker la clé TSIG dans Vault

La clé TSIG ne doit **jamais** être dans Git. On la stocke dans HashiCorp Vault :

```bash
vault kv put secret/dns/rfc2136 \
  tsig-secret="VotreCleBase64IciTresLongue=="
```

---

## Étape 3 — Injecter la clé via External Secrets Operator

ESO crée automatiquement le Secret Kubernetes depuis Vault :

```yaml
# infrastructure/external-dns/templates/external-secret.yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: external-dns-bind-secret
  namespace: external-dns
spec:
  refreshInterval: 1m
  secretStoreRef:
    name: vault-backend
    kind: ClusterSecretStore
  target:
    name: rfc2136-tsig-secret
    creationPolicy: Owner
  data:
    - secretKey: tsig-secret
      remoteRef:
        key: secret/dns/rfc2136
        property: tsig-secret
```

Zero secret dans Git. ESO synchronise depuis Vault toutes les minutes.

---

## Étape 4 — Déployer ExternalDNS via Helm

### Chart.yaml

```yaml
apiVersion: v2
name: external-dns
version: 1.0.0
dependencies:
  - name: external-dns
    version: 1.20.0
    repository: https://kubernetes-sigs.github.io/external-dns/
```

### values.yaml

```yaml
external-dns:
  logLevel: info
  logFormat: text
  interval: 1m

  sources:
    - service
    - ingress
    - gateway-httproute        # Support Cilium Gateway API

  policy: sync                 # Crée ET supprime les entrées DNS
  registry: txt                # Garde la trace via enregistrements TXT
  domainFilters:
    - mirecloud.com

  provider: rfc2136

  extraArgs:
    - --rfc2136-host=192.168.2.74
    - --rfc2136-port=53
    - --rfc2136-zone=mirecloud.com
    - --rfc2136-tsig-keyname=externaldns-key
    - --rfc2136-tsig-axfr
    - --rfc2136-tsig-secret-alg=hmac-sha256

  env:
    - name: EXTERNAL_DNS_RFC2136_TSIG_SECRET
      valueFrom:
        secretKeyRef:
          name: rfc2136-tsig-secret
          key: tsig-secret

  securityContext:
    runAsNonRoot: true
    runAsUser: 65532
    runAsGroup: 65532
    fsGroup: 65534
    readOnlyRootFilesystem: true
    allowPrivilegeEscalation: false
    capabilities:
      drop: ["ALL"]
    seccompProfile:
      type: RuntimeDefault
```

---

## Étape 5 — Application ArgoCD

```yaml
# clusters/home-lab/external-dns-app.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: external-dns
  namespace: argocd
spec:
  project: default
  source:
    repoURL: "git@github.com:mirecloud/home_lab.git"
    targetRevision: HEAD
    path: infrastructure/external-dns
  destination:
    server: https://kubernetes.default.svc
    namespace: external-dns
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

Un `git push` suffit. ArgoCD déploie ExternalDNS sans aucune intervention manuelle.

---

## Étape 6 — Test en conditions réelles

Voici le manifeste de test complet pour valider le setup : Certificate → Gateway → HTTPRoute → DNS.

```yaml
# test-route-external-dns.yaml

# 1. Certificat TLS via cert-manager
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: testexternal-tls-cert
  namespace: default
spec:
  secretName: externaldns-tls-secret
  issuerRef:
    name: mirecloud-ca-issuer
    kind: ClusterIssuer
  commonName: testexternal.mirecloud.com
  dnsNames:
    - testexternal.mirecloud.com
---
# 2. Cilium Gateway (point d'entrée L4)
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: externaldns-gateway
  namespace: default
spec:
  gatewayClassName: cilium
  listeners:
    - name: http
      protocol: HTTP
      port: 80
      allowedRoutes:
        namespaces:
          from: Same
    - name: https
      protocol: HTTPS
      port: 443
      tls:
        mode: Terminate
        certificateRefs:
          - kind: Secret
            name: externaldns-tls-secret
      allowedRoutes:
        namespaces:
          from: Same
---
# 3. HTTPRoute (routing L7)
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: externaldns-route
  namespace: default
spec:
  parentRefs:
    - name: externaldns-gateway
  hostnames:
    - "testexternal.mirecloud.com"
  rules:
    - matches:
        - path:
            type: PathPrefix
            value: /
      backendRefs:
        - name: kubernetes
          port: 443
```

```bash
kubectl apply -f test-route-external-dns.yaml
```

### Résultat — Zone BIND mise à jour automatiquement

En moins d'une minute, la zone `/var/lib/bind/db.mirecloud.com` sur `node-3` affichait :

```dns
; Enregistrement A créé automatiquement par ExternalDNS
testexternal    A       192.168.2.206

; Enregistrement TXT de tracking (ownership)
a-testexternal  TXT     "heritage=external-dns,external-dns/owner=default,\
                          external-dns/resource=httproute/default/externaldns-route"
```

Zone complète gérée par ExternalDNS :

```dns
$ORIGIN mirecloud.com.
argocd          A   192.168.2.201
grafana         A   192.168.2.205
keycloak        A   192.168.2.204
pgadmin         A   192.168.2.202
testexternal    A   192.168.2.206   ← ajouté automatiquement en < 1 min
```

### Logs ExternalDNS

```
time="2026-02-22T18:53:32Z" level=info msg="All records are already up to date"
```

ExternalDNS confirme la synchronisation toutes les 60 secondes. Quand un nouveau service est détecté, tu verras :

```
time="2026-02-22T03:05:12Z" level=info msg="Updating A record in zone mirecloud.com"
time="2026-02-22T03:05:12Z" level=info msg="Updating TXT record in zone mirecloud.com"
```

---

## Le flow complet — de git push au DNS

```
1. git push  →  ArgoCD détecte le changement
2. ArgoCD applique Gateway + HTTPRoute dans le cluster
3. Cilium Gateway API assigne une IP externe (192.168.2.206)
4. ExternalDNS détecte le HTTPRoute (source: gateway-httproute)
5. ExternalDNS envoie RFC2136 Dynamic Update signé TSIG → BIND
6. BIND crée l'enregistrement A dans la zone mirecloud.com
7. BIND crée un TXT de tracking pour ExternalDNS
8. testexternal.mirecloud.com → 192.168.2.206 ✓

Durée totale : < 60 secondes
```

Si tu supprimes le HTTPRoute, ExternalDNS supprime aussi l'entrée DNS. La politique `sync` garantit que le DNS reflète toujours l'état réel du cluster.

---

## Sécurité

| Aspect | Implémentation |
|--------|----------------|
| Clé TSIG | Stockée dans HashiCorp Vault · jamais dans Git |
| Injection | External Secrets Operator → Secret K8s · refresh 1m |
| Algorithme | HMAC-SHA256 |
| Container | `runAsNonRoot` · `readOnlyRootFilesystem` · no capabilities |
| Scope DNS | Filtré sur `mirecloud.com` uniquement |
| Updates BIND | Autorisés uniquement avec la clé TSIG |

---

## Conclusion

ExternalDNS + BIND + RFC2136 + Vault + ArgoCD = **DNS as Code**.

Plus jamais d'entrée DNS oubliée. Plus jamais de divergence entre ce qui tourne dans le cluster et ce qui est déclaré dans BIND. Le DNS suit automatiquement l'état du cluster, dans les deux sens — création et suppression.

C'est exactement ce genre d'automatisation qui fait la différence entre un homelab bricolé et une infrastructure qui ressemble à une vraie prod.

---

*Repo : [github.com/mirecloud/home_lab](https://github.com/mirecloud/home_lab)*
