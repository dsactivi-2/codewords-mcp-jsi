# Jobstep Kandidaten-MCP

MCP-Dienst, der einen Agenten an das Jobstep-Kandidaten-CRM anbindet.
18 feste Werkzeuge — kein freies SQL, keine Tabellenwahl.

## Aufbau

| Datei | Zweck |
|---|---|
| `jobstep_mcp.py` | Der Dienst: FastAPI + FastMCP, 18 Werkzeuge, `/mcp/`, `/skill.md`, `/tools.json`, `/test/{werkzeug}` |
| `tools.json` | Maschinenlesbare Werkzeugdefinitionen fuer Function Calling |
| `AGENTS.md` | Immer geladene Regeln fuer Coding-Agenten (Intake-Reihenfolge, Verbote) |
| `.agents/skills/jobstep-crm/` | Skill mit Frontmatter plus vollstaendiger Anleitung als Referenz |

## Verbindung

- MCP: `https://runtime.codewords.ai/run/jobstep_mcp_4a31136a/mcp/`
- Anleitung: `GET .../skill.md`
- Werkzeuge: `GET .../tools.json`
- Einzelaufruf ohne MCP-Client: `POST .../test/<werkzeug>` mit JSON

Authentifizierung: `Authorization: Bearer <CODEWORDS_API_KEY>`.

## Werkzeuge

Lesen (12): `kandidat_identifizieren`, `kandidat_profil`, `kandidat_lebenslauf`,
`unterlagen_soll`, `unterlagen_katalog`, `job_details`, `jobs_fuer_kandidat`,
`kandidat_dokumente`, `unterlage_verlauf`, `kandidat_notizen`, `kandidat_vertraege`,
`datei_pruefen`

Schreiben (6): `unterlage_anlegen`, `unterlage_status_setzen`, `unterlage_anfordern`,
`notiz_anlegen`, `kontakt_korrigieren`, `datei_bestaetigen`

## Statusleiter

3 Hochgeladen · 6 Geprueft · 9 Bereit zum Versenden · 12 Gesendet · 15 Erhalten ·
18 Bereit · 21 Defekt · 24 Abgelehnt · 27 Archiviert

Status 6 und 15 sind menschlichen Bearbeitern vorbehalten.

## Sicherheit

- Gesperrte Spalten: Passwoerter, Tokens, JMBG-, Pass- und Ausweisnummern.
- Jeder schreibende Aufruf betrifft genau einen Datensatz.
- Bearer-Token niemals in Dateien, Commits oder Ausgaben aufnehmen.

## Herkunft der Anleitung

`skill.md` wird vom Dienst selbst ausgeliefert und ist die einzige Quelle.
Die Referenz unter `.agents/skills/jobstep-crm/references/service-guide.md`
ist eine Kopie davon mit Herkunftskopf. Sie wird nicht von Hand bearbeitet.

---

## Dokumenteingang: die sechs Schritte und ihre Werkzeuge

Jede eingehende Unterlage durchläuft diese Reihenfolge. Die Schritte sind nicht
verhandelbar: wird einer übersprungen, entstehen doppelte oder tote Einträge.
Parameter unten sind aus `tools.json` erzeugt, nicht abgeschrieben.

Anlass: eine Datei kommt über WhatsApp, Web, SMS oder E-Mail.

### 1. Kandidat identifizieren

**Werkzeug:** `kandidat_identifizieren`

Wer schreibt? Ohne eindeutige Nummer darf kein Schritt folgen.

| Parameter | Typ | Pflicht | Bedeutung |
|---|---|---|---|
| `suchbegriff` | string | ja | Telefonnummer, E-Mail oder Kandidatennummer |
| `limit` | integer | nein | Max. Treffer 1-10 |

**Abbruchbedingung:** Genau ein Treffer → weiter. Mehrere → nach Name und Geburtsdatum fragen, **anhalten**. Kein Treffer → einmal mit Ziffern wiederholen, dann fragen, **anhalten**.

### 2. Duplikate prüfen

**Werkzeug:** `kandidat_dokumente`

Liegt dieselbe Unterlage schon vor? Ein zweites Exemplar ist schlimmer als ein fehlendes.

| Parameter | Typ | Pflicht | Bedeutung |
|---|---|---|---|
| `kandidat_id` | integer | ja | Kandidatennummer |
| `limit` | integer | nein | Max. Anzahl je Liste 1-100 |

**Abbruchbedingung:** Typ bereits vorhanden mit Status ≥ 9 (Gesendet, Erhalten, Bereit) → **anhalten** und melden. Vorhanden, aber Defekt/Abgelehnt → weiter.

### 3. Dokumenttyp auflösen

**Werkzeug:** `unterlagen_katalog`

Welcher Typ ist gemeint? Nie den nächstbesten nehmen.

| Parameter | Typ | Pflicht | Bedeutung |
|---|---|---|---|
| `limit` | integer | nein | Max. Anzahl 1-200 |

**Abbruchbedingung:** Kein plausibler Typ → beim Menschen nachfragen, **anhalten**. Bei Bedarf vorher `unterlagen_soll` für den Pflichtkontext.

### 4. Datei-URL prüfen

**Werkzeug:** `datei_pruefen`

Ist die Datei wirklich abrufbar? Das ist das Tor — ohne es kein Schreiben.

| Parameter | Typ | Pflicht | Bedeutung |
|---|---|---|---|
| `datei_url` | string | ja | Oeffentliche https-Adresse der Datei |

**Abbruchbedingung:** `erreichbar: false` → **anhalten**, Kandidaten um erneutes Senden bitten, `notiz_anlegen`. Interne Pfade wie `/jobstep_pp/files/...` sind keine gültigen URLs.

