"""Gemeinsame Testbasis fuer tools/tests.

Prinzip: Ein Test extrahiert den Rumpf einer View oder Prozedur WOERTLICH aus der kanonischen
Datei in sql/objects, ersetzt Tabellen durch VALUES-CTEs (Logiktest, Sekunden) oder laesst sie
stehen (Volltest, Minuten) und prueft das Ergebnis gegen eine Python-Referenz oder gegen
Konsistenzregeln. Jede Abfrage laeuft ueber tools/sql.py (nur SELECT, Lesebenutzer).
Ergebnisse landen in outputs/tests/ (gitignored). Ein Test endet mit einer Zeile
"<name>: n Werte, k Abweichungen" und Exit 0 (k = 0) oder 1.
"""
from __future__ import annotations

import csv
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OBJECTS = ROOT / "sql" / "objects"
OUT = ROOT / "outputs" / "tests"
SQL_PY = ROOT / "tools" / "sql.py"
NL = chr(10)


def read_object(name: str, schema: str = "dbo") -> str:
    """Kanonische Datei eines Objekts (ohne Schema-Praefix im Namen), ASCII."""
    return (OBJECTS / f"{schema}.{name}.sql").read_text(encoding="ascii")


def view_body(text: str) -> str:
    """Rumpf einer View: alles nach 'ALTER VIEW <name> AS' (auch CREATE OR ALTER) bis vor das
    abschliessende GO - ein einzelnes SELECT oder WITH ... SELECT, wie tools/sql.py es annimmt."""
    m = re.search(r"(?is)\bALTER\s+VIEW\s+\S+\s+AS\s+", text)
    if not m:
        raise ValueError("kein 'ALTER VIEW <name> AS' in der Datei")
    body = text[m.end():]
    end = re.search(r"(?im)^\s*GO\s*$", body)
    return (body[:end.start()] if end else body).strip().rstrip(";").rstrip()


def values_cte(name: str, cols: list[str], rows: list[str]) -> str:
    """CTE `name` aus VALUES-Zeilen (jede Zeile ein fertiger '(...)'-Ausdruck)."""
    return (f"{name} AS" + NL + "(" + NL + "    SELECT * FROM (VALUES" + NL + "         "
            + (NL + "        ,").join(rows) + NL + f"    ) AS v({', '.join(cols)})" + NL + ")")


def run_sql(sql: str, name: str, timeout_s: int = 120, max_rows: int = 100000) -> list[dict]:
    """SQL ueber tools/sql.py ausfuehren, Ergebnis als Liste von Dicts (Spaltenname -> Text)."""
    OUT.mkdir(parents=True, exist_ok=True)
    sql_path = OUT / f"{name}.sql"
    csv_path = OUT / f"{name}.csv"
    sql_path.write_text(sql, encoding="ascii", newline=NL)
    if csv_path.exists():
        csv_path.unlink()
    r = subprocess.run([sys.executable, str(SQL_PY), "--file", str(sql_path), "--csv", str(csv_path),
                        "--max-rows", str(max_rows), "--timeout", str(timeout_s)],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0 or not csv_path.exists():
        raise RuntimeError(f"sql.py Exit {r.returncode}: {(r.stdout + r.stderr).strip()[-600:]}")
    with csv_path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh, delimiter=";"))


def num(x: str) -> float:
    return float(str(x).replace(",", "."))


def compare(rows: list[dict], ref: dict[tuple, list[float]], key_cols: list[str], cols: list[str],
            tol: float = 0.002, label: str = "") -> tuple[int, int]:
    """Zeilen (Dicts) gegen Referenz {schluessel: [werte in cols-Reihenfolge]} pruefen."""
    n = bad = 0
    seen = set()
    for row in rows:
        key = tuple(row[k] if not row[k].replace(".", "", 1).isdigit() else str(int(float(row[k]))) for k in key_cols)
        if key not in ref:
            print(f"{label}UNERWARTET {key}")
            bad += 1
            continue
        seen.add(key)
        for c, want in zip(cols, ref[key]):
            n += 1
            got = num(row[c])
            if abs(got - want) > tol:
                bad += 1
                print(f"{label}ABWEICHUNG {key} {c}: SQL {got} Referenz {round(want, 4)}")
    for key in ref:
        if key not in seen:
            print(f"{label}FEHLT {key}")
            bad += 1
    return n, bad


def finish(name: str, n: int, bad: int) -> int:
    print(f"{name}: {n} Werte, {bad} Abweichungen")
    return 0 if bad == 0 else 1
