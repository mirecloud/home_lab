"""
notifier.py — Restitue la proposition de l'agent : console (toujours) et Slack (option).
"""

from __future__ import annotations
import json

_SEV_EMOJI = {"P1": "🔴", "P2": "🟠", "P3": "🟡", "P4": "🔵"}


def render_console(result: dict) -> str:
    """Formate joliment la proposition pour le terminal."""
    if not result.get("incident_detecte", False):
        return "✅ Aucun incident détecté dans la fenêtre analysée."

    sev = result.get("severite", "P3")
    conf = result.get("confiance", 0.0)
    rem = result.get("remediation", {}) or {}
    lines = [
        "",
        "═" * 68,
        f"{_SEV_EMOJI.get(sev, '⚪')}  INCIDENT PROPOSÉ  [{sev}]  confiance={conf:.0%}",
        "═" * 68,
        f"Titre        : {result.get('titre', '-')}",
        f"Service      : {result.get('service_impacte', '-')}",
        "",
        "🔎 Diagnostic :",
        f"   {result.get('diagnostic', '-')}",
        "",
        f"🎯 Cause racine probable : {result.get('cause_racine_probable', '-')}",
    ]
    preuves = result.get("preuves") or []
    if preuves:
        lines.append("\n📋 Preuves :")
        for p in preuves:
            lines.append(f"   • {p}")

    lines.append("\n🛠️  Remédiation proposée :")
    lines.append(f"   {rem.get('resume', '-')}")
    lines.append(f"   type={rem.get('type', '?')}  "
                 f"réversible={rem.get('reversible', '?')}  "
                 f"risque={rem.get('risque', '?')}")
    for cmd in rem.get("commandes", []) or []:
        lines.append(f"   $ {cmd}")

    etapes = result.get("etapes_diagnostic") or []
    if etapes:
        lines.append("\n🔬 Si confiance faible — vérifier ensuite :")
        for e in etapes:
            lines.append(f"   • {e}")

    meta = result.get("_meta", {})
    if meta:
        lines.append("\n" + "-" * 68)
        lines.append(f"ℹ️  {meta.get('clusters', 0)} clusters | "
                     f"modèle={meta.get('model', '?')} | "
                     f"tokens={meta.get('input_tokens', 0)}/{meta.get('output_tokens', 0)} | "
                     f"coût≈${meta.get('cost_usd', 0):.4f}")
    lines.append("═" * 68 + "\n")
    return "\n".join(lines)


def notify_slack(result: dict, webhook_url: str) -> bool:
    """Poste la proposition dans un canal Slack via Incoming Webhook."""
    import requests

    if not result.get("incident_detecte", False):
        return False
    sev = result.get("severite", "P3")
    rem = result.get("remediation", {}) or {}
    cmds = "\n".join(f"`{c}`" for c in rem.get("commandes", []) or []) or "_aucune_"
    text = (
        f"{_SEV_EMOJI.get(sev, '⚪')} *{sev} — {result.get('titre', 'Incident')}*  "
        f"(confiance {result.get('confiance', 0):.0%})\n"
        f"*Service* : {result.get('service_impacte', '-')}\n"
        f"*Diagnostic* : {result.get('diagnostic', '-')}\n"
        f"*Cause probable* : {result.get('cause_racine_probable', '-')}\n"
        f"*Remédiation* ({rem.get('risque', '?')}, "
        f"réversible={rem.get('reversible', '?')}) : {rem.get('resume', '-')}\n{cmds}"
    )
    resp = requests.post(webhook_url, json={"text": text}, timeout=15)
    return resp.status_code == 200


def save_json(result: dict, path: str) -> None:
    """Sauvegarde brute pour audit / historique (cf. traçabilité, §7 du guide)."""
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")
