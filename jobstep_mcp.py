# /// script
# requires-python = "==3.11.*"
# dependencies = [
#   "fastapi==0.116.1",
#   "pydantic==2.11.7",
#   "fastmcp==2.10.6",
#   "codewords-client==0.4.11",
#   "httpx==0.28.1"
# ]
# [tool.env-checker]
# env_vars = [
#   "PORT=8000",
#   "LOGLEVEL=INFO",
#   "CODEWORDS_API_KEY",
#   "CODEWORDS_RUNTIME_URI"
# ]
# ///

import asyncio
import json
import os
from pathlib import Path
from textwrap import dedent
from typing import Annotated, Any, Literal
from urllib.parse import urljoin

from codewords_client import AsyncCodewordsClient, logger, run_service
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from fastmcp import FastMCP
from fastmcp.exceptions import McpError
from pydantic import BaseModel, Field, field_validator
from structlog.contextvars import get_contextvars


# -------------------------
# Sandbox Creation Models
# -------------------------
class SandboxCreationRequest(BaseModel):
    """Request model for creating a sandbox with this MCP service."""

    codewords_api_key: str = Field(
        ...,
        json_schema_extra={"format": "password"},
        description="The CodeWords API key, you can get it `https://codewords.agemo.ai/#settings/api-keys`",
        min_length=10,
    )
    service_type: Literal["MCP", "SSE"] = Field(default="MCP", description="Type of service to deploy")
    duration_minutes: int = Field(
        default=15, description="Duration in minutes for the sandbox to live", ge=1, le=60
    )

    @field_validator("codewords_api_key")
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        """Validate and clean the API key field."""
        api_key = v.strip()
        if not api_key:
            raise ValueError("API key cannot be empty")
        if len(api_key) < 10:
            raise ValueError("API key must be at least 10 characters long")
        return api_key


class SandboxCreationResponse(BaseModel):
    """Response model for the created sandbox."""

    message: str = Field(..., description="Markdown-formatted message with instructions")
    service_uri: str = Field(..., description="The URI where the service is accessible")
    sandbox_id: str = Field(..., description="The ID of the created sandbox")
    cost: str = Field(..., description="The cost of running the sandbox")
    duration_minutes: int = Field(..., description="Duration in minutes the sandbox will live")


# -------------------------
# Sandbox Creation Handler
# -------------------------
async def create_sandbox_handler(request: SandboxCreationRequest):
    """
    Create a new sandbox running this MCP service.

    This endpoint:
    1. Takes the current service code and required environment variables
    2. Creates an E2B sandbox with the service running
    3. Returns connection details for the MCP endpoint

    The sandbox will be available for the specified duration in minutes.
    """
    duration_minutes = request.duration_minutes

    logger.info("STEPLOG START create_mcp_sandbox")
    # Read the current file
    service_code = Path(__file__).read_text()

    # Modify service code based on service type
    if request.service_type == "SSE":
        service_code = service_code.replace("stateless_http=True)", "stateless_http=False)")

    # Prepare environment variables (excluding GITHUB_ACCESS_TOKEN)
    env_vars = {key: os.environ[key] for key in ["CODEWORDS_RUNTIME_URI"] if key in os.environ}
    env_vars["CODEWORDS_API_KEY"] = request.codewords_api_key

    # Call the e2b_sandbox service
    async with AsyncCodewordsClient() as client:
        response = await client.run(
            service_id="e2b_sandbox",
            path="/create_sandbox",
            in_background=False,
            correlation_id=get_contextvars().get("correlation_id"),
            inputs={
                "service_code": service_code,
                "timeout": duration_minutes * 60,  # Convert to seconds
                "env_variables": env_vars,
                "port": 8080,  # Use the default port
            },
        )

    logger.debug("Sandbox creation response", response=response.json())
    if response.status_code != 200:
        if response.status_code == 401:
            raise HTTPException(status_code=401, detail=response.json())
        else:
            logger.error("Failed to create sandbox", status=response.status_code, content=response.text)
            raise HTTPException(status_code=500, detail=f"Failed to create sandbox: {response.text}")

    # Extract service URI and format response
    result = response.json()

    # Format service URI based on service type
    service_uri = urljoin(result["service_uri"], "mcp/" if request.service_type == "MCP" else "sse")

    if request.service_type == "MCP":
        markdown_message = dedent(
            f"""\
            ## CodeWords MCP Skeleton - Ready to Connect!

            Your MCP service is now ready! Here's how to get started:

            ### For Claude Desktop Users:
            1. Open your Claude Desktop configuration file
            2. Add the following to your MCP servers section:
            ```json
            {{
                "mcpServers": {{
                "CodeWords-MCP-Skeleton": {{
                    "url": "{service_uri}"
                }}
                }}
            }}
            ```

            ### For Other MCP Clients:
            Use this MCP server URL: `{service_uri}`

            **Note:** This connection will automatically close after {duration_minutes} minutes.

            Happy building with MCP!"""
        )
    else:  # SSE
        markdown_message = dedent(
            f"""\
            ## CodeWords MCP Skeleton (SSE) - Ready to Connect!

            Your SSE service is now ready! Here's how to get started:

            ### For Claude AI Web/Desktop Users:
            1. Go to [Claude AI Settings > Integrations](https://claude.ai/settings/integrations)
            2. Click on the "Add more" button
            3. Type "CodeWords MCP Skeleton" in Integration Name
            4. Add the following URL to "Integration URL": `{service_uri}`
            5. Click on "Add" and wait a few seconds for the integration to be ready

            ### For Other MCP Clients with SSE Support:
            Use this SSE server URL: `{service_uri}`

            **Note:** This connection will automatically close after {duration_minutes} minutes.

            Happy building with MCP!"""
        )

    return SandboxCreationResponse(
        message=markdown_message,
        service_uri=service_uri,
        sandbox_id=result["sandbox_id"],
        cost=result["cost"],
        duration_minutes=duration_minutes,
    )


# -------------------------
# MCP Server Setup
# -------------------------
fast_app = FastMCP("Jobstep Kandidaten-MCP", json_response=False, stateless_http=True)


# -------------------------
# Feste Grenzen
# -------------------------
MAX_ROWS = 50
HARD_LIMIT = 200

DOC_STATUS: dict[int, str] = {
    3: "Hochgeladen",
    6: "Geprueft",
    9: "Bereit zum Versenden",
    12: "Gesendet",
    15: "Erhalten",
    18: "Bereit",
    21: "Defekt",
    24: "Abgelehnt",
    27: "Archiviert",
}


# -------------------------
# Datenbank-Zugriff
# -------------------------
def _esc(value: str) -> str:
    """Escaped einen Textwert fuer MySQL und weist alles Unerwartete ab."""
    if not isinstance(value, str):
        raise McpError("Textwert erwartet", code=-32602)
    cleaned = value.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')
    cleaned = "".join(ch for ch in cleaned if ord(ch) >= 32)
    if ";" in cleaned or "--" in cleaned or "/*" in cleaned:
        raise McpError("Unzulaessige Zeichen im Wert", code=-32602)
    return cleaned


def _like(value: str) -> str:
    return f"%{_esc(value.strip())}%"


def _num(value: Any, name: str = "Wert") -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise McpError(f"{name} muss eine ganze Zahl sein", code=-32602) from exc


def _limit(value: Any, default: int = MAX_ROWS) -> int:
    return max(1, min(_num(value, "limit"), HARD_LIMIT))


