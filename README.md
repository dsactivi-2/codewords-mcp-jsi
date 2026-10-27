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
