#!/usr/bin/env bash
# Erzeugt beide Anleitungsdateien aus einer Quelle: /skill.md des Dienstes.
# Schreibt nur, wenn sich der Rumpf geaendert hat — ein neues Abrufdatum allein zaehlt nicht.
set -euo pipefail

BASE="${CODEWORDS_BASE_URL:-https://runtime.codewords.ai/run/jobstep_mcp_4a31136a}"
KEY="${CODEWORDS_API_KEY:?CODEWORDS_API_KEY ist nicht gesetzt}"
SKILL_URL="$BASE/skill.md"
SKILL_PATH="${SKILL_PATH:-skills/jobstep-crm/SKILL.md}"
GUIDE_PATH="${GUIDE_PATH:-.agents/skills/jobstep-crm/references/service-guide.md}"
MIN_BYTES="${MIN_BYTES:-5000}"

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

echo "Quelle: $SKILL_URL"
curl -fsS --max-time 60 -H "Authorization: Bearer $KEY" "$SKILL_URL" -o "$TMP/skill.md"

# --- Plausibilitaetspruefungen: bei Fehlschlag bleiben die vorhandenen Dateien unberuehrt
SIZE=$(wc -c < "$TMP/skill.md" | tr -d ' ')
[ "$SIZE" -ge "$MIN_BYTES" ] || { echo "FEHLER: Antwort zu kurz ($SIZE Bytes)"; exit 1; }
head -n 1 "$TMP/skill.md" | grep -qx -- '---' || { echo "FEHLER: kein YAML-Frontmatter"; exit 1; }
grep -q '^name: jobstep-candidate-operations' "$TMP/skill.md" || { echo "FEHLER: unerwarteter Skill-Name"; exit 1; }
grep -q 'No gate, no write' "$TMP/skill.md" || { echo "FEHLER: Kernregel fehlt — Anleitung unvollstaendig"; exit 1; }
grep -q '## 9. Error recovery' "$TMP/skill.md" || { echo "FEHLER: Abschnitt Fehlerbehebung fehlt"; exit 1; }

VERSION=$(grep -m1 '^version:' "$TMP/skill.md" | sed 's/^version:[[:space:]]*//' | tr -d '\r')
NEW_HASH=$(sha256sum "$TMP/skill.md" | cut -d' ' -f1)
echo "Version: $VERSION | Groesse: $SIZE Bytes | sha256: ${NEW_HASH:0:12}"

# --- Rumpf der bestehenden Referenz vergleichen (Kopfzeile ignorieren)
OLD_HASH=""
if [ -f "$GUIDE_PATH" ]; then
  sed '1,/^-->$/d' "$GUIDE_PATH" | sed '/./,$!d' > "$TMP/old.md"
  OLD_HASH=$(sha256sum "$TMP/old.md" | cut -d' ' -f1)
fi

if [ "$NEW_HASH" = "$OLD_HASH" ]; then
  echo "Unveraendert — keine Datei geschrieben."
  exit 0
fi

mkdir -p "$(dirname "$SKILL_PATH")" "$(dirname "$GUIDE_PATH")"
cp "$TMP/skill.md" "$SKILL_PATH"
{
  echo "<!--"
  echo "Quelle: $SKILL_URL"
  echo "Dienst: Jobstep Kandidaten-MCP (jobstep_mcp_4a31136a)"
  echo "Version: $VERSION"
  echo "Abgerufen: $(date -u +%Y-%m-%d)"
  echo "Hinweis: automatisch erzeugte Kopie — nicht von Hand bearbeiten."
  echo "-->"
  echo
  cat "$TMP/skill.md"
} > "$GUIDE_PATH"

echo "Geschrieben:"
echo "  $SKILL_PATH ($SIZE Bytes)"
echo "  $GUIDE_PATH ($(wc -c < "$GUIDE_PATH" | tr -d ' ') Bytes)"
exit 0
