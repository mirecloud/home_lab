# Résolution du problème Helm avec GatewayClass Cilium

## Contexte

Lors de l'activation de Gateway API avec Cilium, le déploiement Helm a échoué avec l'erreur suivante :

```bash
Error: UPGRADE FAILED: unable to continue with update:

GatewayClass "cilium" in namespace "" exists and cannot be imported into the current release:

invalid ownership metadata;

label validation error:
missing key "app.kubernetes.io/managed-by": must be set to "Helm";

annotation validation error:
missing key "meta.helm.sh/release-name": must be set to "cilium";

annotation validation error:
missing key "meta.helm.sh/release-namespace": must be set to "kube-system"
```

## Cause

Le contrôleur Cilium avait déjà créé la ressource :

```bash
GatewayClass/cilium
```

Cependant, cette ressource n'était pas gérée par Helm.

Lorsque Helm a tenté de mettre à jour le chart Cilium avec :

```bash
helm upgrade cilium cilium/cilium \
  --namespace kube-system \
  --values home_lab/cil-val-1.yaml
```

Helm a détecté que la ressource existait déjà mais ne possédait pas les métadonnées de propriété nécessaires.

Par mesure de sécurité, Helm refuse de prendre le contrôle d'une ressource qu'il ne possède pas.

---

## Vérification

Vérifier l'existence du GatewayClass :

```bash
kubectl get gatewayclass
```

Résultat :

```bash
NAME     CONTROLLER
cilium   io.cilium/gateway-controller
```

Vérifier les métadonnées :

```bash
kubectl get gatewayclass cilium -o yaml
```

Absence des champs :

```yaml
app.kubernetes.io/managed-by: Helm

meta.helm.sh/release-name: cilium

meta.helm.sh/release-namespace: kube-system
```

---

## Solution

Adopter manuellement la ressource dans Helm.

### Ajouter le label Helm

```bash
kubectl label gatewayclass cilium \
  app.kubernetes.io/managed-by=Helm \
  --overwrite
```

### Ajouter les annotations Helm

```bash
kubectl annotate gatewayclass cilium \
  meta.helm.sh/release-name=cilium \
  --overwrite
```

```bash
kubectl annotate gatewayclass cilium \
  meta.helm.sh/release-namespace=kube-system \
  --overwrite
```

---

## Validation

Vérifier que les métadonnées sont présentes :

```bash
kubectl get gatewayclass cilium -o yaml
```

Résultat attendu :

```yaml
labels:
  app.kubernetes.io/managed-by: Helm

annotations:
  meta.helm.sh/release-name: cilium
  meta.helm.sh/release-namespace: kube-system
```

---

## Relancer Helm

```bash
helm upgrade cilium cilium/cilium \
  --namespace kube-system \
  --values home_lab/cil-val-1.yaml
```

Résultat :

```bash
Release "cilium" has been upgraded.
STATUS: deployed
```

---

# Validation Gateway API

Vérifier le GatewayClass :

```bash
kubectl get gatewayclass
```

Résultat attendu :

```bash
NAME     CONTROLLER                     ACCEPTED
cilium   io.cilium/gateway-controller   True
```

Détails :

```bash
kubectl describe gatewayclass cilium
```

Résultat :

```text
Status:
  Conditions:
    Type: Accepted
    Status: True
    Reason: Accepted
    Message: Valid GatewayClass
```

---

# Redémarrage du contrôleur Gateway API

Après activation de Gateway API :

```bash
kubectl -n kube-system rollout restart deployment/cilium-operator

kubectl -n kube-system rollout restart daemonset/cilium
```

Validation :

```bash
kubectl get gatewayclass
```

Résultat :

```text
ACCEPTED=True
```

---

# Vérification Hubble

Vérifier la configuration :

```bash
kubectl -n kube-system get cm cilium-config -o yaml | grep hubble
```

Vérifier les flows :

```bash
kubectl -n kube-system logs ds/cilium \
  -c cilium-agent \
  -f
```

Exemple observé :

```json
{
  "source":"coredns",
  "destination":"4.4.4.4",
  "destination_port":53,
  "verdict":"FORWARDED"
}
```

Cela confirme que :

* Hubble fonctionne
* L'export JSON fonctionne
* Les flux réseau sont observables
* Les logs peuvent être envoyés vers Loki via Promtail ou Grafana Alloy

---

# Leçons apprises

1. GatewayClass peut exister avant Helm.
2. Helm refuse de gérer une ressource qu'il ne possède pas.
3. L'adoption via labels/annotations Helm est une méthode supportée.
4. Après activation de Gateway API, un redémarrage de Cilium est souvent nécessaire.
5. Toujours documenter les ressources adoptées manuellement afin d'éviter des problèmes lors des futures mises à jour.
