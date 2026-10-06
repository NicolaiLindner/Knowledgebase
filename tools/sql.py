#!/usr/bin/env python3
"""sql.py — read-only Abfragen gegen die Arbeitsdatenbank (Microsoft SQL Server).

Teil des Moduls Datenbank (kb.config.yaml: module.datenbank, Regeln in MODUL-DATENBANK.md).
Zugang ausschliesslich ueber .env im Repo-Stamm (Vorlage .env.example, nie committen):
Server, Datenbank, Windows-Anmeldung oder SQL-Login und der Lesebenutzer KB_READER.

Zwei unabhaengige Schutzschichten:

  1. Datenbank: Jede Abfrage laeuft nach 'EXECUTE AS USER = kb_reader
     WITH NO REVERT'. Der Benutzer hat nur db_datareader; die Sitzung kann
     nicht mehr zurueck (NO REVERT). Schreibversuche scheitern am Server,
     unabhaengig davon, welche Rechte der aufrufende Login hat.
     Einrichtung: tools/setup_kb_reader.sql (einmalig). Nur wenn KB_READER in
     der .env ausdruecklich leer gesetzt ist, entfaellt diese Schicht - dann
     warnt --check, und allein der Werkzeug-Guard schuetzt.

  2. Werkzeug: Nur einzelne SELECT-Anweisungen werden ueberhaupt gesendet.
     Alles andere - inklusive REVERT, EXECUTE AS und SELECT INTO - wird
     vorher abgelehnt, damit Schicht 1 nicht ausgehebelt werden kann.

Zusaetzlich: Zeilenlimit, Abfrage-Timeout und Sperr-Timeout, damit eine
unglueckliche Abfrage weder den Kontext flutet noch die Datenbank blockiert.

Aufrufe
-------
    python tools/sql.py --check
    python tools/sql.py --list "v_%"                    Objekte suchen
    python tools/sql.py --ddl  "v_Kunde_Umsatz"         Quelltext ansehen
    python tools/sql.py "SELECT TOP 10 * FROM dbo.Kunde"
    python tools/sql.py --file abfrage.sql --max-rows 500
    python tools/sql.py "SELECT ..." --csv outputs/ergebnis.csv
    python tools/sql.py --file abfrage.sql --accdb outputs/x.accdb --table Ergebnis --index "Kunde,Datum"

--accdb schreibt das Ergebnis vollstaendig (ohne --max-rows-Deckel) in eine
Access-Tabelle. Die Datei wird angelegt, wenn sie fehlt; existiert die
Tabelle schon, bricht das Werkzeug ab. Braucht ein installiertes Access
(MSACCESS.EXE wird per COM gesteuert, siehe tools/accdb_import.ps1). Der
Lesepfad zur Datenbank bleibt derselbe (Guard + kb_reader) — nur das
Ausgabeziel ist anders.

--ddl liest sys.sql_modules. Das setzt 'GRANT VIEW DEFINITION TO kb_reader'
voraus (im Setup-Skript enthalten) — ohne dieses Recht liefert SQL Server
still NULL statt einer Fehlermeldung.

Exit-Codes: 0 = ok, 1 = Abfrage/Verbindung fehlgeschlagen, 2 = Guard hat abgelehnt.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

try:
    import pyodbc
except ImportError:
    sys.exit("pyodbc fehlt. Installation:  pip install pyodbc")

# --- Zugang: .env im Repo-Stamm (nie committen; Vorlage .env.example) --------
ROOT = Path(__file__).resolve().parents[1]


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


ENV = load_env()
SERVER = ENV.get("KB_SERVER", "")
DATABASE = ENV.get("KB_DATABASE", "")
USER = ENV.get("KB_USER", "")
PASSWORD = ENV.get("KB_PASSWORD", "")
TRUSTED = ENV.get("KB_TRUSTED", "1" if not USER else "0") == "1"
# Lesebenutzer: Standard kb_reader. Nur ein ausdruecklich leerer Eintrag (KB_READER=)
# schaltet EXECUTE AS ab - fuer Server, auf denen der Nutzer keinen Benutzer anlegen darf.
READER = ENV.get("KB_READER", "kb_reader")
DRIVER = ENV.get("KB_DRIVER", "ODBC Driver 18 for SQL Server")

DEFAULT_MAX_ROWS = 200
DEFAULT_TIMEOUT_S = 30
LOCK_TIMEOUT_MS = 10_000

# --- Access-Ausgabe (--accdb) ------------------------------------------------
ACCESS_BATCH = 20_000         # Zeilen je fetchmany beim Schreiben der Import-CSV
ACCESS_PROGRESS = 500_000     # Fortschrittsmeldung alle n Zeilen

# --- Guard ------------------------------------------------------------------
# Nur diese Anweisungsart wird gesendet: SELECT, auch mit vorangestellter
# CTE-Kette (WITH ... SELECT) - die verbotenen Schluesselwoerter unten
# fangen WITH ... INSERT/UPDATE/DELETE/MERGE weiterhin ab.
RE_STARTS_SELECT = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)

# Verbotene Schluesselwoerter. Wortgrenzen, damit Spalten wie 'Created' oder
# 'Bestand_Korrektur' keine Fehlalarme ausloesen.
FORBIDDEN = [
    "INSERT", "UPDATE", "DELETE", "MERGE", "TRUNCATE",
    "CREATE", "ALTER", "DROP", "RENAME",
    "GRANT", "REVOKE", "DENY",
    "EXEC", "EXECUTE", "REVERT", "IMPERSONATE",
    "BACKUP", "RESTORE", "SHUTDOWN", "RECONFIGURE", "KILL",
    "OPENROWSET", "OPENDATASOURCE", "OPENQUERY", "BULK",
    "WAITFOR", "DBCC",
]
RE_FORBIDDEN = re.compile(r"\b(" + "|".join(FORBIDDEN) + r")\b", re.IGNORECASE)
RE_XP_SP = re.compile(r"\b(xp_|sp_)\w+", re.IGNORECASE)
RE_SELECT_INTO = re.compile(r"\bINTO\s+(?!\s*\()[#\[\w]", re.IGNORECASE)


def strip_noise(sql: str) -> str:
    """Kommentare und Zeichenketten entfernen — nur fuer die Guard-Pruefung."""
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    sql = re.sub(r"--[^\n]*", " ", sql)
    sql = re.sub(r"'(?:[^']|'')*'", "''", sql)
    return sql


def check_query(sql: str) -> str | None:
    """Gibt die Ablehnungsbegruendung zurueck, oder None wenn die Abfrage passiert."""
    bare = strip_noise(sql).strip().rstrip(";").strip()
    if not bare:
        return "leere Abfrage"
    if not RE_STARTS_SELECT.match(bare):
        return "nur einzelne SELECT-Anweisungen sind erlaubt (Abfrage beginnt nicht mit SELECT oder WITH)"
    if ";" in bare:
        return "mehrere Anweisungen in einer Abfrage sind nicht erlaubt"
    hit = RE_FORBIDDEN.search(bare)
    if hit:
        return f"verbotenes Schluesselwort: {hit.group(1).upper()}"
    hit = RE_XP_SP.search(bare)
    if hit:
        return f"Prozeduraufruf nicht erlaubt: {hit.group(0)}"
    if RE_SELECT_INTO.search(bare):
        return "SELECT ... INTO erzeugt eine Tabelle und ist nicht erlaubt"
    return None


# --- Verbindung -------------------------------------------------------------
def connect(timeout_s: int):
    pyodbc.pooling = False  # keine Wiederverwendung einer bereits gewechselten Sitzung
    if not (ROOT / ".env").is_file():
        sys.exit("Keine .env im Repo-Stamm. Vorlage kopieren:  .env.example -> .env  (Zugangsdaten nie committen).")
    if not SERVER or not DATABASE:
        sys.exit("KB_SERVER und KB_DATABASE muessen in .env gesetzt sein.")
    if TRUSTED:
        auth = "Trusted_Connection=yes;"
    else:
        if not PASSWORD:
            sys.exit("KB_PASSWORD fehlt in .env (oder KB_TRUSTED=1 setzen). Zugangsdaten nie im Aufruf.")
        auth = f"UID={USER};PWD={PASSWORD};"
    cs = (
        f"DRIVER={{{DRIVER}}};SERVER={SERVER};DATABASE={DATABASE};"
        f"{auth}TrustServerCertificate=yes;Connection Timeout=10"
    )
    conn = pyodbc.connect(cs, timeout=10)
    conn.timeout = timeout_s
    cur = conn.cursor()
    cur.execute(f"SET LOCK_TIMEOUT {LOCK_TIMEOUT_MS}")
    return conn, cur


def become_reader(cur) -> None:
    """Sicherheitskontext unwiderruflich auf den Lesebenutzer wechseln (entfaellt nur bei KB_READER=)."""
    if not READER:
        return
    try:
        cur.execute(f"EXECUTE AS USER = '{READER}' WITH NO REVERT")
    except pyodbc.Error as exc:
        sys.exit(
            f"Wechsel auf '{READER}' fehlgeschlagen: {exc}\n\n"
            "Der Lesebenutzer ist vermutlich noch nicht eingerichtet. Einmalig ausfuehren:\n"
            f'    sqlcmd -S "{SERVER}" -d "{DATABASE}" -E -i tools/setup_kb_reader.sql   (oder in SSMS, mit db_owner-Rechten)'
        )
    actual = cur.execute("SELECT USER_NAME()").fetchval()
    if actual != READER:
        sys.exit(f"Sicherheitskontext ist '{actual}', erwartet '{READER}'. Abbruch.")


# --- Ausgabe ----------------------------------------------------------------
def fmt(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, float):
        return f"{value:,.2f}".replace(",", " ").replace(".", ",", 1) if abs(value) >= 1000 else f"{value:.2f}"
    if isinstance(value, int):
        return f"{value:,}".replace(",", ".")
    return str(value).strip()


MAX_CELL = 70


def cell(value) -> str:
    """Tabellenzelle: einzeilig und begrenzt, damit die Tabelle nie zerbricht."""
    text = fmt(value)
    if "\n" in text or "\r" in text:
        text = " ".join(text.split())
    if len(text) > MAX_CELL:
        text = text[: MAX_CELL - 1] + "…"
    return text.replace("|", "\\|")


def as_markdown(cols: list[str], rows: list) -> str:
    if not rows:
        return "_(keine Zeilen)_"
    table = [[cell(v) for v in row] for row in rows]
    widths = [max(len(c), *(len(r[i]) for r in table)) for i, c in enumerate(cols)]
    out = ["| " + " | ".join(c.ljust(widths[i]) for i, c in enumerate(cols)) + " |",
           "|" + "|".join("-" * (w + 2) for w in widths) + "|"]
    out += ["| " + " | ".join(r[i].ljust(widths[i]) for i in range(len(cols))) + " |" for r in table]
    note = ""
    if any(len(fmt(v)) > MAX_CELL or "\n" in fmt(v) for row in rows for v in row):
        note = f"\n\n_(Zellen ab {MAX_CELL} Zeichen gekürzt — voller Inhalt mit `--ddl` oder `--csv`)_"
    return "\n".join(out) + note


# --- Modi -------------------------------------------------------------------
def run_check() -> int:
    conn, cur = connect(DEFAULT_TIMEOUT_S)
    login = cur.execute("SELECT SUSER_SNAME()").fetchval()
    before = cur.execute("SELECT USER_NAME()").fetchval()
    become_reader(cur)
    rights = cur.execute(
        "SELECT IS_ROLEMEMBER('db_datareader'), IS_ROLEMEMBER('db_datawriter'),"
        " IS_ROLEMEMBER('db_owner'), IS_ROLEMEMBER('db_ddladmin')"
    ).fetchone()
    print(f"Server        {SERVER}")
    print(f"Datenbank     {DATABASE}")
    print(f"Login         {login} ({'Windows' if TRUSTED else 'SQL-Login'})")
    print(f"Lesebenutzer  {READER or 'KEINER (KB_READER leer) - nur der Werkzeug-Guard schuetzt'}")
    print(f"Kontext       {before}  ->  {cur.execute('SELECT USER_NAME()').fetchval()}")
    print(f"  lesen       {'ja' if rights[0] else 'NEIN'}")
    print(f"  schreiben   {'JA (unerwartet!)' if rights[1] else 'nein'}")
    print(f"  db_owner    {'JA (unerwartet!)' if rights[2] else 'nein'}")
    print(f"  Schema      {'JA (unerwartet!)' if rights[3] else 'nein'}")

    # Gegenprobe: ein Schreibversuch muss scheitern.
    try:
        cur.execute("CREATE TABLE dbo._kb_schreibtest (x int)")
        conn.rollback()
        print("\nWARNUNG: Schreibversuch wurde NICHT abgelehnt.")
        conn.close()
        return 1
    except pyodbc.Error as exc:
        msg = str(exc).split("]")[-1].strip()[:90]
        print(f"\nSchreibprobe   abgelehnt ({msg})")
    conn.close()
    print("\nBereit.")
    return 0


SQL_LIST = """
SELECT  Schema_ = s.name
      , Objekt  = o.name
      , Typ     = o.type_desc
      , Geaendert = CONVERT(char(16), o.modify_date, 120)
