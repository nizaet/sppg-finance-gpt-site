from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from backend.db import connection, database_ready
from backend.operational_api import WhatsAppReceiptIn, choose_po, extract_receipt_items, infer_vendor

router = APIRouter(prefix="/whatsapp", tags=["whatsapp-ingress"])

MONTHS_ID = {
    "januari": 1, "februari": 2, "maret": 3, "april": 4, "mei": 5, "juni": 6,
    "juli": 7, "agustus": 8, "september": 9, "oktober": 10, "november": 11, "desember": 12,
}


def require_db() -> None:
    if not database_ready():
        raise HTTPException(503, "database unavailable")


def clean_group_name(value: str | None) -> str:
    text = (value or "").strip()
    text = re.sub(r"^WhatsApp Chat with\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\.txt$", "", text, flags=re.IGNORECASE)
    return " ".join(text.split())


def norm(value: str | None) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).split())


def parse_reported_date(text: str) -> date | None:
    patterns = [
        re.compile(r"\b(\d{1,2})\s+(januari|februari|maret|april|mei|juni|juli|agustus|september|oktober|november|desember)\s+(20\d{2})\b", re.I),
        re.compile(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b"),
    ]
    m = patterns[0].search(text)
    if m:
        try:
            return date(int(m.group(3)), MONTHS_ID[m.group(2).lower()], int(m.group(1)))
        except ValueError:
            return None
    m = patterns[1].search(text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def classify_event(text: str, source_role: str | None) -> tuple[str, list[dict[str, Any]]]:
    items = extract_receipt_items(text or "")
    low = (text or "").lower()
    if (source_role or "").upper() == "RECEIVING" and (items or "barang masuk" in low or "#barang masuk" in low):
        return "RECEIVING_REPORT", items
    if "barang masuk" in low or "#barang masuk" in low:
        return "RECEIVING_REPORT", items
    if re.search(r"\d+(?:[\.,]\d+)?\s*[xX]\s*\d{3,}", text or "") and "total" in low:
        return "VENDOR_INVOICE", items
    return "UNCLASSIFIED_WHATSAPP", items


def resolve_source(cur, source_key: str | None, group_name: str | None) -> dict[str, Any] | None:
    if source_key:
        cur.execute("select * from whatsapp_sources where source_key=%s and active=true", (source_key,))
        return cur.fetchone()
    wanted = norm(clean_group_name(group_name))
    if not wanted:
        return None
    cur.execute("select * from whatsapp_sources where active=true order by id")
    for row in cur.fetchall():
        if norm(row["display_name"]) == wanted:
            return row
    return None


def stable_event_key(provider: str, message_id: str) -> str:
    return "wa-event:" + hashlib.sha256(f"{provider}:{message_id}".encode("utf-8")).hexdigest()


def source_hash(provider: str, message_id: str, raw: dict[str, Any]) -> str:
    canonical = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{provider}:{message_id}:{canonical}".encode("utf-8")).hexdigest()


def verify_signature(raw_body: bytes, signature: str | None) -> None:
    secret = os.getenv("WHATSAPP_APP_SECRET", "").strip()
    if not secret:
        return
    if not signature or not signature.startswith("sha256="):
        raise HTTPException(401, "missing WhatsApp webhook signature")
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    actual = signature.split("=", 1)[1]
    if not hmac.compare_digest(expected, actual):
        raise HTTPException(401, "invalid WhatsApp webhook signature")


def require_ingest_auth(request: Request) -> None:
    ingest_key = os.getenv("WHATSAPP_INGEST_KEY", "").strip()
    bearer_key = os.getenv("SPPG_GPT_API_KEY", "").strip()
    supplied = request.headers.get("x-sppg-webhook-key", "").strip()
    auth = request.headers.get("authorization", "").strip()
    if ingest_key:
        if not hmac.compare_digest(supplied, ingest_key):
            raise HTTPException(401, "invalid WhatsApp ingest key")
        return
    if bearer_key and auth.lower().startswith("bearer "):
        token = auth.split(" ", 1)[1].strip()
        if hmac.compare_digest(token, bearer_key):
            return
    raise HTTPException(503, "WhatsApp ingest authentication is not configured")


class NormalizedWhatsAppIn(BaseModel):
    provider: str = "WHATSAPP"
    message_id: str = Field(min_length=1)
    group_name: str | None = None
    source_key: str | None = None
    sender: str | None = None
    sender_name: str | None = None
    message_type: str = "text"
    text: str = ""
    media_id: str | None = None
    media_mime_type: str | None = None
    media_sha256: str | None = None
    provider_timestamp: datetime | None = None
    reported_date: date | None = None
    corrected_effective_date: date | None = None
    date_correction_reason: str | None = None
    corrected_by: str | None = None
    purchase_order_id: int | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)


def preview_receiving(cur, site: str, text: str, purchase_order_id: int | None, event_time: datetime | None) -> dict[str, Any]:
    reported_items = extract_receipt_items(text)
    if not reported_items:
        return {
            "canCommit": False,
            "reason": "no quantity items could be extracted from text/caption",
            "reportedItems": [],
            "purchaseOrderId": purchase_order_id,
        }
    vendor = infer_vendor(text)
    payload = WhatsAppReceiptIn(
        site=site,
        text=text,
        vendor_code=vendor,
        purchase_order_id=purchase_order_id,
        received_at=event_time,
        commit=False,
    )
    po, matches, score, alternatives = choose_po(cur, payload, reported_items, vendor)
    all_matched = bool(matches) and all(x["matched"] and x["match_confidence"] >= 0.62 for x in matches)
    candidate_clear = purchase_order_id is not None or (
        score >= 0.66 and (len(alternatives) < 2 or score - alternatives[1]["score"] >= 0.06)
    )
    return {
        "canCommit": bool(po and all_matched and candidate_clear),
        "vendorCode": vendor,
        "purchaseOrderId": po["id"] if po else purchase_order_id,
        "poCode": po["po_code"] if po else None,
        "poStatus": po["status"] if po else None,
        "poMatchConfidence": score,
        "reportedItems": reported_items,
        "matches": matches,
        "alternatives": alternatives,
        "requiresConfirmation": True,
    }


def stage_normalized(payload: NormalizedWhatsAppIn) -> dict[str, Any]:
    require_db()
    provider = payload.provider.upper().strip() or "WHATSAPP"
    group_name = clean_group_name(payload.group_name)
    raw_payload = payload.raw_payload or {}
    with connection() as conn:
        with conn.cursor() as cur:
            source = resolve_source(cur, payload.source_key, group_name)
            site = source["site"] if source else None
            source_role = source["source_role"] if source else None
            event_type, extracted = classify_event(payload.text, source_role)
            reported = payload.reported_date or parse_reported_date(payload.text)
            effective = payload.corrected_effective_date or reported
            corrected = bool(payload.corrected_effective_date and reported and payload.corrected_effective_date != reported)
            status = "STAGED"
            if payload.media_id and not payload.text.strip():
                status = "MEDIA_PENDING"
            elif event_type == "RECEIVING_REPORT" and site:
                status = "READY_FOR_RECEIVING_PREVIEW"
            elif not source:
                status = "NEEDS_REVIEW"

            event_key = stable_event_key(provider, payload.message_id)
            digest = source_hash(provider, payload.message_id, raw_payload or {"text": payload.text, "group": group_name})
            cur.execute(
                """insert into ingest_sources(source_type,external_id,source_uri,source_hash)
                   values ('WHATSAPP',%s,null,%s)
                   on conflict (source_type,external_id)
                   do update set source_hash=excluded.source_hash
                   returning id""",
                (payload.message_id, digest),
            )
            ingest_source_id = cur.fetchone()["id"]

            event_payload = {
                "whatsapp_source_key": source["source_key"] if source else None,
                "group_name": group_name or None,
                "source_role": source_role,
                "message_type": payload.message_type,
                "media_id": payload.media_id,
                "media_mime_type": payload.media_mime_type,
                "reported_date": reported.isoformat() if reported else None,
                "effective_date": effective.isoformat() if effective else None,
                "date_corrected": corrected,
                "date_correction_reason": payload.date_correction_reason,
                "extracted_items": extracted,
                "purchase_order_id_hint": payload.purchase_order_id,
            }
            cur.execute(
                """insert into candidate_events(
                     event_key,source_id,event_type,site,vendor_code,entity_code,event_time,
                     confidence,requires_confirmation,payload,raw_text,parser_version
                   ) values (%s,%s,%s,%s,%s,%s,%s,%s,true,%s::jsonb,%s,'whatsapp-v0.18')
                   on conflict (event_key) do update set
                     payload=excluded.payload,raw_text=excluded.raw_text,event_time=excluded.event_time
                   returning id,status""",
                (
                    event_key, ingest_source_id, event_type, site, infer_vendor(payload.text), payload.sender,
                    payload.provider_timestamp or datetime.now(timezone.utc), 0.95 if source else 0.55,
                    json.dumps(event_payload, ensure_ascii=False), payload.text,
                ),
            )
            candidate = cur.fetchone()

            cur.execute(
                """insert into whatsapp_inbox(
                     provider,message_id,source_key,group_name,sender,sender_name,message_type,text_body,
                     media_id,media_mime_type,media_sha256,provider_timestamp,reported_date,effective_date,
                     date_corrected,date_correction_reason,corrected_by,event_type,normalized_status,
                     candidate_event_id,raw_payload
                   ) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                   on conflict (provider,message_id) do update set
                     source_key=excluded.source_key,group_name=excluded.group_name,text_body=excluded.text_body,
                     media_id=excluded.media_id,media_mime_type=excluded.media_mime_type,
                     reported_date=excluded.reported_date,effective_date=excluded.effective_date,
                     date_corrected=excluded.date_corrected,date_correction_reason=excluded.date_correction_reason,
                     corrected_by=excluded.corrected_by,event_type=excluded.event_type,
                     normalized_status=excluded.normalized_status,candidate_event_id=excluded.candidate_event_id,
                     raw_payload=excluded.raw_payload,updated_at=now()
                   returning id""",
                (
                    provider, payload.message_id, source["source_key"] if source else None, group_name or None,
                    payload.sender, payload.sender_name, payload.message_type, payload.text,
                    payload.media_id, payload.media_mime_type, payload.media_sha256,
                    payload.provider_timestamp or datetime.now(timezone.utc), reported, effective, corrected,
                    payload.date_correction_reason, payload.corrected_by, event_type, status,
                    candidate["id"], json.dumps(raw_payload, ensure_ascii=False),
                ),
            )
            inbox_id = cur.fetchone()["id"]

            receiving_preview = None
            if event_type == "RECEIVING_REPORT" and site and payload.text.strip():
                receiving_preview = preview_receiving(
                    cur,
                    site,
                    payload.text,
                    payload.purchase_order_id,
                    payload.provider_timestamp,
                )
            conn.commit()

    return {
        "inboxId": inbox_id,
        "candidateEventId": candidate["id"],
        "candidateStatus": candidate["status"],
        "provider": provider,
        "messageId": payload.message_id,
        "sourceKey": source["source_key"] if source else None,
        "sourceRole": source_role,
        "site": site,
        "groupName": group_name or None,
        "eventType": event_type,
        "normalizedStatus": status,
        "reportedDate": reported.isoformat() if reported else None,
        "effectiveDate": effective.isoformat() if effective else None,
        "dateCorrected": corrected,
        "dateCorrectionReason": payload.date_correction_reason,
        "receivingPreview": receiving_preview,
        "autoCommitted": False,
        "financeTransactionCreated": False,
    }


@router.get("/webhook", include_in_schema=False)
def verify_webhook(
    hub_mode: str = Query(default="", alias="hub.mode"),
    hub_verify_token: str = Query(default="", alias="hub.verify_token"),
    hub_challenge: str = Query(default="", alias="hub.challenge"),
) -> Response:
    expected = os.getenv("WHATSAPP_VERIFY_TOKEN", "").strip()
    if not expected:
        raise HTTPException(503, "WHATSAPP_VERIFY_TOKEN is not configured")
    if hub_mode != "subscribe" or not hmac.compare_digest(hub_verify_token, expected):
        raise HTTPException(403, "webhook verification failed")
    return Response(content=hub_challenge, media_type="text/plain")


@router.post("/webhook", include_in_schema=False)
async def receive_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
) -> dict[str, Any]:
    raw = await request.body()
    verify_signature(raw, x_hub_signature_256)
    try:
        body = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(400, f"invalid JSON webhook payload: {exc}")

    staged: list[dict[str, Any]] = []
    for entry in body.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value", {}) or {}
            contacts = value.get("contacts", []) or []
            contact_name = None
            if contacts:
                contact_name = ((contacts[0].get("profile") or {}).get("name"))
            for message in value.get("messages", []) or []:
                message_type = message.get("type") or "unknown"
                text = ""
                media_id = None
                media_mime = None
                media_sha = None
                if message_type == "text":
                    text = ((message.get("text") or {}).get("body")) or ""
                elif message_type in {"image", "document", "video", "audio"}:
                    media = message.get(message_type) or {}
                    media_id = media.get("id")
                    media_mime = media.get("mime_type")
                    media_sha = media.get("sha256")
                    text = media.get("caption") or ""
                ts = None
                if message.get("timestamp"):
                    try:
                        ts = datetime.fromtimestamp(int(message["timestamp"]), tz=timezone.utc)
                    except Exception:
                        ts = None
                normalized = NormalizedWhatsAppIn(
                    provider="META_WHATSAPP",
                    message_id=str(message.get("id") or hashlib.sha256(json.dumps(message, sort_keys=True).encode()).hexdigest()),
                    group_name=message.get("group_name") or value.get("group_name"),
                    source_key=None,
                    sender=message.get("from"),
                    sender_name=contact_name,
                    message_type=message_type,
                    text=text,
                    media_id=media_id,
                    media_mime_type=media_mime,
                    media_sha256=media_sha,
                    provider_timestamp=ts,
                    raw_payload={"entry": entry.get("id"), "change_field": change.get("field"), "value_metadata": value.get("metadata"), "message": message},
                )
                staged.append(stage_normalized(normalized))
    return {"received": True, "stagedCount": len(staged), "items": staged}


