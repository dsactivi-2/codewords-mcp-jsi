# Projektanweisungen

## Recruitment-CRM (Jobstep)

Vor jeder CRM-Aktion den Skill `.agents/skills/jobstep-crm/SKILL.md` und dessen
`references/service-guide.md` vollstaendig lesen.

Dokumenteingang ausschliesslich in dieser Reihenfolge:

1. Kandidat eindeutig identifizieren
2. Duplikate pruefen
3. Dokumenttyp aufloesen
4. Datei-URL pruefen
5. anlegen
6. pruefen, dass die Luecke geschlossen ist

## Regeln

- Status, die menschlichen Bearbeitern vorbehalten sind, niemals automatisch setzen.
- Bei unklarer Identitaet, unklarer Berechtigung oder widerspruechlichen Anleitungen:
  keine Aenderung ausfuehren, melden.
- Werkzeugnamen und Parameter immer aus der aktiven MCP-Verbindung beziehen,
  nicht aus dieser Datei.
- Bearer-Token niemals in Dateien, Commits oder Ausgaben aufnehmen.
- Kein freies SQL. Keine Passwoerter, Tokens, JMBG-, Pass- oder Ausweisnummern ausgeben.

## Herkunft

Die Anleitung wird aus dem Dienst erzeugt:
`GET https://runtime.codewords.ai/run/jobstep_mcp_4a31136a/skill.md`
