# Déploiement vLLM sur MireCloud — Runbook de debug complet

> Déploiement d'un serveur d'inférence vLLM (production-stack) sur un cluster
> Kubernetes bare-metal, via ArgoCD, sur un node GPU Proxmox (RTX 5060 Ti 16GB,
> Ryzen 5 7600, passthrough PCIe). Session de troubleshooting de bout en bout :
> 9 problèmes distincts, dont une cause racine qui masquait presque tout le reste.

---

## Contexte & architecture

| Élément | Valeur |
|---|---|
| Chart | `vllm-wrapper` (parapluie) → dépendance `vllm-stack` 0.1.11 (production-stack) |
| Déploiement | ArgoCD, source git `mirecloud/home_lab`, path `apps/vllm`, `targetRevision: HEAD` |
| Sync | `sourceType: Helm`, **aucun** `valueFiles`/`values` → utilise `apps/vllm/values.yaml` par défaut |
| Node GPU | VM Proxmox 104 (`k8s-gpu`), RTX 5060 Ti 16GB en passthrough PCIe |
| Stockage | StorageClass `nfs-client` (défaut), `nfs-subdir-external-provisioner`, mode `Immediate` |
| Modèle visé | Mistral-7B-Instruct-v0.3 |

---

## Résumé des problèmes (chronologique)

| # | Symptôme | Cause racine | Fix |
|---|---|---|---|
| 1 | PVC `FailedBinding` — "no storage class is set" | Schéma `pvcStorage` en objet imbriqué au lieu de string + champs frères | Corriger le schéma du chart |
| 2 | (anticipé) OOM au load | fp16 Mistral-7B (~14.5GB) ne tient pas dans 16GB | Modèle FP8 (~7.5GB) |
| 3 | Le fix #1 ne prend pas | values éditées localement mais **pas committées/pushées** | `git commit` + `git push` |
| 4 | Pile de pods `Evicted`, `DiskPressure=True` | Root disk VM trop petit (48G), VG LVM à moitié non-alloué | `lvextend` + `resize2fs` → 97G |
| 5 | Router `CrashLoopBackOff` (Exit 137) | startupProbe trop agressive (~20s vs ~38s de cold start) | Desserrer la startupProbe |
| 6 | (aparté) `cilium connectivity test` : 11 échecs L7 | Problème Cilium séparé (proxy Envoy + direct-routing) | Hors scope, parqué |
| **7** | **storageClass vide + aucun Deployment engine** | **Chart parapluie : values au top-level jamais transmises au subchart** | **Imbriquer sous `vllm-stack:`** |
| 8 | Engine pod `Pending` — Insufficient cpu/memory | VM sous-dimensionné (4 vCPU / 10.7 GiB) + `enabled` non défini | Resize VM + `enabled: true` |
| 9 | `UCX library compiled with avx but CPU does not support it` → SIGSEGV | CPU type Proxmox `x86-64-v2-AES` masque l'AVX | CPU type `host` |

**Le problème #7 était la cause racine.** Les fixes #1, #5 et le `enabled: true` étaient corrects en contenu mais n'ont jamais atteint le subchart tant que l'imbrication n'était pas faite. Ils se sont appliqués *seulement après* #7.

---

## Détail des problèmes

### 1. PVC FailedBinding — schéma `pvcStorage`

**Symptôme** : `no persistent volumes available for this claim and no storage class is set`, PVC `Pending`.

**Diagnostic** : le chart `vllm-stack` attend, sous `modelSpec`, des champs **à plat** :
- `pvcStorage` = une **string** (la taille, ex. `"50Gi"`)
- `pvcAccessMode` = une **liste** (champ frère)
- `storageClass` = la classe (champ frère, **pas** `storageClassName`)

Le fichier utilisait un objet imbriqué `pvcStorage: { enabled, size, accessMode, storageClassName }`. Un map non-vide étant *truthy* en Go template, le PVC se rendait quand même, mais avec `storageClassName: ""` (string vide explicite) → désactive la StorageClass par défaut → FailedBinding.

**Fix** :
```yaml
pvcStorage: "50Gi"
pvcAccessMode:
  - ReadWriteOnce
storageClass: "nfs-client"
```

