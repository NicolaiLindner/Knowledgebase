#!/usr/bin/env python3
"""kb_dream.py — Konsolidierungslauf ("Traum") der Wissensbasis.

Liest log.md (episodisch), review-queue.md, das Wiki (semantisch), Git und —
nur mit eingeschaltetem Modul Datenbank (kb.config.yaml) und wenn erreichbar — die Datenbank, und schreibt GENAU EINE Datei:
traeume/YYYY-MM-DD.md. Sonst nichts. Der Traum aendert kein Wissen
(CLAUDE.md, Invariante 10); Umsetzen ist die Wachsitzung.

Jeder Befund traegt drei getrennte Felder: Beobachtung (messbar),
Interpretation (Deutung), Vorschlag (Handlung) — plus Konfidenz und Belege.
Die Wachsitzung notiert im log.md je Vorschlags-ID (T-YYYY-MM-DD-NN):
    T-... umgesetzt (wert: hoch|mittel|niedrig)
    T-... verworfen: Beobachtung falsch | Interpretation falsch | Vorschlag schlecht
    T-... vertagt | T-... in Queue
Der naechste Traum rechnet daraus Precision / Adoption / Value je Kategorie.

Aufruf:
  python tools/kb_dream.py [--since YYYY-MM-DD] [--no-db] [--out PFAD] [--stdout] [--bilanz] [--lage]
Exit 0 = Protokoll geschrieben (DB-Ausfall ist kein Fehler)
Exit 1 = Parse-/Laufzeitfehler
Exit 2 = Zieldatei existiert bereits committet (Hinweis: --out traeume/<datum>-2.md)

Fachliche Einordnung: CLAUDE.md, Workflow "Traeumen (Konsolidierungslauf)".
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kb_config as C  # noqa: E402
import kb_lint as L  # noqa: E402  (nur die seiteneffektfreien Helfer)

ROOT, WIKI = L.ROOT, L.WIKI
TRAEUME = ROOT / "traeume"
LOG = ROOT / "log.md"
QUEUE = ROOT / "review-queue.md"
INDEX = ROOT / "index.md"

STALE_DAYS = 30
WINDOW_DEFAULT_DAYS = 30
MOC_THRESHOLD = 50
MOC_WARN = 45
MAX_PER_GROUP = 15            # Maschinendatei: mehr als so viele je Gruppe werden abgeschnitten
TID_GROUPS = {"Queue-Triage: Erledigungskandidaten"}   # nur diese mechanischen Befunde bekommen T-IDs
MAX_TID_PER_GROUP = 12        # Deckel fuer nummerierte Befunde im Protokoll
MAX_TEASER = 3                # Beispiele je Zaehlergruppe im Protokoll
LAGE_LOG_ENTRIES = 5          # --lage: so viele letzte Log-Eintraege
RE_OPEN_LINE = re.compile(r"^\s*-\s*(Offen|Naechste Schritte|Naechster Schritt|Nächste Schritte|Nächster Schritt)\b", re.I)
DRIFT_TOL = timedelta(minutes=2)
HUB_PAGES = C.HUB_PAGES       # kb.config.yaml: hub_seiten
DB_MODULE = C.DB_MODULE       # kb.config.yaml: module.datenbank

RE_LOG_HEAD = re.compile(r"^## (\d{4}-\d{2}-\d{2})\s*[—–-]+\s*(.+?)\s*$")
RE_QUEUE = re.compile(r"^- \[( |x)\] (\d{4}-\d{2}-\d{2}) \| ([^|]+) \| (.*)$")
# Typwort (optional, drittes Feld): PRUEFEN = Datenpruefung durch den Agenten,
# ENTSCHEIDUNG = braucht Nutzer/Kollegen, NACHZUG = Folgeaenderung nach getroffener Entscheidung, DOKU = nur dokumentieren
QUEUE_TYPES = {"PRUEFEN", "ENTSCHEIDUNG", "NACHZUG", "DOKU"}
RE_WAITS = re.compile(r"\bwartet:\s*(Nutzer|Kollegen|Deploy)\b", re.I)
RE_OBJECT = re.compile(r"\b(?:(?:dbo|cfg)\.)?(?:v_|usp_|sf_)[A-Za-z0-9_]+\b|\bcfg\.[A-Za-z0-9_]+\b")
RE_SQLFILE = re.compile(r"sql/(?:objects|config)/[A-Za-z0-9_.]+\.sql")
RE_TID = re.compile(r"\bT-\d{4}-\d{2}-\d{2}-\d{2,3}\b")
RE_TID_STATUS = re.compile(
    r"\b(T-\d{4}-\d{2}-\d{2}-\d{2,3})\s+(umgesetzt|verworfen|vertagt|in Queue)"
    r"(?:\s*\(wert:\s*(hoch|mittel|niedrig)\))?"
    r"(?::\s*(Beobachtung falsch|Interpretation falsch|Vorschlag schlecht))?",
    re.IGNORECASE)
RE_QUEUE_BACKREF = re.compile(r"Queue(?:-Eintrag|-Punkt)?(?:\s+vom)?\s+(\d{2})\.(\d{2})\.")
RE_NOT_DEPLOYED = re.compile(r"nicht\s+(?:deployt|eingespielt)|neu\s+deployt", re.I)
RE_BACKTICK = re.compile(r"`([^`\n]+)`")
RE_RESOLVED = re.compile(
    r"\b(erledigt|entschieden|gebaut|beantwortet|geklaert|geklärt|aufgeloest|aufgelöst|umgesetzt|korrigiert)\b", re.I)
RE_WAITS_USER = re.compile(r"\b(entscheiden|klaeren|klären|Nutzer|User)\b", re.I)
RE_NOT_RESOLVED = re.compile(r"umsetzbar|bleibt offen|weiter offen|noch offen|nachziehen|nachzuziehen", re.I)
RE_GENERAL_HINT = re.compile(r"uebertragbar|übertragbar|Fallstrick|Fehlerbild|Muster|Betriebsregel", re.I)
RE_USER_SIGNAL = re.compile(
    r"Nutzerfrage|Nutzerauftrag|Nutzerhinweis|Nutzerkorrektur|Nutzerwunsch|Nachfrage des Nutzers|Kollegen", re.I)
RE_GAP_SIGNAL = re.compile(
    r"steht nicht im Wiki|im Wiki nicht dokumentiert|nirgends dokumentiert|hatte keinen Einstiegspunkt"
    r"|stand (?:bisher )?(?:nirgends|nur)", re.I)
RE_DATE_IN_LINE = re.compile(r"\d{2}\.\d{2}\.\d{4}|\d{4}-\d{2}-\d{2}")
RE_TOKEN_ALLCAPS = re.compile(r"\b[A-Z][A-Z_0-9]{4,}\b")
RE_QUOTED = re.compile(r"'([^'\n]{3,60})'")
RE_ADR = re.compile(r"\b[Aa][Dd][Rr]-\d{3}\b")
RE_FINDING_LINE = re.compile(r"^- (T-\d{4}-\d{2}-\d{2}-\d{2,3})\s+(?:\[(V-[A-Z]+)\]\s+)?")

# Tokens, die als Beleg nichts taugen: SQL-Schluesselwoerter, Claim-Tags,
# ALLCAPS-Alltagswoerter. Nur Bezeichner (v_..., KUNDENNR, ADR-007) zaehlen.
STOPWORDS = {
    "SELECT", "FROM", "WHERE", "JOIN", "INNER", "OUTER", "LEFT", "RIGHT", "CROSS", "APPLY",
    "GROUP", "ORDER", "HAVING", "UNION", "DISTINCT", "VALUES", "INSERT", "UPDATE", "DELETE",
    "CREATE", "ALTER", "DROP", "TABLE", "VIEW", "INDEX", "EXISTS", "ISNULL", "COALESCE",
    "NULLIF", "CASE", "WHEN", "THEN", "ELSE", "BETWEEN", "EXEC", "EXECUTE", "TRUNCATE",
    "CEILING", "FLOOR", "COUNT", "SUM", "AVG", "MAX", "MIN", "CAST", "CONVERT", "PARTITION",
    "OVER", "WITH", "NOLOCK", "TOP", "IIF", "DECLARE", "BEGIN", "RETURN", "PRINT",
    "NICHT", "KEINE", "KEIN", "ALLE", "NULL", "BEWUSST", "GEMESSEN", "WARNUNG", "ERSTEN",
    "ACHTUNG", "STOPP", "HINWEIS", "PFLICHT", "MUSS", "IMMER", "NIE", "ENTSCHIEDEN",
    "OFFEN", "FAKT", "ENTSCHEIDUNG", "ERFAHRUNG", "ANNAHME", "HISTORISCH",
    "ASCII", "UTF", "CSV", "SSMS", "PDF", "XLSX",
}
DF_MAX_DISCRIMINATIVE = 10   # Tokens, die in mehr Log-Eintraegen vorkommen, belegen nichts
DF_RARE = 3


# --- Datenklassen -----------------------------------------------------------
@dataclass
class Page:
    stem: str
    path: Path
    fm: dict
    body: str
    text: str
    domain: str
    ptype: str
    status: str
    created: date | None
    updated: date | None
    links_out: set = field(default_factory=set)
    claims: Counter = field(default_factory=Counter)
    offen_lines: list = field(default_factory=list)      # (lineno, text)
    erfahrung_lines: list = field(default_factory=list)


@dataclass
class LogEntry:
    date: date
    title: str
    line_start: int
    line_end: int
    text: str
    pages: set = field(default_factory=set)
    objects: set = field(default_factory=set)
    sql_files: set = field(default_factory=set)
    tags: Counter = field(default_factory=Counter)
    not_deployed: bool = False
    user_signals: list = field(default_factory=list)   # (lineno, text)
    gap_signals: list = field(default_factory=list)
    tids: dict = field(default_factory=dict)           # tid -> (status, wert, grund)


@dataclass
class QueueEntry:
    line: int
    done: bool
    date: date
    pages: list
    reason: str
    resolution: str
    tokens: set = field(default_factory=set)
    backrefs: list = field(default_factory=list)       # date
    waits_user: bool = False
    tids: dict = field(default_factory=dict)
    typ: str = ""                                      # PRUEFEN | ENTSCHEIDUNG | NACHZUG | DOKU | ""
    waits: str = ""                                    # Nutzer | Kollegen | Deploy | ""


@dataclass
class Finding:
    kind: str
    observation: str
    interpretation: str
    suggestion: str
    confidence: str            # hoch | mittel | niedrig | Info
    evidence: list = field(default_factory=list)
    pages: list = field(default_factory=list)
    in_queue: list = field(default_factory=list)
    tid: str = ""


NOTES: list[str] = []          # Hinweise fuer den Protokollkopf (z. B. DB nicht erreichbar)


def note(msg: str) -> None:
    NOTES.append(msg)


# --- Sammler ----------------------------------------------------------------
def read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def collect_pages() -> dict[str, Page]:
    pages: dict[str, Page] = {}
    for path in sorted(WIKI.rglob("*.md")):
        text = read(path)
        fm, body, fm_err = L.split_frontmatter(text)
        if fm_err or fm is None:
            note(f"Seite ohne lesbares Frontmatter uebersprungen (kb_lint zustaendig): {path.name}")
            continue
        links = {m.group(1).strip() for m in L.RE_WIKILINK.finditer(text)}
        for rel in fm.get("related") or []:
            links.add(str(rel).strip())
        page = Page(
            stem=path.stem, path=path, fm=fm, body=body, text=text,
            domain=str(fm.get("domain", "")), ptype=str(fm.get("type", "")),
            status=str(fm.get("status", "")),
            created=L.parse_date(fm.get("created")), updated=L.parse_date(fm.get("updated")),
            links_out=links, claims=Counter(m.group(1) for m in L.RE_CLAIM.finditer(body)),
        )
        for lineno, line in enumerate(text.splitlines(), 1):
            s = line.strip()
            if s.startswith("- [OFFEN]"):
                page.offen_lines.append((lineno, s))
            elif s.startswith("- [ERFAHRUNG]"):
                page.erfahrung_lines.append((lineno, s))
        pages[page.stem] = page
    return pages


def build_link_graph(pages: dict[str, Page]) -> tuple[dict[str, set], set]:
    incoming: dict[str, set] = defaultdict(set)
    for p in pages.values():
        for t in p.links_out:
            if t != p.stem and t in pages:
                incoming[t].add(p.stem)
    in_index: set = set()
    if INDEX.is_file():
        in_index = {m.group(1).strip() for m in L.RE_WIKILINK.finditer(read(INDEX))}
    return incoming, in_index


def tids_in(text: str) -> dict:
    found: dict = {}
    for m in RE_TID_STATUS.finditer(text):
        found[m.group(1).upper()] = (m.group(2).lower(), (m.group(3) or "").lower(), (m.group(4) or ""))
    for m in RE_TID.finditer(text):
        found.setdefault(m.group(0), ("erwaehnt", "", ""))
    return found


def parse_log_entries(pages: dict[str, Page]) -> list[LogEntry]:
    lines = read(LOG).splitlines()
    heads = [(i + 1, m) for i, ln in enumerate(lines) if (m := RE_LOG_HEAD.match(ln))]
    entries: list[LogEntry] = []
    for idx, (lineno, m) in enumerate(heads):
        end = heads[idx + 1][0] - 1 if idx + 1 < len(heads) else len(lines)
        text = "\n".join(lines[lineno - 1:end])
        e = LogEntry(date=date.fromisoformat(m.group(1)), title=m.group(2),
                     line_start=lineno, line_end=end, text=text)
        e.pages = {t.strip() for t in
                   (x.group(1) for x in L.RE_WIKILINK.finditer(text)) if t.strip() in pages}
        e.pages |= {t for t in (x.group(1).strip() for x in RE_BACKTICK.finditer(text)) if t in pages}
        e.objects = {norm_object(x) for x in RE_OBJECT.findall(text)}
        e.sql_files = set(RE_SQLFILE.findall(text))
        e.tags = Counter(x.group(1) for x in L.RE_CLAIM.finditer(text))
        e.not_deployed = bool(RE_NOT_DEPLOYED.search(text))
        for off, ln in enumerate(lines[lineno - 1:end]):
            if RE_USER_SIGNAL.search(ln):
                e.user_signals.append((lineno + off, ln.strip()))
            if RE_GAP_SIGNAL.search(ln):
                e.gap_signals.append((lineno + off, ln.strip()))
        e.tids = tids_in(text)
        entries.append(e)
    return entries


def norm_object(name: str) -> str:
    """dbo.v_X / v_X -> v_X ; cfg.Best_VolGr bleibt cfg.Best_VolGr."""
    if name.startswith("dbo."):
        return name[4:]
    return name


def parse_queue_entries(pages: dict[str, Page]) -> list[QueueEntry]:
    entries: list[QueueEntry] = []
    for lineno, ln in enumerate(read(QUEUE).splitlines(), 1):
        m = RE_QUEUE.match(ln)
        if not m:
            continue
        field3 = m.group(3).strip()
        rest = m.group(4).strip()
        typ = ""
        if field3.upper() in QUEUE_TYPES and " | " in rest:
            # neues Format: Datum | TYP | seiten | Grund
            typ = field3.upper()
            field3, _, rest = rest.partition(" | ")
        reason_full = rest.strip()
        reason, _, resolution = reason_full.partition(" -- ")
        q = QueueEntry(line=lineno, done=(m.group(1) == "x"), date=date.fromisoformat(m.group(2)),
                       pages=[p.strip() for p in field3.split(",") if p.strip()],
                       reason=reason.strip(), resolution=resolution.strip(), typ=typ)
        mw = RE_WAITS.search(q.reason)
        q.waits = mw.group(1).capitalize() if mw else ""
        toks = {norm_object(x) for x in RE_OBJECT.findall(q.reason)}
        toks |= {x.strip() for x in RE_QUOTED.findall(q.reason)}
        toks |= set(RE_TOKEN_ALLCAPS.findall(q.reason))
        toks |= {x.upper() for x in RE_ADR.findall(q.reason)}
        q.tokens = {t for t in toks
                    if len(t) >= 4 and t.upper() not in STOPWORDS
                    and "(" not in t and ")" not in t and any(ch.isalpha() for ch in t)}
        for d, mo in RE_QUEUE_BACKREF.findall(reason_full):
            try:
                q.backrefs.append(date(q.date.year, int(mo), int(d)))
            except ValueError:
                pass
        q.waits_user = bool(q.waits) or bool(RE_WAITS_USER.search(q.reason))
        q.tids = tids_in(reason_full)
        unknown = [p for p in q.pages if p not in pages]
        if unknown and not q.done:
            note(f"Queue Z.{lineno} nennt unbekannte Seite(n): {', '.join(unknown)}")
        entries.append(q)
    return entries


def git_last_commit_dates() -> dict[str, datetime]:
    try:
        out = subprocess.run(
            ["git", "log", "--format=%x00%cI", "--name-only", "--", "sql/objects", "sql/config"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        note(f"git nicht abfragbar: {exc}")
        return {}
    dates: dict[str, datetime] = {}
    current: datetime | None = None
    for ln in out.splitlines():
        if ln.startswith("\x00"):
            current = datetime.fromisoformat(ln[1:].strip()).replace(tzinfo=None)
        elif ln.strip() and current is not None:
            dates.setdefault(ln.strip(), current)
    return dates


def db_object_dates(timeout_s: int = 10) -> dict[str, tuple[datetime, str]] | None:
    try:
        import sql as kbsql  # tools/sql.py — ruft sys.exit(), wenn pyodbc fehlt
    except SystemExit:
        note("DB-Abgleich uebersprungen: pyodbc fehlt")
        return None
    except Exception as exc:  # noqa: BLE001
        note(f"DB-Abgleich uebersprungen: {exc}")
        return None
    try:
        conn, cur = kbsql.connect(timeout_s)
        kbsql.become_reader(cur)
        cur.execute(kbsql.SQL_LIST, "%")
        rows = cur.fetchall()
        conn.close()
    except (SystemExit, Exception) as exc:  # noqa: BLE001
        note(f"DB nicht erreichbar — Deploy-Abgleich nur aus Log/Git: {str(exc)[:120]}")
        return None
    result: dict[str, tuple[datetime, str]] = {}
    for r in rows:
        try:
            result[f"{r[0]}.{r[1]}"] = (datetime.strptime(str(r[3]), "%Y-%m-%d %H:%M"), str(r[2]))
        except (ValueError, TypeError):
            continue
    return result


# --- Hilfen -----------------------------------------------------------------
def fmt_pages(stems) -> str:
    return ", ".join(f"[[{s}]]" for s in stems)


def queue_lines_for(pages_: list[str], queue: list[QueueEntry], exclude: int | None = None) -> list[int]:
    ps = set(pages_)
    return [q.line for q in queue if not q.done and q.line != exclude and ps & set(q.pages)]


def cap(items: list, group: str) -> tuple[list, str]:
    if len(items) > MAX_PER_GROUP:
        return items[:MAX_PER_GROUP], f"… und {len(items) - MAX_PER_GROUP} weitere ({group})"
    return items, ""


def token_df(entries: list[LogEntry]) -> Counter:
    """Dokumentfrequenz: in wie vielen Log-Eintraegen kommt ein Token vor."""
    df: Counter = Counter()
    for e in entries:
        low = e.text.lower()
        for t in ALL_TOKENS:
            if t.lower() in low:
                df[t] += 1
    return df


ALL_TOKENS: set = set()


# --- Checks -----------------------------------------------------------------
def check_queue_triage(queue: list[QueueEntry], log: list[LogEntry], pages: dict[str, Page],
                       today: date) -> tuple[list[Finding], list[Finding]]:
    global ALL_TOKENS
    ALL_TOKENS = set().union(*(q.tokens for q in queue)) if queue else set()
    df = token_df(log)
    candidates: list[Finding] = []
    stale: list[Finding] = []
    per_page: Counter = Counter()
    for q in queue:
        if q.done:
            continue
        for p in q.pages:
            per_page[p] += 1
        # E1: Zielseite nach Eintragsdatum aktualisiert
        e1 = [f"{p} updated {pages[p].updated}" for p in q.pages
              if p in pages and pages[p].updated and pages[p].updated > q.date]
        # E2: spaeterer Log-Eintrag mit Token-Treffern
        e2: list[str] = []
        for e in log:
            if e.date < q.date:
                continue
            low = e.text.lower()
            hits = [t for t in q.tokens if t.lower() in low and df[t] <= DF_MAX_DISCRIMINATIVE]
            rare = [t for t in hits if df[t] <= DF_RARE]
            if len(hits) >= 2 or rare:
                shown = ", ".join(f"{t} (df={df[t]})" for t in sorted(hits)[:4])
                e2.append(f"log {e.date} Z.{e.line_start} '{e.title[:60]}' — {shown}")
        # E3: spaeterer Queue-Eintrag mit Rueckverweis auf das Datum. Stark, wenn er
        # den Ursprungseintrag zitiert oder einen seltenen Bezeichner teilt;
        # schwach, wenn nur das Datum und eine Seite passen (Datum ist oft
        # mehrdeutig). "umsetzbar / bleibt offen" ist keine Erledigung.
        e3_strong: list[str] = []
        e3_weak: list[str] = []
        same_day = sum(1 for x in queue if not x.done and x.date == q.date)
        for o in queue:
            if o.line == q.line or o.date < q.date or q.date not in o.backrefs:
                continue
            if not (set(o.pages) & set(q.pages)):
                continue
            if RE_NOT_RESOLVED.search(o.reason) and not RE_RESOLVED.search(o.reason):
                continue
            word = RE_RESOLVED.search(o.reason)
            q_low = q.reason.lower()
            quotes = [z for z in RE_QUOTED.findall(o.reason) if z.lower()[:40] in q_low]
            shared = [t for t in (q.tokens & o.tokens) if df[t] <= DF_MAX_DISCRIMINATIVE]
            if word and (quotes or shared):
                e3_strong.append(f"Queue Z.{o.line} ({o.date}) verweist auf {q.date:%d.%m.}, sagt "
                                 f"'{word.group(1)}' und nennt {('Zitat ' + repr(quotes[0][:40])) if quotes else ', '.join(sorted(shared)[:3])}")
            elif word:
                e3_weak.append(f"Queue Z.{o.line} ({o.date}) verweist auf {q.date:%d.%m.} ('{word.group(1)}') — "
                               f"mehrdeutig, Datum passt auf {same_day} Eintraege")
        e3 = e3_strong + e3_weak
        if e3_strong or (e2 and e1):
            conf = "hoch"
        elif e2 or e3_weak:
            conf = "mittel"
        else:
            conf = ""
        if conf:
            sammel = ";" in q.reason or q.reason.count(",") >= 3
            evidence = [f"[E3] {x}" for x in e3] + [f"[E2] {x}" for x in e2[:3]] + \
                       ([f"[E1] {', '.join(e1)}"] if e1 else ["[E1] keine Zielseite seither aktualisiert"])
            candidates.append(Finding(
                kind="queue-erledigt",
                observation=f"Queue Z.{q.line} ({q.date}, {', '.join(q.pages)}): "
                            f"{len(e3)} Rueckverweis(e), {len(e2)} spaetere Log-Treffer, "
                            f"{len(e1)} aktualisierte Zielseite(n)",
                interpretation="Eintrag ist wahrscheinlich erledigt" + (
                    " — Sammel-Eintrag, vermutlich nur teilweise" if sammel else ""),
                suggestion="In Wachsitzung pruefen und mit Beleg abhaken ([x] + ' -- ' Resolution)"
                           + ("; Teilerledigung benennen, Rest stehen lassen" if sammel else ""),
                confidence=conf, evidence=evidence, pages=list(q.pages),
                in_queue=queue_lines_for(q.pages, queue, exclude=q.line)[:6]))
        elif (today - q.date).days > STALE_DAYS and not e1:
            stale.append(Finding(
                kind="queue-veraltet",
                observation=f"Queue Z.{q.line} ({q.date}, {', '.join(q.pages)}): {(today - q.date).days} Tage alt, "
                            f"keine Zielseite seither aktualisiert, keine Log-Treffer",
                interpretation="Vermutlich vergessen" + (
                    " — oder wartet auf eine Nutzerentscheidung" if q.waits_user else ""),
                suggestion="Triage: jetzt machen, bewusst schliessen (mit Begruendung) oder stehen lassen",
                confidence="niedrig", evidence=[q.reason[:120]], pages=list(q.pages), in_queue=[q.line]))
    clusters = [Finding(
        kind="queue-cluster",
        observation=f"{p}: {n} offene Queue-Eintraege (Z."
                    f"{', '.join(str(q.line) for q in queue if not q.done and p in q.pages)})",
        interpretation="Die Seite sammelt unerledigte Arbeit",
        suggestion="Eintraege gemeinsam abarbeiten — ein Nachzug der Seite loest vermutlich mehrere",
        confidence="Info", pages=[p]) for p, n in per_page.most_common() if n >= 4]
    return candidates, stale + clusters


def check_backlog_pages(pages: dict[str, Page], queue: list[QueueEntry], log: list[LogEntry]) -> list[Finding]:
    out: list[Finding] = []
    for p in pages.values():
        if not p.updated:
            continue
        gt = [q for q in queue if not q.done and p.stem in q.pages and q.date > p.updated]
        ge = [q for q in queue if not q.done and p.stem in q.pages and q.date >= p.updated]
        mentions = [e for e in log if e.date > p.updated and p.stem in e.pages]
        if len(gt) >= 3:
            out.append(Finding(
                kind="rueckstau", confidence="hoch",
                observation=f"{p.stem}: updated {p.updated}, danach {len(gt)} offene Queue-Eintraege "
                            f"(Z.{', '.join(str(q.line) for q in gt)}; inkl. gleichen Tags: {len(ge)})",
                interpretation="Seite ist wahrscheinlich fachlich zurueckgefallen",
                suggestion="Nachzug in einer Wachsitzung buendeln; die Queue-Eintraege danach mit Beleg schliessen",
                evidence=[f"Log-Nennungen seit updated: {len(mentions)}"], pages=[p.stem],
                in_queue=[q.line for q in gt]))
        elif len(mentions) >= 3:
            out.append(Finding(
                kind="rueckstau", confidence="mittel",
                observation=f"{p.stem}: updated {p.updated}, seither in {len(mentions)} Log-Eintraegen genannt "
                            f"({', '.join(str(e.date) for e in mentions[:5])})",
                interpretation="Die Seite wird benutzt, aber nicht gepflegt — moeglicherweise nur Verweise",
                suggestion="Pruefen, ob die genannten Aenderungen auf die Seite gehoeren",
                evidence=[f"log Z.{e.line_start} '{e.title[:50]}'" for e in mentions[:3]], pages=[p.stem],
                in_queue=queue_lines_for([p.stem], queue)))
    out.sort(key=lambda f: (f.confidence != "hoch", f.pages[0]))
    return out


def check_link_hygiene(pages: dict[str, Page], incoming: dict[str, set], in_index: set,
                       window: list[LogEntry], today: date) -> list[Finding]:
    out: list[Finding] = []
    mentions: Counter = Counter()
    for e in window:
        mentions.update(e.pages)
    for p in pages.values():
        n_in = len(incoming.get(p.stem, ()))
        age = (today - p.created).days if p.created else 999
        if n_in <= 1 and (age > 7 or mentions[p.stem] >= 3):
            out.append(Finding(
                kind="link-arm",
                confidence="hoch" if (n_in == 0 or mentions[p.stem] >= 3) else "niedrig",
                observation=f"{p.stem}: {n_in} eingehende Wiki-Links"
                            f"{' (nur index.md)' if n_in == 0 and p.stem in in_index else ''}, "
                            f"{mentions[p.stem]} Log-Nennungen im Fenster, Alter {age} Tage",
                interpretation="Die Seite ist ueber die Navigation kaum erreichbar — Wissen ohne Anschluss",
                suggestion="Von den fachlich naechsten Seiten verlinken (related: und im Text)",
                pages=[p.stem]))
    pairs: Counter = Counter()
    for e in window:
        ps = sorted(s for s in e.pages if s not in HUB_PAGES)
        if 2 <= len(ps) <= 6:
            for i in range(len(ps)):
                for j in range(i + 1, len(ps)):
                    pairs[(ps[i], ps[j])] += 1
    for (a, b), n in pairs.most_common():
        if n >= 2 and b not in pages[a].links_out and a not in pages[b].links_out:
            out.append(Finding(
                kind="link-paar", confidence="mittel",
                observation=f"{a} und {b}: in {n} Log-Eintraegen gemeinsam bearbeitet, in keiner Richtung verlinkt",
                interpretation="Fachlich zusammengehoerig, aber im Wiki unverbunden",
                suggestion="Querverweis in beide Richtungen setzen, sofern die Naehe fachlich ist",
                pages=[a, b]))
    n = len(pages)
    if n >= MOC_WARN:
        out.append(Finding(
            kind="moc", confidence="Info",
            observation=f"{n} von {MOC_THRESHOLD} Seiten (MOC-Schwelle laut CLAUDE.md)",
            interpretation="index.md naehert sich der Unuebersichtlichkeit",
            suggestion="moc-<ordner>.md je Ordner vorbereiten", pages=[]))
    return out


def check_deploy_drift(git_dates: dict[str, datetime], db: dict | None, window: list[LogEntry]) -> list[Finding]:
    out: list[Finding] = []
    repo_objects = {}
    for path, dt in git_dates.items():
        name = Path(path).name
        if name.endswith(".sql") and name.count(".") >= 2:
            repo_objects[name[:-4]] = (path, dt)
    if db is not None:
        for key, (path, repo_dt) in sorted(repo_objects.items()):
            if key in db:
                db_dt, typ = db[key]
                if repo_dt > db_dt + DRIFT_TOL:
                    out.append(Finding(
                        kind="deploy-drift", confidence="hoch",
                        observation=f"{key}: Repo-Commit {repo_dt:%Y-%m-%d %H:%M} > DB-Aenderung {db_dt:%Y-%m-%d %H:%M}",
                        interpretation="Kanonische Datei ist neuer als das deployte Objekt — nicht deployt",
                        suggestion=f"Datei {path} in SSMS ausfuehren (Reihenfolge laut Kopfkommentar)",
                        evidence=[f"DB-Typ {typ}"]))
                elif db_dt > repo_dt + DRIFT_TOL:
                    out.append(Finding(
                        kind="deploy-drift", confidence="hoch",
                        observation=f"{key}: DB-Aenderung {db_dt:%Y-%m-%d %H:%M} > Repo-Commit {repo_dt:%Y-%m-%d %H:%M}",
                        interpretation="Das Objekt wurde in der DB veraendert, ohne dass das Repo nachgezogen wurde",
                        suggestion="DDL vergleichen (tools/sql.py --ddl) und die kanonische Datei angleichen",
                        evidence=[f"DB-Typ {typ}"]))
            else:
                out.append(Finding(
                    kind="deploy-drift", confidence="hoch",
                    observation=f"{key}: im Repo ({repo_dt:%Y-%m-%d}), in der DB nicht vorhanden",
                    interpretation="Objekt wurde nie deployt",
                    suggestion=f"Datei {path} in SSMS ausfuehren"))
        unkanon = [k for k, (dt, typ) in db.items()
                   if k not in repo_objects and (typ in ("VIEW", "SQL_STORED_PROCEDURE") or k.startswith("cfg."))]
        if unkanon:
            shown = ", ".join(sorted(unkanon)[:10]) + (" …" if len(unkanon) > 10 else "")
            out.append(Finding(
                kind="nicht-kanonisiert", confidence="Info",
                observation=f"{len(unkanon)} Views/Prozeduren/cfg-Objekte in der DB ohne kanonische Datei: {shown}",
                interpretation="Sollzustand fuer diese Objekte liegt nur in der DB",
                suggestion="Entscheiden, welche davon eine sql/objects-Datei bekommen (CLAUDE.md, SQL-Dateien)"))
    else:
        # Rueckfall ohne DB: je kanonischem Objekt die JUENGSTE Log-Markierung "nicht deployt"
        latest: dict[str, LogEntry] = {}
        for e in window:
            if not e.not_deployed:
                continue
            for f in e.sql_files:
                key = Path(f).name[:-4]
                if key in repo_objects and (key not in latest or e.date >= latest[key].date):
                    latest[key] = e
        for key, e in sorted(latest.items(), key=lambda kv: (kv[1].date, kv[0]), reverse=True):
            path, repo_dt = repo_objects[key]
            out.append(Finding(
                kind="deploy-drift", confidence="mittel",
                observation=f"{key}: zuletzt am {e.date} als 'nicht deployt' markiert (log Z.{e.line_start}); "
                            f"Repo-Commit {repo_dt:%Y-%m-%d %H:%M}",
                interpretation="Laut Log stand ein Deployment aus; ob es inzwischen erfolgt ist, konnte ohne DB nicht geprueft werden",
                suggestion="Mit erreichbarer DB erneut traeumen oder per tools/sql.py --list pruefen",
                evidence=[f"log '{e.title[:60]}'"]))
    return out


def check_generalisation_raw(pages: dict[str, Page], queue: list[QueueEntry], window: list[LogEntry]) -> list[Finding]:
    out: list[Finding] = []
    for p in pages.values():
        if p.domain != "allgemein":
            continue
        qs = [q for q in queue if not q.done and p.stem in q.pages]
        if qs:
            out.append(Finding(
                kind="allgemein-rohstoff", confidence="Info",
                observation=f"{p.stem} (allgemein): {len(qs)} offene Queue-Eintraege (Z.{', '.join(str(q.line) for q in qs)})",
                interpretation="Uebertragbares Wissen wartet in der Queue statt auf der Seite",
                suggestion="Kandidaten fuer [V-ALLG] — Skill prueft die Episode→Regel→Grenzen-Struktur",
                pages=[p.stem], in_queue=[q.line for q in qs]))
    erf = sorted(((len(p.erfahrung_lines), p) for p in pages.values()
                  if p.domain != "allgemein" and p.erfahrung_lines), key=lambda t: -t[0])[:5]
    for n, p in erf:
        out.append(Finding(
            kind="erfahrung-projekt", confidence="Info",
            observation=f"{p.stem} ({p.domain}): {n} [ERFAHRUNG]-Bullets (Z.{', '.join(str(l) for l, _ in p.erfahrung_lines[:4])})",
            interpretation="Projektseite traegt Regeln, die ueber das Projekt hinaus gelten koennten",
            suggestion="Testfrage je Bullet: gilt die Aussage ohne Projektzahlen noch? Dann allgemein-Seite",
            pages=[p.stem]))
    for e in window:
        if RE_GENERAL_HINT.search(e.text):
            hits = sorted({m.group(0) for m in RE_GENERAL_HINT.finditer(e.text)})
            out.append(Finding(
                kind="muster-log", confidence="Info",
                observation=f"log {e.date} Z.{e.line_start} '{e.title[:60]}': {', '.join(hits)}",
                interpretation="Der Eintrag beschreibt ein Muster, kein Einzelereignis",
                suggestion="Als Episode fuer eine [V-ALLG]-Regel heranziehen",
                pages=sorted(e.pages)[:3]))
    return out


def check_question_raw(pages: dict[str, Page], window: list[LogEntry], since: date) -> tuple[list[Finding], int]:
    out: list[Finding] = []
    touched = set().union(*(e.pages for e in window)) if window else set()
    total_undated = 0
    for p in pages.values():
        undated = [(l, t) for l, t in p.offen_lines if not RE_DATE_IN_LINE.search(t)]
        total_undated += len(undated)
        relevant = p.domain == "allgemein" or p.stem in touched or (p.updated and p.updated >= since)
        if undated and relevant:
            out.append(Finding(
                kind="offen-ohne-datum", confidence="Info",
                observation=f"{p.stem}: {len(undated)} [OFFEN] ohne Datum (Z.{', '.join(str(l) for l, _ in undated[:3])})",
                interpretation="Offene Punkte ohne Alter lassen sich nicht priorisieren",
                suggestion="Kandidaten fuer [V-FRAGE]; beim naechsten Edit Datum/Anlass ergaenzen",
                evidence=[t[:110] for _, t in undated[:2]], pages=[p.stem]))
    for e in window:
        for lineno, txt in e.user_signals[:2] + e.gap_signals[:2]:
            out.append(Finding(
                kind="frage-signal", confidence="Info",
                observation=f"log {e.date} Z.{lineno}: {txt[:140]}",
                interpretation="Hier hat der Nutzer etwas gefragt oder eine Luecke benannt",
                suggestion="Pruefen, ob die KB die Frage heute beantworten koennte ([V-FRAGE])",
                pages=sorted(e.pages)[:3]))
    return out, total_undated


# --- Vitalwerte, Replay, Bilanz ---------------------------------------------
def previous_protocols(before: date | None = None) -> list[Path]:
    """Protokolle, sortiert; mit `before` nur die mit Datum davor (der heutige
    Lauf darf sich nicht selbst als Vorprotokoll sehen)."""
    if not TRAEUME.is_dir():
        return []
    out = []
    for p in sorted(TRAEUME.glob("*.md")):
        m = re.match(r"(\d{4}-\d{2}-\d{2})", p.name)
        if not m:
            continue
        if before and date.fromisoformat(m.group(1)) >= before:
            continue
        out.append(p)
    return out


def read_previous_vitals(prev: Path | None) -> dict[str, str]:
    if not prev:
        return {}
    vitals: dict[str, str] = {}
    in_table = False
    for ln in read(prev).splitlines():
        if ln.startswith("## Vitalwerte"):
            in_table = True
            continue
        if in_table and ln.startswith("## "):
            break
        if in_table and ln.startswith("| ") and not ln.startswith("| Kennzahl") and not ln.startswith("|---"):
            cells = [c.strip() for c in ln.strip("|").split("|")]
            if len(cells) >= 2:
                vitals[cells[0]] = cells[1]
    return vitals


def tids_with_kind(protocol: Path) -> dict[str, str]:
    kinds: dict[str, str] = {}
    section = ""
    for ln in read(protocol).splitlines():
        if ln.startswith("### "):
            section = ln[4:].strip()
        m = RE_FINDING_LINE.match(ln)
        if m:
            # erste Nennung gewinnt: Bestaetigungszeilen des Skills nennen
            # mechanische IDs erneut, aendern aber nicht deren Kategorie
            kinds.setdefault(m.group(1), m.group(2) or section or "?")
    return kinds


def quality_balance(protocols: list[Path], log: list[LogEntry], queue: list[QueueEntry]) -> tuple[list[str], list[str]]:
    """Precision / Adoption / Value je Kategorie ueber die gegebenen Protokolle."""
    status: dict[str, tuple] = {}
    for e in log:
        status.update(e.tids)
    for q in queue:
        status.update(q.tids)
    per_kind: dict[str, Counter] = defaultdict(Counter)
    echoless: list[str] = []
    for proto in protocols:
        for tid, kind in tids_with_kind(proto).items():
            # Die Bilanz zaehlt nur semantische Vorschlaege ([V-...]); mechanische Befunde
            # wuerden sonst das Werkzeug fuer sich selbst bestrafen
            if not kind.startswith("V-"):
                continue
            c = per_kind[kind]
            c["n"] += 1
            st = status.get(tid)
            if not st or st[0] == "erwaehnt":
                c["ohne_echo"] += 1
                echoless.append(f"{tid} ({kind})")
                continue
            s, wert, grund = st
            if s == "umgesetzt":
                c["umgesetzt"] += 1
                c["bewertet"] += 1
                if wert:
                    c[f"wert_{wert}"] += 1
            elif s == "verworfen":
                c["bewertet"] += 1
                c["verworfen"] += 1
                if grund.lower().startswith("beobachtung") or grund.lower().startswith("interpretation"):
                    c["falsch"] += 1
            elif s == "vertagt":
                c["vertagt"] += 1
            elif s == "in queue":
                c["bewertet"] += 1
                c["in_queue"] += 1
    rows = ["| Kategorie | n | Precision | Adoption | Value hoch/mittel/niedrig | vertagt | ohne Echo |",
            "|---|---|---|---|---|---|---|"]
    for kind, c in sorted(per_kind.items()):
        bew = c["bewertet"]
        prec = f"{100 * (bew - c['falsch']) / bew:.0f} %" if bew else "–"
        adop = f"{100 * c['umgesetzt'] / bew:.0f} %" if bew else "–"
        rows.append(f"| {kind} | {c['n']} | {prec} | {adop} | "
                    f"{c['wert_hoch']}/{c['wert_mittel']}/{c['wert_niedrig']} | {c['vertagt']} | {c['ohne_echo']} |")
    if len(rows) == 2:
        rows.append("| – | 0 | – | – | – | – | – |")
    return rows, echoless


# --- Rendering ---------------------------------------------------------------
def render_finding(f: Finding) -> str:
    head = f"- {f.tid} " if f.tid else f"- [{f.kind}] "
    parts = [f"{head}({f.confidence}) **{f.observation}** · *{f.interpretation}* · → {f.suggestion}"]
    if f.evidence:
        parts.append("  Belege: " + " ; ".join(f.evidence))
    if f.in_queue:
        parts.append(f"  bereits in Queue: Z.{', '.join(str(z) for z in f.in_queue)}")
    return "\n".join(parts)


def compute_vitals(today: date, pages: dict[str, Page], queue: list[QueueEntry], incoming: dict[str, set],
                   undated_offen: int, n_drift: int, db_ok: bool) -> list[tuple[str, str]]:
    """Vitalwerte der KB - fuer das Protokoll und fuer --lage."""
    open_q = [q for q in queue if not q.done]
    done_q = [q for q in queue if q.done]
    quote = 100 * len(done_q) / len(queue) if queue else 0
    stale_q = [q for q in open_q if (today - q.date).days > STALE_DAYS]
    claims: Counter = Counter()
    for p in pages.values():
        claims.update(p.claims)
    low_link = [p.stem for p in pages.values() if len(incoming.get(p.stem, ())) <= 1]
    allg = sum(1 for p in pages.values() if p.domain == "allgemein")
    return [
        ("Seiten (davon allgemein)", f"{len(pages)} ({allg})"),
        ("FAKT / ENTSCHEIDUNG / ERFAHRUNG", f"{claims['FAKT']} / {claims['ENTSCHEIDUNG']} / {claims['ERFAHRUNG']}"),
        ("ANNAHME / OFFEN / HISTORISCH", f"{claims['ANNAHME']} / {claims['OFFEN']} / {claims['HISTORISCH']}"),
        ("OFFEN ohne Datum", str(undated_offen)),
        ("Queue offen / erledigt / Quote", f"{len(open_q)} / {len(done_q)} / {quote:.0f} %"),
        (f"Queue offen > {STALE_DAYS} Tage", str(len(stale_q))),
        ("Seiten mit <= 1 eingehendem Link", str(len(low_link))),
        ("Deploy-Drift (Befunde)", (f"{n_drift}" + ("" if db_ok else " (ohne DB, nur Log/Git)")) if DB_MODULE else "Modul Datenbank aus"),
        ("MOC-Schwelle", f"{len(pages)} / {MOC_THRESHOLD}"),
    ]


def render_befunde(today: date, groups: list[tuple[str, list[Finding]]]) -> str:
    """Maschinendatei traeume/<datum>.befunde.md: alle Befunde vollstaendig, ohne Deckel je Gruppe ausser MAX_PER_GROUP."""
    out = [f"# Befunde {today} (Maschinendatei zu traeume/{today}.md)", "",
           "Vollstaendige mechanische Befunde. Nicht zum Lesen gedacht; das Protokoll fuehrt nur Zaehler und Beispiele. "
           "Kein Wissen, keine Vorschlaege mit Status.", ""]
    for name, fs in groups:
        out.append(f"## {name} ({len(fs)})")
        shown, more = cap(fs, name)
        if not shown:
            out.append("- keine")
        for f in shown:
            out.append(render_finding(f))
        if more:
            out.append(f"- {more}")
        out.append("")
    return "\n".join(out)


def render_protocol(today: date, since: date, window: list[LogEntry], all_log: list[LogEntry],
                    pages: dict[str, Page], queue: list[QueueEntry], incoming: dict[str, set],
                    groups: list[tuple[str, list[Finding]]], vitals_prev: dict[str, str],
                    prev: Path | None, db_ok: bool, undated_offen: int,
                    balance_rows: list[str], echoless: list[str]) -> str:
    tid_counter = 0
    out: list[str] = []
    for name, fs in groups:
        if name not in TID_GROUPS:
            continue
        for f in fs[:MAX_TID_PER_GROUP]:
            tid_counter += 1
            f.tid = f"T-{today:%Y-%m-%d}-{tid_counter:02d}"

    drift = [f for g, fs in groups if g == "Deploy-Drift" for f in fs if f.kind == "deploy-drift"]
    vit = compute_vitals(today, pages, queue, incoming, undated_offen, len(drift), db_ok)
    vit.append(("Vorschlaege Vortraum ohne Echo", str(len(echoless)) if prev else "–"))

    out.append(f"# Traum {today}")
    out.append("")
    out.append(f"Fenster: Log-Eintraege ab {since} ({'Vorprotokoll ' + prev.name if prev else 'kein Vorprotokoll'}) "
               f"· {len(window)} Eintraege · Werkzeug: tools/kb_dream.py · DB: {('abgeglichen' if db_ok else 'nicht erreichbar / uebersprungen') if DB_MODULE else 'Modul aus'}")
    out.append("Konfidenz: hoch = zwei unabhaengige Belege · mittel = ein Beleg · niedrig = Heuristik ohne Beleg · Info = Rohstoff ohne Wertung")
    out.append("Jeder Befund: **Beobachtung** (messbar) · *Interpretation* (Deutung) · → Vorschlag (Handlung). "
               "Status wird NICHT hier gefuehrt, sondern in log.md: "
               "`T-…-NN umgesetzt (wert: hoch|mittel|niedrig)` / `verworfen: Beobachtung falsch | Interpretation falsch | Vorschlag schlecht` / `vertagt` / `in Queue`.")
    for n in NOTES:
        out.append(f"Hinweis: {n}")
    out.append("")
    out.append("## Vitalwerte")
    out.append("| Kennzahl | Wert | Vortraum |")
    out.append("|---|---|---|")
    for k, v in vit:
        out.append(f"| {k} | {v} | {vitals_prev.get(k, '–')} |")
    out.append("")
    out.append("## Replay")
    out.append(f"- {len(window)} Log-Eintraege im Fenster:")
    shown_entries = window if len(window) <= 8 else window[:4] + window[-3:]
    for i, e in enumerate(shown_entries):
        if len(window) > 8 and i == 4:
            out.append(f"  - … {len(window) - 7} weitere …")
        out.append(f"  - {e.date} — {e.title} (log.md Z.{e.line_start})")
    pm: Counter = Counter()
    om: Counter = Counter()
    tg: Counter = Counter()
    for e in window:
        pm.update(e.pages)
        om.update(e.objects)
        tg.update(e.tags)
    out.append("- Meistberuehrte Seiten: " + (", ".join(f"{fmt_pages([p])} ({n})" for p, n in pm.most_common(6)) or "–"))
    out.append("- Meistgenannte Objekte: " + (", ".join(f"`{o}` ({n})" for o, n in om.most_common(6)) or "–"))
    out.append("- Tags in Log-Bullets: " + (" · ".join(f"{t} {n}" for t, n in tg.most_common()) or "–"))
    out.append("- Qualitaetsbilanz Vortraum" + (f" ({prev.name})" if prev else "") + ":")
    out.extend("  " + r for r in balance_rows)
    if echoless:
        out.append("- Ohne Echo: " + ", ".join(echoless[:5]) + (" …" if len(echoless) > 5 else ""))
    out.append("")
    out.append("## Mechanische Befunde")
    out.append(f"Vollstaendig in `traeume/{today}.befunde.md`; hier nur die nummerierten Queue-Kandidaten und je Gruppe Zaehler mit Beispielen.")
    out.append("")
    for name, fs in groups:
        if name not in TID_GROUPS:
            continue
        out.append(f"### {name}")
        shown = fs[:MAX_TID_PER_GROUP]
        if not shown:
            out.append("- keine")
        for f in shown:
            out.append(render_finding(f))
        if len(fs) > MAX_TID_PER_GROUP:
            out.append(f"- … und {len(fs) - MAX_TID_PER_GROUP} weitere in der Maschinendatei")
        out.append("")
    out.append("### Zaehler")
    out.append("| Gruppe | Befunde | Beispiele |")
    out.append("|---|---|---|")
    for name, fs in groups:
        if name in TID_GROUPS:
            continue
        ex = " · ".join(f.observation.replace("|", "/")[:70] for f in fs[:MAX_TEASER]) or "–"
        out.append(f"| {name} | {len(fs)} | {ex} |")
    out.append("")
    out.append(f"letzte ID: T-{today:%Y-%m-%d}-{tid_counter:02d}")
    out.append("")
    out.append("## Semantische Vorschlaege")
    out.append("_(wird von /traeumen ergaenzt; bleibt leer, wenn nur das Werkzeug lief)_")
    out.append("")
    out.append("## Fragen")
    out.append("_(wird von /traeumen ergaenzt)_")
    out.append("")
    out.append("## Triage-Tabelle")
    out.append("| ID | Typ | Kurz | Konfidenz | Ziel |")
    out.append("|---|---|---|---|---|")
    for name, fs in groups:
        for f in fs:
            if not f.tid:
                continue
            kurz = f.observation.replace("|", "/")
            kurz = kurz[:90] + ("…" if len(kurz) > 90 else "")
            out.append(f"| {f.tid} | {f.kind} | {kurz} | {f.confidence} | {', '.join(f.pages) or '–'} |")
    out.append("")
    return "\n".join(out)


def verify_links(text: str, pages: dict[str, Page]) -> list[str]:
    return sorted({m.group(1).strip() for m in L.RE_WIKILINK.finditer(text)} - set(pages))


def is_tracked(path: Path) -> bool:
    r = subprocess.run(["git", "ls-files", "--error-unmatch", str(path.relative_to(ROOT))],
                       cwd=ROOT, capture_output=True, text=True)
    return r.returncode == 0


# --- Lage (Sitzungsstart) -----------------------------------------------------
def run_lage(today: date, pages: dict[str, Page], incoming: dict[str, set], log: list[LogEntry],
             queue: list[QueueEntry], no_db: bool) -> int:
    """Kurzlage: letzte Log-Eintraege mit offenen Punkten, Queue zu den zuletzt beruehrten Seiten,
    Deploy-Drift der zuletzt genannten Objekte, Vitalwerte in einer Zeile. Schreibt nichts."""
    last = log[-LAGE_LOG_ENTRIES:]
    touched: set[str] = set()
    for e in last[-3:]:
        touched |= e.pages
    open_q = [q for q in queue if not q.done]
    q_touched = [q for q in open_q if touched & set(q.pages)]
    db = None if (no_db or not DB_MODULE) else db_object_dates()
    drift = [f for f in check_deploy_drift(git_last_commit_dates(), db, last[-3:]) if f.kind == "deploy-drift"] if DB_MODULE else []
    vit = dict(compute_vitals(today, pages, queue, incoming, 0, len(drift), db is not None))
    lines: list[str] = []
    lines.append(f"Lage {today} · {C.NAME} · letzter Traum: {(previous_protocols(before=today) or [Path('keiner')])[-1].name[:10]} "
                 f"· Queue offen {vit['Queue offen / erledigt / Quote'].split(' / ')[0]} · Seiten {vit['Seiten (davon allgemein)']}")
    lines.append("Zuletzt im Log:")
    for e in last:
        lines.append(f"  {e.date} {e.title[:80]}")
    open_lines = []
    for e in last:
        for ln in e.text.splitlines():
            if RE_OPEN_LINE.match(ln):
                open_lines.append(f"  {e.date}: {ln.strip().lstrip('- ')[:110]}")
    if open_lines:
        lines.append("Offen laut Log:")
        lines.extend(open_lines[-6:])
    typed = [q for q in open_q if q.typ]
    waiting = [q for q in open_q if q.waits]
    lines.append(f"Queue: {len(open_q)} offen, davon {len(typed)} typisiert, {len(waiting)} warten (" +
                 ", ".join(f"{k} {v}" for k, v in Counter(q.waits for q in waiting).most_common()) + ")" if waiting else
                 f"Queue: {len(open_q)} offen, davon {len(typed)} typisiert")
    lines.append(f"Queue zu zuletzt beruehrten Seiten ({', '.join(sorted(touched)[:4]) or '–'}): {len(q_touched)} offen")
    for q in q_touched[:4]:
        lines.append(f"  Z.{q.line} {q.date} {q.reason[:95]}")
    if DB_MODULE:
        lines.append(f"Deploy-Drift der zuletzt genannten Objekte: {len(drift)}" + (" (ohne DB)" if db is None else ""))
        for f in drift[:3]:
            lines.append(f"  {f.observation[:100]}")
    print("\n".join(lines[:25]))
    return 0


# --- main -------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="Konsolidierungslauf (Traum) der Knowledge Base")
    ap.add_argument("--since", help="Fensterbeginn YYYY-MM-DD (Default: Datum des letzten Protokolls, sonst 30 Tage)")
    ap.add_argument("--no-db", action="store_true", help="Datenbank nicht abfragen")
    ap.add_argument("--out", help="Zieldatei (Default: traeume/<heute>.md)")
    ap.add_argument("--stdout", action="store_true", help="nur drucken, nichts schreiben")
    ap.add_argument("--bilanz", action="store_true", help="nur die kumulierte Qualitaetsbilanz ueber alle Protokolle drucken")
    ap.add_argument("--lage", action="store_true", help="Kurzlage fuer den Sitzungsstart (max. 25 Zeilen), schreibt nichts")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    today = date.today()
    try:
        pages = collect_pages()
        incoming, in_index = build_link_graph(pages)
        log = parse_log_entries(pages)
        queue = parse_queue_entries(pages)
    except Exception as exc:  # noqa: BLE001
        print(f"kb_dream: Parse-Fehler: {exc}", file=sys.stderr)
        return 1

    if args.bilanz:
        protocols = previous_protocols()
        rows, echoless = quality_balance(protocols, log, queue)
        print(f"Kumulierte Qualitaetsbilanz ueber {len(protocols)} Protokoll(e):")
        print("\n".join(rows))
        if echoless:
            print(f"Ohne Echo ({len(echoless)}): " + ", ".join(echoless[:12]) + (" …" if len(echoless) > 12 else ""))
        return 0
    if args.lage:
        return run_lage(today, pages, incoming, log, queue, no_db=args.no_db)
    protocols = previous_protocols(before=today)

    prev = protocols[-1] if protocols else None
    if args.since:
        since = date.fromisoformat(args.since)
    elif prev:
        since = date.fromisoformat(prev.name[:10])
    else:
        since = today - timedelta(days=WINDOW_DEFAULT_DAYS)
    window = [e for e in log if e.date >= since]

    git_dates = git_last_commit_dates() if DB_MODULE else {}
    db = None if (args.no_db or not DB_MODULE) else db_object_dates()
    if args.no_db and DB_MODULE:
        note("DB-Abgleich uebersprungen (--no-db)")

    cand, rest = check_queue_triage(queue, log, pages, today)
    groups: list[tuple[str, list[Finding]]] = [
        ("Queue-Triage: Erledigungskandidaten", cand),
        ("Queue-Triage: veraltet und Cluster", rest),
        ("Rueckstau-Seiten", check_backlog_pages(pages, queue, log)),
        ("Link-Hygiene", check_link_hygiene(pages, incoming, in_index, window, today)),
        ("Generalisierungs-Rohstoff", check_generalisation_raw(pages, queue, window)),
    ]
    if DB_MODULE:
        groups.insert(4, ("Deploy-Drift", check_deploy_drift(git_dates, db, window)))
    fragen, undated = check_question_raw(pages, window, since)
    groups.append(("Fragen-Rohstoff", fragen))

    balance_rows, echoless = quality_balance([prev] if prev else [], log, queue)
    text = render_protocol(today, since, window, log, pages, queue, incoming, groups,
                           read_previous_vitals(prev), prev, db is not None, undated,
                           balance_rows, echoless)

    bad = verify_links(text, pages)
    if bad:
        print(f"kb_dream: Protokoll enthaelt kaputte Wikilinks: {', '.join(bad)}", file=sys.stderr)
        return 1
    befunde = render_befunde(today, groups)
    if args.stdout:
        print(text)
        return 0

    target = Path(args.out) if args.out else TRAEUME / f"{today}.md"
    if not target.is_absolute():
        target = ROOT / target
    if target.exists() and is_tracked(target):
        print(f"kb_dream: {target.relative_to(ROOT).as_posix()} ist bereits committet — "
              f"Protokolle sind append-only. Neuer Lauf: --out traeume/{today}-2.md", file=sys.stderr)
        return 2
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text + "\n", encoding="utf-8", newline="\n")
    befunde_target = target.with_name(target.stem + ".befunde.md")
    befunde_target.write_text(befunde + "\n", encoding="utf-8", newline="\n")
    n_find = sum(len(fs) for _, fs in groups)
    shown_target = target.relative_to(ROOT).as_posix() if target.is_relative_to(ROOT) else str(target)
    print(f"kb_dream: {shown_target} geschrieben — {len(window)} Log-Eintraege, "
          f"{n_find} Befunde" + (f", DB {'abgeglichen' if db is not None else 'nicht abgeglichen'}" if DB_MODULE else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
