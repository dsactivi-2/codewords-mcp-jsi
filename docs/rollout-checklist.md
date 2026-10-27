# Roll-out-Checkliste — Jobstep Kandidaten-MCP

Gültig für den nächsten Versionssprung (Ziel: v3). Heute steht der Dienst auf
Skill-Version `2.0.0`; ein eigenes Versionsfeld im Dienst und in `tools.json` gibt
es noch nicht — Punkt 1 schließt diese Lücke.

**Regel für den Sprung:** Die Hauptversion steigt, wenn sich der Werkzeugsatz, die
Parameter oder die Statuspolitik ändern. Ein neuer Werkzeugtyp, ein neues Feld oder
ein geänderter Status ist **immer** eine Hauptversion. Reine Textkorrekturen sind
eine Nebenversion, Änderungen an der Anleitung ohne Verhaltenswirkung eine Patch-Version.

Jeder Punkt hat ein Kästchen und ein **Abbruchkriterium**. Wer ein Abbruchkriterium
auslöst, hält an — er arbeitet nicht daran vorbei.

---

## 0. Vorbereitung (am Tag vorher)

- [ ] **Änderungsfenster festlegen.** Während des Roll-outs bearbeitet niemand die
      Dateien im Repository und niemand deployt den Dienst.
- [ ] **Ausgangsstand festhalten** — Commit-Hash und Dienst-Implementierung notieren:
      ```bash
      git -C codewords-mcp-jsi rev-parse HEAD
      curl -s "$BASE/health" -H "Authorization: Bearer $KEY"
      ```
- [ ] **Baseline der Werkzeuge sichern:**
      ```bash
      curl -s "$BASE/tools.json" -H "Authorization: Bearer $KEY" > baseline-tools.json
      ```
      Abbruch, wenn die Datei nicht genau 18 Werkzeuge enthält.
- [ ] **Backup der aktuellen Konfiguration** — aus dem Repository, nicht aus dem Kopf:
      ```bash
      git tag pre-v3-$(date +%Y%m%d)
      git push origin --tags
      ```
      Der Tag ist das Backup. Ein kopierter Ordner auf einem Laptop ist keines.
      Abbruch, wenn der Tag nicht gepusht ist.

---

## 1. Versionsbump

- [ ] **`skill.md` im Dienst:** `version: 2.0.0` → `version: 3.0.0` im Frontmatter.
- [ ] **`tools.json`:** Feld `version` ergänzen — heute nicht vorhanden:
      ```json
      { "version": "3.0.0", "service_id": "jobstep_mcp_4a31136a", "generated_at": "…", "tools": [ … ] }
      ```
- [ ] **Dienst:** Konstante `SERVICE_VERSION = "3.0.0"` einführen und in `/health`
      ausgeben, damit die laufende Fassung abfragbar ist.
- [ ] **Prüfen:** `curl -s "$BASE/health"` zeigt `"version": "3.0.0"`.
      Abbruch, wenn `/health` und `skill.md` unterschiedliche Versionen melden.

---

## 2. Service-Guide aktualisieren

Der Dienst ist die Quelle. Die Datei im Repository ist eine Kopie — **nie umgekehrt**.

- [ ] Deploy abwarten und Erreichbarkeit prüfen:
      `GET /skill.md` → 200, Inhaltstyp `text/markdown`.
- [ ] Neue Fassung ziehen und **gegen die Kopie im Repo diffen**:
      ```bash
      curl -s "$BASE/skill.md" -H "Authorization: Bearer $KEY" > neu.md
      diff references/service-guide.md neu.md | head -40
      ```
- [ ] Diff **vor** dem Commit lesen. Jede Zeile, die eine Statusregel, eine
      Reihenfolge oder ein Verbot ändert, ist eine Freigabe-Frage — kein Commit.
- [ ] Herkunftskopf aktualisieren: Abrufdatum und Version.
      Abbruch, wenn der Diff leer ist, aber die Version gestiegen ist — dann wurde
      der Dienst nicht wirklich neu ausgeliefert.

---

## 3. AGENTS.md validieren

`AGENTS.md` ist der Dauerkontext. Er darf **nicht** mitwachsen.

- [ ] Länge prüfen: Ziel ≤ 1.500 Zeichen. Heute 1.005.
      Ein Anstieg über 2.000 ist ein Signal, dass Details hineinrutschen, die in den Skill gehören.
- [ ] Sechs Intake-Schritte in der richtigen Reihenfolge vorhanden.
- [ ] Verbot „menschlich vorbehaltene Status niemals automatisch setzen" vorhanden.
- [ ] Keine Werkzeugliste, keine Parametertabellen (die gehören in `tools.json` und die Referenz).
- [ ] Verweis auf `.agents/skills/jobstep-crm/SKILL.md` intakt.
      **Abbruch:** Ändert der neue Service-Guide die Intake-Reihenfolge, wird `AGENTS.md`
      **nicht** automatisch angepasst. Das ist eine Entscheidung für Menschen — Punkt
      auf die Agenda, Roll-out pausieren.

