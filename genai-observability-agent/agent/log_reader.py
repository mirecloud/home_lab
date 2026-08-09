"""
log_reader.py — Lit les logs depuis différentes sources et les normalise.

Sources supportées :
  - "file"       : un fichier local (ou plusieurs), y compris en mode "tail"
  - "opensearch" : un cluster OpenSearch / Elasticsearch
  - "loki"       : Grafana Loki

Toutes les sources renvoient une liste de dicts normalisés :
  { "timestamp": str, "level": str, "service": str, "message": str, "raw": str }
"""

from __future__ import annotations
import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

# Niveaux considérés comme "intéressants" pour l'analyse
ERROR_LEVELS = {"ERROR", "FATAL", "CRITICAL", "WARN", "WARNING"}

# Regex tolérante pour parser une ligne de log texte de la forme :
#   2026-08-06T10:15:03Z ERROR [payment-service] Connection pool exhausted
_LINE_RE = re.compile(
    r"^(?P<ts>\S+)\s+(?P<level>[A-Z]+)\s+\[(?P<service>[^\]]+)\]\s+(?P<msg>.*)$"
)


def _parse_text_line(line: str) -> dict | None:
    line = line.rstrip("\n")
    if not line.strip():
        return None
    m = _LINE_RE.match(line)
    if m:
        return {
            "timestamp": m.group("ts"),
            "level": m.group("level").upper(),
            "service": m.group("service"),
            "message": m.group("msg"),
            "raw": line,
        }
    # Ligne non structurée (stack trace, message libre) : on la garde quand même
    return {"timestamp": "", "level": "INFO", "service": "unknown",
            "message": line, "raw": line}


def read_file(paths: list[str], level_filter: bool = True) -> list[dict]:
    """Lit un ou plusieurs fichiers de logs et renvoie les entrées normalisées."""
    entries: list[dict] = []
    for p in paths:
        fp = Path(p)
        if not fp.exists():
            print(f"[log_reader] fichier introuvable : {p}")
            continue
        for line in fp.read_text(encoding="utf-8", errors="replace").splitlines():
            e = _parse_text_line(line)
            if e is None:
                continue
            if level_filter and e["level"] not in ERROR_LEVELS:
                continue
            entries.append(e)
    return entries


def tail_file(path: str, poll_seconds: float = 2.0) -> Iterable[dict]:
    """Générateur : suit un fichier en continu (comme `tail -f`)."""
    fp = Path(path)
    fp.touch(exist_ok=True)
    with fp.open("r", encoding="utf-8", errors="replace") as f:
        f.seek(0, 2)  # se positionne à la fin
        while True:
            line = f.readline()
            if not line:
                time.sleep(poll_seconds)
                continue
            e = _parse_text_line(line)
            if e:
                yield e


def read_opensearch(url: str, index: str, minutes: int = 15,
                    level_field: str = "level", size: int = 500,
                    auth: tuple | None = None) -> list[dict]:
    """Récupère les logs ERROR/WARN récents depuis OpenSearch."""
    import requests  # import local pour ne pas imposer la dépendance en mode fichier

    since = (datetime.utcnow() - timedelta(minutes=minutes)).isoformat() + "Z"
    query = {
        "size": size,
        "sort": [{"@timestamp": "desc"}],
        "query": {
            "bool": {
                "must": [{"range": {"@timestamp": {"gte": since}}}],
                "should": [{"match": {level_field: lvl}} for lvl in ("ERROR", "FATAL", "WARN")],
                "minimum_should_match": 1,
            }
        },
    }
    resp = requests.get(f"{url}/{index}/_search", json=query, auth=auth, timeout=30,
                        verify=False)
    resp.raise_for_status()
    hits = resp.json().get("hits", {}).get("hits", [])
    entries = []
    for h in hits:
        src = h.get("_source", {})
        entries.append({
            "timestamp": src.get("@timestamp", ""),
            "level": str(src.get(level_field, "INFO")).upper(),
            "service": src.get("service.name") or src.get("service", "unknown"),
            "message": src.get("message") or src.get("msg", ""),
            "raw": json.dumps(src, ensure_ascii=False),
        })
    return entries


def read_loki(url: str, query: str = '{level=~"error|warn"}',
              minutes: int = 15, limit: int = 500) -> list[dict]:
    """Récupère les logs depuis Grafana Loki via son API range."""
    import requests

    end = int(time.time() * 1e9)
    start = int((time.time() - minutes * 60) * 1e9)
    resp = requests.get(f"{url}/loki/api/v1/query_range",
                        params={"query": query, "start": start, "end": end,
                                "limit": limit, "direction": "backward"},
                        timeout=30)
    resp.raise_for_status()
    entries = []
    for stream in resp.json().get("data", {}).get("result", []):
        labels = stream.get("stream", {})
        for ts_ns, line in stream.get("values", []):
            e = _parse_text_line(line)
            if e:
                e["service"] = labels.get("service", e.get("service", "unknown"))
                e["level"] = labels.get("level", e["level"]).upper()
                entries.append(e)
    return entries


def load_logs(config: dict) -> list[dict]:
    """Point d'entrée unique piloté par la config (config.yaml -> section 'source')."""
    src = config.get("source", {})
    kind = src.get("type", "file")
    if kind == "file":
        return read_file(src.get("paths", []), level_filter=src.get("only_errors", True))
    if kind == "opensearch":
        return read_opensearch(src["url"], src["index"],
                               minutes=src.get("lookback_minutes", 15),
                               auth=tuple(src["auth"]) if src.get("auth") else None)
    if kind == "loki":
        return read_loki(src["url"], src.get("query", '{level=~"error|warn"}'),
                         minutes=src.get("lookback_minutes", 15))
    raise ValueError(f"Type de source inconnu : {kind}")
