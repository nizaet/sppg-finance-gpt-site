import hashlib
import json
import os
from datetime import date, datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.db import connection, database_ready
from backend.reference_api import router as reference_router
from backend.planning_api import router as planning_router

app = FastAPI(title="SPPG Core API", version="0.4.0")
app.include_router(reference_router)
app.include_router(planning_router)

origins = [x.strip() for x in os.getenv("SPPG_ALLOWED_ORIGINS", "").split(",") if x.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SITE_DEFS = [
    {"siteId": "sppg-maja-gpt-site", "siteLabel": "SPPG MAJA BARU", "dbSite": "MAJA"},
    {"siteId": "sppg-cemplang2-gpt-site", "siteLabel": "SPPG CEMPLANG 2", "dbSite": "CEMPLANG"},
]


def empty_site(site: dict[str, str]) -> dict[str, Any]:
    return {
        "siteId": site["siteId"],
        "siteLabel": site["siteLabel"],
        "summary": {
            "poDueToday": 0,
            "poOverdue": 0,
            "deliveriesExpected": 0,
            "unresolvedRejects": 0,
            "paymentsDue": 0,
            "reviewQueue": 0,
        },
        "lanes": {
            "procurement": [],
            "receiving": [],
            "payments": [],
            "costing": [],
            "accountant": [],
            "bgn": [],
        },
    }


class ReviewDecision(BaseModel):
    decision: str
    note: str = ""
    actor: str = "operator"


class CandidateEventIn(BaseModel):
    source_type: str = "CHAT"
    external_id: str | None = None
    source_uri: str | None = None
    event_type: str
    site: str | None = None
    vendor_code: str | None = None
    entity_code: str | None = None
    event_time: datetime | None = None
    confidence: float = Field(default=0.5, ge=0, le=1)
    requires_confirmation: bool = True
    payload: dict[str, Any] = Field(default_factory=dict)
    raw_text: str = ""
    parser_version: str = "manual-v1"
    event_key: str | None = None


def stable_event_key(payload: CandidateEventIn) -> str:
    if payload.event_key:
        return payload.event_key
    base = {
        "source_type": payload.source_type,
        "external_id": payload.external_id,
        "event_type": payload.event_type,
        "site": payload.site,
        "vendor_code": payload.vendor_code,
        "event_time": payload.event_time.isoformat() if payload.event_time else None,
        "raw_text": payload.raw_text,
        "payload": payload.payload,
    }
    digest = hashlib.sha256(json.dumps(base, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return f"evt:{digest}"


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "service": "sppg-core", "databaseReady": database_ready()}


@app.post("/v1/events")
def ingest_event(payload: CandidateEventIn) -> dict[str, Any]:
    if not database_ready():
        raise HTTPException(503, "DATABASE_URL is not configured or database is unavailable")

    event_key = stable_event_key(payload)
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into ingest_sources(source_type, external_id, source_uri, source_hash)
                values (%s, %s, %s, %s)
                on conflict (source_type, external_id) do update set source_uri = coalesce(excluded.source_uri, ingest_sources.source_uri)
                returning id
                """,
                (payload.source_type, payload.external_id or event_key, payload.source_uri, event_key),
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
                    event_key, source_id, payload.event_type, payload.site, payload.vendor_code,
                    payload.entity_code, payload.event_time or datetime.now(timezone.utc), payload.confidence,
                    payload.requires_confirmation, json.dumps(payload.payload, ensure_ascii=False),
                    payload.raw_text, payload.parser_version,
                ),
            )
            inserted = cur.fetchone()
            if inserted is None:
                cur.execute("select id, status from candidate_events where event_key=%s", (event_key,))
                inserted = cur.fetchone()
            conn.commit()
    return {"eventId": inserted["id"], "eventKey": event_key, "status": inserted["status"]}


@app.get("/v1/control-tower")
def control_tower(target_date: date = Query(alias="date")) -> dict[str, Any]:
    sites = [empty_site(x) for x in SITE_DEFS]
    if not database_ready():
        return {"date": target_date.isoformat(), "databaseReady": False, "sites": sites}

    with connection() as conn:
        with conn.cursor() as cur:
            for definition, out in zip(SITE_DEFS, sites):
                site = definition["dbSite"]
                cur.execute(
                    """select count(*) as n from candidate_events
                       where upper(coalesce(site,''))=%s and status='PENDING' and requires_confirmation=true""",
                    (site,),
                )
                out["summary"]["reviewQueue"] = cur.fetchone()["n"]

                cur.execute(
                    """select count(*) as n from vendor_payments
                       where upper(coalesce(site,''))=%s and payment_status not in ('PAID','RECONCILED')""",
                    (site,),
                )
                out["summary"]["paymentsDue"] = cur.fetchone()["n"]

                cur.execute(
                    """select count(*) as n
                       from goods_receipt_items gri
                       join goods_receipts gr on gr.id=gri.goods_receipt_id
                       join purchase_orders po on po.id=gr.purchase_order_id
                       where upper(coalesce(po.site,''))=%s and coalesce(gri.rejected_qty,0)>0
                         and coalesce(gri.quality_status,'') not in ('RECONCILED','CLOSED')""",
                    (site,),
                )
                out["summary"]["unresolvedRejects"] = cur.fetchone()["n"]

                cur.execute(
                    """select id, event_type, vendor_code, confidence, raw_text, created_at
                       from candidate_events where upper(coalesce(site,''))=%s and status='PENDING'
                       order by created_at desc limit 8""",
                    (site,),
                )
                pending = cur.fetchall()
                for row in pending:
                    lane = "payments" if "PAYMENT" in row["event_type"] else "procurement"
                    out["lanes"][lane].append({
                        "id": row["id"],
                        "title": row["vendor_code"] or row["event_type"],
                        "subtitle": row["raw_text"][:120] if row["raw_text"] else row["event_type"],
                        "status": "REVIEW",
                        "severity": "warning",
                    })

    return {"date": target_date.isoformat(), "databaseReady": True, "sites": sites}


@app.get("/v1/po-calendar")
def po_calendar(from_: date = Query(alias="from"), to: date = Query(), site: str | None = None) -> dict[str, Any]:
    if not database_ready():
        return {"from": from_.isoformat(), "to": to.isoformat(), "site": site, "items": []}
    with connection() as conn:
        with conn.cursor() as cur:
            sql = """select po.id, po.po_code, po.revision_no, po.site, po.vendor_code, po.status,
                            po.sent_at, pc.cycle_code, pc.distribution_date, pc.cooking_at
                     from purchase_orders po left join production_cycles pc on pc.id=po.production_cycle_id
                     where pc.distribution_date between %s and %s"""
            params: list[Any] = [from_, to]
            if site:
                sql += " and upper(po.site)=upper(%s)"
                params.append(site)
            sql += " order by pc.distribution_date, po.vendor_code, po.po_code, po.revision_no desc"
            cur.execute(sql, params)
            items = cur.fetchall()
    return {"from": from_.isoformat(), "to": to.isoformat(), "site": site, "items": items}


@app.get("/v1/vendor-payments")
def vendor_payments(status: str = "", site: str = "") -> dict[str, Any]:
    if not database_ready():
        return {"status": status, "site": site, "items": []}
    with connection() as conn:
        with conn.cursor() as cur:
            sql = """select vp.*, vi.invoice_number, vi.gross_amount, vi.reject_deduction, vi.net_amount
                     from vendor_payments vp left join vendor_invoices vi on vi.id=vp.vendor_invoice_id where true"""
            params: list[Any] = []
            if status:
                sql += " and upper(vp.payment_status)=upper(%s)"
                params.append(status)
            if site:
                sql += " and upper(coalesce(vp.site,''))=upper(%s)"
                params.append(site)
            sql += " order by vp.created_at desc limit 250"
            cur.execute(sql, params)
            items = cur.fetchall()
    return {"status": status, "site": site, "items": items}


@app.get("/v1/review-queue")
def review_queue() -> dict[str, Any]:
    if not database_ready():
        return {"items": []}
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """select id, event_key, event_type, site, vendor_code, entity_code, event_time,
                          confidence, requires_confirmation, payload, raw_text, parser_version, status, created_at
                   from candidate_events where status='PENDING'
                   order by requires_confirmation desc, confidence asc, created_at asc limit 500"""
            )
            return {"items": cur.fetchall()}


@app.post("/v1/review-queue/{event_id}")
def review_decision(event_id: int, payload: ReviewDecision) -> dict[str, Any]:
    decision = payload.decision.upper().strip()
    if decision not in {"APPROVE", "REJECT"}:
        raise HTTPException(400, "decision must be APPROVE or REJECT")
    if not database_ready():
        raise HTTPException(503, "database unavailable")

    status = "VALIDATED" if decision == "APPROVE" else "REJECTED"
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """update candidate_events set status=%s, validated_at=now(), validated_by=%s,
                          rejection_reason=case when %s='REJECTED' then %s else null end
                   where id=%s and status='PENDING' returning id, status""",
                (status, payload.actor, status, payload.note, event_id),
            )
            row = cur.fetchone()
            if row is None:
                raise HTTPException(409, "event not found or no longer pending")
            cur.execute(
                "insert into event_audit_log(candidate_event_id, action, actor, details) values (%s,%s,%s,%s::jsonb)",
                (event_id, f"REVIEW_{decision}", payload.actor, json.dumps({"note": payload.note}, ensure_ascii=False)),
            )
            conn.commit()
    return {"eventId": row["id"], "decision": decision, "status": row["status"]}