async def db(query: str) -> list[dict]:
    """Fuehrt genau eine vorbereitete Abfrage ueber die MySQL-Verbindung aus."""
    api_key = get_contextvars().get("codewords_api_key")
    if not api_key:
        api_key = os.environ["CODEWORDS_API_KEY"]

    async with AsyncCodewordsClient(api_key=api_key) as client:
        try:
            response = await client.run(
                service_id="pipedream",
                correlation_id=get_contextvars().get("correlation_id"),
                in_background=False,
                inputs={
                    "app": "mysql",
                    "action": "execute-raw-query",
                    "props": {"sql": {"query": query}},
                },
            )
        except httpx.HTTPError as exc:
            logger.error("Datenbank-Aufruf fehlgeschlagen", error=str(exc)[:300])
            raise McpError(f"Datenbank nicht erreichbar: {str(exc)[:180]}", code=-32603) from exc

    if response.status_code != 200:
        logger.error("Datenbank-Aufruf Status", status=response.status_code, body=response.text[:240])
        raise McpError(f"Datenbankfehler: {response.text[:180]}", code=-32603)

    payload = response.json()
    if not isinstance(payload, dict):
        return []
    if payload.get("status") not in (None, "ok"):
        raise McpError(f"Abfrage abgelehnt: {str(payload.get('error'))[:160]}", code=-32603)
    result = payload.get("ret")
    return result if isinstance(result, list) else []


async def _kandidat_oder_fehler(kandidat_id: int) -> dict:
    rows = await db(
        "SELECT kandidat_id, kandidat_ime, kandidat_prezime FROM idk_kandidati "
        f"WHERE kandidat_id = {kandidat_id} LIMIT 1"
    )
    if not rows:
        raise McpError(f"Kandidat {kandidat_id} existiert nicht", code=-32602)
    return rows[0]


async def _dokumenttyp(doc_type_id: int) -> dict:
    rows = await db(
        "SELECT doc_type_id, doc_type_name, doc_type_name_de FROM idk_pp_document_types "
        f"WHERE doc_type_id = {doc_type_id} LIMIT 1"
    )
    if not rows:
        raise McpError(f"Dokumenttyp {doc_type_id} existiert nicht", code=-32602)
    return rows[0]


# -------------------------
# MCP Tools - Nachschauen
# -------------------------
@fast_app.tool()
async def kandidat_identifizieren(
    suchbegriff: Annotated[str, Field(description="Telefonnummer, E-Mail-Adresse oder Kandidatennummer", min_length=2, max_length=80)],
    limit: Annotated[int, Field(description="Maximale Trefferzahl", ge=1, le=10)] = 5,
) -> dict[str, Any]:
    """Kandidat anhand von Telefon, E-Mail oder Kandidatennummer finden.

    Immer zuerst aufrufen, wenn eine Nachricht eingeht und unklar ist, wer schreibt.
    Liefert hoechstens zehn Treffer mit Kandidatennummer, Name, Kontakt und Status.
    """
    term = _esc(suchbegriff.strip())
    digits = "".join(ch for ch in term if ch.isdigit())
    clauses = [
        f"kandidat_mobitel LIKE '{_like(term)}'",
        f"kandidat_email LIKE '{_like(term)}'",
    ]
    if digits:
        clauses.append(f"kandidat_id = {int(digits)}")
        clauses.append(f"kandidat_mobitel LIKE '%{digits}%'")

    rows = await db(
        "SELECT kandidat_id, kandidat_ime, kandidat_prezime, kandidat_email, kandidat_mobitel, "
        "kandidat_status FROM idk_kandidati WHERE " + " OR ".join(clauses)
        + f" ORDER BY kandidat_id DESC LIMIT {int(limit)}"
    )
    return {"success": True, "anzahl": len(rows), "treffer": rows}


@fast_app.tool()
async def kandidat_profil(
    kandidat_id: Annotated[int, Field(description="Kandidatennummer im CRM")],
) -> dict[str, Any]:
    """Profil eines Kandidaten fuer das Gespraech: Kontakt, Status, Auftrag, Fristen.

    Enthaelt bewusst kein Passwort, keine JMBG und keine Passnummer.
    """
    kid = _num(kandidat_id, "kandidat_id")
    rows = await db(
        "SELECT k.kandidat_id, k.kandidat_ime, k.kandidat_prezime, k.kandidat_email, "
        "k.kandidat_mobitel, k.kandidat_grad, k.kandidat_drzava, k.kandidat_status, "
        "s.status_naziv, k.kandidat_nalog_id, n.nalog_naziv, k.kandidat_pp_pozicija, "
        "k.kandidat_viza_vrijedi_do, k.kandidat_datum_ugovora, k.kandidat_datum_pocetakrada "
        "FROM idk_kandidati k "
        "LEFT JOIN idk_kandidat_status s ON s.status_id = k.kandidat_status "
        "LEFT JOIN idk_nalozi n ON n.nalog_id = k.kandidat_nalog_id "
        f"WHERE k.kandidat_id = {kid} LIMIT 1"
    )
    if not rows:
        raise McpError(f"Kandidat {kid} existiert nicht", code=-32602)
    return {"success": True, "profil": rows[0]}


@fast_app.tool()
async def unterlagen_soll(
    kandidat_id: Annotated[int, Field(description="Kandidatennummer im CRM")],
    nalog_id: Annotated[int | None, Field(description="Auftrag; leer = Auftrag des Kandidaten")] = None,
) -> dict[str, Any]:
    """Soll-Ist-Abgleich der Pflichtunterlagen: was der Auftrag verlangt und was vorliegt.

    Je Unterlage: Typ, kroatischer und deutscher Name, Anzahl vorhandener Dokumente
    und der erreichte Status. Genau hieraus ergibt sich, wonach der Agent fragen muss.
    """
    kid = _num(kandidat_id, "kandidat_id")
    if nalog_id is None:
        rows = await db(f"SELECT kandidat_nalog_id FROM idk_kandidati WHERE kandidat_id = {kid} LIMIT 1")
        if not rows or not rows[0].get("kandidat_nalog_id"):
            raise McpError("Kandidat hat keinen Auftrag; bitte nalog_id angeben", code=-32602)
        nid = _num(rows[0]["kandidat_nalog_id"], "nalog_id")
    else:
        nid = _num(nalog_id, "nalog_id")

    erforderlich = await db(
        "SELECT d.nrd_id, d.nrd_type_id, t.doc_type_name, t.doc_type_name_de "
        "FROM idk_pp_nalog_required_documents d "
        "LEFT JOIN idk_pp_document_types t ON t.doc_type_id = d.nrd_type_id "
        f"WHERE d.nrd_nalog_id = {nid} AND d.nrd_status = 1 "
        "ORDER BY t.doc_type_name LIMIT 60"
    )
    vorhanden = await db(
        "SELECT doc_nrd_id, COUNT(*) anzahl, MAX(doc_status) status "
        "FROM idk_pp_documents "
        f"WHERE doc_candidate_id = {kid} AND doc_nalog_id = {nid} GROUP BY doc_nrd_id LIMIT 200"
    )
    ist = {r["doc_nrd_id"]: r for r in vorhanden}

    liste = []
    for eintrag in erforderlich:
        treffer = ist.get(eintrag["nrd_id"], {})
        status = treffer.get("status")
        liste.append(
            {
                "nrd_id": eintrag["nrd_id"],
                "doc_type_id": eintrag["nrd_type_id"],
                "name": eintrag["doc_type_name"],
                "name_de": eintrag["doc_type_name_de"],
                "dokumente": treffer.get("anzahl", 0),
                "status": status,
                "status_name": DOC_STATUS.get(status, "—") if status else "fehlt",
                "fehlt": treffer.get("anzahl", 0) == 0,
            }
        )
    fehlend = [x for x in liste if x["fehlt"]]
    return {
        "success": True,
        "kandidat_id": kid,
        "nalog_id": nid,
        "pflicht_gesamt": len(liste),
        "fehlend_anzahl": len(fehlend),
        "unterlagen": liste,
    }


