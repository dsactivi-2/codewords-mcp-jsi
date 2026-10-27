# HTTP-Referenz — vier Adressen

Basis: `https://runtime.codewords.ai/run/jobstep_mcp_4a31136a`

Alle vier Adressen verlangen `Authorization: Bearer <CODEWORDS_API_KEY>`.
Jede Angabe unten wurde am 27.10.2026 gegen den laufenden Dienst gemessen —
jeweils HTTP-Status und Antwortkörper.

| Adresse | Methode | Zweck | Antworttyp |
|---|---|---|---|
| `/mcp/` | POST | MCP-Protokoll (JSON-RPC über Streamable HTTP) | `text/event-stream` |
| `/skill.md` | GET | Bedienanleitung für den Agenten | `text/markdown` |
| `/tools.json` | GET | Werkzeugkatalog für Function Calling | `application/json` |
| `/test/<tool>` | POST | Einzelnes Werkzeug ohne MCP-Client | `application/json` |

---

## `/mcp/` — MCP-Protokoll

**Methode:** `POST`. Kopfzeilen: `Authorization`, `Accept: application/json, text/event-stream`,
`Content-Type: application/json`.

**Parameter:** im Rumpf als JSON-RPC 2.0 — `method` (`initialize`, `tools/list`, `tools/call`),
`params`, `id`.

**Antwort:** `200` mit `text/event-stream`. Die Nutzdaten stehen in einer Zeile, die mit
`data: ` beginnt und JSON-RPC enthält.

```bash
curl -s -X POST "$BASE/mcp/" \
  -H "Authorization: Bearer $KEY" \
  -H "Accept: application/json, text/event-stream" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

**Fehlerfälle (gemessen):**

| Situation | Status | Antwort |
|---|---|---|
| fehlende oder falsche Anmeldung | `401` | `{"detail":"Unauthorized"}` |
| `Accept` fehlt oder ohne `text/event-stream` | `406` | JSON-RPC-Fehler `-32600` „Not Acceptable" |
| Rumpf ist kein gültiges JSON-RPC | `400` | JSON-RPC-Fehler `-32602` „Validation error" |
| unbekannte Methode | `200` | SSE mit JSON-RPC-Fehler `-32602` — **Protokollfehler kommen mit 200** |

Der letzte Fall ist eine Eigenheit des Protokolls, kein Fehler: MCP meldet Anwendungsfehler
im Rumpf, nicht über den HTTP-Status. Wer den Status allein auswertet, übersieht sie.

---

## `/skill.md` — Bedienanleitung

**Methode:** `GET`. Keine Parameter.

**Antwort:** `200`, `text/markdown; charset=utf-8`, derzeit 14.956 Zeichen. Beginnt mit
YAML-Frontmatter (`name`, `description`, `version`, `applies_to`).

```bash
curl -s "$BASE/skill.md" -H "Authorization: Bearer $KEY" -o AGENTS.md
```

**Fehlerfälle (gemessen):**

| Situation | Status | Antwort |
|---|---|---|
| fehlende oder falsche Anmeldung | `401` | `{"detail":"Unauthorized"}` |

Diese Adresse ist **nicht öffentlich** — ohne Token kein Inhalt. Das ist Absicht: die
Anleitung beschreibt interne Regeln und Statusberechtigungen.

---

## `/tools.json` — Werkzeugkatalog

**Methode:** `GET`. Keine Parameter.

**Antwort:** `200`, `application/json`, Form `{"tools":[{"type":"function","function":{...}}]}`,
derzeit 18 Einträge. Direkt als Function-Calling-Definition verwendbar.

```bash
curl -s "$BASE/tools.json" -H "Authorization: Bearer $KEY" | jq '.tools | length'
```

**Fehlerfälle (gemessen):** identisch zu `/skill.md` — `401` ohne gültiges Token.

---

## `/test/<tool>` — Einzelaufruf

**Methode:** `POST`. `<tool>` ist der Werkzeugname aus `/tools.json`.

**Parameter:** im Rumpf als JSON-Objekt mit den Parametern des Werkzeugs — dieselben Namen
wie im Katalog, keine Verpackung in `arguments`.

```bash
curl -s -X POST "$BASE/test/kandidat_identifizieren" \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"suchbegriff":"+38766084109"}'
```

**Antwort:** `200`, `application/json` mit dem Ergebnis des Werkzeugs, plus `success`.

**Fehlerfälle (gemessen):**

| Situation | Status | Antwort |
|---|---|---|
| fehlende oder falsche Anmeldung | `401` | `{"detail":"Unauthorized"}` |
| unbekannter Werkzeugname | `404` | `{"detail":"Unbekanntes Werkzeug: <name>"}` |
| `GET` statt `POST` | `405` | `{"detail":"Method Not Allowed"}` |
| Prüffehler (fehlender Pflichtwert, ungültiger Status) | `500` | Stacktrace — **siehe Defekt unten** |

### Defekt: Prüffehler liefern 500 statt 400

Am 27.10.2026 gemessen: `unterlage_status_setzen` ohne `doc_id` und mit `status_id: 99`
antworten beide mit `500 Internal Server Error` und einem vollständigen Python-Stacktrace,
inklusive interner Dateipfade wie `.cache/uv/environments-v2/...`.

Drei Folgen:

1. **Falsche Einordnung.** Ein `500` heißt für jeden Client „Server gestört, später erneut
   versuchen". Tatsächlich ist die Eingabe falsch — Wiederholen ändert nichts.
2. **Informationsleck.** Der Stacktrace nennt interne Pfade und Modulnamen.
3. **Abweichung von der Anleitung.** `docs/error-recovery.md` beschreibt Meldungen wie
   `Unbekannter Status` und `Kandidat ... existiert nicht`. Diese Texte stehen im
   Stacktrace, sind aber nicht sauber als Feldfehler abrufbar.

**Sollverhalten:** `400` mit `{"detail":"Unbekannter Status: 99"}` — ohne Stacktrace.
Bis zur Korrektur gilt: bei `500` den Rumpf nach dem Feldnamen durchsuchen, nicht blind
wiederholen.

---

## Kurzprüfung nach jedem Deploy

```bash
curl -s -o /dev/null -w "mcp %{http_code}\n" -X POST "$BASE/mcp/" \
  -H "Authorization: Bearer $KEY" -H "Accept: application/json, text/event-stream" \
  -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
curl -s -o /dev/null -w "skill %{http_code}\n" "$BASE/skill.md" -H "Authorization: Bearer $KEY"
curl -s -o /dev/null -w "tools %{http_code}\n" "$BASE/tools.json" -H "Authorization: Bearer $KEY"
curl -s -o /dev/null -w "test %{http_code}\n" -X POST "$BASE/test/unterlagen_katalog" \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" -d '{"limit":1}'
```

Erwartet: `200 200 200 200`. Alles andere ist ein Abbruchgrund.
