"""Logiktest <objekt> (Sekunden) - Muster, nach tools/tests/test_<objekt>.py kopieren.

Der View-Rumpf wird WOERTLICH aus sql/objects/dbo.<objekt>.sql gelesen; die Quelltabelle wird durch
synthetische Zeilen (VALUES) ersetzt. Referenz: dieselbe Regel in Python. Weichen beide ab, ist
entweder die View oder das Verstaendnis der Regel falsch - beides gehoert ins Wiki.
Volltest statt Logiktest: VOLL = True setzen und keine Tabelle ersetzen (laeuft gegen die Datenbank).
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _testbase import NL, compare, finish, read_object, run_sql, values_cte, view_body  # noqa: E402

VOLL = False
NAME = "test_<objekt>"

# Synthetische Quelle: (Kunde, Datum, Menge) - Faelle so waehlen, dass jede Regel der View greift
ZEILEN = [
    ("k1", "2025-01-02", 10),
    ("k1", "2025-01-02", 5),
    ("k2", "2025-01-03", 7),
]


def referenz() -> dict[tuple, list[float]]:
    """Die Regel der View in Python: hier Summe Menge je Kunde."""
    ref: dict[tuple, list[float]] = defaultdict(lambda: [0.0])
    for kunde, _datum, menge in ZEILEN:
        ref[(kunde,)][0] += menge
    return dict(ref)


def main() -> int:
    body = view_body(read_object("<objekt>"))
    # Quelltabelle im Rumpf durch die CTE 'quelle' ersetzen (exakter Text aus der Datei)
    body = body.replace("dbo.<Quelltabelle>", "quelle")
    rows_sql = [f"('{k}', CAST('{d}' AS date), {m})" for k, d, m in ZEILEN]
    cte = values_cte("quelle", ["Kunde", "Datum", "Menge"], rows_sql)
    if body.upper().startswith("WITH"):
        sql = "WITH " + cte + "," + NL + body[4:].lstrip()
    else:
        sql = "WITH " + cte + NL + body
    rows = run_sql(sql, NAME)
    n, bad = compare(rows, referenz(), key_cols=["Kunde"], cols=["Menge_Summe"])
    return finish(NAME, n, bad)


if __name__ == "__main__":
    sys.exit(main())
