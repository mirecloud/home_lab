"""
analyzer.py — Le cerveau GenAI.

Deux étapes :
  1) clustering LOCAL (sans LLM) : regroupe les logs par "signature" d'erreur
     pour réduire le bruit et le coût en tokens.
  2) analyse LLM : envoie les clusters au modèle Claude, qui LIT les logs et
     PROPOSE un diagnostic + une remédiation, en JSON structuré exploitable.

Le LLM n'exécute jamais rien : il propose. L'exécution est gérée ailleurs
(remediation.py) sous garde-fous.
"""

from __future__ import annotations
import hashlib
import json
import os
import re
from collections import defaultdict

# --- Étape 1 : clustering local, bon marché --------------------------------

# On remplace les valeurs variables (nombres, IDs, IPs, UUIDs) par des jokers
# pour que deux erreurs "identiques à un ID près" tombent dans le même cluster.
_NORMALIZERS = [
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"), "<UUID>"),
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b"), "<IP>"),
    (re.compile(r"\d+"), "<N>"),   # nombres, même collés à une unité (5031ms -> <N>ms)
    (re.compile(r"0x[0-9a-fA-F]+"), "<HEX>"),
]


def _signature(message: str) -> str:
    sig = message
    for rx, repl in _NORMALIZERS:
        sig = rx.sub(repl, sig)
    return sig.strip()[:200]


def cluster_logs(entries: list[dict]) -> list[dict]:
    """Regroupe les entrées par signature. Renvoie les clusters triés par volume."""
    groups: dict[str, dict] = {}
    for e in entries:
        sig = _signature(e["message"])
        key = hashlib.md5(f'{e["service"]}|{sig}'.encode()).hexdigest()[:8]
        g = groups.setdefault(key, {
            "id": key, "service": e["service"], "signature": sig,
            "level": e["level"], "count": 0, "samples": [], "first_ts": e["timestamp"],
            "last_ts": e["timestamp"],
        })
        g["count"] += 1
        g["last_ts"] = e["timestamp"] or g["last_ts"]
        if len(g["samples"]) < 3:               # on garde 3 exemples bruts par cluster
            g["samples"].append(e["raw"])
    clusters = sorted(groups.values(), key=lambda c: c["count"], reverse=True)
    return clusters


# --- Étape 2 : analyse LLM --------------------------------------------------

SYSTEM_PROMPT = """Tu es un ingénieur SRE senior expérimenté en systèmes distribués.
On te fournit des clusters de logs d'erreur agrégés d'une plateforme en production.
Ta mission : LIRE ces logs, identifier l'incident le plus probable, et PROPOSER
un diagnostic et une remédiation.

Règles :
- Distingue corrélation et causalité.
- Ne propose que des remédiations concrètes et réversibles quand c'est possible.
- Donne un niveau de confiance honnête (0.0 à 1.0). Si les logs sont insuffisants,
  dis-le et propose une étape de diagnostic plutôt qu'une correction.
- Réponds UNIQUEMENT avec un objet JSON valide, sans texte autour, au schéma :

{
  "incident_detecte": true/false,
  "titre": "résumé court de l'incident",
  "service_impacte": "nom du service",
  "severite": "P1|P2|P3|P4",
  "diagnostic": "explication en 2-4 phrases de ce qui se passe et pourquoi",
  "preuves": ["extrait de log ou fait qui étaye le diagnostic", "..."],
  "cause_racine_probable": "hypothèse principale",
  "confiance": 0.0,
  "remediation": {
    "resume": "ce qu'il faut faire",
    "type": "restart|scale|rollback|config|investigation|manuel",
    "commandes": ["commande shell/kubectl proposée (à valider par un humain)", "..."],
    "reversible": true/false,
    "risque": "faible|moyen|élevé"
  },
  "etapes_diagnostic": ["si confiance faible, quoi vérifier ensuite", "..."]
}"""


def _build_user_prompt(clusters: list[dict], max_clusters: int = 8) -> str:
    top = clusters[:max_clusters]
    lines = ["Voici les clusters de logs d'erreur (les plus fréquents en premier) :\n"]
    for c in top:
        lines.append(f"### Cluster {c['id']} — service '{c['service']}' "
                     f"[{c['level']}] — {c['count']} occurrences")
        lines.append(f"Signature : {c['signature']}")
        lines.append("Exemples bruts :")
        for s in c["samples"]:
            lines.append(f"  {s[:300]}")
        lines.append("")
    lines.append("Analyse ces logs et renvoie le JSON demandé.")
    return "\n".join(lines)


def analyze_with_llm(clusters: list[dict], model: str = "claude-sonnet-5",
                     max_tokens: int = 1200) -> dict:
    """Envoie les clusters à Claude et renvoie le diagnostic structuré + le coût."""
    import anthropic

    if not clusters:
        return {"incident_detecte": False, "titre": "Aucune erreur détectée",
                "confiance": 1.0, "_meta": {"clusters": 0}}

    client = anthropic.Anthropic()  # lit ANTHROPIC_API_KEY dans l'environnement
    user_prompt = _build_user_prompt(clusters)

    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    text = resp.content[0].text.strip()
    result = _safe_json(text)

    # Métadonnées d'observabilité DE l'agent lui-même (tokens, coût) — cf. §6 du guide
    usage = resp.usage
    result["_meta"] = {
        "model": model,
        "clusters": len(clusters),
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cost_usd": _estimate_cost(model, usage.input_tokens, usage.output_tokens),
    }
    return result


def _safe_json(text: str) -> dict:
    """Extrait un objet JSON même si le modèle a ajouté des fences ``` autour."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Récupère le premier bloc {...} plausible
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    return {"incident_detecte": True, "titre": "Analyse non parsable",
            "diagnostic": text[:500], "confiance": 0.0, "remediation": {}}


# Grille tarifaire indicative (USD par million de tokens). À ajuster selon votre contrat.
_PRICING = {
    "claude-opus-5":   (15.0, 75.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-haiku-4-5-20251001": (0.80, 4.0),
}


def _estimate_cost(model: str, in_tok: int, out_tok: int) -> float:
    pin, pout = _PRICING.get(model, (3.0, 15.0))
    return round(in_tok / 1e6 * pin + out_tok / 1e6 * pout, 6)