@fast_app.tool()
async def unterlagen_katalog(
    limit: Annotated[int, Field(description="Maximale Anzahl Typen", ge=1, le=200)] = MAX_ROWS,
) -> dict[str, Any]:
    """Alle Dokumenttypen mit kroatischem und deutschem Namen.

    Aufrufen, bevor eine Unterlage angelegt oder angefordert wird — damit der Agent
    die richtige doc_type_id waehlt und nicht raet.
    """
    rows = await db(
        "SELECT doc_type_id, doc_type_name, doc_type_name_de FROM idk_pp_document_types "
        f"ORDER BY doc_type_name LIMIT {_limit(limit)}"
    )
    return {"success": True, "anzahl": len(rows), "typen": rows}


@fast_app.tool()
async def job_details(
    nalog_id: Annotated[int, Field(description="Auftragsnummer im CRM")],
) -> dict[str, Any]:
    """Einzelheiten eines Auftrags: Position, Ort, Konditionen, Status, Bedarf."""
    nid = _num(nalog_id, "nalog_id")
    rows = await db(
        "SELECT nalog_id, nalog_broj, nalog_naziv, nalog_opis, nalog_status, "
        "nalog_potrebno_kandidata, nalog_partner_app_location, nalog_partner_app_salary, "
        "nalog_created FROM (SELECT nalog_id, nalog_broj, nalog_naziv, nalog_opis, nalog_status, "
        "nalog_potrebno_kandidata, nalog_partner_app_location, nalog_partner_app_salary, "
        "nalog_kreirano AS nalog_created FROM idk_nalozi) t "
        f"WHERE nalog_id = {nid} LIMIT 1"
    )
    if not rows:
        raise McpError(f"Auftrag {nid} existiert nicht", code=-32602)
    return {"success": True, "auftrag": rows[0]}


@fast_app.tool()
async def jobs_fuer_kandidat(
    kandidat_id: Annotated[int, Field(description="Kandidatennummer im CRM")],
    status_ids: Annotated[list[int], Field(description="Nur diese Auftrags-Status (leer = alle)")] = [],
    limit: Annotated[int, Field(description="Maximale Trefferzahl", ge=1, le=25)] = 10,
) -> dict[str, Any]:
    """Offene Auftraege, die zur Position des Kandidaten passen.

    Vergleicht die hinterlegte Position des Kandidaten mit Auftragsname und -beschreibung.
    Ohne passende Position kommen die neuesten Auftraege zurueck.
    """
    kid = _num(kandidat_id, "kandidat_id")
    profil = await db(
        f"SELECT kandidat_pp_pozicija FROM idk_kandidati WHERE kandidat_id = {kid} LIMIT 1"
    )
    position = (profil[0].get("kandidat_pp_pozicija") or "").strip() if profil else ""

    where = ""
    if status_ids:
        ids = ", ".join(str(_num(x, "status_id")) for x in status_ids[:12])
        where = f" WHERE nalog_status IN ({ids})"
    if position:
        passung = f"nalog_naziv LIKE '{_like(position)}' OR nalog_opis LIKE '{_like(position)}'"
        where = f"{where} AND ({passung})" if where else f" WHERE ({passung})"

    rows = await db(
        "SELECT nalog_id, nalog_naziv, nalog_status, nalog_partner_app_location, "
        "nalog_partner_app_salary, nalog_kreirano FROM idk_nalozi"
        f"{where} ORDER BY nalog_kreirano DESC LIMIT {_limit(limit, 10)}"
    )
    return {
        "success": True,
        "position_des_kandidaten": position or None,
        "anzahl": len(rows),
        "auftraege": rows,
    }


@fast_app.tool()
async def unterlage_verlauf(
    doc_id: Annotated[int, Field(description="Dokumentnummer im CRM")],
) -> dict[str, Any]:
    """Verlauf einer Unterlage: aktueller Stand und alle Statuswechsel mit Kommentar."""
    did = _num(doc_id, "doc_id")
    doc = await db(
        "SELECT doc_id, doc_file_name, doc_candidate_id, doc_nalog_id, doc_status "
        f"FROM idk_pp_documents WHERE doc_id = {did} LIMIT 1"
    )
    if not doc:
        raise McpError(f"Dokument {did} existiert nicht", code=-32602)
    verlauf = await db(
        "SELECT dsl_doc_status, dsl_date, dsl_comment FROM idk_pp_documents_status_logs "
        f"WHERE dsl_doc_id = {did} ORDER BY dsl_date DESC LIMIT 50"
    )
    for eintrag in verlauf:
        eintrag["status_name"] = DOC_STATUS.get(eintrag.get("dsl_doc_status"), "—")
    return {"success": True, "dokument": doc[0], "verlauf": verlauf}


@fast_app.tool()
async def kandidat_lebenslauf(
    kandidat_id: Annotated[int, Field(description="Kandidatennummer im CRM")],
) -> dict[str, Any]:
    """Vollstaendiger Lebenslauf: Ausbildung, Berufserfahrung, Sprachen, Kenntnisse, CV-Dateien.

    Alle Angaben stammen aus den hinterlegten Kandidatenprofilen. Enthaelt keine Fotos,
    Ausweis- oder Passnummern.
    """
    kid = _num(kandidat_id, "kandidat_id")
    await _kandidat_oder_fehler(kid)

    ausbildung, erfahrung, sprachen, kenntnisse, cv, akademie, kontakt = await asyncio.gather(
        db(
            "SELECT ke_naziv, ke_naziv_de, ke_naziv_kvalifikacije, ke_grad, ke_drzava, "
            "ke_datumod, ke_datumdo, ke_aktuelno FROM idk_kandidat_edukacija "
            f"WHERE ke_kandidat_id = {kid} ORDER BY ke_orderid LIMIT 30"
        ),
        db(
            "SELECT kri_pozicija, kri_pozicija_de, kri_naziv, kri_grad, kri_drzava, "
            "kri_darum_od, kri_datum_do, kri_aktuelno FROM idk_kandidat_radno_iskustvo "
            f"WHERE kri_kandidat_id = {kid} ORDER BY kri_order LIMIT 30"
        ),
        db(
            "SELECT kj_naziv, kj_slusanje, kj_citanje, kj_govorna_interakcija, "
            "kj_govorna_produkcija, kj_pisanje FROM idk_kandidat_jezici "
            f"WHERE kj_kandidatid = {kid} LIMIT 20"
        ),
        db(
            "SELECT kv_naziv, kv_opis FROM idk_kandidat_vjestine "
            f"WHERE kv_kandidat_id = {kid} LIMIT 40"
        ),
        db(
            f"SELECT kcv_ba, kcv_de FROM idk_kandidat_cv WHERE kcv_kandidatid = {kid} LIMIT 5"
        ),
        db(
            "SELECT ka_status, ka_date_from, ka_date_to, ka_note, ka_rating FROM idk_kandidat_akademija "
            f"WHERE ka_kandidat_id = {kid} LIMIT 10"
        ),
        db(
            "SELECT kki_naziv, kki_naziv_de, kki_podatak, kki_grupa FROM idk_kandidat_kontakt_info "
            f"WHERE kki_kandidat_id = {kid} ORDER BY kki_orderid LIMIT 30"
        ),
    )
    return {
        "success": True,
        "kandidat_id": kid,
        "ausbildung": ausbildung,
        "berufserfahrung": erfahrung,
        "sprachen": sprachen,
        "kenntnisse": kenntnisse,
        "cv_dateien": cv,
        "akademie": akademie,
        "weitere_kontaktdaten": kontakt,
        "hinweis": "Leere Listen bedeuten: im Profil nicht gepflegt.",
    }


