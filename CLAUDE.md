# Wissensbasis — Betriebsanleitung für KI-Agenten

Dieses Dokument ist die verbindliche Anleitung für jede (menschliche oder KI-) Pflege dieser Wissensbasis. Bei Konflikten zwischen diesem Dokument und Gewohnheit gilt dieses Dokument.

**Projektspezifische Werte** (Name, erlaubte `domain`- und `topics`-Werte, Sammelseiten, Module) stehen ausschließlich in `kb.config.yaml`. **Projektspezifische Regeln** stehen in Abschnitt 9 am Ende dieses Dokuments. Ist dort noch nichts eingetragen, ist die Wissensbasis nicht eingerichtet → Skill `/einrichten`.

## 1. Zweck und Architektur

Vier Ablagen:

1. **`raw/`** — unveränderte Quelldokumente (Protokolle, Mails, Auszüge, PDF-Extrakte, Übergaben). Verifikationsbasis: Jede Aussage im Wiki muss auf eine Datei in `raw/` zurückführbar sein.
2. **`wiki/`** — das gepflegte Wissen. Kleine, verlinkte Markdown-Seiten mit Frontmatter.
3. **`CLAUDE.md`** (dieses Dokument) — Schema und Regeln.
4. **`traeume/`** — Protokolle der Konsolidierungsläufe (eine Datei je Lauf, `YYYY-MM-DD.md`). Vorschläge, kein Wissen.

Leseweg für Anfragen: `index.md` → passende Seite(n) → Antwort mit `[[wikilinks]]` als Quellenangabe.

**Drei Gedächtnisschichten:**

```
 WIKI (semantisch)  ◄── Konsolidierung ──  TRAUM (Reflexion)  ◄── Replay ──  LOG (episodisch)
 quer dazu:  Queue = unerledigte kognitive Arbeit · Git = tatsächliche Veränderungshistorie
```

