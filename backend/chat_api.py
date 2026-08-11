import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.db import connection, database_ready
from parser.parser_v04 import parse_message

router = APIRouter(prefix="/v1", tags=["chat-ingest"])


class ChatMessageIn(BaseModel):
    text: str
    source_type: str = "CHAT"
    external_id: str | None = None
    source_uri: str | None = None
    actor: str | None = None
    context_site: str | None = None
    context_vendor: str | None = None
    stage: bool = True


def event_key(payload: ChatMessageIn, parsed: dict[str, Any]) -> str:
    base = {
        "source_type": payload.source_type,
        "external_id": payload.external_id,
        "text": payload.text,
        "event_type": parsed.get("event_type"),
        "site": parsed.get("site") or payload.context_site,
        "vendor": parsed.get("vendor") or payload.context_vendor,
    }
    return "evt:" + hashlib.sha256(json.dumps(base, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


@router.post("/parse-message")
def parse_chat_message(payload: ChatMessageIn) -> dict[str, Any]:
    parsed = parse_message(payload.text)
    if not parsed.get("site") and payload.context_site:
        parsed["site"] = payload.context_site.upper()
    if not parsed.get("vendor") and payload.context_vendor:
        parsed["vendor"] = payload.context_vendor.upper()

    result: dict[str, Any] = {"parsed": parsed, "staged": False}
    if not payload.stage:
        return result
    if not database_ready():
        raise HTTPException(503, "database unavailable")

    key = event_key(payload, parsed)
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into ingest_sources(source_type, external_id, source_uri, source_hash)
                values (%s,%s,%s,%s)
                on conflict (source_type, external_id)
                do update set source_uri=coalesce(excluded.source_uri, ingest_sources.source_uri)
                returning id
                """,
                (payload.source_type, payload.external_id or key, payload.source_uri, key),
            )
            source_id = cur.fetchone()["id"]
            cur.execute(
                """
                insert into candidate_events(
                  event_key, source_id, event_type, site, vendor_code, entity_code,
                  event_time, confidence, requires_confirmation, payload, raw_text, parser_version
                ) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)
                on conflict (event_key) do nothing
                returning id, status
                """,
                (
                    key,
                    source_id,
                    parsed.get("event_type") or "UNCLASSIFIED",
                    parsed.get("site"),
                    parsed.get("vendor"),
                    parsed.get("counterparty"),
                    datetime.now(timezone.utc),
                    float(parsed.get("confidence") or 0),
                    bool(parsed.get("requires_confirmation", True)),
                    json.dumps(parsed.get("structured_payload") or {}, ensure_ascii=False),
                    parsed.get("raw_text") or payload.text,
                    "parser-v0.4",
                ),
            )
            row = cur.fetchone()
            if row is None:
                cur.execute("select id, status from candidate_events where event_key=%s", (key,))
                row = cur.fetchone()
            conn.commit()

    result.update({"staged": True, "eventId": row["id"], "eventKey": key, "status": row["status"]})
    return result