> Note : `storageClassName` d'un PVC est **immuable**. Le vieux PVC cassé doit être supprimé pour qu'ArgoCD le recrée avec la bonne classe.

---

### 2. Modèle trop gros pour 16GB → FP8

**Diagnostic** : Mistral-7B en fp16 = ~14.5GB de poids seuls. Avec `gpuMemoryUtilization: 0.80` sur 16GB (= 12.8GB de budget), ça ne rentre pas, et même à 0.95 il ne reste rien pour le KV cache.

**Fix** : `RedHatAI/Mistral-7B-Instruct-v0.3-FP8` (~7.5GB, ~50% de mémoire en moins, qualité quasi-fp16, FP8 accéléré nativement par Blackwell). vLLM auto-détecte la quantization depuis le config du modèle (`dtype: auto`, pas de flag à ajouter).

Alternative : AWQ 4-bit (`solidrust/Mistral-7B-Instruct-v0.3-AWQ`, ~4.2GB) avec `extraArgs: ["--quantization","awq_marlin"]`.

---

### 3. Values pas committées/pushées

**Symptôme** : le fix #1 appliqué localement, mais le PVC ressort cassé à l'identique après sync.

**Diagnostic** : ArgoCD sync depuis le **HEAD du repo git distant**, pas depuis le disque local. Dans VSCode, le `M` sur l'onglet/fichier + le badge sur Source Control = fichier modifié **non committé**.

**Fix** :
```bash
git add apps/vllm/values.yaml
git commit -m "..."
git push
```

---

### 4. DiskPressure — eviction storm

**Symptôme** : pods `Evicted` en boucle (`The node had condition: [DiskPressure]`), 15+ pods morts, exit 137.

