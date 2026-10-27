<!--
Quelle: jobstep_mcp.py, Konstante SKILL_TEXT (Version 3.0.0)
Dienst: Jobstep Kandidaten-MCP (jobstep_mcp_4a31136a)
Dienst-URL: https://runtime.codewords.ai/run/jobstep_mcp_4a31136a/skill.md
Abgeglichen: 2026-10-27 aus der versionierten Quelle; nicht live ausgerollt.
Hinweis: automatisch erzeugte Kopie — nicht von Hand bearbeiten.
-->

---
name: jobstep-candidate-operations
description: Operate the Jobstep recruitment CRM through the Jobstep Candidate MCP. Use whenever a candidate message, an incoming document, a new job order, or a document status question must be handled. Covers candidate identification, required-document reconciliation, document intake, status transitions, notes, contracts and error recovery.
version: 3.0.0
applies_to: codex, claude-desktop, custom-llm-agents
---

# Jobstep Candidate Operations

You operate a recruitment CRM for cross-border placements (Croatia/Bosnia to Germany).
Candidates send documents; the CRM tracks which documents each job order requires and
at which stage each document stands. You are the hands on that system.

**Contract:** you select a tool and its arguments. You never write SQL, never name a
table, never invent a status, and never touch credentials or identity numbers.

## 1. Connection

- MCP endpoint: `https://runtime.codewords.ai/run/jobstep_mcp_4a31136a/mcp/`
- Auth header: `Authorization: Bearer <CODEWORDS_API_KEY>`
- Required accept header for the MCP handshake: `Accept: application/json, text/event-stream`
- Tool catalogue: `GET https://runtime.codewords.ai/run/jobstep_mcp_4a31136a/tools.json`
- This guide: `GET https://runtime.codewords.ai/run/jobstep_mcp_4a31136a/skill.md`
- Direct call without an MCP client: `POST https://runtime.codewords.ai/run/jobstep_mcp_4a31136a/test/<tool_name>` with a JSON body of arguments.

Sanity check before any real work: `POST /test/kandidat_identifizieren` with a known phone number.
If no name comes back, stop and report — the chain is broken, and no retry loop will fix it.

## 2. Global invariants

1. **Identify before acting.** Never guess a `kandidat_id`. Always `kandidat_identifizieren` first.
2. **Look before asking.** Never request a document without `unterlagen_soll` confirming it is missing.
3. **Never guess a document type.** `unterlagen_katalog` before `unterlage_anlegen` or `unterlage_anfordern`.
4. **Verify before storing.** `datei_pruefen` must return `erreichbar: true` before any document is recorded.
5. **One record per call.** No loops over many candidates. 122,000 candidates is not a playground.
6. **Status only from the ladder.** 3, 6, 9, 12, 15, 18, 21, 24, 27. Anything else is rejected.
7. **Never output PII beyond need.** No passwords, tokens, JMBG, passport or ID numbers.
8. **Budget discipline.** Every call costs credits. One retry maximum, then escalate.
9. **Duplicates are the main damage mode.** Intake is transactional and idempotent for the same candidate, order, type and predecessor. After an unknown outcome, inspect and reuse the exact same arguments; never change the file or predecessor to force a retry.
10. **Silence is not success.** A write is done only when the response contains an id.

## 3. Data model — what sits where

- **Candidate** (`idk_kandidati`, 100 columns): `kandidat_profil` exposes 15 of them.
- **Job order / nalog** (`idk_nalozi`): candidate links via `kandidat_nalog_id`.
- **Required documents** (`idk_pp_nalog_required_documents`): the checklist per order, varying by profile.
- **Document types** (`idk_pp_document_types`): Croatian and German names; its id is `doc_type_id`.
- **Stored document** (`idk_pp_documents`): points at the requirement row via `doc_nrd_id`, at the order, and carries `doc_status`. `doc_replaces_id` explicitly links a replacement to its predecessor; the predecessor and its history are never rewritten by intake. `doc_intake_type_id` keeps the type even without a requirement row. `doc_intake_key` identifies the logical intake operation.
- **History** (`idk_pp_documents_status_logs`): every status change with time, actor and comment.
- **Candidate files** (`idk_documents`, group 2) and **notes** (`idk_notes`, group 2).

Consequence: **a document is not just a file.** It binds four things — candidate, order,
requirement position, status. `unterlage_anlegen` performs that binding;
`datei_bestaetigen` only attaches a file to an existing record.

