#!/usr/bin/env python3
"""pdf.py — PDF-Quellen (Ausschreibungen, Lastenhefte, Handbuecher, Studien) deterministisch fuer die KB aufbereiten.

Ein Sprachmodell liest keine 300-Seiten-PDF am Stueck. Es arbeitet ueber dieses
Werkzeug: Text wortgetreu je Seite, Tabellen als CSV, Volltextsuche mit
Seitenangabe, einzelne Seiten als Bild. Der Extrakt ist die Quelle in raw/
(Invariante 1: nie bearbeiten); das Wiki zitiert ihn mit Seitenanker.

Aufrufe
-------
    python tools/pdf.py info    quelle.pdf
    python tools/pdf.py extract quelle.pdf --out raw/projekt-lastenheft
    python tools/pdf.py tables  quelle.pdf --pages 45-60 --out raw/projekt-lastenheft/tabellen
    python tools/pdf.py search  raw/projekt-lastenheft "Liefertermin|Frist"
    python tools/pdf.py page    quelle.pdf 112            Text einer Seite
    python tools/pdf.py page    quelle.pdf 112 --png      Seite als Bild (scratch/)

extract
    Je Kapitel der obersten Lesezeichen-Ebene eine Datei NN-<kapitel>.md, darin je
    Seite der Anker "## S. 45" (Zitat im Wiki: raw/<ordner>/<datei>.md#s-45).
    Ohne Lesezeichen: Bloecke zu 20 Seiten. Dazu 00-index.md mit Quelle, SHA-256,
    Kapiteln und Seiten ohne Textschicht. Idempotent: gleiche PDF -> identische
    Dateien. Existiert der Zielordner schon mit einem anderen Inhalt, bricht das
    Werkzeug ab (raw/ wird nie still ueberschrieben).

tables
    pdfplumber-Tabellen je Seite als S045_T1.csv (Semikolon, UTF-8 mit BOM fuer
    Excel). Zahlen aus Tabellen im Wiki immer aus der CSV, nie aus dem Fliesstext.

Normalisiert wird nur: Zeilenenden, weiches Trennzeichen U+00AD -> '-', geschuetzte
Leerzeichen U+00A0/U+202F -> ' '. Alle anderen Zeichen bleiben wortgetreu.

Seiten ohne Textschicht (gescannt) werden erkannt und gemeldet, aber nicht per
OCR gelesen - dafuer 'page --png' und Sichtpruefung; Aussagen daraus bleiben
[ANNAHME], bis sie gegengelesen sind.

Exit-Codes: 0 = ok, 1 = Fehler, 2 = abgelehnt (Schutz von raw/).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import re
import sys
from pathlib import Path

try:
    import pymupdf
except ImportError:
    try:
        import fitz as pymupdf  # aeltere Installationen
    except ImportError:
        sys.exit("PyMuPDF fehlt. Installation:  pip install --user pymupdf pdfplumber")

TOOL_VERSION = "1.0"
BLOCK_PAGES = 20           # Blockgroesse ohne Lesezeichen
SCAN_MIN_CHARS = 50        # weniger Zeichen + Bild auf der Seite = gescannt

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# --- Hilfen ------------------------------------------------------------------
def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def kebab(text: str, maxlen: int = 50) -> str:
    t = text.lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        t = t.replace(a, b)
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return (t[:maxlen].rstrip("-")) or "kapitel"


def clean(text: str) -> str:
    """Einzige Normalisierung: Zeilenenden auf \\n, weiches Trennzeichen U+00AD auf '-',
    geschuetzte Leerzeichen U+00A0 und U+202F auf ' '. Viele PDFs kodieren den sichtbaren Bindestrich
    als U+00AD und Leerzeichen als U+00A0; ohne Umsetzung findet eine Suche nach 'A-1.1' oder
    'bei -24' nichts. Alle anderen Zeichen bleiben unveraendert."""
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("­", "-").replace(" ", " ").replace(" ", " ")


def page_text(page) -> str:
    return clean(page.get_text("text"))


def is_scan(page) -> bool:
    return len(page_text(page).strip()) < SCAN_MIN_CHARS and bool(page.get_images(full=False))


def parse_pages(spec: str, n_pages: int) -> list[int]:
    out: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            lo, hi = int(a), int(b)
            out.update(range(lo, hi + 1))
        else:
            out.add(int(part))
    bad = [p for p in out if p < 1 or p > n_pages]
    if bad:
        raise ValueError(f"Seiten ausserhalb 1..{n_pages}: {sorted(bad)[:5]}")
    return sorted(out)


def open_pdf(path: str):
    p = Path(path)
    if not p.is_file():
        sys.exit(f"Datei nicht gefunden: {p}")
    return p, pymupdf.open(p)


# --- info --------------------------------------------------------------------
def cmd_info(args) -> int:
    p, doc = open_pdf(args.pdf)
    meta = doc.metadata or {}
    print(f"Datei:    {p.name}")
    print(f"Seiten:   {doc.page_count}")
    print(f"SHA-256:  {sha256(p)}")
    for key in ("title", "author", "subject", "creationDate"):
        if meta.get(key):
            print(f"{key:9} {meta[key]}")
    toc = doc.get_toc(simple=True)
    print(f"\nInhaltsverzeichnis (Lesezeichen): {len(toc)} Eintraege")
    for lvl, title, pg in toc:
        print(f"  {'  ' * (lvl - 1)}{title}  ... S. {pg}")
    scans = [i + 1 for i in range(doc.page_count) if is_scan(doc[i])]
    empty = [i + 1 for i in range(doc.page_count) if not page_text(doc[i]).strip() and (i + 1) not in scans]
    print(f"\nSeiten ohne Textschicht (Scan, OCR noetig): {scans or 'keine'}")
    if empty:
        print(f"Leere Seiten: {empty}")
    return 0


# --- extract -----------------------------------------------------------------
def segments(doc) -> list[tuple[str, int, int]]:
    """(Titel, erste Seite, letzte Seite), 1-basiert."""
    n = doc.page_count
    starts = sorted({(pg, title) for lvl, title, pg in doc.get_toc(simple=True) if lvl == 1 and 1 <= pg <= n}, key=lambda x: x[0])
    segs: list[tuple[str, int, int]] = []
    if starts:
        if starts[0][0] > 1:
            segs.append(("Vorspann", 1, starts[0][0] - 1))
        for i, (pg, title) in enumerate(starts):
            end = starts[i + 1][0] - 1 if i + 1 < len(starts) else n
            if end >= pg:
                segs.append((title, pg, end))
    else:
        for a in range(1, n + 1, BLOCK_PAGES):
            b = min(a + BLOCK_PAGES - 1, n)
            segs.append((f"Seiten {a:03d}-{b:03d}", a, b))
    return segs


def build_extract(p: Path, doc) -> dict[str, str]:
    digest = sha256(p)
    files: dict[str, str] = {}
    segs = segments(doc)
    scans = [i + 1 for i in range(doc.page_count) if is_scan(doc[i])]
    index_rows = []
    for k, (title, a, b) in enumerate(segs, start=1):
        name = f"{k:02d}-{kebab(title)}.md"
        parts = [
            f"# {title}\n",
            f"Quelle: `{p.name}`, Seiten {a}–{b}, SHA-256 `{digest[:16]}`. Wortgetreuer Textauszug (tools/pdf.py {TOOL_VERSION}) — nicht bearbeiten.\n",
        ]
        for pg in range(a, b + 1):
            page = doc[pg - 1]
            parts.append(f"## S. {pg}\n")
            if pg in scans:
                parts.append(f"_[Keine Textschicht, Seite ist ein Bild — OCR nötig. Ansicht: `python tools/pdf.py page {p.name} {pg} --png`]_\n")
            else:
                txt = page_text(page).rstrip()
                parts.append((txt if txt else "_[leere Seite]_") + "\n")
        files[name] = "\n".join(parts)
        index_rows.append(f"| {k:02d} | {title} | {a}–{b} | [{name}]({name}) |")
    index = [
        f"# Extrakt: {p.name}\n",
        f"- Quelle: `{p.name}`",
        f"- SHA-256: `{digest}`",
        f"- Seiten: {doc.page_count}",
        f"- Werkzeug: tools/pdf.py {TOOL_VERSION}",
        f"- Seiten ohne Textschicht (Scan): {', '.join(map(str, scans)) if scans else 'keine'}",
        "",
        "Wortgetreuer Textauszug je Seite. Nicht bearbeiten (Invariante 1). Zitieren mit Seitenanker, z. B. `datei.md#s-12`. Zahlen aus Tabellen aus den CSV-Dateien von `tools/pdf.py tables`.",
        "",
        "| Nr | Kapitel | Seiten | Datei |",
        "|---|---|---|---|",
        *index_rows,
        "",
    ]
    files["00-index.md"] = "\n".join(index)
    return files


def cmd_extract(args) -> int:
    p, doc = open_pdf(args.pdf)
    out = Path(args.out)
    files = build_extract(p, doc)
    if out.exists() and any(out.iterdir()):
        idx = out / "00-index.md"
        old = idx.read_text(encoding="utf-8") if idx.exists() else ""
        if f"`{sha256(p)}`" not in old:
            print(f"ABGELEHNT: {out} enthaelt bereits einen Extrakt einer anderen Datei (oder keinen 00-index.md). raw/ wird nicht ueberschrieben.", file=sys.stderr)
            return 2
        changed = [n for n, c in files.items() if not (out / n).exists() or (out / n).read_text(encoding="utf-8") != c]
        extra = sorted(f.name for f in out.glob("*.md") if f.name not in files)
        if not changed and not extra:
            print(f"unveraendert: {out} ({len(files)} Dateien, identisch)")
            return 0
        print(f"ABGELEHNT: gleiche PDF, aber abweichende Dateien in {out}: {changed or ''} {extra or ''}. Ursache pruefen (Werkzeugversion?), dann Ordner bewusst neu anlegen.", file=sys.stderr)
        return 2
    out.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (out / name).write_text(content, encoding="utf-8", newline="\n")
    print(f"{len(files) - 1} Kapiteldateien + 00-index.md nach {out}")
    for name in sorted(files):
        print(f"  {name}")
    return 0


# --- tables ------------------------------------------------------------------
def cmd_tables(args) -> int:
    try:
        import pdfplumber
    except ImportError:
        sys.exit("pdfplumber fehlt. Installation:  pip install --user pdfplumber")
    p = Path(args.pdf)
    if not p.is_file():
        sys.exit(f"Datei nicht gefunden: {p}")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    found = 0
    with pdfplumber.open(p) as pdf:
        pages = parse_pages(args.pages, len(pdf.pages)) if args.pages else list(range(1, len(pdf.pages) + 1))
        for pg in pages:
            for t, table in enumerate(pdf.pages[pg - 1].extract_tables(), start=1):
                rows = [["" if c is None else clean(str(c)).replace("\n", " ").strip() for c in row] for row in table]
                name = out / f"S{pg:03d}_T{t}.csv"
                with name.open("w", encoding="utf-8-sig", newline="") as f:
                    csv.writer(f, delimiter=";").writerows(rows)
                cols = max((len(r) for r in rows), default=0)
                print(f"S. {pg:>4}  Tabelle {t}: {len(rows)} Zeilen x {cols} Spalten -> {name}")
                found += 1
    print(f"{found} Tabelle(n) gefunden")
    return 0


# --- search ------------------------------------------------------------------
def iter_pages(target: Path):
    """(Seite, Datei, Zeilen) aus PDF oder Extrakt-Ordner."""
    if target.is_dir():
        for f in sorted(target.glob("*.md")):
            if f.name == "00-index.md":
                continue
            cur, buf = None, []
            for line in f.read_text(encoding="utf-8").split("\n"):
                m = re.match(r"^## S\. (\d+)$", line)
                if m:
                    if cur is not None:
                        yield cur, f.name, buf
                    cur, buf = int(m.group(1)), []
                elif cur is not None:
                    buf.append(line)
            if cur is not None:
                yield cur, f.name, buf
    else:
        doc = pymupdf.open(target)
        for i in range(doc.page_count):
            yield i + 1, target.name, page_text(doc[i]).split("\n")


def cmd_search(args) -> int:
    target = Path(args.target)
    if not target.exists():
        sys.exit(f"Nicht gefunden: {target}")
    rx = re.compile(args.pattern, re.IGNORECASE)
    hits = 0
    for pg, fname, lines in iter_pages(target):
        for i, line in enumerate(lines):
            if rx.search(line):
                hits += 1
                lo, hi = max(0, i - args.context), min(len(lines), i + args.context + 1)
                print(f"S. {pg} ({fname}#s-{pg}):")
                for j in range(lo, hi):
                    print(f"  {'>' if j == i else ' '} {lines[j]}")
    print(f"{hits} Treffer")
    return 0


# --- page --------------------------------------------------------------------
def cmd_page(args) -> int:
    p, doc = open_pdf(args.pdf)
    if not 1 <= args.n <= doc.page_count:
        sys.exit(f"Seite {args.n} ausserhalb 1..{doc.page_count}")
    page = doc[args.n - 1]
    if args.png:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        target = out / f"{p.stem}_S{args.n:03d}.png"
        page.get_pixmap(dpi=args.dpi).save(target)
        print(target)
    else:
        if is_scan(page):
            print(f"[Seite {args.n} hat keine Textschicht — mit --png ansehen]")
        print(page_text(page))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="PDF-Quellen fuer die KB aufbereiten (read-only gegenueber der PDF).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("info"); s.add_argument("pdf"); s.set_defaults(func=cmd_info)
    s = sub.add_parser("extract"); s.add_argument("pdf"); s.add_argument("--out", required=True); s.set_defaults(func=cmd_extract)
    s = sub.add_parser("tables"); s.add_argument("pdf"); s.add_argument("--pages", default=""); s.add_argument("--out", required=True); s.set_defaults(func=cmd_tables)
    s = sub.add_parser("search"); s.add_argument("target"); s.add_argument("pattern"); s.add_argument("--context", type=int, default=1); s.set_defaults(func=cmd_search)
    s = sub.add_parser("page"); s.add_argument("pdf"); s.add_argument("n", type=int); s.add_argument("--png", action="store_true"); s.add_argument("--dpi", type=int, default=150); s.add_argument("--out", default="scratch"); s.set_defaults(func=cmd_page)
    args = ap.parse_args()
    try:
        return args.func(args)
    except ValueError as e:
        print(f"Fehler: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
