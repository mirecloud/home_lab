# Agent d'observabilité GenAI — intégrer l'IA à vos logs, pas à pas

Un agent **fonctionnel** qui montre concrètement comment brancher la GenAI sur
l'observabilité : il **lit vos logs**, les analyse, et **propose automatiquement**
un diagnostic + une remédiation. Optionnellement, il peut poster dans Slack et —
sous garde-fous stricts — exécuter une remédiation réversible.

> Ce n'est pas un jouet théorique : le code tourne. Vous pouvez le tester en
> **une minute sur des logs d'exemple**, puis le brancher sur OpenSearch, Loki
> ou vos fichiers de logs réels en changeant **une seule section** de config.

```
   Vos logs ──►  1. LIRE  ──►  2. CLUSTERISER  ──►  3. ANALYSER (LLM)  ──►  4. PROPOSER
 (fichier /                    (regroupe par         (Claude lit et         (console / Slack /
  OpenSearch /                  signature, réduit     raisonne, renvoie      JSON d'audit)
  Loki)                         le bruit & le coût)   un JSON structuré)          │
                                                                                  ▼
                                                                    5. REMÉDIER (optionnel,
                                                                       sous 4 garde-fous)
```

---

## Ce que fait l'agent, très concrètement

Sur les logs d'exemple fournis (un incident réaliste d'épuisement de pool de
connexions qui casse le service de paiement puis le checkout), l'agent :

1. **lit** 21 lignes de logs et n'en garde que les erreurs/warnings ;
2. **regroupe** en 8 clusters distincts (« Connection pool exhausted » ×8, etc.)
   — cela réduit drastiquement le nombre de tokens envoyés au LLM ;
3. **envoie** ces clusters à Claude qui **lit et raisonne** ;
4. **propose** un diagnostic structuré du type :

```
🔴  INCIDENT PROPOSÉ  [P1]  confiance=90%
Titre        : Épuisement du pool de connexions JDBC du payment-service
Service      : payment-service

🔎 Diagnostic :
   Le pool de connexions (taille 50) est saturé. Une requête lente
   (SELECT ... status='pending', 4800ms) retient les connexions, provoquant
   des HTTP 500 en cascade et l'ouverture du circuit breaker côté checkout.

🎯 Cause racine probable : requête non indexée sur transactions.status

🛠️  Remédiation proposée :
   Augmenter temporairement le pool + investiguer/indexer la requête lente
   type=scale  réversible=True  risque=faible
   $ kubectl scale deploy/payment-service --replicas=4
```

---

## Étape 1 — Prérequis