@fast_app.tool()
async def kandidat_dokumente(
    kandidat_id: Annotated[int, Field(description="Kandidatennummer im CRM")],
    limit: Annotated[int, Field(description="Maximale Anzahl je Liste", ge=1, le=100)] = 40,
) -> dict[str, Any]:
    """Alle Dokumente eines Kandidaten: Akten-Dateien und Unterlagen des Verfahrens.

    Zeigt je Dokument Name, Dateiverweis, Zeitpunkt und — bei Verfahrensunterlagen —
    Status und Unterlagentyp.
    """
    kid = _num(kandidat_id, "kandidat_id")
    grenze = _limit(limit, 40)
    await _kandidat_oder_fehler(kid)

    akte, verfahren = await asyncio.gather(
        db(
            "SELECT document_name, document_desc, document_file, document_icon, document_datetime "
            f"FROM idk_documents WHERE document_dataid = {kid} AND document_group = 2 "
            f"ORDER BY document_datetime DESC LIMIT {grenze}"
        ),
        db(
            "SELECT p.doc_id, p.doc_status, p.doc_file_name, p.doc_nalog_id, t.doc_type_name, "
            "t.doc_type_name_de FROM idk_pp_documents p "
            "LEFT JOIN idk_pp_nalog_required_documents r ON r.nrd_id = p.doc_nrd_id "
            "LEFT JOIN idk_pp_document_types t ON t.doc_type_id = r.nrd_type_id "
            f"WHERE p.doc_candidate_id = {kid} ORDER BY p.doc_id DESC LIMIT {grenze}"
        ),
    )
    for eintrag in verfahren:
        eintrag["status_name"] = DOC_STATUS.get(eintrag.get("doc_status"), "—")
    return {
        "success": True,
        "kandidat_id": kid,
        "dateien_in_der_akte": akte,
        "unterlagen_verfahren": verfahren,
        "anzahl_akte": len(akte),
        "anzahl_verfahren": len(verfahren),
    }


@fast_app.tool()
async def kandidat_notizen(
    kandidat_id: Annotated[int, Field(description="Kandidatennummer im CRM")],
    limit: Annotated[int, Field(description="Maximale Anzahl", ge=1, le=100)] = 30,
) -> dict[str, Any]:
    """Alle Notizen eines Kandidaten, neueste zuerst.

    Notizen mit dem Praefix 'Agent:' stammen vom Assistenten, alle anderen von Mitarbeitern.
    """
    kid = _num(kandidat_id, "kandidat_id")
    await _kandidat_oder_fehler(kid)
    rows = await db(
        "SELECT note_txt, note_datetime, note_employeeid, note_files FROM idk_notes "
        f"WHERE note_dataid = {kid} AND note_group = 2 ORDER BY note_datetime DESC LIMIT {_limit(limit, 30)}"
    )
    for eintrag in rows:
        eintrag["vom_agenten"] = str(eintrag.get("note_txt") or "").startswith("Agent:")
    return {"success": True, "kandidat_id": kid, "anzahl": len(rows), "notizen": rows}


@fast_app.tool()
async def kandidat_vertraege(
    kandidat_id: Annotated[int, Field(description="Kandidatennummer im CRM")],
    limit: Annotated[int, Field(description="Maximale Anzahl", ge=1, le=100)] = 20,
) -> dict[str, Any]:
    """Vertraege und Zahlungen eines Kandidaten.

    Vertraege mit Unterschriftsstand und Auftragsbezug, dazu die erfassten Zahlungen
    mit Betrag und Zahlungsstand.
    """
    kid = _num(kandidat_id, "kandidat_id")
    await _kandidat_oder_fehler(kid)
    vertraege, zahlungen = await asyncio.gather(
        db(
            "SELECT kc_id, kc_file_name, kc_nalog_id, kc_upload_time, kc_signed "
            f"FROM idk_kandidati_contracts WHERE kc_candidate_id = {kid} "
            f"ORDER BY kc_upload_time DESC LIMIT {_limit(limit, 20)}"
        ),
        db(
            "SELECT kf_iznos, kf_placeno, kf_datum, kf_datum_placanja, kf_status, nalog_id "
            f"FROM idk_kandidat_financije WHERE kandidat_id = {kid} "
            f"ORDER BY kf_datum DESC LIMIT {_limit(limit, 20)}"
        ),
    )
    return {
        "success": True,
        "kandidat_id": kid,
        "vertraege": vertraege,
        "zahlungen": zahlungen,
        "anzahl_vertraege": len(vertraege),
        "anzahl_zahlungen": len(zahlungen),
    }


# -------------------------
# MCP Tools - Eintragen
# -------------------------
@fast_app.tool()
async def unterlage_anlegen(
    kandidat_id: Annotated[int, Field(description="Kandidatennummer im CRM")],
    nalog_id: Annotated[int, Field(description="Auftragsnummer im CRM")],
    doc_type_id: Annotated[int, Field(description="Dokumenttyp aus unterlagen_katalog")],
    datei_url: Annotated[str, Field(description="Oeffentliche https-Adresse der abgelegten Datei", min_length=10, max_length=500)],
    doc_status: Annotated[int, Field(description="Startstatus: 3 = Hochgeladen")] = 3,
    nrd_id: Annotated[int | None, Field(description="Pflichtposition, gegen die abgehakt wird")] = None,
    kommentar: Annotated[str, Field(description="Kurzer Hinweis fuer das Team", max_length=500)] = "",
) -> dict[str, Any]:
    """Neue Unterlage eintragen: Dokument, allgemeiner Dateieintrag und Verlaufseintrag.

    Kandidat, Auftrag und Dokumenttyp werden vorher geprueft. Der Dateiverweis muss eine
    oeffentliche https-Adresse sein. Der Link steht zusaetzlich im Verlauf, damit das Team
    ihn im CRM sicher sieht.
    """
    kid = _num(kandidat_id, "kandidat_id")
    nid = _num(nalog_id, "nalog_id")
    tid = _num(doc_type_id, "doc_type_id")
    status = _num(doc_status, "doc_status")
    if status not in DOC_STATUS:
        raise McpError(f"Unbekannter Status {status}; erlaubt: {sorted(DOC_STATUS)}", code=-32602)
    if not datei_url.strip().startswith("https://"):
        raise McpError("datei_url muss mit https:// beginnen", code=-32602)

    await _kandidat_oder_fehler(kid)
    typ = await _dokumenttyp(tid)
    auftrag = await db(f"SELECT nalog_id FROM idk_nalozi WHERE nalog_id = {nid} LIMIT 1")
    if not auftrag:
        raise McpError(f"Auftrag {nid} existiert nicht", code=-32602)

    url = _esc(datei_url.strip())
    name = _esc(str(typ["doc_type_name"] or "Unterlage"))
    ext = url.rsplit(".", 1)[-1].lower()[:5] if "." in url else "bin"
    if nrd_id is not None:
        nrd_feld = _num(nrd_id, "nrd_id")
    else:
        pflicht = await db(
            "SELECT nrd_id FROM idk_pp_nalog_required_documents "
            f"WHERE nrd_nalog_id = {nid} AND nrd_type_id = {tid} AND nrd_status = 1 LIMIT 1"
        )
        nrd_feld = _num(pflicht[0]["nrd_id"], "nrd_id") if pflicht else "NULL"

    await db(
        "INSERT INTO idk_pp_documents (doc_file_name, doc_candidate_id, doc_nalog_id, doc_nrd_id, doc_status) "
        f"VALUES ('{url}', {kid}, {nid}, {nrd_feld}, {status})"
    )
    neu = await db(
        f"SELECT doc_id FROM idk_pp_documents WHERE doc_candidate_id = {kid} ORDER BY doc_id DESC LIMIT 1"
    )
    if not neu:
        raise McpError("Dokument wurde angelegt, Nummer konnte nicht gelesen werden", code=-32603)
    doc_id = _num(neu[0]["doc_id"], "doc_id")

    await db(
        "INSERT INTO idk_documents (document_name, document_desc, document_file, document_icon, "
        "document_datetime, document_group, document_dataid, document_employeeid) "
        f"VALUES ('{name}', '{_esc(kommentar)}', '{url}', '{_esc(ext)}', NOW(), 2, {kid}, 0)"
    )

    log_text = f"Agent: Unterlage angelegt ({DOC_STATUS[status]}). Datei: {url}"
    if kommentar:
        log_text += f" | {kommentar}"
    await db(
        "INSERT INTO idk_pp_documents_status_logs "
        "(dsl_doc_id, dsl_doc_status, dsl_date, dsl_user_id, dsl_days_count, dsl_comment) "
        f"VALUES ({doc_id}, {status}, NOW(), 0, 0, '{_esc(log_text)[:900]}')"
    )

    logger.info("Unterlage angelegt", doc_id=doc_id, kandidat_id=kid, doc_type_id=tid)
    return {
        "success": True,
        "doc_id": doc_id,
        "kandidat_id": kid,
        "nalog_id": nid,
        "unterlagentyp": typ["doc_type_name"],
        "status": DOC_STATUS[status],
        "datei_url": datei_url.strip(),
        "hinweis": "Datei liegt im Speicher; der Link steht im Verlaufseintrag des CRM.",
    }