FROM sys.objects o
JOIN sys.schemas s ON s.schema_id = o.schema_id
WHERE o.is_ms_shipped = 0
  AND o.type IN ('U','V','P','FN','IF','TF')
  AND o.name LIKE ?
ORDER BY s.name, o.name
"""

SQL_DDL = """
SELECT  Objekt = s.name + '.' + o.name
      , Typ    = o.type_desc
      , Code   = m.definition
FROM sys.sql_modules m
JOIN sys.objects o  ON o.object_id = m.object_id
JOIN sys.schemas s  ON s.schema_id = o.schema_id
WHERE o.name LIKE ?
ORDER BY o.name
"""

SQL_COLUMNS = """
SELECT  Spalte    = c.name
      , Datentyp  = t.name + CASE WHEN t.name IN ('varchar','nvarchar','char','nchar')
                                  THEN '(' + IIF(c.max_length = -1, 'max',
                                       CAST(c.max_length / IIF(t.name LIKE 'n%', 2, 1) AS varchar)) + ')'
                                  WHEN t.name IN ('decimal','numeric')
                                  THEN '(' + CAST(c.precision AS varchar) + ',' + CAST(c.scale AS varchar) + ')'
                                  ELSE '' END
      , Nullable  = IIF(c.is_nullable = 1, 'ja', 'nein')
      , Position  = c.column_id
