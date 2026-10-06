"""run_tests.py - fuehrt die Tests in tools/tests aus.

    python tools/tests/run_tests.py                 # alle Logiktests (Sekunden)
    python tools/tests/run_tests.py --voll          # zusaetzlich die Volltests (Minuten, gegen die Datenbank)
    python tools/tests/run_tests.py --only usp_WA_MF_Aufbau   # nur Tests, deren Name den Text enthaelt
    python tools/tests/run_tests.py --timeout 900   # Zeitlimit je Test in Sekunden

Jeder Test ist ein eigenes Skript test_<objekt>.py mit einer Konstante VOLL (True = Volltest).
Exit 0, wenn alle ausgefuehrten Tests 0 Abweichungen melden; sonst 1. Ergebnisse: outputs/tests/.
Regel (CLAUDE.md): vor jedem Commit in sql/objects laeuft der Logiktest des Objekts gruen.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def is_voll(path: Path) -> bool:
    m = re.search(r"^VOLL\s*=\s*(True|False)", path.read_text(encoding="utf-8"), re.M)
    return bool(m and m.group(1) == "True")


def main() -> int:
    ap = argparse.ArgumentParser(description="Tests der SQL-Objekte ausfuehren")
    ap.add_argument("--voll", action="store_true", help="auch Volltests (Minuten, Datenbank)")
    ap.add_argument("--only", help="nur Tests, deren Dateiname diesen Text enthaelt")
    ap.add_argument("--timeout", type=int, default=3600, help="Zeitlimit je Test in Sekunden")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    tests = sorted(HERE.glob("test_*.py"))
    if not tests:
        print("run_tests: noch keine Tests angelegt (Muster: vorlagen/test_objekt.py)")
        return 0
    if args.only:
        tests = [t for t in tests if args.only in t.name]
    if not args.voll:
        tests = [t for t in tests if not is_voll(t)]
    if not tests:
        print("run_tests: keine passenden Tests")
        return 1

    failed: list[str] = []
    for t in tests:
        kind = "Volltest" if is_voll(t) else "Logiktest"
        t0 = time.time()
        print(f"--- {t.stem} ({kind})")
        try:
            r = subprocess.run([sys.executable, str(t)], cwd=ROOT, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=args.timeout)
            out = (r.stdout + r.stderr).strip()
            code = r.returncode
        except subprocess.TimeoutExpired:
            out, code = f"Zeitlimit {args.timeout} s ueberschritten", 1
        print(out)
        print(f"    -> {'OK' if code == 0 else 'FEHLER'} ({time.time() - t0:.0f} s)")
        if code != 0:
            failed.append(t.stem)
    print(f"run_tests: {len(tests) - len(failed)} von {len(tests)} Tests gruen" + (f"; FEHLER: {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