@fast_app.tool()
async def unterlage_status_setzen(
    doc_id: Annotated[int, Field(description="Dokumentnummer im CRM")],
    status_id: Annotated[int, Field(description="Zielstatus aus der Statusleiter")],
    kommentar: Annotated[str, Field(description="Begruendung fuer das Team", max_length=500)] = "",
) -> dict[str, Any]:
    """Status einer Unterlage setzen und den Wechsel im Verlauf protokollieren.

    Erlaubte Werte: 3 Hochgeladen, 6 Geprueft, 9 Bereit zum Versenden, 12 Gesendet,
    15 Erhalten, 18 Bereit, 21 Defekt, 24 Abgelehnt, 27 Archiviert.
    """
    did = _num(doc_id, "doc_id")
    status = _num(status_id, "status_id")
    if status not in DOC_STATUS:
        raise McpError(f"Unbekannter Status {status}; erlaubt: {sorted(DOC_STATUS)}", code=-32602)

    doc = await db(f"SELECT doc_id, doc_status FROM idk_pp_documents WHERE doc_id = {did} LIMIT 1")
    if not doc:
        raise McpError(f"Dokument {did} existiert nicht", code=-32602)

    await db(f"UPDATE idk_pp_documents SET doc_status = {status} WHERE doc_id = {did} LIMIT 1")
    log_text = f"Agent: Status gesetzt auf {DOC_STATUS[status]}"
    if kommentar:
        log_text += f" | {kommentar}"
    await db(
        "INSERT INTO idk_pp_documents_status_logs "
        "(dsl_doc_id, dsl_doc_status, dsl_date, dsl_user_id, dsl_days_count, dsl_comment) "
        f"VALUES ({did}, {status}, NOW(), 0, 0, '{_esc(log_text)[:900]}')"
    )
    return {
        "success": True,
        "doc_id": did,
        "vorher": DOC_STATUS.get(doc[0].get("doc_status"), str(doc[0].get("doc_status"))),
        "nachher": DOC_STATUS[status],
    }


@fast_app.tool()
async def unterlage_anfordern(
    kandidat_id: Annotated[int, Field(description="Kandidatennummer im CRM")],
    nalog_id: Annotated[int, Field(description="Auftragsnummer im CRM")],
    doc_type_id: Annotated[int, Field(description="Dokumenttyp aus unterlagen_katalog")],
    kanal: Annotated[Literal["whatsapp", "web", "sms", "email"], Field(description="Ueber welchen Kanal angefragt wurde")] = "whatsapp",
    frist_tage: Annotated[int, Field(description="Frist in Tagen", ge=1, le=60)] = 3,
    kommentar: Annotated[str, Field(description="Wortlaut oder Hinweis", max_length=400)] = "",
) -> dict[str, Any]:
    """Festhalten, dass eine Unterlage angefordert wurde — Grundlage fuers Nachfassen.

    Schreibt einen datierten Eintrag in die Kandidatennotizen.
    """
    kid = _num(kandidat_id, "kandidat_id")
    nid = _num(nalog_id, "nalog_id")
    tid = _num(doc_type_id, "doc_type_id")
    tage = _num(frist_tage, "frist_tage")
    await _kandidat_oder_fehler(kid)
    typ = await _dokumenttyp(tid)

    text = (
        f"Agent: Unterlage angefordert — {typ['doc_type_name']} ({typ['doc_type_name_de']}), "
        f"Auftrag {nid}, Kanal {kanal}, Frist {tage} Tage"
    )
    if kommentar:
        text += f" | {kommentar}"

    await db(
        "INSERT INTO idk_notes (note_txt, note_files, note_datetime, note_group, note_dataid, note_employeeid) "
        f"VALUES ('{_esc(text)[:900]}', NULL, NOW(), 2, {kid}, 0)"
    )
    return {"success": True, "kandidat_id": kid, "doc_type_id": tid, "kanal": kanal, "frist_tage": tage}


@fast_app.tool()
async def notiz_anlegen(
    kandidat_id: Annotated[int, Field(description="Kandidatennummer im CRM")],
    text: Annotated[str, Field(description="Inhalt der Notiz", min_length=3, max_length=900)],
) -> dict[str, Any]:
    """Gespraechsnotiz am Kandidaten ablegen."""
    kid = _num(kandidat_id, "kandidat_id")
    await _kandidat_oder_fehler(kid)
    await db(
        "INSERT INTO idk_notes (note_txt, note_files, note_datetime, note_group, note_dataid, note_employeeid) "
        f"VALUES ('{_esc(text.strip())[:900]}', NULL, NOW(), 2, {kid}, 0)"
    )
    return {"success": True, "kandidat_id": kid}


@fast_app.tool()
async def kontakt_korrigieren(
    kandidat_id: Annotated[int, Field(description="Kandidatennummer im CRM")],
    telefon: Annotated[str | None, Field(description="Neue Telefonnummer", max_length=40)] = None,
    email: Annotated[str | None, Field(description="Neue E-Mail-Adresse", max_length=120)] = None,
) -> dict[str, Any]:
    """Telefon oder E-Mail eines Kandidaten berichtigen — nur diese beiden Felder.

    Mindestens ein Wert ist erforderlich. Andere Felder koennen nicht geaendert werden.
    """
    kid = _num(kandidat_id, "kandidat_id")
    if not telefon and not email:
        raise McpError("Bitte telefon oder email angeben", code=-32602)
    if email and "@" not in email:
        raise McpError("E-Mail-Adresse ungueltig", code=-32602)

    await _kandidat_oder_fehler(kid)
    aenderungen = []
    if telefon:
        aenderungen.append(f"kandidat_mobitel = '{_esc(telefon.strip())}'")
    if email:
        aenderungen.append(f"kandidat_email = '{_esc(email.strip())}'")
    await db(f"UPDATE idk_kandidati SET {', '.join(aenderungen)} WHERE kandidat_id = {kid} LIMIT 1")
    return {"success": True, "kandidat_id": kid, "geaendert": [a.split(" =")[0] for a in aenderungen]}


