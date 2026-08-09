"""
main.py — Orchestrateur de l'agent d'observabilité GenAI.

Enchaîne : lire les logs -> clusteriser -> analyser avec le LLM -> proposer
(-> éventuellement remédier sous garde-fous).

Modes :
  --once      : analyse une fois et affiche la proposition (défaut)
  --watch     : boucle en continu à l'intervalle configuré
  --dry-run   : n'appelle pas le LLM, montre seulement les clusters (aucun coût, aucune clé requise)

Exemples :
  python -m agent.main --once
  python -m agent.main --watch
  python -m agent.main --dry-run
"""

from __future__ import annotations
import argparse
import sys
import time
from pathlib import Path

# Sous Windows, la console est souvent en cp1252 : on force l'UTF-8 pour
# afficher accents et emojis sans planter.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

import yaml

from agent import log_reader, analyzer, notifier, remediation


def load_config(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def run_once(config: dict, dry_run: bool = False) -> dict:
    # 1) LIRE les logs
    entries = log_reader.load_logs(config)
    print(f"[agent] {len(entries)} entrées de log lues "
          f"(source={config['source']['type']})")

    # 2) CLUSTERISER (local, gratuit)
    clusters = analyzer.cluster_logs(entries)
    print(f"[agent] {len(clusters)} clusters d'erreur distincts")

    if dry_run:
        for c in clusters[:8]:
            print(f"  - [{c['count']:>4}x] {c['service']}: {c['signature'][:90]}")
        return {"incident_detecte": False, "_meta": {"dry_run": True}}

    if not clusters:
        print(notifier.render_console({"incident_detecte": False}))
        return {"incident_detecte": False}

    # 3) ANALYSER avec le LLM -> PROPOSER
    model = config.get("llm", {}).get("model", "claude-sonnet-5")
    result = analyzer.analyze_with_llm(clusters, model=model)

    # 4) RESTITUER
    print(notifier.render_console(result))
    out = config.get("output", {})
    if out.get("json_log"):
        notifier.save_json(result, out["json_log"])
    if out.get("slack_webhook"):
        ok = notifier.notify_slack(result, out["slack_webhook"])
        print(f"[agent] Slack : {'envoyé' if ok else 'non envoyé'}")

    # 5) REMÉDIER (sous garde-fous) — propose seulement par défaut
    policy = config.get("remediation", {})
    decision = remediation.decide(result, policy)
    print(f"[agent] décision de remédiation : {decision['action']} "
          f"({decision['reason']})")
    execution = None
    if decision["action"] == "auto_execute":
        cmds = (result.get("remediation", {}) or {}).get("commandes", [])
        execution = remediation.execute(cmds, dry_run=policy.get("dry_run", True))
        for r in execution:
            print(f"    → {r}")
    if out.get("audit_log"):
        remediation.audit(result, decision, execution, out["audit_log"])
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Agent d'observabilité GenAI")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--once", action="store_true", help="analyse unique (défaut)")
    parser.add_argument("--watch", action="store_true", help="boucle continue")
    parser.add_argument("--dry-run", action="store_true",
                        help="clusters seulement, sans appel LLM")
    args = parser.parse_args()

    config = load_config(args.config)

    if args.watch:
        interval = config.get("watch", {}).get("interval_seconds", 60)
        print(f"[agent] mode watch — analyse toutes les {interval}s. Ctrl+C pour arrêter.")
        try:
            while True:
                run_once(config, dry_run=args.dry_run)
                time.sleep(interval)
        except KeyboardInterrupt:
            print("\n[agent] arrêt.")
            return 0
    else:
        run_once(config, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
