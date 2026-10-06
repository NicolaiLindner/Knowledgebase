---
name: lage
description: Kurzlage der Wissensbasis fuer den Sitzungsstart (max. 25 Zeilen) - letzte Log-Eintraege mit offenen Punkten, Queue zu den zuletzt beruehrten Seiten, Vitalwerte, bei eingeschaltetem Modul Datenbank auch Deploy-Drift. Fuehrt nur tools/kb_dream.py --lage aus, schreibt nichts, liest sonst nichts. Aufruf /lage [--no-db]
---

# /lage — Sitzungsstart in 25 Zeilen

Du zeigst dem Nutzer, wo die Wissensbasis steht, bevor gearbeitet wird. Du liest nichts weiter und aenderst nichts.

## Verfahren

1. `python tools/kb_dream.py --lage` ausfuehren (mit `--no-db`, wenn der Nutzer es mitgibt oder die
   Datenbank nicht erreichbar ist).
2. Die Ausgabe unveraendert zeigen (sie ist auf 25 Zeilen begrenzt).
3. Darunter genau drei Zeilen: (a) woran zuletzt gearbeitet wurde (aus "Zuletzt im Log"),
   (b) was laut Log offen ist (aus "Offen laut Log"), (c) ob ein Traum faellig ist
   (letzter Traum aelter als 7 Tage oder mehr als 10 Log-Eintraege seither -> "Traum faellig").
4. Ist `log.md` leer und Abschnitt 9 der CLAUDE.md noch nicht ausgefuellt: statt (a)-(c) nur
   "Wissensbasis noch nicht eingerichtet -> /einrichten".
5. Keine Vorschlaege, keine Seiten oeffnen, keine Queue-Eintraege bewerten. Das ist Sache der
   Wachsitzung oder des Traums (/traeumen).

## Was du nicht tust

Dateien schreiben, Queue abhaken, Wiki lesen "um sicherzugehen", laengere Zusammenfassungen liefern.
Die Lage ist ein Blick auf die Uhr, kein Bericht.