### 5. Unterlage anlegen

**Werkzeug:** `unterlage_anlegen`

Der eigentliche Schreibvorgang: Dokument, Akteneintrag und Verlauf in einem.

| Parameter | Typ | Pflicht | Bedeutung |
|---|---|---|---|
| `kandidat_id` | integer | ja | Kandidatennummer |
| `nalog_id` | integer | ja | Auftragsnummer |
| `doc_type_id` | integer | ja | Dokumenttyp aus unterlagen_katalog |
| `datei_url` | string | ja | Oeffentliche https-Adresse der Datei |
| `doc_status` | integer | nein | Startstatus, Standard 3 = Hochgeladen |
| `nrd_id` | integer | nein | Pflichtposition, gegen die abgehakt wird |
| `kommentar` | string | nein | Kurzer Hinweis fuer das Team |

**Abbruchbedingung:** Erfolg nur mit `doc_id` in der Antwort. Ohne `nalog_id` vorher `kandidat_profil` lesen. Ohne `nrd_id` sucht der Dienst die Pflichtposition selbst und hakt sie ab.

### 6. Lücke bestätigen

**Werkzeug:** `unterlagen_soll`

Nachkontrolle. Erst damit ist der Vorgang abgeschlossen.

| Parameter | Typ | Pflicht | Bedeutung |
|---|---|---|---|
| `kandidat_id` | integer | ja | Kandidatennummer |
| `nalog_id` | integer | nein | Auftrag; leer = Auftrag des Kandidaten |

**Abbruchbedingung:** `fehlt` muss für den Typ auf `false` stehen bzw. der Zähler gestiegen sein. Nicht geschlossen → **nicht neu anlegen**, mit `doc_id` melden.

### Reihenfolge als Prüfliste

```
kandidat_identifizieren  →  kandidat_dokumente  →  unterlagen_katalog
                         →  datei_pruefen      →  unterlage_anlegen  →  unterlagen_soll
```

Zwei Regeln fassen alles zusammen: **kein Tor, kein Schreiben** (Schritt 4 blockiert
Schritt 5) und **Duplikat schlägt fehlend** (Schritt 2 blockiert Schritt 5).

### Statusleiter und wer sie bewegen darf

| Id | Kroatisch | Deutsch | Bedeutung | Wer darf setzen |
|---|---|---|---|---|
| 3 | Uploadan | Hochgeladen | Eingangszustand jeder neuen Unterlage | Agent, automatisch |
| 6 | Provjeren | Geprueft | ein Mensch hat die Datei angesehen | **nur Mensch** |
| 9 | Cekamo original | Bereit zum Versenden | vollständig für den Versand | Mensch, oder Agent nach Freigabe |
| 12 | Poslan | Gesendet | tatsächlich übertragen | Mensch, oder Agent mit Sendenachweis |
| 15 | Imamo original | Erhalten | Original liegt physisch vor | **nur Mensch** |
| 18 | Spreman | Bereit | endgültig guter Zustand | Mensch |
| 21 | Nije prosao provjeru | Defekt | Datei unbrauchbar | Agent darf melden, Mensch bestätigt |
| 24 | Odbijen | Abgelehnt | mit Begründung im Kommentar | **nur Mensch** |
| 27 | Arhiviran | Archiviert | Endzustand | **nur Mensch**, ausdrückliche Anweisung |

Werkzeug: `unterlage_status_setzen` mit `doc_id`, `status_id`, `kommentar`.
Jeder Aufruf schreibt selbst einen Verlaufseintrag — keine zusätzliche Notiz nötig.

Rückwärtsbewegungen (18 → 6, 12 → 6) sind zulässig, wenn eine Unterlage ersetzt wird.
Immer mit Kommentar: eine unbegründete Rückstufung sieht aus wie ein Fehler.

### Fehlerbehebung

| Meldung / Signal | Ursache | Was zu tun ist | Wiederholen? |
|---|---|---|---|
| `Kandidat ... existiert nicht` | falsche Nummer | erneut identifizieren | nein |
| `Auftrag ... existiert nicht` | Kandidat hat keinen Auftrag | an Menschen übergeben, Auftrag nicht erfinden | nein |
| `Unbekannter Status` | Wert außerhalb der Leiter | einen der neun Werte verwenden | nein |
| `datei_url muss mit https:// beginnen` | interner Serverpfad | öffentliche Adresse besorgen | nein |
| `Adresse nicht erreichbar` | Link tot oder privat | erneut senden lassen, Notiz, anhalten | nein |
| `Unzulaessige Zeichen im Wert` | Sonderzeichen im Suchbegriff | nur Ziffern oder Klartext | einmal |
| `Datenbank nicht erreichbar` | Plattform oder Verbindung | mit Zeitstempel und Werkzeug melden | nein |
| Zeitüberschreitung, keine Antwort | unklar | **erst** `kandidat_dokumente` prüfen, dann entscheiden | einmal, nach Prüfung |
| Leeres Ergebnis, wo Daten erwartet | nicht gepflegt oder falscher Filter | neu interpretieren, nicht blind wiederholen | einmal |

**Nach jedem fehlgeschlagenen Schreibvorgang gilt:** prüfen, ob der Datensatz doch
entstanden ist, bevor erneut geschrieben wird. Der unsichtbare Wiederholungsversuch
erzeugt die teuersten Fehler in diesem System.

### Übergabe an einen Menschen

Immer diese fünf Angaben: Zeitpunkt mit Uhrzeit · `kandidat_id` und, falls vorhanden,
`doc_id` · was getan werden sollte (ein Satz) · was tatsächlich passierte, mit der
wörtlichen Meldung · was bereits versucht wurde.
