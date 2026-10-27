# Team-Anleitung: Was der Agent tut — und woran ihr es erkennt

**Stand:** Die Werkzeuge sind live und getestet. Der Chat-Agent (WhatsApp/Web) folgt als nächster Schritt.
Ab dem Moment, in dem er schreibt, gilt diese Anleitung.

Der Agent übernimmt die Schleife: fehlende Unterlagen erkennen, beim Kandidaten anfragen,
das Eingegangene ablegen und in der Akte vermerken. Ihr arbeitet weiter wie bisher — nur dass
ein Teil der Einträge künftig nicht von Menschen stammt.

---

## 1. Was er kann

Vierzehn feste Fähigkeiten. Er kann nichts anderes — keine eigenen Abfragen, keine Massenänderungen.

| Bereich | Im Klartext |
|---|---|
| Kandidat erkennen | Wer schreibt? Über Telefon, E-Mail oder Kandidatennummer. |
| Akte lesen | Status, Auftrag, Fristen — ohne Passwörter und ohne Ausweisnummern. |
| Unterlagen abgleichen | Welche Pflichtunterlagen der Auftrag verlangt und welche fehlen. |
| Aufträge zeigen | Einzelheiten eines Auftrags; passende Aufträge zu einem Kandidaten. |
| Unterlage anlegen | Datei + Dokumenteintrag + Verlaufseintrag in einem Vorgang. |
| Status setzen | Auf der gewohnten Leiter: hochgeladen, geprüft, bereit, gesendet, erhalten, fertig — plus Defekt, Abgelehnt, Archiviert. |
| Anfordern | Festhalten: was angefordert wurde, über welchen Kanal, mit welcher Frist. |
| Notieren | Gesprächsnotiz am Kandidaten. |
| Kontakt berichtigen | Nur Telefon und E-Mail — mehr Felder kann er nicht anfassen. |
| Dateien prüfen | Adresse testen, bevor sie in die Akte kommt. Keine toten Verweise. |

---

## 2. Woran ihr einen Agent-Eintrag erkennt

**Alles, was der Agent schreibt, beginnt mit `Agent:`** — das ist Filter und Beweis zugleich.

- **Im Verlauf der Unterlage:** `Agent: Unterlage angelegt (Hochgeladen). Datei: https://…`
- **In den Notizen:** `Agent: Unterlage angefordert — Zeugnis, Auftrag 353, Kanal whatsapp, Frist 3 Tage`
- **Bearbeiter-Nummer:** Agent-Einträge tragen die Nummer `0`. Alles andere ist von euch.

**Dateien:** Die Datei liegt im Speicher; der Link steht im Dokumentfeld **und** im Verlauf.
Als Vorschaubild direkt in der Akte erscheint sie erst, wenn Jobstep einen eigenen Upload-Weg freigibt.

---

## 3. Wo ihr die Ergebnisse seht

| Ort in Jobstep | Was dort steht |
|---|---|
| Dokumente des Kandidaten | Die neue Unterlage, Status „Hochgeladen", mit Dateiverweis. |
| Verlauf der Unterlage | Jeder Schritt mit Zeit, Status und Kommentar — inklusive Dateilink. |
| Notizen | Anforderungen und Gesprächsnotizen, jeweils mit Kanal und Frist. |

**Prüfroutine in 30 Sekunden:** Akte öffnen → Verlauf der Unterlage ansehen → Dateilink anklicken.
Wenn die Datei sich öffnet und der Status zur Wirklichkeit passt, ist alles in Ordnung.

---

## 4. Was er nicht tut

- **Nichts löschen** — kein Dokument, kein Kandidat, keine Notiz.
- **Nichts in Massen** — ein Vorgang, ein Datensatz.
- **Keine sensiblen Felder** — Passwörter, Tokens, Ausweis- und JMBG-Nummern liest und schreibt er nicht.
- **Keine neuen Status** — nur die neun Werte, die in eurem System stehen.

---

## 5. Fehler melden — drei Stufen

### Stufe 1 — Kleiner Fehler, sofort selbst korrigierbar
Falscher Status, fehlender Kommentar, Datei am falschen Kandidaten: im CRM korrigieren wie immer.
Danach eine Notiz mit `Bitte Agent prüfen: …`, damit der Fall sichtbar bleibt.

### Stufe 2 — Verdächtiger Eintrag
Unterlage bei einem Kandidaten, der nie geschrieben hat? Datei, die nicht zum Dokumenttyp passt?
Screenshot, Kandidatennummer, Dokumentnummer und Zeitpunkt an die verantwortliche Person.
**Nicht selbst löschen — erst sichern, dann aufräumen.**

### Stufe 3 — Technischer Fehler
Nichts passiert, oder es erscheint eine Fehlermeldung. Diese fünf Angaben reichen:
1. Zeitpunkt mit Uhrzeit
2. Kandidatennummer
3. Was der Agent tun sollte (ein Satz)
4. Was stattdessen passiert ist
5. Screenshot der Meldung, falls es eine gab

---

## 6. Die erste Woche

- **Täglich 10 Minuten** die neuen `Agent:`-Einträge durchsehen. Muster fallen schnell auf.
- **Status prüfen, nicht nur Dateien:** Steht eine Unterlage auf „Geprüft", obwohl niemand geprüft hat, ist das ein Fall für Stufe 2.
- **Fristen im Blick behalten:** Anforderungen mit 3 Tagen Frist laufen ab — wer nicht nachfasst, verliert den Kandidaten.
- **Rückmeldung sammeln:** Was fragt der Agent zu oft? Was vergisst er? Mit Ort und Zeitpunkt notieren — Grundlage für die nächste Ausbaustufe.

---

*Jobstep Kandidaten-MCP · 14 Werkzeuge · geprüft am 24.10.2026*
