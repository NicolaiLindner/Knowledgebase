#!/usr/bin/env python3
"""kb_config.py - liest kb.config.yaml (projektspezifische Werte an genau einer Stelle).

Von kb_lint.py und kb_dream.py importiert. Fehlt die Datei, gelten neutrale Standardwerte,
damit die Werkzeuge auch in einer frisch geklonten Vorlage laufen.
"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "kb.config.yaml"

DEFAULTS = {
    "name": "Wissensbasis",
    "domains": ["projekt"],
    "topics": [],
    "hub_seiten": [],
    "module": {"datenbank": False},
}


def load() -> dict:
    cfg = {k: (dict(v) if isinstance(v, dict) else list(v) if isinstance(v, list) else v) for k, v in DEFAULTS.items()}
    if CONFIG_PATH.is_file():
        data = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig")) or {}
        if not isinstance(data, dict):
            raise ValueError("kb.config.yaml ist kein Mapping")
        for key, value in data.items():
            if key == "module" and isinstance(value, dict):
                cfg["module"].update(value)
            elif value is not None:
                cfg[key] = value
    cfg["domains"] = [str(d).strip() for d in cfg["domains"] or [] if str(d).strip()]
    cfg["topics"] = [str(t).strip() for t in cfg["topics"] or [] if str(t).strip()]
    cfg["hub_seiten"] = [str(h).strip() for h in cfg["hub_seiten"] or [] if str(h).strip()]
    return cfg


CONFIG = load()
NAME: str = str(CONFIG["name"])
PROJECT_DOMAINS: set[str] = set(CONFIG["domains"]) - {"allgemein"}
DOMAINS: set[str] = PROJECT_DOMAINS | {"allgemein"}
TOPICS: set[str] = set(CONFIG["topics"])
HUB_PAGES: set[str] = set(CONFIG["hub_seiten"])
DB_MODULE: bool = bool(CONFIG["module"].get("datenbank"))
