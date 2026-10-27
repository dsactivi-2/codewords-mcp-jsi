# /// script
# requires-python = "==3.11.*"
# dependencies = [
#   "codewords-client==0.4.11",
#   "fastapi==0.116.1"
# ]
# [tool.env-checker]
# env_vars = [
#   "PORT=8000",
#   "LOGLEVEL=INFO",
#   "CODEWORDS_API_KEY",
#   "CODEWORDS_RUNTIME_URI"
# ]
# ///
"""Spiegelt Warnungen und Fehler aus der Tabelle mcp_fehler nach Notion.

Bereinigt anschliessend beide Seiten nach 90 Tagen. Aufruf: POST /
"""
import json
from typing import Any

from codewords_client import AsyncCodewordsClient, logger, run_service
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

NOTION_DB = "4062cc93-a106-8127-8e3f-fa6425006728"
AUFBEWAHRUNG_TAGE = 90
MAX_ZEILEN = 200

# Ein Client fuer den gesamten Lauf — keine Neuanlage je Aufruf.
_client: AsyncCodewordsClient | None = None


async def _hole_client() -> AsyncCodewordsClient:
    """Liefert den gemeinsamen Client und legt ihn beim ersten Bedarf an."""
    global _client
    if _client is None:
        _client = AsyncCodewordsClient()
    return _client

# -------------------------
# Hilfsfunktionen
# -------------------------

async def _db(sql: str) -> list[dict]:
    """Fuehrt genau eine vorbereitete Abfrage ueber die MySQL-Verbindung aus."""
    client = await _hole_client()
    antwort = await client.run(service_id="pipedream", inputs={
        "app": "mysql", "action": "execute-raw-query", "props": {"sql": {"query": sql}}})
    daten = antwort.json().get("output", antwort.json())
    if isinstance(daten, str):
        daten = json.loads(daten)
    daten = daten.get("ret", daten)
    if isinstance(daten, dict):
        return [daten]
    if not isinstance(daten, list):
        raise HTTPException(status_code=502, detail=f"Datenbank antwortet unerwartet: {str(daten)[:150]}")
    return daten


async def _notion(slug: str, argumente: dict) -> dict:
    """Ruft ein Notion-Werkzeug ueber Composio auf."""
    client = await _hole_client()
    antwort = await client.run(service_id="composio",
                               path="api/v3/tools/execute/" + slug,
                               inputs={"arguments": argumente})
    inhalt = antwort.json().get("output", antwort.json())
    if isinstance(inhalt, str):
        inhalt = json.loads(inhalt)
    return inhalt if isinstance(inhalt, dict) else {}


def _zeile_zu_notion(zeile: dict) -> list[dict]:
    """Baut die Notion-Eigenschaften aus einer Protokollzeile."""
    return [
        {"name": "Werkzeug", "type": "title", "value": str(zeile.get("f_werkzeug") or "unbekannt")[:200]},
        {"name": "Zeitpunkt", "type": "date", "value": str(zeile.get("f_zeit"))},
        {"name": "Art", "type": "select", "value": str(zeile.get("f_art") or "Warnung")},
        {"name": "Meldung", "type": "rich_text", "value": str(zeile.get("f_meldung") or "")[:1900]},
        {"name": "Kontext", "type": "rich_text", "value": str(zeile.get("f_kontext") or "")[:1900]},
    ]

# -------------------------
# FastAPI Application
# -------------------------
app = FastAPI(
    title="Jobstep Fehlerprotokoll",
    description="Uebertraegt Warnungen und Fehler des Jobstep-MCP nach Notion und bereinigt nach 90 Tagen.",
    version="1.0.0",
)


class SyncRequest(BaseModel):
    limit: int = Field(default=200, ge=1, le=MAX_ZEILEN,
                       description="Hoechstzahl der Eintraege pro Lauf (Obergrenze 200).")


class SyncResponse(BaseModel):
    success: bool = Field(..., description="Immer true, wenn der Lauf ohne Ausnahme endete.")
    gelesen: int = Field(..., description="Zahl der gelesenen, noch nicht uebertragenen Zeilen.")
    uebertragen: int = Field(..., description="Zahl der erfolgreich in Notion angelegten Seiten.")
    fehlgeschlagen: list[dict[str, Any]] = Field(default_factory=list, description="Fehler je Zeile, falls aufgetreten.")
    verblieben: int | None = Field(default=None, description="Zeilen nach der Bereinigung im Protokoll.")
    aufbewahrung_tage: int = Field(..., description="Aufbewahrungsdauer in Tagen.")


@app.get("/health")
async def health() -> dict:
    """Statusauskunft des Dienstes."""
    return {"status": "ok", "dienst": "jobstep-log-sync", "notion_database": NOTION_DB}


@app.post("/", response_model=SyncResponse)
async def sync(request: SyncRequest) -> SyncResponse:
    """Uebertraegt neue Eintraege nach Notion, markiert sie und bereinigt alte."""
    logger.info("STEPLOG START lesen")
    # Die Obergrenze steht fest im Abfragetext; request.limit wird darauf begrenzt.
    grenze = str(int(min(request.limit, MAX_ZEILEN)))
    neu = await _db(
        "SELECT f_id, f_zeit, f_art, f_werkzeug, f_meldung, f_kontext FROM mcp_fehler "
        "WHERE f_exportiert = 0 ORDER BY f_id LIMIT " + grenze
    )
    logger.info("Synchronisation gestartet", offen=len(neu))

    logger.info("STEPLOG START uebertragen")
    uebertragen, fehlgeschlagen, letzte_id = 0, [], 0
    for zeile in neu:
        antwort = await _notion("NOTION_INSERT_ROW_DATABASE",
                                {"database_id": NOTION_DB, "properties": _zeile_zu_notion(zeile)})
        if antwort.get("successful"):
            uebertragen += 1
            letzte_id = int(zeile["f_id"])
        else:
            fehler = str(antwort.get("error"))[:200]
            logger.error("Notion-Uebertragung fehlgeschlagen", f_id=zeile.get("f_id"), fehler=fehler)
            fehlgeschlagen.append({"f_id": zeile.get("f_id"), "fehler": fehler})
            break

    # Alles bis zur letzten erfolgreichen Id ist uebertragen — eine Markierung, kein Loop.
    if letzte_id > 0:
        await _db("UPDATE mcp_fehler SET f_exportiert = 1 WHERE f_id <= " + str(letzte_id)
                  + " AND f_exportiert = 0")

    logger.info("STEPLOG START bereinigen")
    await _db("DELETE FROM mcp_fehler WHERE f_zeit < (NOW() - INTERVAL "
              + str(int(AUFBEWAHRUNG_TAGE)) + " DAY)")
    verblieben = await _db("SELECT COUNT(*) AS c FROM mcp_fehler")
    logger.info("Synchronisation beendet", uebertragen=uebertragen, fehler=len(fehlgeschlagen))

    return SyncResponse(
        success=True,
        gelesen=len(neu),
        uebertragen=uebertragen,
        fehlgeschlagen=fehlgeschlagen,
        verblieben=verblieben[0]["c"] if verblieben else None,
        aufbewahrung_tage=AUFBEWAHRUNG_TAGE,
    )


if __name__ == "__main__":
    run_service(app)