# -------------------------
# MCP Tools - Dateien
# -------------------------
@fast_app.tool()
async def datei_pruefen(
    datei_url: Annotated[str, Field(description="Oeffentliche https-Adresse der abgelegten Datei", min_length=10, max_length=500)],
) -> dict[str, Any]:
    """Dateiverweis pruefen, bevor er eingetragen wird.

    Ruft die Adresse ab und meldet, ob sie erreichbar ist, welcher Inhaltstyp geliefert wird
    und wie gross die Datei ist. Verhindert tote Verweise in der Akte.
    """
    url = datei_url.strip()
    if not url.startswith("https://"):
        raise McpError("datei_url muss mit https:// beginnen", code=-32602)

    async with httpx.AsyncClient(follow_redirects=True, timeout=20.0) as client:
        try:
            antwort = await client.get(url)
        except httpx.HTTPError as exc:
            raise McpError(f"Adresse nicht erreichbar: {str(exc)[:150]}", code=-32603) from exc

    inhaltstyp = antwort.headers.get("content-type", "unbekannt")
    brauchbar = antwort.status_code == 200 and len(antwort.content) > 0
    return {
        "success": True,
        "erreichbar": brauchbar,
        "http_status": antwort.status_code,
        "inhaltstyp": inhaltstyp,
        "bytes": len(antwort.content),
        "hinweis": "Bei erreichbar=true kann die Adresse an unterlage_anlegen oder datei_bestaetigen gehen.",
    }


@fast_app.tool()
async def datei_bestaetigen(
    doc_id: Annotated[int, Field(description="Dokumentnummer im CRM")],
    datei_url: Annotated[str, Field(description="Oeffentliche https-Adresse der Datei", min_length=10, max_length=500)],
    kommentar: Annotated[str, Field(description="Kurzer Hinweis", max_length=300)] = "",
) -> dict[str, Any]:
    """Dateiverweis einer bestehenden Unterlage nachtragen und protokollieren."""
    did = _num(doc_id, "doc_id")
    if not datei_url.strip().startswith("https://"):
        raise McpError("datei_url muss mit https:// beginnen", code=-32602)
    doc = await db(f"SELECT doc_id, doc_candidate_id FROM idk_pp_documents WHERE doc_id = {did} LIMIT 1")
    if not doc:
        raise McpError(f"Dokument {did} existiert nicht", code=-32602)

    url = _esc(datei_url.strip())
    await db(f"UPDATE idk_pp_documents SET doc_file_name = '{url}' WHERE doc_id = {did} LIMIT 1")
    log_text = f"Agent: Datei hinterlegt. Datei: {url}"
    if kommentar:
        log_text += f" | {kommentar}"
    await db(
        "INSERT INTO idk_pp_documents_status_logs "
        "(dsl_doc_id, dsl_doc_status, dsl_date, dsl_user_id, dsl_days_count, dsl_comment) "
        f"SELECT {did}, doc_status, NOW(), 0, 0, '{_esc(log_text)[:900]}' "
        f"FROM idk_pp_documents WHERE doc_id = {did}"
    )
    return {"success": True, "doc_id": did, "datei_url": datei_url.strip()}


# -------------------------
# Werkzeug-Definitionen fuer Function / Tool Calling
# -------------------------
def _p(desc: str, typ: str = "string") -> dict[str, Any]:
    return {"type": typ, "description": desc}


def _spec(name: str, desc: str, props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": desc,
            "parameters": {
                "type": "object",
                "properties": props,
                "required": required or [],
                "additionalProperties": False,
            },
        },
    }


TOOL_SPECS: list[dict[str, Any]] = [
    _spec(
        "kandidat_identifizieren",
        "Kandidat anhand von Telefon, E-Mail oder Kandidatennummer finden. Immer zuerst aufrufen, "
        "wenn unklar ist, wer schreibt.",
        {"suchbegriff": _p("Telefonnummer, E-Mail oder Kandidatennummer"), "limit": _p("Max. Treffer 1-10", "integer")},
        ["suchbegriff"],
    ),
    _spec(
        "kandidat_profil",
        "Profil eines Kandidaten: Kontakt, Status, Auftrag, Fristen. Ohne Passwort und Ausweisnummern.",
        {"kandidat_id": _p("Kandidatennummer im CRM", "integer")},
        ["kandidat_id"],
    ),
    _spec(
        "unterlagen_soll",
        "Soll-Ist-Abgleich: welche Unterlagen der Auftrag verlangt und welche vorliegen. "
        "Zeigt je Unterlage, ob sie fehlt.",
        {"kandidat_id": _p("Kandidatennummer", "integer"), "nalog_id": _p("Auftrag; leer = Auftrag des Kandidaten", "integer")},
        ["kandidat_id"],
    ),
    _spec(
        "unterlagen_katalog",
        "Alle Dokumenttypen mit kroatischem und deutschem Namen. Vor dem Anlegen oder Anfordern aufrufen.",
        {"limit": _p("Max. Anzahl 1-200", "integer")},
    ),
    _spec(
        "job_details",
        "Einzelheiten eines Auftrags: Position, Ort, Konditionen, Status, Bedarf.",
        {"nalog_id": _p("Auftragsnummer im CRM", "integer")},
        ["nalog_id"],
    ),
    _spec(
        "jobs_fuer_kandidat",
        "Auftraege, die zur hinterlegten Position des Kandidaten passen.",
        {
            "kandidat_id": _p("Kandidatennummer", "integer"),
            "status_ids": {"type": "array", "items": {"type": "integer"}, "description": "Nur diese Auftrags-Status"},
            "limit": _p("Max. Treffer 1-25", "integer"),
        },
        ["kandidat_id"],
    ),
    _spec(
        "unterlage_verlauf",
        "Verlauf einer Unterlage: aktueller Status und alle Wechsel mit Kommentar.",
        {"doc_id": _p("Dokumentnummer im CRM", "integer")},
        ["doc_id"],
    ),
    _spec(
        "kandidat_lebenslauf",
        "Vollstaendiger Lebenslauf: Ausbildung, Berufserfahrung, Sprachen, Kenntnisse, CV-Dateien.",
        {"kandidat_id": _p("Kandidatennummer im CRM", "integer")},
        ["kandidat_id"],
    ),
    _spec(
        "kandidat_dokumente",
        "Alle Dokumente eines Kandidaten: Akten-Dateien und Unterlagen des Verfahrens mit Status.",
        {"kandidat_id": _p("Kandidatennummer", "integer"), "limit": _p("Max. Anzahl je Liste 1-100", "integer")},
        ["kandidat_id"],
    ),
    _spec(
        "kandidat_notizen",
        "Alle Notizen eines Kandidaten, neueste zuerst; Agent-Eintraege sind markiert.",
        {"kandidat_id": _p("Kandidatennummer", "integer"), "limit": _p("Max. Anzahl 1-100", "integer")},
        ["kandidat_id"],
    ),
    _spec(
        "kandidat_vertraege",
        "Vertraege mit Unterschriftsstand und erfasste Zahlungen eines Kandidaten.",
        {"kandidat_id": _p("Kandidatennummer", "integer"), "limit": _p("Max. Anzahl je Liste 1-100", "integer")},
        ["kandidat_id"],
    ),
    _spec(
        "unterlage_anlegen",
        "Neue Unterlage eintragen: Dokument, allgemeiner Dateieintrag und Verlaufseintrag in einem Schritt.",
        {
            "kandidat_id": _p("Kandidatennummer", "integer"),
            "nalog_id": _p("Auftragsnummer", "integer"),
            "doc_type_id": _p("Dokumenttyp aus unterlagen_katalog", "integer"),
            "datei_url": _p("Oeffentliche https-Adresse der Datei"),
            "doc_status": _p("Startstatus, Standard 3 = Hochgeladen", "integer"),
            "nrd_id": _p("Pflichtposition, gegen die abgehakt wird", "integer"),
            "kommentar": _p("Kurzer Hinweis fuer das Team"),
        },
        ["kandidat_id", "nalog_id", "doc_type_id", "datei_url"],
    ),
    _spec(
        "unterlage_status_setzen",
        "Status einer Unterlage setzen und im Verlauf protokollieren. Erlaubt: 3, 6, 9, 12, 15, 18, 21, 24, 27.",
        {
            "doc_id": _p("Dokumentnummer", "integer"),
            "status_id": _p("Zielstatus", "integer"),
            "kommentar": _p("Begruendung fuer das Team"),
        },
        ["doc_id", "status_id"],
    ),
    _spec(
        "unterlage_anfordern",
        "Festhalten, dass eine Unterlage angefordert wurde — Grundlage fuers Nachfassen.",
        {
            "kandidat_id": _p("Kandidatennummer", "integer"),
            "nalog_id": _p("Auftragsnummer", "integer"),
            "doc_type_id": _p("Dokumenttyp", "integer"),
            "kanal": {"type": "string", "enum": ["whatsapp", "web", "sms", "email"], "description": "Kanal der Anfrage"},
            "frist_tage": _p("Frist in Tagen 1-60", "integer"),
            "kommentar": _p("Wortlaut oder Hinweis"),
        },
        ["kandidat_id", "nalog_id", "doc_type_id"],
    ),
    _spec(
        "notiz_anlegen",
        "Gespraechsnotiz am Kandidaten ablegen.",
        {"kandidat_id": _p("Kandidatennummer", "integer"), "text": _p("Inhalt der Notiz")},
        ["kandidat_id", "text"],
    ),
    _spec(
        "kontakt_korrigieren",
        "Telefon oder E-Mail eines Kandidaten berichtigen — nur diese beiden Felder.",
        {
            "kandidat_id": _p("Kandidatennummer", "integer"),
            "telefon": _p("Neue Telefonnummer"),
            "email": _p("Neue E-Mail-Adresse"),
        },
        ["kandidat_id"],
    ),
    _spec(
        "datei_pruefen",
        "Dateiverweis pruefen, bevor er eingetragen wird: erreichbar, Inhaltstyp, Groesse.",
        {"datei_url": _p("Oeffentliche https-Adresse der Datei")},
        ["datei_url"],
    ),
    _spec(
        "datei_bestaetigen",
        "Dateiverweis einer bestehenden Unterlage nachtragen und protokollieren.",
        {
            "doc_id": _p("Dokumentnummer", "integer"),
            "datei_url": _p("Oeffentliche https-Adresse der Datei"),
            "kommentar": _p("Kurzer Hinweis"),
        },
        ["doc_id", "datei_url"],
    ),
]