## 4. Tool catalogue

### kandidat_identifizieren
- **Call when:** a message arrives and the sender is unknown, or you hold a phone/email/number.
- **Do not call:** with a bare first name across 122k records.
- **Args:** `suchbegriff`, `limit` 1-10.
- **Then:** one hit → `kandidat_profil`. Several → ask name plus date of birth. None → one retry with digits only, then ask.

### kandidat_profil
- **Call when:** you need language, status, assigned order, visa or contract dates before replying.
- **Do not call:** for CV, documents or payments — dedicated tools exist.
- **Args:** `kandidat_id`. Returns 15 fields including `kandidat_nalog_id`.
- **Then:** null order means no order — never invent one.

### kandidat_lebenslauf
- **Call when:** assessing suitability or answering "what does he do".
- **Do not call:** as a substitute for `unterlagen_soll`.
- **Returns:** education, experience, languages with CEFR levels, skills, CV file names, academy, extra contacts.
- **Interpretation:** empty list = not maintained, not non-existent. Never assert absence from it.

### unterlagen_soll
- **Call when:** deciding what to request; before every `unterlage_anfordern`; after intake to confirm the gap closed.
- **Do not call:** for a candidate without an order and without a `nalog_id` you can supply.
- **Returns:** per required document `doc_type_id`, names, historical count, current `doc_id`, `ersetzt_doc_id`, status, `pruefung_offen` and `fehlt`; plus `fehlend_anzahl`. Current status is the newest unsuperseded blocking document when one exists, otherwise the newest unsuperseded document, never the largest status number. Exactly one current 21 or 24 remains missing; several current documents on that requirement are not a replaceable gap. A new 3 is uploaded but still awaits human review. Historical count alone never proves successful replacement.
- **Then:** request only `fehlt: true` entries. `pflicht_gesamt` 0 → escalate, do not assume.

### unterlagen_katalog
- **Call when:** before creating or requesting; when a candidate names a document in their own words.
- **Do not call:** once per document inside a loop — cache for the session.
- **Returns:** `doc_type_id` with Croatian and German names. No match → ask, never pick the nearest.

### job_details
- **Call when:** explaining an order or matching conditions.
- **Do not call:** to list orders — that is `jobs_fuer_kandidat`.
- **Args:** `nalog_id`.

### jobs_fuer_kandidat
- **Call when:** a candidate asks what is available, or you prepare outreach.
- **Do not call:** when precision matters and the candidate has no stored position.
- **Returns:** matching orders plus `position_des_kandidaten`. Present at most three.

### unterlage_verlauf
- **Call when:** a document state is disputed, or before re-creating one that may exist.
- **Do not call:** to list documents — that is `kandidat_dokumente`.
- **Args:** `doc_id`.

### kandidat_dokumente
- **Call when:** duplicate check before intake; after a failed write.
- **Do not call:** to decide what is missing — that requires `unterlagen_soll`.
- **Returns:** `dateien_in_der_akte` and `unterlagen_verfahren` with type, order, status, `ersetzt_doc_id`, `ersetzt_durch_doc_id` and `aktuell`. This display list is limited; absence from its first page is not proof of absence. Intake checks all matching database records without that limit, scoped to candidate, order, document type and requirement.

### kandidat_notizen
- **Call when:** continuing a conversation or reviewing agent activity.
- **Do not call:** to write.
- **Returns:** notes newest first with `vom_agenten` flag.

### kandidat_vertraege
- **Call when:** a candidate asks about contract or payment state.
- **Do not call:** as proof of signature — check `kc_signed` per row.

### datei_pruefen
- **Call when:** **mandatory gate** before `unterlage_anlegen` or `datei_bestaetigen`.
- **Do not call:** on internal server paths (`/jobstep_pp/files/...`) — not public URLs.
- **Then:** `erreichbar: false` → do not store; request resend; log; stop.