`log.md` ist das episodische Gedächtnis (was ist passiert), `wiki/` das semantische (was gilt), `traeume/` die Reflexion dazwischen (was folgt daraus — als Vorschlag). Mit eingeschaltetem Modul Datenbank kommt die **Datenbank als externe Realität** hinzu (Abschnitt 5, „Module").

## 2. Invarianten (harte Regeln)

1. **`raw/` wird NIE verändert.** Neue Quellen kommen als neue Dateien dazu (`raw/<kebab-name>.md`).
2. **Nichts löschen.** Überholte Aussagen werden zu `[HISTORISCH]` umgetaggt (mit Datum/Grund), überholte Seiten bekommen `status: historisch`.
3. **`log.md` und `review-queue.md` sind append-only.** Bestehende Einträge werden nie editiert (Ausnahme: Abhaken `[ ]` → `[x]` in der Review-Queue). `traeume/` ebenso: eine Datei je Lauf, nach dem Commit nie editiert — Korrekturen kommen ins nächste Protokoll.
4. **Keine Kaskaden-Updates.** Ein Ingest/Edit ändert nur die direkt betroffenen Seiten. Mögliche Auswirkungen auf Nachbarseiten werden als Eintrag in `review-queue.md` notiert, nicht still mitgeschrieben.
5. **Lint vor Commit:** `python tools/kb_lint.py` muss Exit-Code 0 liefern.
6. **Single-Source-Prinzip:** Jeder Fakt hat genau EINE Heimatseite. Andere Seiten verlinken dorthin, statt den Fakt zu wiederholen. (Kurze Ein-Satz-Zusammenfassungen mit Link sind erlaubt, Zahlen-Duplikate nicht.)
7. **Ein Commit pro logischem Arbeitsschritt**, Commit-Message beschreibt den Schritt und passt zum log.md-Eintrag.
8. **Nichts erfinden.** Jede neue Aussage braucht eine Quelle in `sources:` oder das Tag `[ANNAHME]`.
9. **Offene Fragen ändern keine produktive Logik.** Eindeutig vom Nutzer bestätigtes Fachwissen darf direkt als `[FAKT]` oder `[ENTSCHEIDUNG]` aufgenommen werden — der Nutzer ist eine Quelle, im Text als solche kenntlich zu machen (und als `raw/`-Notiz abzulegen, wenn es mehr als ein Satz ist). Alles Ungeklärte wird **nur dokumentiert**: als `[OFFEN]` auf der Fachseite und, wenn es Nachbarseiten berührt, in `review-queue.md`. Es fließt nicht in Berechnungen, Code, SQL oder Lieferobjekte ein, solange es nicht entschieden ist.
10. **Ein Traum ändert nichts.** `tools/kb_dream.py` und der Skill `/traeumen` schreiben ausschließlich `traeume/<datum>.md` (und die Maschinendatei `traeume/<datum>.befunde.md`) — nie `wiki/`, `log.md`, `review-queue.md`, `sql/` oder dieses Dokument. Umsetzen ist ein eigener Arbeitsschritt (Wachsitzung) mit normalem Commit und log.md-Eintrag, der die Vorschlags-IDs nennt: `T-YYYY-MM-DD-NN umgesetzt (wert: hoch|mittel|niedrig)` · `T-… verworfen: Beobachtung falsch | Interpretation falsch | Vorschlag schlecht` · `T-… vertagt` · `T-… in Queue`. Der Traum-Commit selbst enthält nur die Protokolldateien und braucht keinen log.md-Eintrag (dokumentierte Ausnahme von Invariante 7).

## 3. Frontmatter-Schema

Jede Seite unter `wiki/` beginnt mit:

```yaml
---
title: "Lieferzeit vs. Durchlaufzeit"     # Pflicht; Anzeigename, Umlaute erlaubt
type: concept                             # Pflicht, an Ordner gekoppelt (s.u.)
domain: projekt                           # Pflicht: ein Kürzel aus kb.config.yaml oder allgemein
topics: [kennzahlen, prozess]             # Pflicht, >= 1 Eintrag; erlaubte Werte in kb.config.yaml
status: aktiv                             # Pflicht: entwurf | aktiv | historisch
summary: "Ein Satz, was die Seite beantwortet."   # Pflicht
sources:                                  # Pflicht, >= 1 raw/-Pfad, optional mit #anker
  - raw/projekt-kickoff-protokoll.md#begriffe
related: [kennzahlen-uebersicht]          # optional, 3-5 kuratierte Links
aliases: ["Lieferzeit vs. Durchlaufzeit"] # optional; Pflicht, wenn title Umlaute/Sonderzeichen hat
created: 2026-01-15                       # Pflicht, YYYY-MM-DD
updated: 2026-01-15                       # Pflicht, >= created; bei JEDEM inhaltlichen Edit setzen
---
```

**YAML-Falle:** Enthält ein Wert deutsche Anführungszeichen („…") oder einen Doppelpunkt, muss er in **einfache** Anführungszeichen (`'…'`). In doppelten Anführungszeichen bricht der Parser. Betrifft vor allem `title` und `summary`.

**`type` ↔ Ordner:** `project` → `wiki/projects/`, `concept` → `wiki/concepts/`, `data-model` → `wiki/data-model/`, `analysis` → `wiki/analyses/`, `decision` → `wiki/decisions/`, `known-issue` → `wiki/known-issues/`.

| type | wofür |
|---|---|
| `project` | Steckbrief, offene Punkte, Kommunikation, Übergaben eines Projekts |
| `concept` | Begriffe, Methoden, Regeln — was etwas *ist* und wie man es richtig benutzt |
| `data-model` | Quellen, Systeme, Tabellen, Dokumentstrukturen — *woher* die Daten kommen |
| `analysis` | Auswertungen mit Ergebnis und Datenstand |
| `decision` | Entscheidungen (`adr-NNN-…`) mit Kontext, Alternativen, Folgen |
| `known-issue` | Fallstricke, Datenfehler, Unsicherheiten |

**`domain`:** Projektkürzel (aus `kb.config.yaml`) = projektspezifisches Wissen, `allgemein` = übertragbare Regeln/Patterns, die über das Projekt hinaus gelten. Übertragbare Regeln von Einzelfällen trennen — im Zweifel den Einzelfall auf einer Projektseite, die Regel auf einer `allgemein`-Seite.

**`topics`** (Mehrfachzuordnung erwünscht): erlaubte Werte stehen in `kb.config.yaml`. Neue Topics sind erlaubt, wenn kein bestehendes passt — dann dort ergänzen und im log.md vermerken.

## 4. Verlässlichkeits-Tags (claim-level)

Kernaussagen stehen als Bullets, die mit genau einem Tag beginnen:

```markdown
- [FAKT] Aufträge werden im Mittel 2,3 Tage nach Eingang ausgeliefert (Auszug Auftragsliste Q1, 1.240 Aufträge).
```

| Tag | Bedeutung |
|---|---|
| `[FAKT]` | in den Daten geprüft, mit Beleg |
| `[ENTSCHEIDUNG]` | bewusst getroffene Festlegung |
| `[ERFAHRUNG]` | Best Practice / übertragbare Regel |
| `[ANNAHME]` | plausibel, aber nicht verifiziert |
| `[HISTORISCH]` | überholt, nur für Nachvollziehbarkeit |
| `[OFFEN]` | ungeklärt / nächster Schritt |

**Lebenszyklus:**
- Tags werden beim Ingest **1:1 aus der Quelle übernommen**, nie stillschweigend aufgewertet.
- Upgrade (z. B. `[ANNAHME]` → `[FAKT]`) nur mit neuer Quelle in `sources:` **und** log.md-Eintrag.
- Überholtes wird umgetaggt: `- [HISTORISCH] (bis 2026-03: ...) alte Aussage` — nie gelöscht.
- Erläuternder Fließtext ohne Tag ist erlaubt, darf aber keine neuen Fakten/Zahlen einführen.
- `[OFFEN]` trägt ein Datum oder einen Anlass, sonst lässt es sich nicht priorisieren.
- **Template für `[ENTSCHEIDUNG]`-Bullets:** *(Quelle, Datum)* **Regel in einem Satz.** *Herleitung oder Kontrollwert:* woraus die Zahl folgt oder welche Probe sie bestätigt. *Nicht enthalten:* was die Regel bewusst weglässt. *Umsetzung:* wo sie wirkt (Dokument, Objekt, Commit). Höchstens etwa 600 Zeichen; Zahlenreihen gehören nicht ins Bullet, sondern in eine Tabelle der Seite. Grund: Bullets mit zehn Zahlen sind im Lint unlesbar und im Chat nicht zitierbar (`kb_lint --warn` meldet Zeilen über 600 Zeichen).
- **`[ERFAHRUNG]` auf `allgemein`-Seiten** folgt nach Möglichkeit der Struktur *Beobachtungen* (≥ 2 Einzelfälle mit Quelle) → *Abstraktion* (die Regel, ohne Projektzahlen) → *Gültigkeitsbereich* (wann sie greift) → *Nicht behaupten* (die Übergeneralisierung, vor der die Regel sich selbst schützt). Der letzte Teil verhindert, dass aus zwei Erfahrungen eine falsche universelle Wahrheit wird.

## 5. Workflows

Muster für Seiten, Log-Einträge und Queue-Zeilen liegen in `vorlagen/` (außerhalb von `wiki/`, damit der Lint sie nicht prüft).

### Ingest (neue Quelle einarbeiten)

1. Quelldokument unverändert nach `raw/<kebab-name>.md` legen. PDF: `python tools/pdf.py extract quelle.pdf --out raw/<name>` (Text je Seite mit Anker `#s-12`, Tabellen mit `tables` als CSV). Andere Formate: wortgetreu als Markdown, Herkunft und Datum im Kopf.
2. Betroffene Seiten finden: `index.md` lesen + Grep über `wiki/` nach Schlüsselbegriffen.
3. Betroffene Seiten editieren bzw. neue Seiten anlegen (Frontmatter vollständig, `updated` setzen, neue Quelle in `sources:` ergänzen). Neue Seite → auch in `index.md` eintragen.
4. Mögliche Auswirkungen auf NICHT editierte Nachbarseiten → `review-queue.md`: `- [ ] YYYY-MM-DD | TYP | seiten-name | Grund`. `TYP`: `PRUEFEN` = Prüfung, die der Agent selbst machen kann · `ENTSCHEIDUNG` = braucht Nutzer oder Kollegen · `NACHZUG` = Folgeänderung nach einer getroffenen Entscheidung · `DOKU` = nur dokumentieren. Wartet der Eintrag auf jemanden, steht `wartet: Nutzer|Kollegen|Deploy` im Grund. Erledigt: `[x]` und hinter dem Grund ` -- <Beleg/Resolution>`.
5. log.md-Eintrag: Datum, Quelle, geänderte/neue Seiten, offene Punkte (Muster: `vorlagen/log-eintrag.md`).
6. `python tools/kb_lint.py` → Fehler beheben → ein Commit.

### Audit (Korrektheit prüfen)

Für jede zu prüfende Seite: den in `sources:` referenzierten raw/-Abschnitt daneben legen und semantisch vergleichen — stimmen Zahlen, Tags und Aussagen? Zahlendreher und still aufgewertete Tags sind die Hauptfehlerbilder. Befunde in `review-queue.md`, Korrekturen als normaler Edit + log-Eintrag.

### Neues Projekt aufnehmen

Die Wissensbasis kann mehrere Projekte tragen (oder je Projekt ein eigenes Repo aus dieser Vorlage — dann bleiben die `allgemein`-Seiten je Repo getrennt zu pflegen).

1. Quelldokument nach `raw/<kuerzel>-<thema>.md` legen (Dateiname trägt das Projektkürzel).
2. Projektkürzel in `kb.config.yaml` unter `domains` eintragen.
3. Projektseiten unter `wiki/projects/` anlegen: mindestens `<kuerzel>-steckbrief` und `<kuerzel>-offene-punkte` (Muster in `vorlagen/`), beide unter `hub_seiten` in `kb.config.yaml`.
4. Fachseiten anlegen. **Vorher prüfen, ob eine bestehende `domain: allgemein`-Seite den Sachverhalt schon abdeckt** — übertragbare Regeln gehören genau einmal in die KB und werden aus allen Projekten verlinkt. Nur projektspezifische Zahlen und Entscheidungen bekommen eigene Seiten.
5. `index.md` um einen Projektabschnitt ergänzen.
6. Lint, log.md-Eintrag, Commit.

Ab etwa 50 Seiten wird `index.md` unübersichtlich. Dann je Ordner eine `moc-<ordner>.md` (Map of Content) anlegen und `index.md` auf die MOCs reduzieren.

### Kennzahl bauen (Definition of Done)

Gilt für jede neue Zahl, die in ein Lieferobjekt geht (Bericht, Tabelle, Präsentation, View). **Vor dem Bau** stehen drei Zeilen im Chat oder im Log, sonst wird nicht gebaut:

1. **Regel in einem Satz.** Ein Fachkollege muss sie ohne Code nachsprechen können.
2. **Herleitung** aus einer Quelle, die die Empfänger selbst kennen (Tabelle, Bericht, Zelle, Rechnung). Ist die Kennzahl prozedural und nicht direkt herleitbar, dann ein **Kontrollwert**: Summenprobe (Teile = Gesamt), Untergrenze, Bilanz (Zufluss = Abfluss).
3. **Kontrollwert für den Empfänger** — der Wert, der nach dem Umbau im Lieferobjekt stehen muss, mit Datum und Datenstand.

**Nach dem Bau:** Abweichungen zwischen Ergebnis und Handrechnung (Rundung, Stichtag, Abgrenzung) werden benannt, bevor jemand fragt — als Fußnote im Lieferobjekt und als Satz im `[ENTSCHEIDUNG]`-Bullet. Eine Zahl, die die Empfänger nicht nachrechnen können, gilt als falsch, auch wenn das Modell recht hat.

### Query (Fragen beantworten)

`index.md` → Seite(n) lesen → antworten und dabei die benutzten Seiten als `[[links]]` nennen. Steht die Antwort nicht im Wiki, das sagen — nicht raten. Fehlt etwas, das in `raw/` steht, ist das eine Lücke: als `[OFFEN]`-Kandidat in `review-queue.md` notieren.

### Träumen (Konsolidierungslauf)

Der Traum ist die Reflexionsschicht zwischen Log und Wiki: Replay der Episoden seit dem letzten Lauf, Ausmisten (Queue), Verallgemeinern (Projekt-Einzelfall → `allgemein`-Regel), Widersprüche und Upgrade-Kandidaten, Fragen.

**Rhythmus:** Verbindlich ist die **Lage** zu Beginn jeder Sitzung (`/lage`, höchstens 25 Zeilen, schreibt nichts). Der **Traum** läuft etwa wöchentlich nach Wiki-Änderungen, nicht je Arbeitsblock. Nur Queue-Kandidaten und semantische Vorschläge bekommen T-IDs; alles Mechanische steht als Zähler mit Beispielen im Protokoll und vollständig in `traeume/<datum>.befunde.md` (Maschinendatei, nicht zum Lesen). Grund: Ein Protokoll mit hundert nummerierten Rohbefunden liest niemand.

- Aufruf: `/traeumen [--since YYYY-MM-DD] [--no-db]` (Skill in `.claude/skills/traeumen/`) — führt `python tools/kb_dream.py` aus und ergänzt semantische Vorschläge. Nur das Werkzeug: `python tools/kb_dream.py [--stdout] [--bilanz] [--lage]`.
- Jeder Befund trägt drei getrennte Felder: **Beobachtung** (messbar), *Interpretation* (Deutung), → Vorschlag (Handlung) — plus Konfidenz (hoch = zwei unabhängige Belege · mittel = ein Beleg · niedrig = Heuristik · Info = Rohstoff) und Belegzeilen. Die Trennung erlaubt später zu sagen, *wo* ein Vorschlag scheiterte.
- Qualität wird in drei Größen gemessen: **Precision** (nicht als Beobachtung/Interpretation falsch verworfen), **Adoption** (umgesetzt), **Value** (`wert:` bei umgesetzten — hätte man es ohne Traum bemerkt?). `--bilanz` zeigt die kumulierte Tabelle über die semantischen Kategorien `[V-…]`.
- **Leitsatz: Signal maximieren, nicht Befunde.** Obergrenze 12 semantische Vorschläge, max. 4 je Kategorie; ein dünner Traum ist erlaubt und muss sich nicht rechtfertigen.
- Aufwachen = normaler Ingest-/Edit-Workflow: Vorschlag prüfen, umsetzen oder verwerfen, Lint, Commit, log.md-Eintrag mit den `T-…`-Notationen aus Invariante 10.

### Module

Optionale Erweiterungen, geschaltet in `kb.config.yaml` unter `module:`.

- **Datenbank** (`module.datenbank: true`): lesender Zugriff auf eine Microsoft-SQL-Server-Datenbank, Sollzustand von Views/Prozeduren in `sql/`, Drift-Prüfung, Tests. **Ist das Modul eingeschaltet, gilt zusätzlich `MODUL-DATENBANK.md` — vor jeder Datenbankarbeit lesen.** Ist es aus, werden `sql/`, `tools/sql.py`, `tools/kb_drift.py`, `tools/deploy.ps1` und `tools/tests/` nicht benutzt.

## 6. Namens-, Link- und Seitenkonventionen

- **Dateinamen:** ASCII-kebab-case, Umlaute transkribiert (`ä→ae, ö→oe, ü→ue, ß→ss`). Global eindeutig über alle Ordner. Präfix `adr-NNN-` für Entscheidungsseiten.
- **Wikilinks:** immer `[[dateiname]]` bzw. `[[dateiname|Anzeigetext]]` — nie Pfade, nie `.md`.
- **`raw/` nie per Wikilink referenzieren** — nur über `sources:` im Frontmatter.
- **Standard-Seitenaufbau:** H1-Titel → 1–3 Sätze Einordnung → getaggte Kernaussagen → Details/Tabellen → (falls vorhanden) Abschnitt „Offene Punkte".
- Tabellen und Code-Blöcke aus Quellen originalgetreu übernehmen; nichts „verschönern".

## 7. Anti-Patterns (NICHT tun)

- `raw/`-Dateien editieren, „korrigieren" oder formatieren.
- Verlässlichkeits-Tags erfinden, weglassen oder ohne Quelle aufwerten.
- Seiten umbenennen ohne alle eingehenden Wikilinks anzupassen (danach Lint!).
- Wissen in `log.md` oder `review-queue.md` ablegen statt auf einer Wiki-Seite.
- Denselben Fakt (insbesondere Zahlen) auf mehreren Seiten ausschreiben — verlinken statt duplizieren.
- Sammel-Commits über mehrere logische Schritte.
- Unsicherheiten wegformulieren — `[ANNAHME]`/`[OFFEN]` sind Feature, nicht Makel.
- Ein Traumprotokoll nachträglich editieren, Vorschläge direkt aus dem Traum heraus umsetzen, oder einen Traum mit Befunden auffüllen, nur damit er voll aussieht.
- Zugangsdaten, Kundennamen in öffentlichen Kopien, `.env`-Inhalte in Dateien, Aufrufen oder im Log.

## 8. Sitzungsregeln

- **Eine schreibende Sitzung je Repo.** Arbeiten zwei KI-Sitzungen gleichzeitig im selben Repo, überschreiben sie Commits und Log-Einträge. Die zweite Sitzung liest nur — oder sie arbeitet in einem eigenen git-Worktree und übergibt per Log-Eintrag. Wer eine Datei geändert vorfindet, die er nicht angefasst hat, stoppt und fragt.
- **Sitzungsstart mit `/lage`.** Letzte Log-Einträge mit offenen Punkten, Queue zu den zuletzt berührten Seiten, Vitalwerte. Danach erst Wiki lesen.
- **Ein Chat je Arbeitsblock.** Ein Chat, der über die Kontextgrenze läuft, verliert Zahlen und wiederholt Erklärungen. Ist ein Block abgeschlossen (Commit, Log-Eintrag), beginnt der nächste in einer neuen Sitzung mit `/lage`.
- **Kein Abschlussritual.** Der Log-Eintrag je Schritt ist der Stand; ein zusätzlicher „Stand"-Eintrag am Sitzungsende ist Doppelung.

## 9. Projektspezifische Regeln

_Noch nicht eingerichtet. `/einrichten` füllt diesen Abschnitt: worum es in der Wissensbasis geht, wer die Empfänger sind, welche Fachregeln in jeder Auswertung gelten (z. B. Pflichtfilter, Einheiten, Stichtage). Regeln hier nur, wenn sie für jede Sitzung gelten — Fachwissen gehört ins Wiki._
