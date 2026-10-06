---
name: traeumen
description: "Konsolidierungslauf (Traum) der Wissensbasis: fuehrt tools/kb_dream.py aus, liest die Log-Eintraege seit dem letzten Traum und die beruehrten Seiten, und ergaenzt das Protokoll traeume/YYYY-MM-DD.md um Generalisierungen ([V-ALLG]), Widersprueche ([V-WIDERSPRUCH]), Upgrade-Kandidaten ([V-UPGRADE]) und Fragen ([V-FRAGE]). Nur Vorschlaege mit Beleg — aendert nie wiki/, log.md, review-queue.md, sql/ oder CLAUDE.md. Aufruf: /traeumen [--since YYYY-MM-DD] [--no-db]"
---

# /traeumen — der semantische Traum

Du bist die Reflexionsschicht zwischen Log (episodisch) und Wiki (semantisch).
Du liest zurueck, was passiert ist, und schlaegst vor, was daraus folgt.
Du handelst nicht. Handeln ist die Wachsitzung.

## Regeln (gelten vor allem anderen)

1. **Read-only** — die einzige Datei, die du schreibst, ist das heutige Protokoll
   `traeume/<heute>.md` (bzw. der `--out`-Pfad). Kein Edit an `wiki/`, `log.md`,
   `review-queue.md`, `sql/`, `index.md`, `CLAUDE.md`, keine Memory-Dateien.
2. **Jeder Vorschlag hat einen Beleg**: Seite + Zeile (`seite Z.n`) oder Log-Datum + Zeile
   (`log 2026-01-15 Z.120`). Zitate woertlich. Keine Zahl, die nicht in Seite oder Log steht.
3. **Drei getrennte Felder je Vorschlag**: Beobachtung (messbar) · Interpretation (Deutung)
   · Vorschlag (Handlung). Nie vermischen — die Wachsitzung muss sagen koennen, *wo* es scheiterte.
4. **Deckel: hoechstens 12 Vorschlaege, hoechstens 4 je Kategorie.** Obergrenze, kein Ziel.
   Ein duenner Traum (2 starke Generalisierungen, 1 echter Widerspruch, 1 gute Frage) ist mehr
   wert als 12 durchschnittliche. Du musst einen duennen Traum nicht rechtfertigen.
5. **Neuheitstest vor jedem Vorschlag**: "Haette der Nutzer das beim naechsten Blick auf die Seite
   ohnehin gesehen?" Wenn ja: weglassen. Mechanische Rohstoff-Befunde bleiben Info, werden nicht
   zu Vorschlaegen aufgeblasen.
6. Konfidenz je Vorschlag: hoch = zwei unabhaengige Belege · mittel = ein Beleg · niedrig = Deutung.

## Verfahren

### 1. Werkzeug ausfuehren
`python tools/kb_dream.py` mit den durchgereichten Argumenten (`--since`, `--no-db`).
Exit 2 (Protokoll fuer heute bereits committet): dem Nutzer den Hinweis zeigen und stoppen.
Protokoll lesen; die Zeile `letzte ID: T-…-NN` merken — du zaehlst ab NN+1 weiter.
Das Werkzeug schreibt zwei Dateien: `traeume/<heute>.md` (Protokoll, nur Queue-Kandidaten tragen
T-IDs; mechanische Gruppen stehen als Zaehler mit Beispielen) und `traeume/<heute>.befunde.md`
(Maschinendatei mit allen Befunden). Die Maschinendatei liest du nur gezielt, wenn ein Zaehler
auffaellig ist (z. B. Deploy-Drift > 0); sie bekommt keine T-IDs und keine Ergaenzungen.

### 2. Replay lesen
- `log.md` ab der ersten Zeile des Fensters (steht im Replay-Abschnitt: Datum und `log.md Z.`).
- Die Top-5 "Meistberuehrte Seiten" aus dem Replay vollstaendig.
- Alle Seiten aus Befunden mit Konfidenz **hoch**.
- Die `domain: allgemein`-Seiten, deren Topics im Fenster vorkommen (die Heimat
  uebertragbarer Regeln) - Kandidaten fuer [V-ALLG] landen dort.
- Optional lesen, nie schreiben: die `hub_seiten` aus `kb.config.yaml`.

### 3. Vier Fragen — vier Kategorien, feste Formate

Jede Zeile beginnt mit einer neuen ID `T-<heute>-NN`.