- **Python 3.10+**
- Une **clé API Anthropic** (gratuite à créer sur https://console.anthropic.com/)
  — nécessaire seulement pour l'étape d'analyse LLM. La lecture et le clustering
  fonctionnent sans clé (mode `--dry-run`).

---

## Étape 2 — Installation

```bash
cd genai-observability-agent
pip install -r requirements.txt
```

---

## Étape 3 — Tester sans clé API (lecture + clustering)

Vérifiez que l'agent lit bien les logs et les regroupe, **sans aucun coût** :

```bash
python -m agent.main --dry-run
```

Vous devez voir la liste des clusters d'erreur détectés. Si oui, la moitié du
pipeline (lecture + réduction du bruit) fonctionne déjà.

---

## Étape 4 — Brancher le LLM (l'analyse automatique)

1. Copiez le modèle d'environnement et renseignez votre clé :

   ```bash
   cp .env.example .env
   # éditez .env et collez votre clé ANTHROPIC_API_KEY
   ```

2. Chargez la clé dans votre session :

   ```bash
   # Linux / macOS
   export $(grep -v '^#' .env | xargs)

   # Windows PowerShell
   Get-Content .env | Where-Object {$_ -notmatch '^#'} | ForEach-Object { $p=$_ -split '=',2; [Environment]::SetEnvironmentVariable($p[0],$p[1]) }
   ```

3. Lancez l'analyse complète :

   ```bash
   python -m agent.main --once
   ```

L'agent lit les logs, appelle Claude, et affiche la proposition d'incident +
remédiation. Le coût de l'appel (tokens, USD) est affiché en bas — l'agent
s'observe lui-même (bonne pratique : mesurer le composant GenAI comme les autres).

---

## Étape 5 — Le brancher sur VOS logs réels

Tout se passe dans la section `source:` de [`config.yaml`](config.yaml).
**Vous ne changez que ça.**

### Option A — Vos fichiers de logs

```yaml
source:
  type: file
  paths:
    - /var/log/myapp/app.log
    - /var/log/myapp/error.log
  only_errors: true
```

Format attendu par le parseur intégré :
`2026-08-06T10:15:03Z ERROR [service-name] message`.
Un autre format ? Adaptez la regex `_LINE_RE` dans
[`agent/log_reader.py`](agent/log_reader.py) — c'est une seule ligne.

### Option B — OpenSearch / Elasticsearch

```yaml
source:
  type: opensearch
  url: http://localhost:9200
  index: logs-otel-*
  lookback_minutes: 15
  auth: ["admin", "admin"]      # optionnel
```

### Option C — Grafana Loki

```yaml
source:
  type: loki
  url: http://localhost:3100
  query: '{level=~"error|warn"}'
  lookback_minutes: 15
```

---

## Étape 6 — Le faire tourner en continu

Pour qu'il surveille et propose en boucle (toutes les 60 s par défaut) :

```bash
python -m agent.main --watch
```

Chaque cycle : relit la fenêtre de logs récente → clusterise → analyse →
propose. Réglez l'intervalle via `watch.interval_seconds` dans la config.

> 💡 En production, on ne lance pas le LLM à chaque tick « à vide ». Deux options
> saines : (a) déclencher l'analyse **seulement quand une alerte se déclenche**
> (webhook Alertmanager → cet agent) ; (b) garder un intervalle raisonnable +
> ne payer le LLM que s'il y a de nouveaux clusters d'erreur.

---

## Étape 7 — Notifier Slack (optionnel)

1. Créez une **Incoming Webhook** dans votre workspace Slack.
2. Collez l'URL dans `config.yaml` :

   ```yaml
   output:
     slack_webhook: "https://hooks.slack.com/services/XXX/YYY/ZZZ"
   ```

Chaque proposition d'incident sera postée dans le canal choisi.

---

## Étape 8 — Activer la remédiation automatique (avancé, avec garde-fous)

**Par défaut l'agent PROPOSE seulement.** L'auto-exécution est délibérément
verrouillée. Pour l'activer, il faut lever plusieurs garde-fous — ce qui est
volontairement contraignant :

```yaml
remediation:
  auto_execute: true       # active l'exécution auto
  dry_run: true            # ⚠️ gardez true d'abord : simule sans exécuter
  min_confidence: 0.85     # n'agit que si le LLM est sûr à ≥ 85 %
```

Les **4 garde-fous** appliqués avant toute action (voir
[`agent/remediation.py`](agent/remediation.py)) :

1. **Confiance** ≥ seuil configuré.
2. **Allowlist** : seules des actions *réversibles* (`restart`, `scale`,
   `rollback`, `clear_cache`) sont automatisables. Un `DROP TABLE` ne passera
   jamais.
3. **Risque** : les remédiations à risque élevé ou non réversibles sont escaladées.
4. **Audit** : toute décision est journalisée dans `audit.jsonl`
   (qui/quoi/quand/pourquoi + hypothèse du LLM).

> 🔒 **Recommandation** : restez en mode *propose* pendant des semaines. Mesurez
> la pertinence des propositions sur des incidents réels **avant** d'automatiser
> quoi que ce soit. Commencez par `dry_run: true` même en auto.

---

## Structure du projet

```
genai-observability-agent/
├── README.md                ← ce guide
├── requirements.txt
├── config.yaml              ← toute la configuration (source, LLM, Slack, garde-fous)
├── .env.example             ← modèle pour la clé API
├── sample_logs/
│   └── app.log              ← incident réaliste pour tester tout de suite
└── agent/
    ├── main.py              ← orchestrateur (lire→clusteriser→analyser→proposer→remédier)
    ├── log_reader.py        ← sources de logs : file / opensearch / loki
    ├── analyzer.py          ← clustering local + analyse LLM (le cerveau)
    ├── notifier.py          ← restitution console / Slack / JSON d'audit
    └── remediation.py       ← exécution sous les 4 garde-fous
```

---

## Comment ça marche, sous le capot

**Pourquoi clusteriser avant d'appeler le LLM ?** Envoyer 10 000 lignes brutes à
un LLM coûte cher et le noie. On normalise chaque message (les IDs, nombres, IPs
deviennent des jokers `<N>`, `<UUID>`…), on regroupe par signature, et on
n'envoie que les ~8 clusters les plus fréquents avec 3 exemples chacun. Résultat :
**90 % de tokens en moins** pour une analyse tout aussi bonne.

**Pourquoi le LLM ne détecte-t-il pas seul ?** La détection (« quelque chose
cloche ») doit être rapide et déterministe → clustering/statistiques. Le LLM
apporte l'**interprétation** (« voici ce qui se passe, pourquoi, et quoi faire »).
C'est le bon partage des rôles.

**Pourquoi une sortie JSON structurée ?** Pour que la proposition soit
exploitable par la machine : routage Slack/PagerDuty, création de ticket,
décision de remédiation. Le prompt système impose ce schéma.

---

## Personnalisation rapide

| Vous voulez… | Où toucher |
|---|---|
| Un autre format de logs | `_LINE_RE` dans `log_reader.py` |
| Une autre source (Datadog, fichier JSON…) | ajouter une fonction `read_*` dans `log_reader.py` |
| Changer le raisonnement / le schéma de sortie | `SYSTEM_PROMPT` dans `analyzer.py` |
| Un modèle moins cher / plus puissant | `llm.model` dans `config.yaml` |
| Élargir/restreindre les actions auto | `AUTO_ALLOWED_TYPES` dans `remediation.py` |

---

## Limites assumées

- Le parseur de fichiers attend un format simple ; adaptez la regex pour vos logs.
- L'agent analyse des **logs** ; pour un vrai RCA multi-signal, enrichissez
  `build_incident_context` (voir le guide de référence) avec métriques + traces +
  déploiements récents.
- Le LLM peut se tromper : c'est pourquoi il **propose** et affiche une confiance.
  La décision et l'action restent sous contrôle humain par défaut.

---

*Compagnon pratique du document « Guide-Observabilite-GenAI-enrichi.md », lui-même
dérivé du livre* Generative AI Observability *(BPB, 2026).*