---

## 4. Test-Abruf der neun Fehlersignale

Jedes Signal wird ausgelöst und die **erwartete Ablehnung** geprüft. Sechs der neun
sind rein lesend. Drei berühren schreibende Werkzeuge — für diese gilt: **nur gegen
einen ausdrücklich benannten Testkandidaten**, niemals gegen einen laufenden Vorgang.

Vorher und nachher gilt: höchste `doc_id` notieren. Sie muss unverändert bleiben.

| # | Signal | Auslösung | Erwartung | Schreibt? |
|---|---|---|---|---|
| 1 | Leeres Ergebnis | `kandidat_identifizieren` mit `+38900000000` | leere Liste, kein Fehler | nein |
| 2 | Kein passender Typ | `unterlage_anlegen` mit `doc_type_id: 99999` | `Unbekannter Dokumenttyp` | Versuch |
| 3 | Adresse nicht erreichbar | `datei_pruefen` mit `https://example.invalid/x.pdf` | `erreichbar: false` | nein |
| 4 | Kein `https://` | `datei_pruefen` mit `/jobstep_pp/files/x.pdf` | `muss mit https:// beginnen` | nein |
| 5 | `doc_id` fehlt | `unterlage_verlauf` mit `doc_id: 99999999` | `Dokument existiert nicht` | nein |
| 6 | Lücke nicht geschlossen | `unterlagen_soll` für Kandidat mit offener Pflicht | `fehlt: true` | nein |
| 7 | Unbekannter Status | `unterlage_status_setzen` mit `status_id: 99` | `Unbekannter Status` | Versuch |
| 8 | Unzulässige Zeichen | `kandidat_identifizieren` mit `'; DROP TABLE` | `Unzulässige Zeichen` | nein |
| 9 | Dienst nicht erreichbar | Aufruf mit ungültigem Token | HTTP 401/403, keine Daten | nein |

**Nachweis nach dem Lauf:**

- [ ] `unterlage_verlauf` der Test-Unterlage zeigt **unveränderten** Status (Signal 7).
- [ ] `kandidat_dokumente` des Testkandidaten zeigt **keine neue** Zeile (Signal 2).
- [ ] höchste `doc_id` unverändert.

Abbruch, wenn eines der drei Schreibe-Signale einen Datensatz erzeugt hat.

---

## 5. Freigabe-Kriterien

Der Roll-out ist erst fertig, wenn **alle** Punkte belegt sind:

- [ ] `/mcp/` beantwortet `tools/list` mit der erwarteten Anzahl Werkzeuge.
- [ ] Die sechs Intake-Werkzeuge sind vorhanden und heißen unverändert.
- [ ] `/skill.md` liefert 200 und die neue Versionsnummer.
- [ ] `/health` meldet dieselbe Version wie `/skill.md`.
- [ ] Neun Fehlersignale geprüft, keine Nebenwirkung bei den drei Schreibe-Signalen.
- [ ] Diff der Referenz von einem Menschen gelesen und freigegeben.
- [ ] `AGENTS.md` unverändert oder bewusst geändert — nicht „irgendwie mitgelaufen".
- [ ] Backup-Tag existiert und ist gepusht.

**Kein Go, wenn:** ein Werkzeug fehlt, Versionen auseinanderlaufen, ein Schreibe-Signal
einen Datensatz hinterlassen hat, oder der Referenz-Diff ungelesen ist.

---

## 6. Rollback

Vorbereitet, bevor deployed wird — nicht danach erfunden.

- [ ] **Dienst:** vorherige Implementierung aktivieren:
      ```
      set_active_implementation(service_id="jobstep_mcp_4a31136a", implementation_id="<vorherige>")
      ```
- [ ] **Repository:** `git revert <commit>` oder Rücksprung auf den Tag `pre-v3-<datum>`.
- [ ] **Reihenfolge:** erst Dienst, dann Repository. Ein Repository, das eine Anleitung
      beschreibt, die der Dienst nicht liefert, ist schlimmer als ein alter Dienst.
- [ ] Nach dem Rollback: Punkt 4 erneut — ein Rollback ist ein Deploy.

---

## 7. Nach dem Roll-out (48 Stunden)

- [ ] Neue `Agent:`-Einträge täglich durchsehen.
- [ ] Keine Unterlage mit Status 6, 15 oder 27, die der Agent gesetzt hat.
- [ ] Keine doppelten Unterlagen: Stichprobe über zehn Kandidaten mit neuen Einträgen.
- [ ] `docs/team-anleitung.md` prüfen, ob sich für das Team etwas geändert hat.
- [ ] Abweichungen mit Zeitpunkt und `kandidat_id` notieren — Grundlage für v4.