# Verwechslungs-Matrix: welches Paar sich aehnelt und worin es sich unterscheidet.
TOOL_CONFUSION_MATRIX: list[dict[str, str]] = [
    {"paar": "kandidat_identifizieren / kandidat_profil", "trenner": "identifizieren findet die Nummer, profil braucht sie schon"},
    {"paar": "unterlagen_soll / unterlagen_katalog", "trenner": "soll = fuer diesen Kandidaten; katalog = alle Typen"},
    {"paar": "unterlagen_soll / unterlage_verlauf", "trenner": "soll = Liste fehlender Unterlagen; verlauf = Historie einer Unterlage"},
    {"paar": "unterlage_anlegen / unterlage_status_setzen", "trenner": "anlegen erzeugt neu; status_setzen aendert nur Bestehendes"},
    {"paar": "unterlage_anlegen / datei_bestaetigen", "trenner": "anlegen = neuer Datensatz; bestaetigen = Datei an bestehenden Datensatz"},
    {"paar": "datei_pruefen / datei_bestaetigen", "trenner": "pruefen = Adresse testen; bestaetigen = Ergebnis eintragen"},
    {"paar": "unterlage_anfordern / notiz_anlegen", "trenner": "anfordern ist strukturiert (Typ, Kanal, Frist); notiz ist Freitext"},
    {"paar": "job_details / jobs_fuer_kandidat", "trenner": "details = ein Auftrag; jobs_fuer_kandidat = Auswahl fuer eine Person"},
    {"paar": "kandidat_profil / unterlagen_soll", "trenner": "profil = Stammdaten; soll = Unterlagenlage"},
    {"paar": "kontakt_korrigieren / notiz_anlegen", "trenner": "korrigieren schreibt ins Kandidatenfeld; notiz nur in den Verlauf"},
]


# -------------------------
# Ausgelieferte Anleitung (eine Quelle der Wahrheit)
# -------------------------
SKILL_TEXT = r"""---
name: jobstep-candidate-operations
description: Operate the Jobstep recruitment CRM through the Jobstep Candidate MCP. Use whenever a candidate message, an incoming document, a new job order, or a document status question must be handled. Covers candidate identification, required-document reconciliation, document intake, status transitions, notes, contracts and error recovery.
version: 2.0.0
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
9. **Duplicates are the main damage mode.** After any failed write, inspect before retrying.
10. **Silence is not success.** A write is done only when the response contains an id.

## 3. Data model — what sits where

- **Candidate** (`idk_kandidati`, 100 columns): `kandidat_profil` exposes 15 of them.
- **Job order / nalog** (`idk_nalozi`): candidate links via `kandidat_nalog_id`.
- **Required documents** (`idk_pp_nalog_required_documents`): the checklist per order, varying by profile.
- **Document types** (`idk_pp_document_types`): Croatian and German names; its id is `doc_type_id`.
- **Stored document** (`idk_pp_documents`): points at the requirement row via `doc_nrd_id`, at the order, and carries `doc_status`.
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
- **Returns:** per required document `doc_type_id`, names, count, status, `fehlt`; plus `fehlend_anzahl`.
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
- **Returns:** `dateien_in_der_akte` and `unterlagen_verfahren` with type and status names.

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
- **Call when:** a verified file must become a document for a specific candidate and order.
- **Do not call:** without a passing `datei_pruefen`; without a catalogue type; on a duplicate at a worked status.
- **Args:** `kandidat_id`, `nalog_id`, `doc_type_id`, `datei_url`, `doc_status` (default 3), `nrd_id` (optional), `kommentar`.
- **Behaviour:** validates candidate, order and type; resolves the matching requirement row when `nrd_id` is omitted and ticks the checklist; writes document, file entry and a history line containing the URL.
- **Then:** confirm with `doc_id`. Never re-create on a timeout — inspect first.

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
1. kandidat_identifizieren            -> candidate resolved
2. kandidat_dokumente                 -> duplicate check
   - present at status >= 9  -> do NOT duplicate. Report. Stop.
   - absent / defective      -> continue
3. unterlagen_katalog                 -> doc_type_id
   - no plausible type       -> ask the human. Stop.
4. datei_pruefen(datei_url)           -> GATE
   - erreichbar: false       -> request resend + notiz_anlegen. Stop.
   - erreichbar: true        -> continue
5. unterlage_anlegen(candidate, order, type, url)
   - order unknown           -> kandidat_profil.kandidat_nalog_id
     - still null            -> human handoff, do not invent an order
   - success                 -> doc_id returned
6. notiz_anlegen               -> only if the conversation carries information
                                 not already captured by the history line
7. verify                      -> unterlagen_soll: gap closed?
   - not closed              -> do not re-create. Report with doc_id.
```

**No gate, no write. Duplicate beats missing.**

## 7. Decision logic — status workflow

| id | Croatian | German | Rule | Who authorises |
|---|---|---|---|---|
| 3 | Uploadan | Hochgeladen | entry state | agent (automatic) |
| 6 | Provjeren | Geprueft | only after human review | human only |
| 9 | Cekamo original | Bereit zum Versenden | file complete for dispatch | human, or agent after human "ready" |
| 12 | Poslan | Gesendet | only after actual transmission | human, or agent with send confirmation |
| 15 | Imamo original | Erhalten | original physically arrived | human only |
| 18 | Spreman | Bereit | final good state | human |
| 21 | Nije prosao provjeru | Defekt | from 3 or 6 only | agent may flag, human confirms |
| 24 | Odbijen | Abgelehnt | from 3 or 6, reason required | human only |
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
| Timeout / no response | unknown | **inspect** via `kandidat_dokumente` before any retry | once, after inspection |
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
"""


