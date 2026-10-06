#!/usr/bin/env python3
"""kb_lint.py — Konsistenzprüfung der Wissensbasis.

Vier Check-Gruppen (siehe CLAUDE.md, Invariante 5):
  1. Kaputte Links          — [[ziel]] und related:-Eintraege ohne existierende Seite
  2. Pflicht-Frontmatter    — YAML parsebar, Pflichtfelder, erlaubte Werte (domain/topics aus
                              kb.config.yaml), Daten
  3. Unbekannte Claim-Tags  — Bullets mit [XYZ] ausserhalb des 6er-Sets
  4. Fehlende sources       — Eintrag fehlt oder raw/-Datei existiert nicht

Lesbarkeit (Zeilen > 600 Zeichen, Seiten > 25 KB) ist nur Warnung, nicht blockierend.

Aufruf:  python tools/kb_lint.py [--warn]   Exit 0 = sauber, Exit 1 = Fehler
"""
from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kb_config as C  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
WIKI = ROOT / "wiki"

REQUIRED = ["title", "type", "domain", "topics", "status", "summary",
            "sources", "created", "updated"]
OPTIONAL = ["related", "aliases"]
TYPES = {  # type -> Pflicht-Ordner unter wiki/
    "project": "projects", "concept": "concepts", "data-model": "data-model",
    "analysis": "analyses", "decision": "decisions", "known-issue": "known-issues",
}
DOMAINS = C.DOMAINS          # Projektkuerzel aus kb.config.yaml + "allgemein"
TOPICS = C.TOPICS            # leer = topics werden nicht geprueft
STATUS = {"entwurf", "aktiv", "historisch"}
CLAIM_TAGS = {"FAKT", "ENTSCHEIDUNG", "ERFAHRUNG", "ANNAHME", "HISTORISCH", "OFFEN"}

RE_WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
RE_CLAIM = re.compile(r"^\s*-\s*\[([A-ZÄÖÜ]{2,})\]", re.MULTILINE)
RE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

errors: list[str] = []
warnings: list[str] = []

# Lesbarkeit: nur Warnung, kein Fehler
MAX_LINE_CHARS = 600
MAX_PAGE_BYTES = 25_000


def err(page: Path, msg: str) -> None:
    errors.append(f"{page.relative_to(ROOT).as_posix()}: {msg}")


def warn(page: Path, msg: str) -> None:
    warnings.append(f"{page.relative_to(ROOT).as_posix()}: {msg}")


def check_size(page: Path, text: str) -> None:
    """Warnungen fuer Seiten ueber MAX_PAGE_BYTES und Zeilen ueber MAX_LINE_CHARS (Bullets mit Zahlenreihen)."""
    size = len(text.encode("utf-8"))
    if size > MAX_PAGE_BYTES:
        warn(page, f"Seite {size // 1000} KB (> {MAX_PAGE_BYTES // 1000} KB) - teilen: Methode bleibt, Ergebnisse/Historie auf eigene Seite")
    long = [i for i, ln in enumerate(text.splitlines(), 1) if len(ln) > MAX_LINE_CHARS]
    if long:
        warn(page, f"{len(long)} Zeile(n) > {MAX_LINE_CHARS} Zeichen (Z.{', '.join(str(i) for i in long[:5])}{', …' if len(long) > 5 else ''}) - Zahlen in Tabelle, Bullet kuerzen")


def split_frontmatter(text: str) -> tuple[dict | None, str, str | None]:
    """Liefert (frontmatter, body, fehlermeldung)."""
    if not text.startswith("---"):
        return None, text, "kein Frontmatter-Block am Dateianfang"
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.DOTALL)
    if not match:
        return None, text, "Frontmatter-Block nicht geschlossen"
    try:
        fm = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        return None, text, f"YAML nicht parsebar: {exc}"
    body = match.group(2)
    if not isinstance(fm, dict):
        return None, body, "Frontmatter ist kein Mapping"
    return fm, body, None