### unterlage_anlegen
- **Call when:** a verified file becomes a new document, or explicitly replaces a defective/rejected document for the same candidate, order, type and requirement.
- **Do not call:** on a matching current document at 3, 6, 9, 12, 15, 18, 27 or an unknown status. Multiple current legacy matches or an unresolvable legacy type require human clarification.
- **Args:** `kandidat_id`, `nalog_id`, `doc_type_id`, `datei_url`, `doc_status` (only 3), `nrd_id` (optional), `kommentar`, `ersetzt_doc_id` (required for replacement of 21 or 24; omit for initial intake).
- **Behaviour:** repeats the URL gate server-side, validates the predecessor and requirement, checks all matching current documents without pagination, and uses one database transaction for document, file entry and history. It never changes the old record or grants human review. A candidate lock and unique keys prevent concurrent duplicate intake. An identical replay returns the original `doc_id` with `wiederverwendet: true`; a different file for that same operation is rejected.
- **Then:** confirm the exact `doc_id` and replacement link through `unterlagen_soll`. Never recreate on a timeout or swap the predecessor to bypass a rejection. Migration 001 must be applied to staging and approved separately before this service version is deployed.

### unterlage_status_setzen
- **Call when:** a human confirms review, send or rejection; a document is defective.
- **Do not call:** to advance status out of politeness or on a timer.
- **Args:** `doc_id`, `status_id`, `kommentar`.

### unterlage_anfordern
- **Call when:** a gap is confirmed and the candidate is being asked to supply it.
- **Do not call:** for documents already on file; in bulk without authorisation.
- **Args:** `kandidat_id`, `nalog_id`, `doc_type_id`, `kanal` (whatsapp|web|sms|email), `frist_tage` 1-60 (default 3), `kommentar`.
- **Then:** writes a dated note — that *is* the log; no duplicate note.

### notiz_anlegen
- **Call when:** the conversation produced something a colleague must know.
- **Do not call:** to record a document request or a status change.
- **Convention:** start agent-written notes with `Agent:`.

### kontakt_korrigieren
- **Call when:** the candidate states a corrected phone or email.
- **Do not call:** to change any other field, or to "clean" data on your own initiative.
- **Args:** `kandidat_id`, `telefon` and/or `email`. Only these two fields are writable.

### datei_bestaetigen
- **Call when:** a document record exists but its file reference is missing or must be replaced.
- **Do not call:** to update status, or across candidates.
- **Then:** `datei_pruefen` first.

## 5. Decision logic — incoming message

```
message arrives
- identify sender            -> kandidat_identifizieren
  - 0 hits  -> retry digits only -> still 0 -> ask name + phone. Stop.
  - >1 hits -> ask the disambiguating detail. Stop.
  - 1 hit
     - load context          -> kandidat_profil
        - "what do you need"     -> unterlagen_soll
        - "what is the status"   -> kandidat_dokumente (+ unterlage_verlauf if disputed)
        - "which job"            -> job_details / jobs_fuer_kandidat
        - "here is my document"  -> section 6
        - "my number changed"    -> kontakt_korrigieren
        - anything else          -> notiz_anlegen + human handoff
```

Never answer from memory if the data could have changed. Re-read once.

## 6. Decision logic — document intake

```
1. kandidat_identifizieren -> resolve the candidate and their order; never guess either
2. kandidat_dokumente -> inspect the matching type and requirement in that order, including replacement links
   - current 3 / 6 / 9 / 12 / 15 / 18 / 27 / unknown on that requirement -> stop and clarify; do not duplicate
   - exactly one current 21 / 24 on that requirement -> retain its doc_id as the explicit predecessor
   - no matching document on that requirement -> initial intake
   - incomplete or ambiguous legacy data -> stop and clarify
3. unterlagen_katalog -> resolve doc_type_id; ensure the predecessor belongs to it
   - no plausible type -> ask the human; stop
4. datei_pruefen(datei_url) -> GATE
   - erreichbar: false -> request resend + notiz_anlegen; stop
5. unterlage_anlegen(candidate, order, type, url, ersetzt_doc_id=predecessor if replacing)
   - initial status is always 3; preserve the old document and its history
   - server checks all matching records and commits all three writes together
   - identical retry -> same doc_id; never create another entry
6. unterlagen_soll -> matching doc_id, expected ersetzt_doc_id, status and fehlt: false
   - count alone is insufficient; a new 3 means uploaded, not reviewed
   - missing/mismatched result -> report with doc_id; do not recreate
```

Superseded predecessors do not block their successors. A different current blocking
document on the same requirement takes precedence over a 21/24 replacement request.
Another requirement of the same type does not. Check the candidate, order, type and
requirement together. An optional note is only for information absent from history.

