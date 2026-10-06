# sql/ — Sollzustand der Arbeitsdatenbank (Modul Datenbank)

Skripte, die **der Nutzer** gegen die Arbeitsdatenbank ausführt (`tools/deploy.ps1`).
Der lesende Zugang der KB (`python tools/sql.py`) kann sie nicht ausführen — er darf nur `SELECT`.
Regeln: [MODUL-DATENBANK.md](../MODUL-DATENBANK.md).

| Ordner / Datei | Bedeutung |
|---|---|
| `objects/` | **aktueller Sollzustand** je Datenbankobjekt, eine kanonische Datei `<schema>.<objekt>.sql` |
| `config/` | Sollzustand der Konfigurationstabellen **inklusive ihres Inhalts**, idempotent |
| `migrations/` | **einmalige Zustandsübergänge** `YYYY-MM-DD_thema.sql`, bleiben historisch liegen |
| `deploy-reihenfolge.txt` | Reihenfolge für `tools/deploy.ps1`, Abhängigkeiten zuerst |

Keine Versionsnummern im Dateinamen, kein `USE` in den Dateien. Die Historie liefert Git.
Ad-hoc-Abfragen gehören nach `scratch/` (in `.gitignore`) — ins Repository kommt das Ergebnis als Wiki-Aussage.