def parse_date(value) -> date | None:
    s = str(value)
    if not RE_DATE.match(s):
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def check_frontmatter(page: Path, fm: dict) -> None:
    for field in REQUIRED:
        if field not in fm or fm[field] in (None, "", []):
            err(page, f"Pflichtfeld fehlt oder leer: {field}")
    unknown = set(fm) - set(REQUIRED) - set(OPTIONAL)
    if unknown:
        err(page, f"unbekannte Frontmatter-Felder: {', '.join(sorted(unknown))}")

    if fm.get("type") not in TYPES:
        err(page, f"type '{fm.get('type')}' nicht erlaubt ({'/'.join(TYPES)})")
    elif page.parent.name != TYPES[fm["type"]]:
        err(page, f"type '{fm['type']}' gehoert in wiki/{TYPES[fm['type']]}/, "
                  f"liegt aber in wiki/{page.parent.name}/")
    if fm.get("domain") not in DOMAINS:
        err(page, f"domain '{fm.get('domain')}' nicht erlaubt ({'/'.join(sorted(DOMAINS))})")
    if fm.get("status") not in STATUS:
        err(page, f"status '{fm.get('status')}' nicht erlaubt ({'/'.join(sorted(STATUS))})")
    if not isinstance(fm.get("topics"), list) or not fm.get("topics"):
        err(page, "topics muss eine nicht-leere Liste sein")
    elif TOPICS:
        unknown_topics = [str(t) for t in fm["topics"] if str(t) not in TOPICS]
        if unknown_topics:
            err(page, f"topics nicht in kb.config.yaml: {', '.join(unknown_topics)} "
                      f"(neues Topic dort ergaenzen und im log.md vermerken)")

    created, updated = parse_date(fm.get("created")), parse_date(fm.get("updated"))
    if fm.get("created") is not None and created is None:
        err(page, f"created ist kein gueltiges Datum (YYYY-MM-DD): {fm.get('created')}")
    if fm.get("updated") is not None and updated is None:
        err(page, f"updated ist kein gueltiges Datum (YYYY-MM-DD): {fm.get('updated')}")
    if created and updated and updated < created:
        err(page, f"updated ({updated}) liegt vor created ({created})")


def check_sources(page: Path, fm: dict) -> None:
    sources = fm.get("sources")
    if not isinstance(sources, list) or not sources:
        return  # bereits als fehlendes Pflichtfeld gemeldet
    for src in sources:
        path_part = str(src).split("#", 1)[0].strip()
        if not path_part.startswith("raw/"):
            err(page, f"source zeigt nicht auf raw/: {src}")
        elif not (ROOT / path_part).is_file():
            err(page, f"source-Datei existiert nicht: {path_part}")


def check_wikilinks(page: Path, text: str, known: set[str]) -> None:
    for match in RE_WIKILINK.finditer(text):
        target = match.group(1).strip()
        if target and target not in known:
            err(page, f"kaputter Wikilink: [[{target}]]")


def check_related(page: Path, fm: dict, known: set[str]) -> None:
    related = fm.get("related")
    if related is None:
        return
    if not isinstance(related, list):
        err(page, "related muss eine Liste sein")
        return
    for entry in related:
        if str(entry).strip() not in known:
            err(page, f"related zeigt auf eine nicht existierende Seite: {entry}")


def check_claim_tags(page: Path, body: str) -> None:
    for match in RE_CLAIM.finditer(body):
        tag = match.group(1)
        if tag not in CLAIM_TAGS:
            err(page, f"unbekannter Claim-Tag: [{tag}]")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    pages = sorted(WIKI.rglob("*.md"))
    known = {p.stem for p in pages}
    dupes = {s for s in known if sum(1 for p in pages if p.stem == s) > 1}
    for d in sorted(dupes):
        errors.append(f"wiki/: Dateiname '{d}.md' existiert mehrfach (muss global eindeutig sein)")

    for page in pages:
        text = page.read_text(encoding="utf-8-sig")
        fm, body, fm_error = split_frontmatter(text)
        if fm_error:
            err(page, fm_error)
        if fm is not None:
            check_frontmatter(page, fm)
            check_sources(page, fm)
            check_related(page, fm, known)
        check_wikilinks(page, text, known)
        check_claim_tags(page, body)
        check_size(page, text)

    index = ROOT / "index.md"
    if index.is_file():
        check_wikilinks(index, index.read_text(encoding="utf-8-sig"), known)

    if errors:
        print(f"kb_lint: {len(errors)} Fehler in {len(pages)} Seiten\n")
        for line in errors:
            print(f"  FEHLER  {line}")
        return 1
    print(f"kb_lint: OK — {len(pages)} Seiten geprueft, keine Fehler" + (f", {len(warnings)} Warnung(en) (Lesbarkeit, nicht blockierend)" if warnings else ""))
    if warnings and "--warn" in sys.argv:
        for line in warnings:
            print(f"  WARNUNG {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
