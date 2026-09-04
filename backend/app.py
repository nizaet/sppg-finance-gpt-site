import hashlib
import json
import os
from datetime import date, datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from backend.db import connection, database_ready
from backend.reference_api import router as reference_router
from backend.planning_api import router as planning_router
from backend.gpt_bridge_api import router as gpt_bridge_router
from backend.gpt_operations_api import router as gpt_operations_router
from backend.firestore_backfill_api import router as firestore_backfill_router
from backend.operational_api import router as operational_router
from backend.vendor_payables_api import router as vendor_payables_router
from backend.inventory_api import router as inventory_router
from backend.vendor_workflow_api import router as vendor_workflow_router
from backend.menu_planning_advisor_api import router as menu_planning_advisor_router
from backend.operations_action_schema_v017_api import schema_v0170, schema_v0171, schema_v0172
from backend.unified_action_schema_api import schema_v0180, schema_v0181, schema_v0182, schema_v0183, schema_v0184, schema_v0185, schema_v0186, schema_v0187

app = FastAPI(title="SPPG Core API", version="0.16.6")
app.include_router(reference_router)
app.include_router(planning_router)
app.include_router(gpt_bridge_router)
app.include_router(gpt_operations_router)
app.include_router(firestore_backfill_router)
app.include_router(operational_router)
app.include_router(menu_planning_advisor_router)
app.include_router(vendor_payables_router, prefix="/v1")
app.include_router(inventory_router)
app.include_router(vendor_workflow_router)

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


def _chatgpt_operations_schema() -> dict[str, Any]:
    """Build a self-contained OpenAPI schema for the operational GPT Action.

    This is generated from the live FastAPI routes, so it never depends on a
    YAML file being present in the Railway filesystem.
    """
    full = app.openapi()
    wanted = {
        "/v1/vendor-invoices/parse-whatsapp",
        "/v1/vendor-payables/from-receipt",
        "/v1/vendor-payables",
        "/v1/vendor-payments/confirm",
        "/v1/inventory/from-receipt",
        "/v1/inventory/usage",
        "/v1/inventory/balance",
        "/v1/inventory/requirement-preview",
    }
    paths = {k: v for k, v in full.get("paths", {}).items() if k in wanted}

    parser = paths.get("/v1/vendor-invoices/parse-whatsapp", {}).get("post")
    if parser:
        parser["operationId"] = "parseOnlySuppliedSppgVendorInvoiceText"
        parser["summary"] = "Parse ONLY vendor invoice text supplied in the current user request"
        parser["description"] = (
            "READ-ONLY. When the user pastes, types, or forwards vendor invoice text, use ONLY that exact supplied text. "
            "Never search or substitute finance transactions, purchase orders, historical MAJA/CEMPLANG records, or other database data. "
            "Do not invent missing prices. Preserve all invoice lines and rijek/reject notes. This action writes nothing."
        )

    payable = paths.get("/v1/vendor-payables/from-receipt", {}).get("post")
    if payable:
        payable["summary"] = "Preview or commit reconciled vendor payable after invoice parsing"
        payable["description"] = (
            "NOT a text parser. Use only when a purchase order and goods receipt already exist. "
            "Always preview with commit=false first. Keep PO qty, received qty, invoice qty, rejected qty, and payable qty separate."
        )

    search_payable = paths.get("/v1/vendor-payables", {}).get("get")
    if search_payable:
        search_payable["summary"] = "Search already-recorded vendor payables"
        search_payable["description"] = "Never use this endpoint to parse newly supplied invoice text."

    payment = paths.get("/v1/vendor-payments/confirm", {}).get("post")
    if payment:
        payment["summary"] = "Preview or confirm payment evidence for an existing vendor payable"
        payment["description"] = (
            "NOT an invoice parser. Use commit=false first. A committed payment updates payable status but does not automatically create a finance ledger transaction."
        )

    return {
        "openapi": full.get("openapi", "3.1.0"),
        "info": {
            "title": "SPPG Vendor and Inventory Operations",
            "version": "0.16.5",
            "description": (
                "Vendor invoice parsing, payable reconciliation, operational stock, and vendor payment confirmation. "
                "For newly supplied invoice text, always use parseOnlySuppliedSppgVendorInvoiceText and only the user's supplied text."
            ),
        },
        "servers": [{"url": "https://sppg-finance-gpt-site-production-5b7d.up.railway.app"}],
        "paths": paths,
        "components": full.get("components", {}),
    }


@app.get("/v1/schema/chatgpt-operations-v0161.json", include_in_schema=False)
def chatgpt_operations_schema_json() -> JSONResponse:
    return JSONResponse(_chatgpt_operations_schema())


# Compatibility aliases. The canonical schema routes live under /v1/schema,
# but these aliases prevent the SPA fallback from being mistaken for an empty
# OpenAPI document when a GPT Builder import omits the /v1 prefix.
@app.get("/schema/chatgpt-operations-v0170.json", include_in_schema=False)
def chatgpt_operations_schema_v0170_alias() -> JSONResponse:
    return JSONResponse(schema_v0170())


@app.get("/schema/chatgpt-operations-v0171.json", include_in_schema=False)
def chatgpt_operations_schema_v0171_alias() -> JSONResponse:
    return JSONResponse(schema_v0171())


@app.get("/schema/chatgpt-operations-v0172.json", include_in_schema=False)
def chatgpt_operations_schema_v0172_alias() -> JSONResponse:
    return JSONResponse(schema_v0172())