# -------------------------
# Application Factory Pattern
# -------------------------
def create_fastapi_app() -> FastAPI:
    """
    Create FastAPI app with MCP capabilities and CodeWords middleware.

    This converts the FastMCP app to a FastAPI instance while preserving
    all MCP functionality and adding CodeWords integration middleware.
    """
    # Get the Starlette app from FastMCP
    starlette_app = fast_app.streamable_http_app()

    # Create FastAPI app with MCP routes and middleware
    app = FastAPI(
        title="Jobstep Kandidaten-MCP",
        description="Feste Werkzeuge fuer den Kandidaten-Agenten: nachschauen, eintragen, Dateien ablegen.",
        version="1.0.0",
        debug=starlette_app.debug,
        routes=starlette_app.routes,
        middleware=starlette_app.user_middleware,
        lifespan=starlette_app.router.lifespan_context,
    )

    # Add sandbox creation endpoint
    @app.post("/", response_model=SandboxCreationResponse, summary="Create a sandbox with this MCP service")
    async def create_sandbox_fastapi(request: SandboxCreationRequest):
        return await create_sandbox_handler(request)

    @app.get("/skill.md", summary="Anleitung fuer den Agenten")
    async def skill_md():
        """Liefert die Bedienanleitung als Markdown — Werkzeuge und Regeln aus einer Quelle."""
        return PlainTextResponse(SKILL_TEXT, media_type="text/markdown; charset=utf-8")

    @app.get("/health", summary="Status des Dienstes")
    async def health():
        return {"status": "ok", "dienst": "jobstep-mcp", "werkzeuge": len(TOOL_SPECS)}

    werkzeuge = {
        "kandidat_identifizieren": kandidat_identifizieren,
        "kandidat_profil": kandidat_profil,
        "unterlagen_soll": unterlagen_soll,
        "unterlagen_katalog": unterlagen_katalog,
        "job_details": job_details,
        "jobs_fuer_kandidat": jobs_fuer_kandidat,
        "unterlage_verlauf": unterlage_verlauf,
        "kandidat_lebenslauf": kandidat_lebenslauf,
        "kandidat_dokumente": kandidat_dokumente,
        "kandidat_notizen": kandidat_notizen,
        "kandidat_vertraege": kandidat_vertraege,
        "unterlage_anlegen": unterlage_anlegen,
        "unterlage_status_setzen": unterlage_status_setzen,
        "unterlage_anfordern": unterlage_anfordern,
        "notiz_anlegen": notiz_anlegen,
        "kontakt_korrigieren": kontakt_korrigieren,
        "datei_pruefen": datei_pruefen,
        "datei_bestaetigen": datei_bestaetigen,
    }

    _specs_by_name: dict[str, dict[str, Any]] = {}
    for eintrag in TOOL_SPECS:
        try:
            _funktion = eintrag["function"]
            _specs_by_name[_funktion["name"]] = _funktion.get("parameters") or {}
        except (KeyError, TypeError):
            continue

    @app.post("/test/{werkzeug}", summary="Ein Werkzeug einzeln pruefen (Betrieb und Test)")
    async def werkzeug_pruefen(werkzeug: str, argumente: dict[str, Any] | None = None):
        """Ruft ein Werkzeug mit denselben Pruefungen auf wie der Agent — nur ohne MCP-Client.

        Eingabefehler werden mit 400 und klarer Meldung beantwortet, nicht mit 500.
        Unerwartete Fehler werden protokolliert, aber ohne Stacktrace ausgeliefert.
        """
        funktion = werkzeuge.get(werkzeug)
        if funktion is None:
            raise HTTPException(status_code=404, detail=f"Unbekanntes Werkzeug: {werkzeug}")

        parameter = argumente or {}
        if not isinstance(parameter, dict):
            raise HTTPException(
                status_code=400,
                detail="Der Rumpf muss ein JSON-Objekt mit den Werkzeugparametern sein.",
            )

        spezifikation = _specs_by_name.get(werkzeug, {})
        pflicht = spezifikation.get("required") or []
        fehlend = [name for name in pflicht if parameter.get(name) is None]
        if fehlend:
            raise HTTPException(
                status_code=400,
                detail=f"Pflichtparameter fehlt: {', '.join(fehlend)}",
            )

        # Statuswerte vor dem Werkzeugaufruf pruefen — sonst ersetzt die MCP-Bibliothek
        # die klare Meldung durch einen generischen Parameterkonflikt.
        status_wert: Any = None
        if werkzeug == "unterlage_status_setzen":
            status_wert = parameter.get("status_id")
        elif "doc_status" in parameter:
            status_wert = parameter.get("doc_status")
        if status_wert is not None:
            try:
                status_zahl = int(status_wert)
            except (TypeError, ValueError):
                raise HTTPException(
                    status_code=400,
                    detail=f"Status muss eine Zahl sein, erhalten: {status_wert!r}",
                )
            if status_zahl not in DOC_STATUS:
                erlaubt = ", ".join(f"{k} {v}" for k, v in sorted(DOC_STATUS.items()))
                raise HTTPException(
                    status_code=400,
                    detail=f"Unbekannter Status: {status_zahl}. Erlaubt sind: {erlaubt}",
                )

        ziel = getattr(funktion, "fn", funktion)
        logger.info("Werkzeug-Test", werkzeug=werkzeug)
        try:
            return await ziel(**parameter)
        except HTTPException:
            raise
        except ValueError as fehler:
            raise HTTPException(status_code=400, detail=str(fehler) or "Ungueltiger Wert") from fehler
        except TypeError as fehler:
            raise HTTPException(
                status_code=400,
                detail=f"Parameter passen nicht zum Werkzeug '{werkzeug}': {fehler}",
            ) from fehler
        except Exception as fehler:  # noqa: BLE001 - bewusst breit, aber ohne Traceback nach aussen
            logger.error("Werkzeug-Test fehlgeschlagen", werkzeug=werkzeug, fehler=str(fehler))
            raise HTTPException(
                status_code=500,
                detail=f"Dienstfehler bei '{werkzeug}': {type(fehler).__name__}",
            ) from fehler

    @app.get("/tools.json", summary="Werkzeug-Definitionen fuer Function Calling")
    async def tools_json():
        return {"tools": TOOL_SPECS}

    @app.post("/datei", summary="Datei ablegen und oeffentliche Adresse zurueckgeben")
    async def datei_ablegen():
        raise HTTPException(
            status_code=501,
            detail="Dateien werden ueber den Plattform-Speicher abgelegt; bitte die dort erzeugte Adresse verwenden.",
        )

    return app


# -------------------------
# Main Entry Point
# -------------------------
if __name__ == "__main__":
    run_service(create_fastapi_app())
