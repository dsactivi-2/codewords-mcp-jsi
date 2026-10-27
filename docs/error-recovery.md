# Fehlerbehebung im Dokumenteingang

Neun Signale, die im Betrieb auftreten. Für jedes: woran man es erkennt, warum es
passiert, was zu tun ist, ob wiederholt werden darf — und wann ein Mensch übernehmen muss.

**Zwei Regeln stehen über allem:**

1. **Erst prüfen, dann wiederholen.** Nach einem fehlgeschlagenen Schreibvorgang ist
   unklar, ob der Datensatz entstanden ist. Ein blind wiederholter `unterlage_anlegen`
   erzeugt die teuersten Fehler in diesem System.
2. **Duplikat schlägt fehlend.** Eine Unterlage, die doppelt in der Akte liegt, ist
   schlimmer als eine, die einen Tag später kommt.

## Schnellentscheidung

| # | Signal | Wiederholen? | Mensch? |
|---|---|---|---|
| 1 | Leeres Ergebnis bei der Identifikation | einmal, mit anderen Parametern | ja, wenn weiter leer |
| 2 | Kein passender Dokumenttyp | nein | ja, immer |
| 3 | Adresse nicht erreichbar | nein | ja, immer |
| 4 | Adresse kein `https://` | nein | nein, selbst behebbar |
| 5 | `doc_id` fehlt in der Antwort | nein, erst prüfen | ja, immer |
| 6 | Lücke nach dem Anlegen nicht geschlossen | nein | ja, immer |
| 7 | Unbekannter Statuswert | nein | nein, selbst behebbar |
| 8 | Unzulässige Zeichen im Suchwert | einmal | nein |
| 9 | Dienst oder Datenbank nicht erreichbar | nein | ja, immer |

---

## 1. Leeres Ergebnis bei der Identifikation

**Woran man es erkennt:** `kandidat_identifizieren` liefert eine leere Liste, obwohl
eine Telefonnummer oder Nummer übergeben wurde.

**Warum:** Die Nummer ist im CRM nicht hinterlegt, wurde mit Leerzeichen oder `+49`
statt `+387` eingegeben, oder der Kandidat ist neu und noch nicht angelegt.

**Vorgehen:**
1. Einmal mit reinen Ziffern wiederholen — Schreibweise ist die häufigste Ursache.
2. Bleibt es leer: den Kandidaten nach **Name, Geburtsdatum und Telefon** fragen.
3. Nicht mit Namen suchen. Über 122.000 Datensätze ist das kein Ergebnis, sondern Rauschen.

**Wiederholen:** einmal, mit anderer Schreibweise.
**Mensch:** wenn der Kandidat laut eigener Aussage schon Kunde ist — dann stimmt die
Nummer im CRM nicht und muss korrigiert werden.

---

## 2. Kein passender Dokumenttyp

**Woran man es erkennt:** `unterlagen_katalog` enthält keinen Typ, der zur eingegangenen
Datei passt — etwa ein „Zeugnis", das sowohl Arbeits- als auch Schulzeugnis sein könnte.

**Warum:** Der Kandidat beschreibt die Unterlage in eigenen Worten, oder der Bestand
kennt diesen Typ für seinen Auftrag nicht.

**Vorgehen:**
1. Typ nicht raten und nicht den nächstbesten nehmen.
2. Beim Kandidaten oder im Team nachfragen, welcher Typ gemeint ist.
3. Bis zur Klärung die Datei **nicht** eintragen.

**Wiederholen:** nein — ein falscher Typ ist ein Datenfehler, der später teuer wird.
**Mensch:** immer. Das ist eine Entscheidung über die Aktenführung, keine technische Frage.

---

## 3. Adresse nicht erreichbar

**Woran man es erkennt:** `datei_pruefen` liefert `erreichbar: false`, oft mit HTTP 403,
404 oder einer Zeitüberschreitung.

**Warum:** Der Link ist abgelaufen, die Datei wurde gelöscht, die Adresse ist privat
statt öffentlich, oder ein interner Serverpfad wurde übergeben.

**Vorgehen:**
1. **Nicht** eintragen. Ohne bestandene Prüfung entsteht ein toter Verweis in der Akte.
2. Kandidaten um erneutes Senden bitten — knapp und ohne Schuldzuweisung.
3. `notiz_anlegen` mit dem Grund, damit die Nachfrage nachvollziehbar bleibt.

**Wiederholen:** nein. Dieselbe tote Adresse bleibt tot.
**Mensch:** ja, wenn die Datei angeblich „schon lange im System" ist — dann liegt es
am Speicherpfad, nicht am Kandidaten.

---

## 4. Adresse ohne `https://`

**Woran man es erkennt:** `datei_url muss mit https:// beginnen`.

**Warum:** Es wurde ein interner Pfad übergeben, wie er in der Datenbank steht —
`/jobstep_pp/files/candidate_contracts/UG193025-10-10_08:33.pdf`. Solche Pfade sind
keine öffentlichen Adressen und für den Agenten nicht abrufbar.

**Vorgehen:**
1. Öffentliche Adresse besorgen — Plattform-Speicher oder ein Abruf über die Weboberfläche.
2. Alternativ: Datei vom Mitarbeiter im CRM hochladen lassen und den entstandenen
   Eintrag mit `datei_bestaetigen` verknüpfen.

**Wiederholen:** nein, erst nachdem eine andere Adresse vorliegt.
**Mensch:** nein, das ist ohne Rückfrage lösbar.