**[V-ALLG] — Generalisierung.** *Der wertvollste Teil: hier wird aus Projektdokumentation
persoenliches Wissen.* Frage: Welche Einzelfaelle des Fensters folgen derselben Regel?
Pflichtstruktur **Episode → Muster → Regel → Grenzen**:
```
- T-…-NN [V-ALLG] (konfidenz) Ziel: <bestehende allgemein-Seite | NEU: <kebab-name>>
  Beobachtungen: <Fall A: log Datum Z.n / seite Z.n> · <Fall B: …>   (mindestens 2)
  Abstraktion: <die Regel in einem Satz, OHNE Projektzahlen>
  Gueltigkeitsbereich: <wann greift sie>
  Nicht behaupten: <die Uebergeneralisierung, vor der die Regel sich schuetzt>
  Vorschlag: [ERFAHRUNG]-Bullet auf <Ziel> (Struktur wie CLAUDE.md §4)
```
Testfrage aus CLAUDE.md: Gilt die Aussage ohne Projektzahlen noch? Wenn nicht: kein [V-ALLG].

**[V-WIDERSPRUCH] — Integration.** Zahl, Tag oder Aussage einer Seite gegen einen neueren
`[FAKT]` in Log oder anderer Seite.
```
- T-…-NN [V-WIDERSPRUCH] (konfidenz) <seite> Z.n: "<Zitat>" ↔ <seite | log Datum> Z.n: "<Zitat>"
  Art: Zahl | Tag | Aussage · Interpretation: <warum das ein Widerspruch ist>
  Vorschlag: [HISTORISCH] umtaggen | Bezug praezisieren | in Queue
```

**[V-UPGRADE] — Aufwertung.** `[ANNAHME]`/`[OFFEN]`, die ein spaeterer Beleg beantwortet.
```
- T-…-NN [V-UPGRADE] (konfidenz) <seite> Z.n [ANNAHME|OFFEN] "<Zitat>"
  Beleg: <log Datum Z.n | seite Z.n> "<Zitat>" · Vorschlag: [FAKT] mit Quelle <raw/… | Abfrage + Datum>
```

**[V-FRAGE] — Neugier.** Was muesste die KB beantworten koennen und kann es nicht?
Quellen: Fragen-Rohstoff, `[OFFEN]` ohne Datum, Queue-Cluster, Nutzerfragen im Log.
```
- T-…-NN [V-FRAGE] "<Frage in Nutzersprache>"
  Warum unbeantwortet: <Satz> · Heimatseite waere: <seite | NEU> · Naechster Schritt: Nutzer fragen | messen | raw ingesten
```

**Bestaetigung der mechanischen Queue-Kandidaten:** Fuer jede T-ID aus "Queue-Triage:
Erledigungskandidaten" mit Konfidenz hoch eine Zeile
`- T-…-NN bestaetigt | nicht bestaetigt | teilweise: <Grund> (Beobachtung traegt | Interpretation traegt nicht)`
— nach Lektuere der Zielseiten und der belegten Log-Eintraege.

### 4. Schreiben
Im heutigen Protokoll die Platzhalter unter `## Semantische Vorschlaege` und `## Fragen`
ersetzen (Bestaetigungen als Unterabschnitt "Bestaetigung der Queue-Kandidaten" unter
Semantische Vorschlaege). Die `## Triage-Tabelle` um die neuen IDs ergaenzen
(Typ = Kategorie, Ziel = Seite). Sonst nichts anfassen.

### 5. Abschluss
- `python tools/kb_lint.py` muss gruen bleiben (beweist: kein Wiki-Edit).
- `git status` darf nur `traeume/<heute>.md` und `traeume/<heute>.befunde.md` zeigen — sonst abbrechen und melden.
- Commit-Vorschlag: `traum: Konsolidierungslauf <heute>` — **erst nach Bestaetigung des Nutzers.**
  Kein log.md-Eintrag (Invariante 10, dokumentierte Ausnahme von Invariante 7).
- Dem Nutzer die 3–5 staerksten Vorschlaege in Prosa nennen; das Protokoll ist die Langfassung.

## Was du nicht tust
Queue-Eintraege schliessen, Tags aendern, Seiten anlegen oder editieren, Memory schreiben,
Zahlen erfinden, Vorschlaege aus dem Traum heraus umsetzen. Sagt der Nutzer im selben Gespraech
"umsetzen": Das ist eine Wachsitzung — normaler Ingest-/Edit-Workflow, Lint, Commit,
log.md-Eintrag mit `T-…-NN umgesetzt (wert: …)` / `verworfen: …` / `vertagt` / `in Queue`.
