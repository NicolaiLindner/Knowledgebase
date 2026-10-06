# Vorlagen

Muster zum Kopieren. Liegen bewusst außerhalb von `wiki/`, damit `kb_lint` sie nicht prüft.
Platzhalter stehen in spitzen Klammern `<…>`; nach dem Kopieren alle ersetzen, dann `python tools/kb_lint.py`.

| Datei | Ziel | wofür |
|---|---|---|
| `raw-notiz.md` | `raw/<kuerzel>-<thema>.md` | Quelle für mündliche Aussagen, Chat-Auskünfte, Besprechungen |
| `seite-steckbrief.md` | `wiki/projects/<kuerzel>-steckbrief.md` | Projektsteckbrief (Hub-Seite) |
| `seite-offene-punkte.md` | `wiki/projects/<kuerzel>-offene-punkte.md` | priorisierte offene Punkte (Hub-Seite) |
| `seite-konzept.md` | `wiki/concepts/` | Begriff, Methode, Regel |
| `seite-allgemein-erfahrung.md` | `wiki/concepts/` (domain allgemein) | übertragbare Regel: Beobachtungen → Abstraktion → Grenzen |
| `seite-datenmodell.md` | `wiki/data-model/` | Quelle, System, Tabelle, Dokumentstruktur |
| `seite-analyse.md` | `wiki/analyses/` | Auswertung mit Ergebnis und Datenstand |
| `adr.md` | `wiki/decisions/adr-NNN-<thema>.md` | Entscheidung |
| `seite-known-issue.md` | `wiki/known-issues/` | Fallstrick, Datenfehler, Unsicherheit |
| `log-eintrag.md` | ans Ende von `log.md` | Journal-Eintrag je Arbeitsschritt |
| `test_objekt.py` | `tools/tests/test_<objekt>.py` | Logiktest eines SQL-Objekts (Modul Datenbank) |