**Diagnostic** :
- `df -h /` → 48G, 51% utilisé, 23G libres — donc **pas** un manque d'octets au repos (seuil kubelet = 10% libre).
- `df -i /` → inodes à 6% — **pas** les inodes non plus.
- Cause réelle : pics transitoires pendant le pull/extraction de l'image vLLM (~10GB+ décompressée) qui franchissaient le seuil par à-coups.
- `vgs` → **48G de VFree non-alloués dans le VG** (défaut classique de l'installeur Ubuntu Server LVM).

**Fix** (à chaud, sans reboot, sans toucher à Proxmox) :
```bash
sudo lvextend -l +100%FREE /dev/ubuntu-vg/ubuntu-lv
sudo resize2fs /dev/mapper/ubuntu--vg-ubuntu--lv   # -> ~97G
```
Bonus : sur ext4, `resize2fs` augmente aussi le nombre d'inodes.

---

### 5. Router CrashLoopBackOff (Exit 137)

**Symptôme** : startup probe `connection refused` sur `:8000/health`, `Killing ... failed startup probe`, Exit 137.

**Diagnostic** : les **logs** montraient `Application startup complete` + `Uvicorn running on http://0.0.0.0:8000` → l'app démarre bien. `Reason: Error` (pas `OOMKilled`) + Exit 137 = SIGKILL par le kubelet.
Timeline : container démarre, startup probe (`delay=5s, period=5s, failure=3` ≈ 20s de budget) échoue avant que l'app soit prête (~38s), SIGTERM puis SIGKILL après les 30s de grâce → ~45s, cohérent avec l'horodatage.

> Le cold start lent était partiellement causé par la contention I/O du DiskPressure. Une fois le disque réglé, le router démarrait assez vite pour passer la probe par défaut — mais la probe desserrée reste la bonne pratique.

**Fix** :
```yaml
startupProbe:
  initialDelaySeconds: 10
  periodSeconds: 10
  failureThreshold: 30   # 300s de budget
```

**Distinction de diagnostic clé** : `connection refused` (RST) = l'app n'écoute pas (problème applicatif). Un problème **réseau** donnerait un **timeout**, pas un refused.

---

### 6. (Aparté) Cilium connectivity test — fausse piste

`cilium connectivity test` → 11/85 échecs, tous des tests **L7** en timeout (exit 28) via le proxy Envoy, + warnings `direct routing device required but not configured` sur plusieurs nodes.

**Conclusion** : problème Cilium réel mais **séparé** du router (cantonné au namespace `cilium-test`, pas de NetworkPolicy dans `vllm`). À investiguer indépendamment — le warning `direct-routing-device` mérite attention surtout avec un node fraîchement ajouté.

---

### 7. ★ Cause racine : imbrication du chart parapluie

**Symptôme** : PVC toujours sans storageClass + **aucun Deployment engine** (`kubectl get deploy` ne montre que le router), malgré tous les fixes committés.

**Diagnostic** : `Chart.yaml` =
```yaml
name: vllm-wrapper
dependencies:
  - name: vllm-stack
    version: 0.1.11
```
C'est un **chart parapluie**. En Helm, les values d'une dépendance doivent être **imbriquées sous le nom de la dépendance**. Les `servingEngineSpec`/`routerSpec` étaient au top-level → transmises au wrapper (qui les ignore), **jamais** au subchart. Le subchart `vllm-stack` tournait sur ses **defaults** : modelSpec d'exemple `name: mistral`, `enabled: false`, `storageClass: ""`.

Ça reproduit *exactement* les 3 symptômes : PVC nommé `vllm-mistral-storage-claim`, storageClass vide, et aucun Deployment (gaté par `enabled: false`).

**Fix** : tout imbriquer sous `vllm-stack:` (voir le `values.yaml` final).

---

### 8. Engine Pending — VM sous-dimensionné

**Symptôme** : après imbrication, le Deployment engine est enfin créé, mais le pod reste `Pending` :
`0/4 nodes available: 1 Insufficient memory, 1 untolerated taint, 2 Insufficient nvidia.com/gpu, 3 Insufficient cpu`.

**Diagnostic** :
- `kubectl describe node node-gpu | grep -i taint` → `Taints: <none>` → le "untolerated taint" concernait un *autre* node (et le `value: value` de la toleration était donc inoffensif, jamais le problème).
- Config VM Proxmox : **4 vCPU, 10.74 GiB RAM**. L'engine demandait `cpu: 4` / `memory: 8Gi` en requests → ne rentrait pas avec le router (2Gi) + overhead système → `Insufficient cpu`/`memory`.
- Le GPU passthrough était libre (pas pris par Ollama).

**Fix** : resize du VM (l'hôte a 64GB / Ryzen 5 7600). Aussi : ajouter `enabled: true` au modelSpec (le chart traite la valeur non-définie comme false).

---

### 9. UCX AVX SIGSEGV (et la chaîne Proxmox)

**Symptôme** : l'engine schedule, vLLM 0.23.0 démarre, trouve le modèle FP8, puis crash :
`FATAL: UCX library was compiled with avx but CPU does not support it.` → SIGSEGV (signal 11) à l'inspection de l'architecture du modèle.

**Diagnostic** : le CPU type du VM était **`x86-64-v2-AES`**, qui **n'expose pas l'AVX** au guest (l'AVX est en x86-64-v3). Le Ryzen 5 7600 (Zen 4) le supporte nativement, mais Proxmox le masquait. UCX (tiré par la stack KV-transfer de vLLM) est compilé avec AVX → instruction illégale → segfault.

**Fix** : passer le CPU type à `host` (expose tous les jeux d'instructions physiques). Aucun inconvénient : le passthrough PCI empêche déjà la live-migration.

**Sous-problèmes Proxmox rencontrés en chemin** :
- `can't lock file lock-104.conf - got timeout` → lock orphelin → `qm unlock 104`.
- `guest-ping failed` / `powerdown timeout` → QEMU Guest Agent pas installé dans le guest → arrêt brutal `qm stop 104`.
- `MAX 12 vcpus allowed per VM` → `sockets: 2` × `cores: 8` = 16 > 12 threads → utiliser `--sockets 1 --cores 8`.

Commande finale :
```bash
qm unlock 104
qm set 104 --sockets 1 --cores 8 --cpu host --memory 24576
qm stop 104
qm start 104
```

---

## values.yaml final (imbriqué sous vllm-stack)

```yaml
vllm-stack:

  servingEngineSpec:
    enableEngine: true
    runtimeClassName: nvidia
    nodeSelector:
      kubernetes.io/hostname: node-gpu
    labels:
      environment: test
      release: test

    modelSpec:
      - name: mistral
        enabled: true                 # sinon pas de Deployment engine
        repository: vllm/vllm-openai
        tag: latest
        modelURL: RedHatAI/Mistral-7B-Instruct-v0.3-FP8
        replicaCount: 1
        requestGPU: 1
        pvcStorage: "50Gi"            # string, pas un objet
        pvcAccessMode:
          - ReadWriteOnce
        storageClass: "nfs-client"    # storageClass, pas storageClassName
        resources:
          requests: { cpu: "4", memory: 8Gi, ephemeral-storage: 20Gi, nvidia.com/gpu: "1" }
          limits:   { cpu: "8", memory: 16Gi, ephemeral-storage: 40Gi, nvidia.com/gpu: "1" }
        vllmConfig:
          maxModelLen: 4096
          gpuMemoryUtilization: 0.90
          dtype: auto

  routerSpec:
    enableRouter: true
    routingLogic: roundrobin
    nodeSelector:
      kubernetes.io/hostname: node-gpu
    startupProbe:
      initialDelaySeconds: 10
      periodSeconds: 10
      failureThreshold: 30
    serviceDiscovery: k8s
    k8sNamespace: vllm
    k8sServiceDiscoveryType: pod-ip
    k8sLabelSelector: environment=test,release=test
```

(Les blocs `tolerations` ont été retirés ici puisque node-gpu n'a aucun taint ; les remettre seulement si tu en ajoutes un.)

---

## Leçons / gotchas réutilisables

1. **ArgoCD lit le git distant, pas le disque local.** Un fichier `M` dans VSCode = non committé.
2. **Chart parapluie** : les values d'une dépendance doivent être imbriquées sous le nom de la dépendance. Au top-level, elles sont silencieusement ignorées.
3. **Helm merge** : les *maps* sont fusionnées en profondeur, les *listes* sont remplacées en entier.
4. **`storageClassName` d'un PVC est immuable** → supprimer/recréer pour changer.
5. **`connection refused` (RST) ≠ `timeout`** : refused = app n'écoute pas ; timeout = réseau/policy.
6. **Exit 137** = SIGKILL. `Reason: Error` = probe-kill ; `Reason: OOMKilled` = mémoire.
7. **DiskPressure** peut venir des **inodes** autant que des octets → toujours `df -i` en plus de `df -h`.
8. **Installeur Ubuntu LVM** laisse souvent ~50% du VG non-alloué → `lvextend -l +100%FREE`.
9. **Proxmox CPU type `x86-64-v2`** masque l'AVX → `host` pour les workloads ML (sauf besoin de live-migration).
10. **Proxmox vCPU = sockets × cores**, plafonné au nombre de threads de l'hôte.
11. **Lire les LOGS, pas les events.** Les events disent *que* ça échoue ; les logs disent *pourquoi*.

---

## État actuel & étapes restantes

**Réglé** : schéma chart, modèle FP8, commit/push, disque, startupProbe, imbrication parapluie, scheduling (VM resize), `enabled`, CPU type `host` (AVX).

**À CONFIRMER** (non vérifié à la fin de la session) :
- [ ] Au reboot du VM (CPU `host`), l'engine passe le segfault UCX.
- [ ] **Le FP8 charge réellement sur la Blackwell** : `vllm/vllm-openai:latest` (vLLM 0.23.0) doit avoir les kernels CUDA **sm_120**. Si trop vieux → `CUDA error: no kernel image is available for execution on the device`. → à valider dans les logs de l'engine.
- [ ] Le router passe de `0 serving engine(s)` à `1` une fois l'engine `Ready`.
- [ ] Test de l'endpoint OpenAI via le router (`/v1/chat/completions`).
- [ ] Installer `qemu-guest-agent` dans le guest pour des shutdowns propres à l'avenir.
- [ ] (Séparé) Investiguer les warnings Cilium L7 / `direct-routing-device`.

---

*Runbook MireCloud — déploiement vLLM. Document de session, à compléter après validation du chargement GPU.*