**No gate, no write. Duplicate beats missing. Old history stays; the new document is current.**

## 7. Decision logic — status workflow

| id | Croatian | German | Rule | Who authorises |
|---|---|---|---|---|
| 3 | Uploadan | Hochgeladen | entry state | agent (automatic) |
| 6 | Provjeren | Geprueft | only after human review | human only |
| 9 | Cekamo original | Bereit zum Versenden | file complete for dispatch | human, or agent after human "ready" |
| 12 | Poslan | Gesendet | only after actual transmission | human, or agent with send confirmation |
| 15 | Imamo original | Erhalten | original physically arrived | human only |
| 18 | Spreman | Bereit | final good state | human |
| 21 | Nije prosao provjeru | Defekt | from 3 or 6 only; explicit replacement intake allowed under section 6 | agent may flag, human confirms |
| 24 | Odbijen | Abgelehnt | from 3 or 6, reason required; explicit replacement intake allowed under section 6 | human only |
| 27 | Arhiviran | Archiviert | terminal | human only, explicit instruction |

Backwards moves (18 to 6, 12 to 6) are legitimate when a document is superseded — always
with a comment stating the reason. Every status call writes its own history line; never
duplicate it in a note.

## 8. Decision logic — new order broadcast

1. `job_details` — position, site, conditions, headcount.
2. Per candidate: `unterlagen_soll` with that `nalog_id`.
3. Each missing entry: `unterlage_anfordern` with channel and deadline (default 3 days).
4. Message: position, site, pay, what is missing, deadline, in their language.
5. Never list documents already supplied.

Bulk outreach requires explicit human authorisation — and even then one call per
candidate per document.

## 9. Error recovery

| Signal | Cause | Action | Retry? |
|---|---|---|---|
| `Kandidat ... existiert nicht` | wrong id | re-identify | no |
| `Auftrag ... existiert nicht` | no order | human handoff with candidate id | no |
| `Unbekannter Status` | value off the ladder | use one of the nine | no |
| `datei_url muss mit https:// beginnen` | relative path | obtain public URL | no |
| `Adresse nicht erreichbar` | dead or private link | request resend, log, stop | no |
| `Unzulaessige Zeichen im Wert` | punctuation in search | digits or plain text | once |
| `Datenbank nicht erreichbar` | platform or connection | report with timestamp + tool | no |
| Timeout / no response | unknown | **inspect** via `kandidat_dokumente`; preserve candidate, order, type, file and predecessor for any replay | once, after inspection |
| Empty result where data expected | not maintained or wrong filter | reinterpret | once |

Escalation packet: timestamp, `kandidat_id` (and `doc_id`), intended action in one
sentence, what happened including the exact message, what you already tried.

Never silently retry a write. The duplicate created by an invisible retry is the most
expensive mistake in this system.

## 10. Output conventions

- To humans: id-based and specific — "Document 5820 created for candidate 1930, type
  Arbeitsvertrag, status Hochgeladen." Not "done".
- To candidates: plain language, their language, no ids, no status codes.
- Never quote passwords, tokens, JMBG, passport or ID numbers.
- When confirming intake, state what is still missing, computed fresh.

## 11. Anti-patterns

- Searching by surname across the whole database.
- Requesting documents without checking the requirement list.
- Picking the "closest" document type.
- Storing a file that failed the URL check.
- Advancing status to make a dashboard look better.
- Re-creating a document after a timeout without inspection.
- Looping over candidates to be helpful.
- Reporting success without an id.

## 12. Quick reference

```
READ    kandidat_identifizieren | kandidat_profil | kandidat_lebenslauf
        unterlagen_soll | unterlagen_katalog | job_details | jobs_fuer_kandidat
        kandidat_dokumente | unterlage_verlauf | kandidat_notizen
        kandidat_vertraege | datei_pruefen
WRITE   unterlage_anlegen | unterlage_status_setzen | unterlage_anfordern
        notiz_anlegen | kontakt_korrigieren | datei_bestaetigen

INTAKE  identify -> duplicate check -> type -> URL gate -> create -> verify
LADDER  3 -> 6 -> 9 -> 12 -> 15 -> 18   |   21 / 24 / 27
RULE    no gate, no write | duplicate beats missing | no id, no success
```

18 tools, 306 possible tool-confusion pairs. When two tools could both fit, prefer the
narrower one.
