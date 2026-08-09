"""
remediation.py — Applique une remédiation SOUS GARDE-FOUS.

Par défaut, l'agent est en mode "propose" : il n'exécute RIEN, il affiche la
commande. L'exécution automatique n'est possible que si TOUS les garde-fous
passent ET que l'auto-exécution est explicitement activée dans la config.

Les 4 garde-fous (cf. §5.5 du guide) :
  1. seuil de confiance minimal
  2. allowlist d'actions réversibles uniquement
  3. risque acceptable
  4. journalisation d'audit systématique
"""

from __future__ import annotations
import shlex
import subprocess
from datetime import datetime

# Actions autorisées en auto-exécution : réversibles et à faible rayon d'impact.
AUTO_ALLOWED_TYPES = {"restart", "scale", "clear_cache", "rollback"}


def decide(result: dict, policy: dict) -> dict:
    """Décide quoi faire de la proposition. Renvoie une décision motivée."""
    rem = result.get("remediation", {}) or {}
    conf = result.get("confiance", 0.0)
    reasons = []

    if not policy.get("auto_execute", False):
        return {"action": "propose_only",
                "reason": "auto-exécution désactivée (mode propose)"}

    if conf < policy.get("min_confidence", 0.85):
        reasons.append(f"confiance {conf:.0%} < seuil {policy.get('min_confidence', 0.85):.0%}")
    if rem.get("type") not in AUTO_ALLOWED_TYPES:
        reasons.append(f"type '{rem.get('type')}' hors allowlist")
    if not rem.get("reversible", False):
        reasons.append("action non réversible")
    if rem.get("risque") == "élevé":
        reasons.append("risque élevé")

    if reasons:
        return {"action": "escalate", "reason": " ; ".join(reasons)}
    return {"action": "auto_execute", "reason": "tous les garde-fous OK"}


def execute(commands: list[str], dry_run: bool = True) -> list[dict]:
    """Exécute (ou simule) les commandes proposées. dry_run=True par défaut."""
    results = []
    for cmd in commands:
        if dry_run:
            results.append({"cmd": cmd, "dry_run": True,
                            "note": "simulation — commande NON exécutée"})
            continue
        try:
            proc = subprocess.run(shlex.split(cmd), capture_output=True,
                                  text=True, timeout=60)
            results.append({"cmd": cmd, "returncode": proc.returncode,
                            "stdout": proc.stdout[-500:], "stderr": proc.stderr[-500:]})
        except Exception as exc:  # noqa: BLE001
            results.append({"cmd": cmd, "error": str(exc)})
    return results


def audit(result: dict, decision: dict, execution: list | None, path: str) -> None:
    """Trace complète de la décision (obligatoire pour toute action)."""
    import json
    record = {
        "ts": datetime.utcnow().isoformat() + "Z",
        "titre": result.get("titre"),
        "confiance": result.get("confiance"),
        "decision": decision,
        "execution": execution,
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
