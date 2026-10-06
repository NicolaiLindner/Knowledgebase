# Wissensbasis-Vorlage

Vorlage für eine **KI-gepflegte, quellengebundene Wissensbasis** in Git: Ein Sprachmodell-Agent (entwickelt mit [Claude Code](https://claude.com/claude-code)) arbeitet Quellen ein, pflegt ein verlinktes Markdown-Wiki und markiert jede Aussage mit ihrer Verlässlichkeit. Fachlich neutral — für Beratungsprojekte, Datenanalysen, Forschung, Produktwissen oder alles andere, bei dem Wissen aus vielen Quellen nachvollziehbar zusammenwachsen soll.

> **Neues Projekt:** auf GitHub „Use this template" → klonen → `pip install -r requirements.txt` → in Claude Code `/einrichten`.

## Das Prinzip

```
 raw/       unveränderte Quellen  ──►  Verifikationsbasis, wird nie editiert
 wiki/      gepflegtes Wissen     ──►  kleine Seiten, Frontmatter, Tags je Aussage
 log.md     was ist passiert      ──►  episodisches Gedächtnis, append-only
 traeume/   was folgt daraus      ──►  Reflexion: Vorschläge mit Beleg, ändert nichts
 review-queue.md                  ──►  offene Denkarbeit statt stiller Kaskaden-Änderungen
 CLAUDE.md  Regeln                ──►  Schema, Invarianten, Workflows für den Agenten
```

**Wissen wird nicht überschrieben, sondern mit Herkunft und Verlässlichkeit angereichert.** Jede Kernaussage beginnt mit einem Tag:

| Tag | Bedeutung |
|---|---|
| `[FAKT]` | geprüft, mit Beleg |
| `[ENTSCHEIDUNG]` | bewusste Festlegung |
| `[ERFAHRUNG]` | übertragbare Regel |
| `[ANNAHME]` | plausibel, nicht verifiziert |
| `[HISTORISCH]` | überholt, bleibt zur Nachvollziehbarkeit |
| `[OFFEN]` | ungeklärt |

Überholtes wird `[HISTORISCH]` statt gelöscht, Ungeklärtes bleibt `[OFFEN]` und fließt nicht in Ergebnisse ein, jede Aussage zeigt über `sources:` auf eine Datei in `raw/`. Ein Linter erzwingt die Form vor jedem Commit, Git liefert die Historie.

Die Idee geht auf das „LLM-Wiki"-Muster (ein Sprachmodell pflegt ein Markdown-Wiki statt eines Vektorspeichers) und Zettelkasten-Gedanken zurück; die Verlässlichkeits-Tags, die Queue und der Traum sind aus der Praxis in mehreren Projekten entstanden.

## Schnellstart

```bash
pip install -r requirements.txt     # mindestens pyyaml
python tools/kb_lint.py             # muss auf der leeren Vorlage "OK" melden
```

Dann in Claude Code im Repo-Ordner:

| Befehl | was passiert |
|---|---|
| `/einrichten` | fragt Name, Projektkürzel, Zweck, Topics ab; legt Quelle, Steckbrief, offene Punkte, Config und ersten Log-Eintrag an |
| `/lage` | Sitzungsstart in 25 Zeilen: was zuletzt passiert ist, was offen ist |
| `/traeumen` | wöchentlicher Konsolidierungslauf: Queue ausmisten, Widersprüche, Verallgemeinerungen — nur Vorschläge |

Danach einfach arbeiten: „Arbeite `raw/protokoll-kickoff.md` ein", „Was wissen wir über X?", „Prüfe die Seite Y gegen ihre Quelle". Die Workflows dafür stehen in [CLAUDE.md](CLAUDE.md).

Ohne Claude Code funktioniert die Struktur genauso mit jedem anderen Agenten, der `CLAUDE.md` liest — oder von Hand. Das Verzeichnis ist zugleich ein [Obsidian](https://obsidian.md)-Vault (`[[Wikilinks]]`).

## Aufbau

| Pfad | Inhalt |
|---|---|
| `kb.config.yaml` | **einzige Datei mit Projektwerten:** Name, erlaubte `domain`- und `topics`-Werte, Sammelseiten, Module |
| `CLAUDE.md` | Schema und Regeln für den Agenten; Abschnitt 9 = projektspezifische Regeln |
| `raw/` | Quellen, unverändert |
| `wiki/` | `projects/` · `concepts/` · `data-model/` · `analyses/` · `decisions/` · `known-issues/` |
| `traeume/` | Protokolle der Konsolidierungsläufe |
| `vorlagen/` | Muster für jede Seitenart, Log-Eintrag, Quellennotiz, Test |
| `tools/` | Werkzeuge (siehe unten) |
| `.claude/skills/` | `/einrichten`, `/lage`, `/traeumen` |
| `sql/`, `MODUL-DATENBANK.md` | optionales Modul Datenbank |

## Werkzeuge

| Werkzeug | Zweck |
|---|---|
| `tools/kb_lint.py` | Konsistenz: kaputte Links, Frontmatter, erlaubte Werte, unbekannte Tags, fehlende Quellen; `--warn` zeigt überlange Zeilen und Seiten. Läuft auch als GitHub Action. |
| `tools/kb_dream.py` | Traum (Replay, Queue-Triage, Link-Hygiene, Rückstau, Generalisierungs-Rohstoff), `--lage`, `--bilanz` (Precision/Adoption/Value der Vorschläge) |
| `tools/pdf.py` | PDF-Quellen wortgetreu je Seite extrahieren (Anker `#s-12`), Tabellen als CSV, Volltextsuche |
| `tools/kb_config.py` | liest `kb.config.yaml` |

### Modul Datenbank (optional)

Für Projekte mit einer Microsoft-SQL-Server-Datenbank: `tools/sql.py` (nur `SELECT`, zweifach abgesichert über Werkzeug-Guard und einen Lesebenutzer mit `EXECUTE AS … WITH NO REVERT`), Sollzustand von Views und Prozeduren in `sql/`, Drift-Prüfung Datei ↔ Datenbank (`kb_drift.py`), Deploy-Skript für den Nutzer, Testgerüst für SQL-Objekte. Einschalten in `kb.config.yaml`, Regeln in [MODUL-DATENBANK.md](MODUL-DATENBANK.md). Wer es nicht braucht, lässt es aus — oder löscht `sql/`, `MODUL-DATENBANK.md`, `tools/sql.py`, `tools/kb_drift.py`, `tools/deploy.ps1`, `tools/accdb_import.ps1`, `tools/setup_kb_reader.sql` und `tools/tests/`.

## Stärken und Grenzen

**Gut:** Nachvollziehbarkeit (zu jeder Zahl Quelle, Datum, Grund), ehrlicher Umgang mit Unsicherheit, kein stilles Überschreiben, Trennung von Projektwissen (`domain: <projekt>`) und übertragbaren Regeln (`domain: allgemein`).

**Bewusster Preis:** Jeder Schritt kostet Frontmatter, Tags, Log-Eintrag, Lint und Commit — das System ist ein revisionssicheres Fachgedächtnis, kein schnelles Notizbuch. Die Review-Queue wächst schneller, als man sie abarbeitet, wenn man sie nicht regelmäßig triagiert (dafür der Traum). Zwei gleichzeitig schreibende Agenten-Sitzungen im selben Repo überschreiben einander — eine schreibende Sitzung je Repo.

## Lizenz

[MIT](LICENSE)
