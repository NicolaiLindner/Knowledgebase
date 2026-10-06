#!/usr/bin/env python3
"""kb_drift.py - Inhaltsvergleich Sollzustand (sql/objects) gegen Datenbank.

Der Traum (kb_dream.py) vergleicht nur Zeitstempel (Commit vs. modify_date).
Dieses Werkzeug vergleicht den DDL-TEXT: je kanonischer Datei wird der
Quelltext normalisiert (Kommentare, USE/GO/SET, CREATE|ALTER, eckige
Klammern, Whitespace entfernt) und gegen `python tools/sql.py --ddl <objekt>`
gehalten. Nur lesend; DB-Zugriff ausschliesslich ueber tools/sql.py.

Aufruf:
    python tools/kb_drift.py              # alle Objekte in sql/objects
    python tools/kb_drift.py v_%          # nur passende (SQL-LIKE-Muster)
    python tools/kb_drift.py --diff NAME  # Wort-Diff fuer ein Objekt zeigen

Exit-Code 0 = alles identisch, 1 = Abweichung oder fehlendes Objekt,
2 = Datenbank nicht erreichbar.
"""
from __future__ import annotations

import argparse
import difflib
import fnmatch
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OBJECTS = ROOT / "sql" / "objects"
SQL_PY = ROOT / "tools" / "sql.py"


def normalize(text: str) -> str:
    """Quelltext auf den vergleichbaren Kern reduzieren."""
    t = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    t = re.sub(r"--[^\n]*", "", t)
    # Markdown-Wrapper von --ddl (## name, (typ), ```sql ... ```)
    t = re.sub(r"(?m)^\s*(##.*|\([a-z_ ]+\)|```\w*|```)\s*$", "", t)
    t = re.sub(r"(?im)^\s*(USE\s+\[?[^\]\n]+\]?|GO|SET\s+(ANSI_NULLS|QUOTED_IDENTIFIER)\s+ON)\s*$", "", t)
    # Platzhalter-Guard der Dateien (IF OBJECT_ID ... EXEC('CREATE ... '))
    t = re.sub(r"(?is)IF\s+OBJECT_ID\s*\([^)]*\)\s+IS\s+NULL\s+EXEC\s*\(\s*'[^']*'\s*\)\s*;?", "", t)
    t = re.sub(r"(?i)\bCREATE\s+OR\s+ALTER\s+|\bALTER\s+|\bCREATE\s+", "", t)
    t = re.sub(r"[\[\];]", "", t)
    t = re.sub(r"\s+", " ", t)
    # Whitespace um Kommas und Klammern ist Formatierung, kein Inhalt
    t = re.sub(r"\s*([,()])\s*", r"\1", t)
    return t.strip().lower()


def object_batch(text: str) -> str:
    """Nur den Batch mit CREATE/ALTER VIEW|PROCEDURE|FUNCTION zurueckgeben.

    Prozedur-Dateien tragen davor CREATE TABLE und danach EXEC-Aufrufe;
    die Datenbank kennt nur den Objektrumpf."""
    batches = re.split(r"(?im)^\s*GO\s*$", text)
    head = re.compile(r"(?i)\b(CREATE\s+OR\s+ALTER|ALTER|CREATE)\s+(VIEW|PROCEDURE|PROC|FUNCTION)\b")
    for b in batches:
        if head.search(b) and "Platzhalter" not in b and "RETURN 0" not in b:
            return b
    return text


def db_ddl(obj: str) -> str | None:
    """DDL aus der Datenbank ueber tools/sql.py --ddl; None wenn nicht vorhanden."""
    r = subprocess.run(
        [sys.executable, str(SQL_PY), "--ddl", obj],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    err = (r.stderr or "").strip()
    # Verbindungs- oder Konfigurationsfehler (keine .env, Server nicht erreichbar) - nicht als "fehlt in DB" werten
    if r.returncode != 0 and err and "Kein Objekt passend" not in err:
        raise ConnectionError(err.splitlines()[-1])
    out = r.stdout or ""
    if "```" not in out:
        return None
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Sollzustand sql/objects gegen DB vergleichen.")
    ap.add_argument("pattern", nargs="?", default="%", help="SQL-LIKE-Muster auf den Objektnamen")
    ap.add_argument("--diff", metavar="NAME", help="Wort-Diff fuer dieses Objekt ausgeben")
    args = ap.parse_args()
    # Windows-Konsole schreibt sonst cp1252: Umlaute in Fehlermeldungen des Treibers brechen die Ausgabe ab.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    glob = args.pattern.replace("%", "*").replace("_", "?") if args.pattern != "%" else "*"
    files = sorted(OBJECTS.glob("*.sql"))
    worst = 0
    print(f"{'Objekt':50s} Befund")
    for f in files:
        obj = f.stem.split(".", 1)[1]
        if args.diff and obj != args.diff:
            continue
        if not args.diff and not fnmatch.fnmatchcase(obj, glob):
            continue
        try:
            ddl = db_ddl(obj)
        except ConnectionError as e:
            print(f"Datenbank nicht erreichbar: {e}")
            return 2
        if ddl is None:
            print(f"{obj:50s} FEHLT in DB")
            worst = max(worst, 1)
            continue
        a = normalize(object_batch(f.read_text(encoding="utf-8", errors="replace")))
        b = normalize(ddl)
        if a == b:
            print(f"{obj:50s} identisch")
            continue
        ratio = difflib.SequenceMatcher(None, a, b).ratio()
        print(f"{obj:50s} ABWEICHUNG  aehnlich={ratio:.2f}  datei={len(a)}  db={len(b)}")
        worst = max(worst, 1)
        if args.diff:
            for line in difflib.unified_diff(a.split(" "), b.split(" "), "datei", "db", n=3, lineterm=""):
                print("   ", line)
    return worst


if __name__ == "__main__":
    sys.exit(main())