@router.post("/ingest-normalized")
def ingest_normalized(payload: NormalizedWhatsAppIn, request: Request) -> dict[str, Any]:
    require_ingest_auth(request)
    return stage_normalized(payload)


@router.get("/status")
def whatsapp_status() -> dict[str, Any]:
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("select source_key,display_name,site,source_role,active from whatsapp_sources order by site,source_key")
            sources = cur.fetchall()
            cur.execute("select count(*) as total from whatsapp_inbox")
            total = cur.fetchone()["total"]
    return {
        "webhookVerifyTokenConfigured": bool(os.getenv("WHATSAPP_VERIFY_TOKEN", "").strip()),
        "appSecretConfigured": bool(os.getenv("WHATSAPP_APP_SECRET", "").strip()),
        "ingestAuthConfigured": bool(os.getenv("WHATSAPP_INGEST_KEY", "").strip() or os.getenv("SPPG_GPT_API_KEY", "").strip()),
        "sources": sources,
        "inboxCount": total,
        "autoCommitReceiving": False,
        "autoCreateFinance": False,
    }


@router.get("/inbox")
def whatsapp_inbox(limit: int = Query(default=50, ge=1, le=500), site: str = "", status: str = "") -> dict[str, Any]:
    require_db()
    sql = """
        select wi.id,wi.provider,wi.message_id,wi.source_key,ws.site,wi.group_name,wi.sender,wi.sender_name,
               wi.message_type,wi.text_body,wi.media_id,wi.media_mime_type,wi.provider_timestamp,
               wi.reported_date,wi.effective_date,wi.date_corrected,wi.date_correction_reason,
               wi.event_type,wi.normalized_status,wi.candidate_event_id,wi.created_at
        from whatsapp_inbox wi
        left join whatsapp_sources ws on ws.source_key=wi.source_key
        where true
    """
    params: list[Any] = []
    if site:
        sql += " and upper(ws.site)=upper(%s)"
        params.append(site)
    if status:
        sql += " and upper(wi.normalized_status)=upper(%s)"
        params.append(status)
    sql += " order by coalesce(wi.provider_timestamp,wi.created_at) desc limit %s"
    params.append(limit)
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return {"items": cur.fetchall()}