---

## 5. `doc_id` fehlt in der Antwort

**Woran man es erkennt:** `unterlage_anlegen` antwortet ohne `doc_id`, oder mit einer
Zeitüberschreitung statt einer Antwort.

**Warum:** Unklar — die Anfrage kann den Datensatz angelegt haben, bevor die Verbindung
abbrach. Genau deshalb ist dieser Fall gefährlich.

**Vorgehen:**
1. **Nicht** sofort erneut anlegen.
2. `kandidat_dokumente` aufrufen und prüfen, ob der Eintrag inzwischen existiert.
3. Existiert er: Vorgang als erledigt behandeln, `doc_id` von dort übernehmen.
4. Existiert er nicht: einmal erneut anlegen — dann mit `nrd_id` aus der vorherigen Antwort,
   falls vorhanden.

**Wiederholen:** nur nach dieser Prüfung, und nur einmal.
**Mensch:** ja, wenn der Datensatz weder vorher noch nachher auffindbar ist.

---

## 6. Lücke nach dem Anlegen nicht geschlossen

**Woran man es erkennt:** Nach erfolgreichem `unterlage_anlegen` zeigt `unterlagen_soll`
für diesen Typ weiterhin `fehlt: true` oder einen unveränderten Zähler.

**Warum:** Die Unterlage wurde einem anderen Auftrag zugeordnet, oder es existiert keine
passende Pflichtposition im Auftrag — dann bleibt `doc_nrd_id` leer.

**Vorgehen:**
1. **Nicht** ein zweites Mal anlegen. Der Datensatz ist da, nur die Verbindung fehlt.
2. `unterlage_verlauf` mit der `doc_id` prüfen: welcher Auftrag, welcher Status?
3. Weicht der Auftrag ab: dem Team mitteilen, welcher Auftrag korrekt ist.
4. Fehlt die Pflichtposition: das ist eine Konfigurationsfrage des Auftrags, kein Fehler
   des Agenten.

**Wiederholen:** nein.
**Mensch:** immer — hier stimmt etwas in der Auftragskonfiguration nicht.

---

## 7. Unbekannter Statuswert

**Woran man es erkennt:** `Unbekannter Status` von `unterlage_status_setzen`.

**Warum:** Ein Wert außerhalb der Leiter wurde übergeben.

**Vorgehen:** Einen der neun erlaubten Werte verwenden:

| Id | Deutsch | Wer darf setzen |
|---|---|---|
| 3 | Hochgeladen | Agent, automatisch |
| 6 | Geprueft | **nur Mensch** |
| 9 | Bereit zum Versenden | Mensch oder Freigabe |
| 12 | Gesendet | Mensch oder Sendenachweis |
| 15 | Erhalten | **nur Mensch** |
| 18 | Bereit | Mensch |
| 21 | Defekt | Agent meldet, Mensch bestätigt |
| 24 | Abgelehnt | **nur Mensch** |
| 27 | Archiviert | **nur Mensch**, ausdrückliche Anweisung |

**Wiederholen:** nein — der falsche Wert wird durch Wiederholung nicht richtiger.
**Mensch:** nein, außer der gewünschte Zustand ist einer der vier gesperrten.

---

## 8. Unzulässige Zeichen im Suchwert

**Woran man es erkennt:** `Unzulaessige Zeichen im Wert`.

**Warum:** Anführungszeichen, Semikolons oder Klammern im Suchbegriff — häufig aus einer
kopierten Notiz.

**Vorgehen:** Suchbegriff auf Ziffern oder reinen Text reduzieren.

**Wiederholen:** einmal, mit bereinigtem Wert.
**Mensch:** nein.

---

## 9. Dienst oder Datenbank nicht erreichbar

**Woran man es erkennt:** `Datenbank nicht erreichbar`, `Datenbankfehler`, HTTP 5xx,
oder gar keine Antwort innerhalb der Zeitgrenze.

**Warum:** Plattformstörung, erschöpfte Verbindungen, oder ein laufender Deploy.

**Vorgehen:**
1. **Nicht** wiederholen. Bei einem Ausfall erzeugt jede Wiederholung nur Last.
2. Zeitpunkt notieren, Werkzeugname notieren.
3. Dem Team melden. Bei längerem Ausfall: Arbeit an anderer Stelle fortsetzen.

**Wiederholen:** nein, erst nach Rückmeldung.
**Mensch:** immer.

---

## Übergabe an einen Menschen

Immer diese fünf Angaben, in dieser Reihenfolge:

1. **Zeitpunkt** mit Uhrzeit und Zeitzone
2. **`kandidat_id`** und, falls vorhanden, **`doc_id`**
3. **Was getan werden sollte** — ein Satz
4. **Was tatsächlich passierte** — mit der wörtlichen Meldung, nicht mit einer Umschreibung
5. **Was bereits versucht wurde**

Ohne Punkt 4 ist jede Meldung wertlos: „hat nicht funktioniert" führt zu keiner Diagnose.

## Was niemals passiert

- Eine Unterlage eintragen, deren Adresse die Prüfung nicht bestanden hat.
- Nach einer Zeitüberschreitung erneut anlegen, ohne vorher nachgesehen zu haben.
- Einen Status außerhalb der Leiter setzen, um eine Anzeige zu berichtigen.
- Bei mehrdeutiger Identität raten, statt zu fragen.
- Einen Ausfall durch Wiederholungen zu überdecken.
