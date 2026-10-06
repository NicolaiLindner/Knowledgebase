---
name: einrichten
description: Richtet eine frisch aus der Vorlage erzeugte Wissensbasis fuer ein Projekt ein - fragt Name, Projektkuerzel, Zweck, Empfaenger, Topics und Module ab, legt die erste raw-Quelle, Steckbrief und offene Punkte an, fuellt kb.config.yaml, index.md, CLAUDE.md Abschnitt 9 und den ersten log.md-Eintrag, prueft mit kb_lint und committet. Aufruf /einrichten (auch fuer ein weiteres Projekt in derselben Wissensbasis)
---

# /einrichten — aus der Vorlage eine Wissensbasis machen

Du fuehrst den Nutzer durch die Einrichtung. Am Ende ist die Wissensbasis lint-gruen, hat zwei
Projektseiten, eine Quelle und einen ersten Log-Eintrag — und nichts ist erfunden.

## 1. Zustand pruefen

- `kb.config.yaml`, Abschnitt 9 der `CLAUDE.md`, `log.md` und `wiki/projects/` lesen.
- Schon eingerichtet (Abschnitt 9 ausgefuellt, Projektseiten vorhanden)? Dann fragen, ob ein
  **weiteres Projekt** aufgenommen werden soll — und den Workflow "Neues Projekt aufnehmen"
  aus CLAUDE.md Abschnitt 5 befolgen (Schritte unten sinngemaess, Abschnitt 9 nur ergaenzen).
- `python tools/kb_lint.py` muss vorher gruen sein; sonst erst das melden.

## 2. Abfragen (eine Nachricht, kompakt)

1. **Name** der Wissensbasis (Anzeigename).
2. **Projektkuerzel** (ASCII, klein, kurz — wird `domain`-Wert und Dateipraefix, z. B. `kundea`).
3. **Worum geht es?** 1–3 Saetze: Gegenstand, Ziel, gewuenschtes Ergebnis.
4. **Fuer wen?** Empfaenger der Ergebnisse (Rolle), und was sie mit den Zahlen tun.
5. **Erste Quelle:** Liegt ein Dokument vor (Pfad: PDF, Markdown, Text, Mail)? Sonst wird das
   Gespraech selbst die erste Quelle (`raw/<kuerzel>-einrichtung.md` nach `vorlagen/raw-notiz.md`).
6. **Topics:** Schlage 8–15 Begriffe aus der Fachsprache des Projekts vor (aus 3. und der Quelle);
   der Nutzer streicht und ergaenzt.
7. **Regeln fuer jede Sitzung** (optional): Pflichtfilter, Einheiten, Stichtage, Sprache der
   Lieferobjekte — nur was wirklich *immer* gilt.
8. **Modul Datenbank?** Nur wenn eine Microsoft-SQL-Server-Datenbank lesend angebunden werden soll.

Nichts davon raten. Fehlt eine Antwort, bleibt das Feld als `[OFFEN]` stehen.

## 3. Anlegen

In dieser Reihenfolge, alles mit dem heutigen Datum:

1. **Quelle** nach `raw/`: vorhandenes Dokument unveraendert (PDF: `python tools/pdf.py extract
   <pdf> --out raw/<kuerzel>-<thema>`), sonst die Einrichtungsnotiz mit den Antworten aus Schritt 2
   — wortnah, als Aussagen des Nutzers gekennzeichnet.
2. **`kb.config.yaml`:** `name`, `domains: [<kuerzel>]` (bei weiterem Projekt anhaengen), `topics`,
   `hub_seiten: [<kuerzel>-steckbrief, <kuerzel>-offene-punkte]`. `module.datenbank` bleibt `false`
   (siehe 5.).
3. **`wiki/projects/<kuerzel>-steckbrief.md`** und **`<kuerzel>-offene-punkte.md`** aus `vorlagen/`.
   Tags ehrlich: Aussagen des Nutzers ueber Ziele/Abgrenzung sind `[ENTSCHEIDUNG]` oder `[FAKT]` mit
   Quelle; alles Vermutete `[ANNAHME]`; jede unbeantwortete Frage `[OFFEN]` mit Datum.
4. **`index.md`:** beide Seiten unter "Projekte" eintragen.
5. **CLAUDE.md Abschnitt 9:** Platzhaltertext ersetzen durch: Zweck (1–2 Saetze), Empfaenger,
   Regeln fuer jede Sitzung (aus 2.7). Kurz halten — Fachwissen gehoert ins Wiki.
6. **README.md:** nur die erste Zeile (Titel) und den ersten Absatz auf diese Wissensbasis anpassen;
   der Rest beschreibt das System und bleibt.
7. **`log.md`:** erster Eintrag nach `vorlagen/log-eintrag.md`
   (`## <heute> — Wissensbasis <Name> eingerichtet`), mit Quelle, angelegten Seiten und offenen Punkten.

## 4. Pruefen und committen

- `python tools/kb_lint.py` → Exit 0, sonst beheben.
- `python tools/kb_dream.py --lage` zeigen (beweist: Log und Queue werden gelesen).
- `git status` zeigen, dann committen: `init: Wissensbasis <Name> eingerichtet (<kuerzel>)`.

## 5. Modul Datenbank (nur wenn gewuenscht)

Nicht selbst einschalten. Dem Nutzer die vier Einrichtungsschritte aus `MODUL-DATENBANK.md` nennen
(`.env` anlegen, `tools/setup_kb_reader.sql` ausfuehren, `python tools/sql.py --check`,
dann `module.datenbank: true`). Zugangsdaten nie in den Chat, nie in Dateien ausser `.env`.
Erst nach erfolgreichem `--check` das Modul einschalten — eigener Log-Eintrag, eigener Commit.

## Was du nicht tust

Fachseiten auf Vorrat anlegen, Inhalte aus allgemeinem Wissen ergaenzen, Topics ohne Rueckfrage
festlegen, `raw/`-Dateien nachtraeglich bearbeiten, Zugangsdaten anfassen.
