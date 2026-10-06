# Modul Datenbank — Regeln

Gilt nur, wenn in `kb.config.yaml` `module.datenbank: true` steht. Ergänzt `CLAUDE.md`, ersetzt nichts davon. Technische Grundlage: Microsoft SQL Server über ODBC (`pip install pyodbc`, „ODBC Driver 18 for SQL Server").

## Einrichtung (einmalig, durch den Nutzer)

1. `.env.example` nach `.env` kopieren und ausfüllen (Server, Datenbank, Anmeldung). `.env` steht in `.gitignore` und wird nie committet.
2. `tools/setup_kb_reader.sql` mit db_owner-Rechten in der Zieldatenbank ausführen (legt den Lesebenutzer `kb_reader` an).
3. `python tools/sql.py --check` — muss „Schreibprobe abgelehnt" und „Bereit." zeigen.
4. `module.datenbank: true` in `kb.config.yaml`, log.md-Eintrag, Commit.

## Datenbankabgleich (Wiki gegen Wirklichkeit prüfen)

Die Arbeitsdatenbank ist lesend erreichbar — **nur so:**

```bash
python tools/sql.py --check                          # Verbindung und Leserechte
python tools/sql.py --list "v_%"                     # Objekte suchen, mit Aenderungsdatum
python tools/sql.py --ddl  "v_Kunde_Umsatz"          # Quelltext ansehen
python tools/sql.py "SELECT TOP 10 * FROM dbo.Kunde"
python tools/sql.py --file abfrage.sql --csv outputs/ergebnis.csv
python tools/sql.py --file abfrage.sql --accdb outputs/x.accdb --table Ergebnis --index "Kunde,Datum"   # vollstaendig nach Access (Windows + Access)
```

**`--ddl` zuerst, dann Zahlen.** Der Quelltext einer View beantwortet meist mehr als jede Ergebnisabfrage: Er zeigt Filterkaskade, Join-Bedingungen, Klassenzuordnung und Sonderfallbehandlung auf einmal — also genau die Stellen, an denen die dokumentierten Entscheidungen (`adr-*`) sichtbar werden oder eben nicht.

Nie mit `sqlcmd`, `pyodbc` oder anderen Wegen direkt auf die Datenbank zugreifen — `tools/sql.py` ist der einzige zugelassene Pfad, weil nur dort beide Schutzschichten greifen:

1. **Datenbankseitig:** Jede Abfrage läuft nach `EXECUTE AS USER = 'kb_reader' WITH NO REVERT`. Dieser Benutzer hat nur `db_datareader`; die Sitzung kann nicht zurückwechseln. Nur ein ausdrücklich leerer Eintrag `KB_READER=` in der `.env` schaltet das ab (für Server ohne eigene Rechte) — `--check` warnt dann.
2. **Werkzeugseitig:** Nur einzelne `SELECT`-Anweisungen werden gesendet (auch mit CTE-Kette `WITH … SELECT` — so lässt sich ein View-Rumpf vor dem Deploy testen); `EXEC`, `REVERT`, `SELECT INTO`, DDL, DML und Mehrfachanweisungen werden vorher abgelehnt.

**Regeln für den Umgang mit Abfrageergebnissen:**

- Ein Datenbankbefund ist eine **Quelle wie jede andere**. Er darf `[FAKT]` tragen, aber nur mit Abfrage und Datum im Text, damit er nachvollziehbar bleibt.
- Weicht die Datenbank vom Wiki ab, ist **nicht automatisch die Datenbank im Recht**. Eine Wiki-Seite kann einen bewusst dokumentierten historischen Stand zeigen. Erst klären, dann ändern.
- Abweichungen, die nicht sofort geklärt werden, gehören in `review-queue.md` — nicht stillschweigend ins Wiki geschrieben (Invariante 4).
- Wird eine Wiki-Aussage durch eine Abfrage widerlegt, gilt Invariante 2: alte Aussage auf `[HISTORISCH]` umtaggen, neue daneben stellen, log.md-Eintrag.
- Ein Tag-Upgrade `[ANNAHME]` → `[FAKT]` durch eine Abfrage ist erlaubt und erwünscht, braucht aber den log.md-Eintrag.

## SQL-Dateien (Ablage und Lebenszyklus)

SQL-Dateien sind **kein Arbeitsgedächtnis**. Es gibt genau drei Klassen:

| Ordner | Inhalt | Regel |
|---|---|---|
| `sql/objects/` | **aktueller Sollzustand** je Datenbankobjekt — eine kanonische Datei, benannt `<schema>.<objekt>.sql` | Bestehende Views und Prozeduren **immer in ihrer kanonischen Datei** aktualisieren |
| `sql/config/` | Sollzustand von Konfigurationstabellen inklusive ihres Inhalts, idempotent ausführbar | wie `objects/` |
| `sql/migrations/` | **einmalige Zustandsübergänge**, benannt `YYYY-MM-DD_thema.sql` | bleiben historisch liegen, werden nie wieder gepflegt und nie als Sollstand gelesen |

- **Keine Versionsnummern im Dateinamen** — kein `_v5`, `_neu`, `_final`. Die Versionshistorie liefert Git.
- **Kein `USE` in den Dateien.** Die Zieldatenbank kommt beim Deploy aus `-Database`.
- **Vor dem Anlegen einer neuen SQL-Datei prüfen, ob für das Objekt schon eine kanonische Datei existiert.** Neue permanente Dateien nur für neue persistente Datenbankobjekte oder echte Migrationen. Neue Datei → Zeile in `sql/deploy-reihenfolge.txt` an der richtigen Stelle (Abhängigkeiten zuerst).
- **Ad-hoc-Abfragen werden nicht committet.** Prüf- und Analyse-SQL läuft über `python tools/sql.py` oder landet in `scratch/` (in `.gitignore`). Ins Repository kommt das **Ergebnis** als Wiki-Aussage, nicht der Weg dorthin.
- **Tests sind Werkzeuge, keine Ad-hoc-Abfragen:** `tools/tests/test_<objekt>.py` (Muster: `vorlagen/test_objekt.py`) extrahiert den Rumpf eines Objekts wörtlich aus `sql/objects`, ersetzt Tabellen durch VALUES (Logiktest, Sekunden) oder nicht (Volltest, Minuten, `VOLL = True`) und prüft gegen eine Python-Referenz oder Konsistenzregeln; Ergebnisse in `outputs/tests/` (gitignored). **Vor jedem Commit in `sql/objects` läuft der Logiktest des Objekts grün:** `python tools/tests/run_tests.py --only <objekt>`; hat ein Objekt keinen Test, steht das im Log-Eintrag.
- **Keine View-Vermehrung durch Filtervarianten.** Eine neue View nur, wenn sie eine eigenständige fachliche Sicht, eine andere Aggregationsebene oder eine echte Schnittstelle darstellt. Reine Filtervarianten werden durch eine **Klassifikationsspalte** in einer gemeinsamen View abgebildet; den Ausschnitt wählt der Verbraucher (`WHERE Klasse = 'A'`). Prüffrage: *Unterscheiden sich die Kandidaten in dem, **was** eine Zeile ist — oder nur darin, **welche** Zeilen übrig bleiben?* Nur im ersten Fall sind es zwei Views.
- **Kopfkommentare bleiben kurz** und verweisen auf die Wiki-Seite. Die Begründung gehört ins Wiki, nicht doppelt in den Quelltext.
- **Formatierung: ein Ausdruck, eine Zeile.** Eine Spaltenberechnung, eine Join-Bedingung, ein Filter stehen komplett in einer Zeile — kein Umbruch mitten in einer Funktion, Division oder einem Vergleich. Einzige Ausnahme ist `CASE`:

  ```sql
  ,CASE
       WHEN a > b THEN a
       WHEN a IS NULL THEN 0
       ELSE b
   END AS Spalte
  ```

  Kommentare stehen in einer eigenen Zeile über dem Ausdruck. Grund: SQL-Dateien werden in SSMS Zeile für Zeile nachvollzogen; ein zerrissener Ausdruck wird dort regelmäßig falsch gelesen.
- **Alle Zeichenketten in `sql/` sind ASCII** (`Kuehlung`, nicht `Kühlung`). `sqlcmd` liest Skriptdateien ohne `-f 65001` mit der ANSI-Codepage und schreibt Umlaute sonst als Mojibake **in die Tabelle**, nicht nur in die Anzeige.

## Deploy und Drift

Den Sollzustand bringt **der Nutzer** in die Datenbank: `.\tools\deploy.ps1 -Server <server> -Database <db>` (Reihenfolge aus `sql/deploy-reihenfolge.txt`, `-WhatIf` zeigt sie nur an, `-MitExec` führt auch die `EXEC`-Zeilen aus). **Der Agent deployt nie.**

Ob Datei und Datenbank übereinstimmen, prüft `python tools/kb_drift.py` (normalisierter DDL-Vergleich) — vor jeder Verifikation laufen lassen. Der Traum vergleicht nur Zeitstempel (Commit gegen Änderungsdatum in der Datenbank).

Arbeitsteilung insgesamt: **Datenbank** = Ist-Zustand · **`sql/objects` und `sql/config`** = Sollzustand · **Git** = Historie · **Wiki** = Erklärung und Entscheidung · **`sql/migrations`** = einmalige Übergänge · **`scratch/`** = wegwerfbar.