@app.get("/schema/chatgpt-sppg-v0180.json", include_in_schema=False)
def chatgpt_sppg_schema_v0180_alias() -> JSONResponse:
    return JSONResponse(schema_v0180())


@app.get("/schema/chatgpt-sppg-v0181.json", include_in_schema=False)
def chatgpt_sppg_schema_v0181_alias() -> JSONResponse:
    return JSONResponse(schema_v0181())


@app.get("/schema/chatgpt-sppg-v0182.json", include_in_schema=False)
def chatgpt_sppg_schema_v0182_alias() -> JSONResponse:
    return JSONResponse(schema_v0182())


@app.get("/schema/chatgpt-sppg-v0183.json", include_in_schema=False)
def chatgpt_sppg_schema_v0183_alias() -> JSONResponse:
    return JSONResponse(schema_v0183())


@app.get("/schema/chatgpt-sppg-v0184.json", include_in_schema=False)
def chatgpt_sppg_schema_v0184_alias() -> JSONResponse:
    return JSONResponse(schema_v0184())


@app.get("/schema/chatgpt-sppg-v0185.json", include_in_schema=False)
def chatgpt_sppg_schema_v0185_alias() -> JSONResponse:
    return JSONResponse(schema_v0185())


@app.get("/schema/chatgpt-sppg-v0186.json", include_in_schema=False)
def chatgpt_sppg_schema_v0186_alias() -> JSONResponse:
    return JSONResponse(schema_v0186())


@app.get("/schema/chatgpt-sppg-v0187.json", include_in_schema=False)
def chatgpt_sppg_schema_v0187_alias() -> JSONResponse:
    return JSONResponse(schema_v0187())


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
    return {"status": "ok", "service": "sppg-core", "version": "0.16.5", "databaseReady": database_ready()}


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
                    """select count(*) as n from purchase_orders po
                       left join production_cycles pc on pc.id=po.production_cycle_id
                       where upper(coalesce(po.site,''))=%s and pc.distribution_date=%s
                         and upper(po.status) in ('FINALIZED','SENT','ACKNOWLEDGED','PARTIAL_RECEIVED')""",
                    (site, target_date),
                )
                out["summary"]["deliveriesExpected"] = cur.fetchone()["n"]

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

                cur.execute(
                    """select gr.id,po.po_code,po.vendor_code,gr.received_at,
                              coalesce(sum(abs(gri.variance_qty)),0) as variance_abs
                       from goods_receipts gr join purchase_orders po on po.id=gr.purchase_order_id
                       left join goods_receipt_items gri on gri.goods_receipt_id=gr.id
                       where upper(coalesce(po.site,''))=%s and date(gr.received_at)=%s
                       group by gr.id,po.id order by gr.received_at desc limit 8""",
                    (site, target_date),
                )
                for row in cur.fetchall():
                    variance_abs = float(row["variance_abs"] or 0)
                    out["lanes"]["receiving"].append({
                        "id": row["id"],
                        "title": f"{row['vendor_code']} · {row['po_code']}",
                        "subtitle": f"Penerimaan tercatat · selisih absolut {variance_abs:g}",
                        "status": "VARIANCE" if variance_abs > 0 else "RECEIVED",
                        "severity": "warning" if variance_abs > 0 else "success",
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
                   from candidate_events
                   where status='PENDING' and event_type not like 'HERMES_PROPOSAL_%'
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
                   where id=%s and status='PENDING'
                     and event_type not like 'HERMES_PROPOSAL_%%'
                   returning id, status""",
                (status, payload.actor, status, payload.note, event_id),
            )
            row = cur.fetchone()
            if row is None:
                raise HTTPException(409, "event not found, no longer pending, or requires Hermes Approval Center")
            cur.execute(
                "insert into event_audit_log(candidate_event_id, action,actor,details) values (%s,%s,%s,%s::jsonb)",
                (event_id, f"REVIEW_{decision}", payload.actor, json.dumps({"note": payload.note}, ensure_ascii=False)),
            )
            conn.commit()
    return {"eventId": row["id"], "decision": decision, "status": row["status"]}



@app.get("/privacy", include_in_schema=False, response_class=HTMLResponse)
def public_privacy_page() -> str:
    return """<!doctype html>
<html lang="id"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kebijakan Privasi — SPPG Finance & Operasional</title></head>
<body><main>
<h1>Kebijakan Privasi</h1>
<p>SPPG Finance &amp; Operasional digunakan secara internal untuk operasional SPPG.</p>
<h2>Data Google Drive</h2>
<p>Aplikasi meminta akses Google Drive hanya untuk membuat, membaca, dan mengarsipkan file Excel serta dokumen operasional ke folder yang dipilih organisasi. Data tidak dijual, digunakan untuk iklan, atau dibagikan kepada pihak lain di luar kebutuhan operasional dan layanan infrastruktur yang menjalankan aplikasi.</p>
<h2>Penyimpanan dan penghapusan</h2>
<p>File tersimpan pada Google Drive organisasi. Akses aplikasi dapat dicabut kapan saja melalui pengaturan Akun Google. Permintaan penghapusan data dapat diajukan melalui alamat dukungan yang tercantum pada layar persetujuan Google.</p>
<h2>Kontak</h2>
<p>Untuk pertanyaan privasi atau akses data, hubungi alamat dukungan yang tercantum pada layar persetujuan Google.</p>
<p><a href="/">Kembali ke beranda</a></p>
</main></body></html>"""