FROM sys.columns c
JOIN sys.types t ON t.user_type_id = c.user_type_id
WHERE c.object_id = OBJECT_ID(?)
ORDER BY c.column_id
"""


def run_list(pattern: str, timeout_s: int) -> int:
    conn, cur = connect(timeout_s)
    become_reader(cur)
    cur.execute(SQL_LIST, pattern)
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    conn.close()
    print(as_markdown(cols, rows))
    print(f"\n{len(rows)} Objekt(e) passend zu {pattern!r}")
    return 0


def run_ddl(pattern: str, timeout_s: int) -> int:
    """Quelltext von Views, Prozeduren und Funktionen; bei Tabellen die Spaltenliste."""
    conn, cur = connect(timeout_s)
    become_reader(cur)
    cur.execute(SQL_DDL, pattern)
    module_rows = cur.fetchall()

    for name, typ, code in module_rows:
        if code is None:
            print(f"## {name} ({typ})\n\nQuelltext nicht lesbar — fehlt `GRANT VIEW DEFINITION TO kb_reader`.\n")
            continue
        print(f"## {name} ({typ})\n\n```sql\n{code.strip()}\n```\n")

    if not module_rows:
        # Kein Modul gefunden — vielleicht eine Tabelle: dann Spalten zeigen.
        cur.execute(SQL_LIST, pattern)
        tables = [r for r in cur.fetchall() if r[2] == "USER_TABLE"]
        if not tables:
            conn.close()
            print(f"Kein Objekt passend zu {pattern!r}.", file=sys.stderr)
            return 1
        for schema, name, typ, _ in tables:
            cur.execute(SQL_COLUMNS, f"{schema}.{name}")
            cols = [d[0] for d in cur.description]
            print(f"## {schema}.{name} (Tabelle)\n")
            print(as_markdown(cols, cur.fetchall()) + "\n")
    conn.close()
    return 0


# --- Access-Ausgabe ---------------------------------------------------------
# Weg: Ergebnis -> temporaere CSV + schema.ini (Typen aus cursor.description)
# -> tools/accdb_import.ps1 laesst MSACCESS.EXE per COM importieren. Warum
# nicht direkt per ODBC einfuegen: ~700 Zeilen/s gegen ~200.000 Zeilen/s.
# Warum nicht DAO/Text-ISAM aus Python: siehe Kopf von accdb_import.ps1.

def accdb_types(desc) -> tuple[str, str]:
    """(Access-DDL-Typ, schema.ini-Typ) fuer einen cursor.description-Eintrag."""
    import datetime
    import decimal
    name, kind, _, size, precision, _, _ = desc
    if kind is bool:
        return "BYTE", "Byte"                 # 0/1, nullable (YESNO kann kein NULL)
    if kind is int:
        if (precision or 0) <= 10:            # bigint passt nicht in LONG
            return "LONG", "Long"
        return "DOUBLE", "Double"
    if kind in (float, decimal.Decimal):
        return "DOUBLE", "Double"
    if kind in (datetime.date, datetime.datetime):
        return "DATETIME", "DateTime"
    if kind is str and 0 < (size or 0) <= 255:
        return f"TEXT({size})", f"Text Width {size}"
    if kind is bytes:
        sys.exit(f"Spalte {name}: Binaerdaten werden von --accdb nicht unterstuetzt.")
    return "LONGTEXT", "Memo"


RE_CTRL = re.compile(r"[\t\r\n]")


def accdb_cell(v) -> str:
    """Zellwert fuer die Import-Datei: NULL leer, Datum ISO, Dezimalpunkt.

    Die Datei ist tabulatorgetrennt OHNE Textbegrenzer (TextDelimiter=none),
    damit Anfuehrungszeichen im Text unveraendert ankommen und kein Escaping
    noetig ist. Dafuer duerfen Texte keine Tabs/Zeilenumbrueche enthalten —
    die werden zu Leerzeichen.
    """
    import datetime
    if v is None:
        return ""
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, datetime.datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, datetime.date):
        return v.strftime("%Y-%m-%d") + " 00:00:00"
    if isinstance(v, str):
        return RE_CTRL.sub(" ", v)
    return str(v)


def write_accdb(cur, path: Path, table: str, indexes: list[str]) -> int:
    """Schreibt das offene Ergebnis vollstaendig in eine neue Access-Tabelle."""
    import json
    import shutil
    import subprocess

    path = path.resolve()
    if path.suffix.lower() != ".accdb":
        sys.exit("--accdb erwartet einen Pfad mit Endung .accdb")
    path.parent.mkdir(parents=True, exist_ok=True)
    work = path.parent / f"_import_{table}"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir()

    cols = [d[0] for d in cur.description]
    types = [accdb_types(d) for d in cur.description]
    csv_name = f"{table}.txt"

    # schema.ini: Spaltennamen und Typen explizit, damit Access nichts raet
    # (sonst wird aus ItemId '0012' eine Zahl). Tab-getrennt ohne
    # Textbegrenzer, siehe accdb_cell.
    ini = [f"[{csv_name}]", "Format=TabDelimited", "TextDelimiter=none", "ColNameHeader=True",
           "CharacterSet=65001", "DecimalSymbol=.", "DateTimeFormat=yyyy-MM-dd HH:nn:ss", "MaxScanRows=1"]
    ini += [f'Col{i + 1}="{c}" {t[1]}' for i, (c, t) in enumerate(zip(cols, types))]
    (work / "schema.ini").write_text("\n".join(ini) + "\n", encoding="ascii", errors="replace")

    total = 0
    next_report = ACCESS_PROGRESS
    with (work / csv_name).open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\r\n", quoting=csv.QUOTE_NONE, quotechar=None)
        w.writerow(cols)
        while True:
            batch = cur.fetchmany(ACCESS_BATCH)
            if not batch:
                break
            w.writerows([accdb_cell(v) for v in row] for row in batch)
            total += len(batch)
            if total >= next_report:
                print(f"  {total:,} Zeilen gelesen ...".replace(",", "."), flush=True)
                next_report += ACCESS_PROGRESS

    job = {
        "accdb": str(path), "table": table, "csvDir": str(work), "csvName": csv_name,
        "columns": [{"name": c, "ddl": t[0]} for c, t in zip(cols, types)],
        "indexes": [[c.strip() for c in spec.split(",") if c.strip()] for spec in indexes],
    }
    (work / "job.json").write_text(json.dumps(job), encoding="utf-8")

    print(f"  {total:,} Zeilen gelesen, Import nach Access ...".replace(",", "."), flush=True)
    script = Path(__file__).with_name("accdb_import.ps1")
    res = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
         "-Job", str(work / "job.json")],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0 or "ROWS=" not in res.stdout:
        sys.exit(f"Access-Import fehlgeschlagen:\n{res.stdout}\n{res.stderr}\n"
                 f"Arbeitsordner bleibt zur Diagnose liegen: {work}")
    imported = int(res.stdout.split("ROWS=")[1].split()[0])
    shutil.rmtree(work)
    if imported != total:
        sys.exit(f"Zeilenzahl weicht ab: {total} gelesen, {imported} importiert.")
    return total


def run_query(sql: str, max_rows: int, timeout_s: int, csv_path: str | None,
              accdb_path: str | None = None, table: str | None = None,
              indexes: list[str] | None = None) -> int:
    reason = check_query(sql)
    if reason:
        print(f"Abgelehnt: {reason}", file=sys.stderr)
        return 2

    conn, cur = connect(timeout_s)
    become_reader(cur)
    try:
        cur.execute(sql)
    except pyodbc.Error as exc:
        print(f"SQL-Fehler: {str(exc).split(']')[-1].strip()}", file=sys.stderr)
        conn.close()
        return 1

    if accdb_path:
        path = Path(accdb_path)
        n = write_accdb(cur, path, table, indexes or [])
        conn.close()
        print(f"{n:,} Zeilen geschrieben nach {path} [{table}]".replace(",", "."))
        return 0

    cols = [d[0] for d in cur.description]
    rows = cur.fetchmany(max_rows + 1)
    truncated = len(rows) > max_rows
    rows = rows[:max_rows]
    conn.close()

    if csv_path:
        path = Path(csv_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh, delimiter=";")
            w.writerow(cols)
            w.writerows(rows)
        print(f"{len(rows)} Zeilen geschrieben nach {path}")
    else:
        print(as_markdown(cols, rows))
        print(f"\n{len(rows)} Zeile(n)" + (f", bei {max_rows} abgeschnitten — mit --max-rows erhoehen" if truncated else ""))
    return 0


def main() -> int:
    # Windows-Konsole schreibt sonst cp1252: Sonderzeichen im Quelltext brechen --ddl ab,
    # und kb_drift.py (liest UTF-8) saehe Umlaute verstuemmelt.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=f"Read-only SELECT gegen {DATABASE or 'die Datenbank aus .env'}.")
    ap.add_argument("query", nargs="?", help="SELECT-Anweisung")
    ap.add_argument("--file", help="Datei mit einer SELECT-Anweisung")
    ap.add_argument("--check", action="store_true", help="Verbindung und Leserechte pruefen")
    ap.add_argument("--ddl", metavar="MUSTER",
                    help="Quelltext von View/Prozedur/Funktion (LIKE-Muster, z. B. 'v_%%'); "
                         "bei Tabellen die Spaltenliste")
    ap.add_argument("--list", dest="list_pattern", metavar="MUSTER",
                    help="Objekte suchen (LIKE-Muster), mit Typ und Aenderungsdatum")
    ap.add_argument("--max-rows", type=int, default=DEFAULT_MAX_ROWS)
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_S, help="Sekunden")
    ap.add_argument("--csv", help="Ergebnis als CSV schreiben statt anzeigen")
    ap.add_argument("--accdb", metavar="PFAD",
                    help="Ergebnis vollstaendig in eine Access-Tabelle schreiben (Datei wird angelegt)")
    ap.add_argument("--table", metavar="NAME", help="Zieltabelle fuer --accdb")
    ap.add_argument("--index", action="append", default=[], metavar="SPALTEN",
                    help="Index in der Access-Tabelle, Spalten kommagetrennt; mehrfach erlaubt")
    args = ap.parse_args()

    if bool(args.accdb) != bool(args.table):
        ap.error("--accdb und --table gehoeren zusammen")
    if args.accdb and args.csv:
        ap.error("--accdb und --csv schliessen sich aus")

    if args.check:
        return run_check()
    if args.list_pattern:
        return run_list(args.list_pattern, args.timeout)
    if args.ddl:
        return run_ddl(args.ddl, args.timeout)
    sql = Path(args.file).read_text(encoding="utf-8") if args.file else args.query
    if not sql:
        ap.print_help()
        return 2
    return run_query(sql, args.max_rows, args.timeout, args.csv,
                     args.accdb, args.table, args.index)


if __name__ == "__main__":
    sys.exit(main())
