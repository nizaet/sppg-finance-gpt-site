import json
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.db import connection, database_ready
from backend.inventory_api import commit_receipt_stock

router = APIRouter(tags=["domain"])


def require_db() -> None:
    if not database_ready():
        raise HTTPException(503, "database unavailable")


class ReceiptItemIn(BaseModel):
    purchase_order_item_id: int | None = None
    received_qty: float
    rejected_qty: float = 0
    accepted_qty: float | None = None
    unit: str | None = None
    quality_status: str | None = None
    notes: str | None = None


class GoodsReceiptIn(BaseModel):
    purchase_order_id: int
    receipt_code: str | None = None
    received_at: datetime | None = None
    items: list[ReceiptItemIn] = Field(default_factory=list)


@router.post("/goods-receipts")
def create_goods_receipt(payload: GoodsReceiptIn) -> dict[str, Any]:
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("select id,site,status from purchase_orders where id=%s", (payload.purchase_order_id,))
            po = cur.fetchone()
            if not po:
                raise HTTPException(404, "purchase order not found")
            cur.execute(
                "select id,item_name,po_qty,unit from purchase_order_items where purchase_order_id=%s order by id",
                (payload.purchase_order_id,),
            )
            po_items = {int(row["id"]): dict(row) for row in cur.fetchall()}
            supplied_ids = [int(item.purchase_order_item_id) for item in payload.items if item.purchase_order_item_id is not None]
            unknown_ids = sorted({item_id for item_id in supplied_ids if item_id not in po_items})
            if unknown_ids:
                raise HTTPException(400, f"item bukan milik PO {payload.purchase_order_id}: {unknown_ids}")
            exact_match = bool(payload.items) and len(supplied_ids) == len(payload.items)
            cur.execute(
                """insert into goods_receipts(
                     purchase_order_id,receipt_code,received_at,source_type,match_status,match_confidence,confirmed_at
                   ) values (%s,%s,coalesce(%s,now()),'MANUAL',%s,%s,case when %s then now() else null end)
                   returning id""",
                (
                    payload.purchase_order_id, payload.receipt_code, payload.received_at,
                    "CONFIRMED" if exact_match else "REVIEW", 1 if exact_match else 0, exact_match,
                ),
            )
            receipt_id = cur.fetchone()["id"]
            for item in payload.items:
                accepted = item.accepted_qty
                if accepted is None:
                    accepted = max(0, item.received_qty - item.rejected_qty)
                po_item = po_items.get(int(item.purchase_order_item_id)) if item.purchase_order_item_id is not None else None
                po_qty = float(po_item.get("po_qty") or 0) if po_item else None
                item_confidence = 1 if po_item else 0
                cur.execute(
                    """insert into goods_receipt_items(
                         goods_receipt_id, purchase_order_item_id, received_qty, rejected_qty,
                         accepted_qty, unit, quality_status, notes,reported_item_name,
                         po_qty_snapshot,variance_qty,match_confidence,match_method
                       ) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (receipt_id, item.purchase_order_item_id, item.received_qty, item.rejected_qty,
                     accepted, item.unit or (po_item.get("unit") if po_item else None),
                     item.quality_status or "ACCEPTED", item.notes,
                     po_item.get("item_name") if po_item else None, po_qty,
                     round(float(accepted) - po_qty, 4) if po_qty is not None else None,
                     item_confidence, "explicit_po_item_id" if po_item else "unmatched_manual"),
                )
            stock = commit_receipt_stock(cur, receipt_id, str(po["site"]))
            cur.execute(
                """select poi.po_qty,coalesce(sum(gri.accepted_qty),0) as accepted_total
                   from purchase_order_items poi
                   left join goods_receipt_items gri on gri.purchase_order_item_id=poi.id
                   where poi.purchase_order_id=%s group by poi.id order by poi.id""",
                (payload.purchase_order_id,),
            )
            totals = cur.fetchall()
            complete = bool(totals) and all(float(row["accepted_total"] or 0) >= float(row["po_qty"] or 0) for row in totals)
            any_received = any(float(row["accepted_total"] or 0) > 0 for row in totals)
            new_status = "RECEIVED" if complete else "PARTIAL_RECEIVED" if any_received else str(po.get("status") or "")
            if new_status:
                cur.execute("update purchase_orders set status=%s,updated_at=now() where id=%s", (new_status, payload.purchase_order_id))
            conn.commit()
    return {
        "receiptId": receipt_id,
        "itemCount": len(payload.items),
        "matchStatus": "CONFIRMED" if exact_match else "REVIEW",
        "matchConfidence": 1 if exact_match else 0,
        "purchaseOrderStatus": new_status,
        "stockCommitted": True,
        "stockInserted": stock["inserted"],
        "stockDuplicates": stock["duplicates"],
    }


@router.get("/goods-receipts")
def list_goods_receipts(site: str = "", limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            sql = """
                select gr.id, gr.receipt_code, gr.received_at, po.po_code, po.site, po.vendor_code,
                       count(gri.id) as item_count,
                       coalesce(sum(gri.received_qty),0) as received_qty_total,
                       coalesce(sum(gri.rejected_qty),0) as rejected_qty_total
                from goods_receipts gr
                join purchase_orders po on po.id=gr.purchase_order_id
                left join goods_receipt_items gri on gri.goods_receipt_id=gr.id
                where true
            """
            params: list[Any] = []
            if site:
                sql += " and upper(po.site)=upper(%s)"
                params.append(site)
            sql += " group by gr.id, po.id order by gr.received_at desc nulls last, gr.id desc limit %s"
            params.append(limit)
            cur.execute(sql, params)
            return {"items": cur.fetchall()}


class ActualUsageItemIn(BaseModel):
    item_code: str | None = None
    item_name: str
    actual_used_qty: float
    unit: str | None = None
    vendor_cost_price: float | None = None
    claim_price: float | None = None


class ActualUsageBatchIn(BaseModel):
    production_cycle_id: int
    items: list[ActualUsageItemIn]


@router.post("/actual-usage")
def save_actual_usage(payload: ActualUsageBatchIn) -> dict[str, Any]:
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("select id from production_cycles where id=%s", (payload.production_cycle_id,))
            if not cur.fetchone():
                raise HTTPException(404, "production cycle not found")
            for item in payload.items:
                cur.execute(
                    """insert into actual_usage(
                         production_cycle_id,item_code,item_name,actual_used_qty,unit,
                         vendor_cost_price,claim_price
                       ) values (%s,%s,%s,%s,%s,%s,%s)""",
                    (payload.production_cycle_id, item.item_code, item.item_name,
                     item.actual_used_qty, item.unit, item.vendor_cost_price, item.claim_price),
                )
            conn.commit()
    return {"productionCycleId": payload.production_cycle_id, "itemCount": len(payload.items)}


@router.get("/actual-usage")
def get_actual_usage(production_cycle_id: int = Query(alias="productionCycleId")) -> dict[str, Any]:
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """select *, actual_used_qty * coalesce(vendor_cost_price,0) as cost_total,
                          actual_used_qty * coalesce(claim_price,0) as claim_total
                   from actual_usage where production_cycle_id=%s order by id""",
                (production_cycle_id,),
            )
            rows = cur.fetchall()
    return {
        "productionCycleId": production_cycle_id,
        "items": rows,
        "costTotal": sum(float(x["cost_total"] or 0) for x in rows),
        "claimTotal": sum(float(x["claim_total"] or 0) for x in rows),
    }


class AccountantSubmissionIn(BaseModel):
    production_cycle_id: int | None = None
    site: str
    accountant_code: str
    excel_evidence_uri: str | None = None
    sent_at: datetime | None = None
    status: str = "SENT"


@router.post("/accountant-submissions")
def create_accountant_submission(payload: AccountantSubmissionIn) -> dict[str, Any]:
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """insert into accountant_submissions(
                     production_cycle_id,site,accountant_code,excel_evidence_uri,sent_at,status
                   ) values (%s,%s,%s,%s,coalesce(%s,now()),%s) returning id""",
                (payload.production_cycle_id, payload.site.upper(), payload.accountant_code.upper(),
                 payload.excel_evidence_uri, payload.sent_at, payload.status),
            )
            submission_id = cur.fetchone()["id"]
            conn.commit()
    return {"submissionId": submission_id}


class AccountantInvoiceIn(BaseModel):
    accountant_submission_id: int
    invoice_number: str | None = None
    invoice_amount: float | None = None
    invoice_evidence_uri: str | None = None
    received_at: datetime | None = None


@router.post("/accountant-invoices")
def create_accountant_invoice(payload: AccountantInvoiceIn) -> dict[str, Any]:
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("select id from accountant_submissions where id=%s", (payload.accountant_submission_id,))
            if not cur.fetchone():
                raise HTTPException(404, "accountant submission not found")
            cur.execute(
                """insert into accountant_invoices(
                     accountant_submission_id,invoice_number,invoice_amount,invoice_evidence_uri,received_at
                   ) values (%s,%s,%s,%s,coalesce(%s,now())) returning id""",
                (payload.accountant_submission_id, payload.invoice_number, payload.invoice_amount,
                 payload.invoice_evidence_uri, payload.received_at),
            )
            invoice_id = cur.fetchone()["id"]
            conn.commit()
    return {"accountantInvoiceId": invoice_id}


@router.get("/accountant-flow")
def accountant_flow(site: str = "") -> dict[str, Any]:
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            sql = """
                select s.id as submission_id, s.production_cycle_id, s.site, s.accountant_code,
                       s.excel_evidence_uri, s.sent_at, s.status as submission_status,
                       i.id as invoice_id, i.invoice_number, i.invoice_amount,
                       i.invoice_evidence_uri, i.received_at
                from accountant_submissions s
                left join accountant_invoices i on i.accountant_submission_id=s.id
                where true
            """
            params: list[Any] = []
            if site:
                sql += " and upper(s.site)=upper(%s)"
                params.append(site)
            sql += " order by s.created_at desc limit 250"
            cur.execute(sql, params)
            return {"items": cur.fetchall()}


class BgnMakerIn(BaseModel):
    production_cycle_id: int | None = None
    site: str
    reference_number: str | None = None
    amount: float | None = None


@router.post("/bgn-makers")
def create_bgn_maker(payload: BgnMakerIn) -> dict[str, Any]:
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """insert into bgn_makers(production_cycle_id,site,reference_number,amount,status)
                   values (%s,%s,%s,%s,'CREATED') returning id""",
                (payload.production_cycle_id, payload.site.upper(), payload.reference_number, payload.amount),
            )
            maker_id = cur.fetchone()["id"]
            conn.commit()
    return {"makerId": maker_id, "status": "CREATED"}


class BgnApprovalIn(BaseModel):
    bgn_maker_id: int
    approver_code: str
    status: str = "PENDING"
    requested_at: datetime | None = None
    approved_at: datetime | None = None
    rejected_at: datetime | None = None


@router.post("/bgn-approvals")
def create_bgn_approval(payload: BgnApprovalIn) -> dict[str, Any]:
    require_db()
    status = payload.status.upper()
    if status not in {"PENDING","APPROVED","REJECTED","DEFERRED"}:
        raise HTTPException(400, "invalid approval status")
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("select id from bgn_makers where id=%s", (payload.bgn_maker_id,))
            if not cur.fetchone():
                raise HTTPException(404, "maker not found")
            cur.execute(
                """insert into bgn_approvals(
                     bgn_maker_id,approver_code,status,requested_at,approved_at,rejected_at
                   ) values (%s,%s,%s,coalesce(%s,now()),%s,%s) returning id""",
                (payload.bgn_maker_id, payload.approver_code.upper(), status,
                 payload.requested_at, payload.approved_at, payload.rejected_at),
            )
            approval_id = cur.fetchone()["id"]
            conn.commit()
    return {"approvalId": approval_id, "status": status}


class BgnReceiptIn(BaseModel):
    bgn_maker_id: int | None = None
    destination_account_type: str
    amount: float
    received_at: datetime | None = None
    evidence_uri: str | None = None


@router.post("/bgn-receipts")
def create_bgn_receipt(payload: BgnReceiptIn) -> dict[str, Any]:
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """insert into bgn_receipts(
                     bgn_maker_id,destination_account_type,amount,received_at,evidence_uri
                   ) values (%s,%s,%s,coalesce(%s,now()),%s) returning id""",
                (payload.bgn_maker_id, payload.destination_account_type,
                 payload.amount, payload.received_at, payload.evidence_uri),
            )
            receipt_id = cur.fetchone()["id"]
            conn.commit()
    return {"bgnReceiptId": receipt_id}


class SettlementIn(BaseModel):
    from_account_type: str
    to_account_type: str = "BCA_OPERATIONAL"
    amount: float
    settled_at: datetime | None = None
    evidence_uri: str | None = None
    production_cycle_id: int | None = None


@router.post("/settlements")
def create_settlement(payload: SettlementIn) -> dict[str, Any]:
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """insert into settlements(
                     from_account_type,to_account_type,amount,settled_at,evidence_uri,production_cycle_id
                   ) values (%s,%s,%s,coalesce(%s,now()),%s,%s) returning id""",
                (payload.from_account_type, payload.to_account_type, payload.amount,
                 payload.settled_at, payload.evidence_uri, payload.production_cycle_id),
            )
            settlement_id = cur.fetchone()["id"]
            conn.commit()
    return {"settlementId": settlement_id, "classification": "INTER_ACCOUNT_SETTLEMENT"}


@router.get("/bgn-flow")
def bgn_flow(site: str = "") -> dict[str, Any]:
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            sql = """
                select m.id as maker_id, m.production_cycle_id, m.site, m.reference_number,
                       m.amount as maker_amount, m.status as maker_status, m.created_at as maker_created_at,
                       a.id as approval_id, a.approver_code, a.status as approval_status,
                       a.requested_at, a.approved_at, a.rejected_at
                from bgn_makers m
                left join lateral (
                  select * from bgn_approvals x where x.bgn_maker_id=m.id order by x.created_at desc limit 1
                ) a on true
                where true
            """
            params: list[Any] = []
            if site:
                sql += " and upper(m.site)=upper(%s)"
                params.append(site)
            sql += " order by m.created_at desc limit 250"
            cur.execute(sql, params)
            return {"items": cur.fetchall()}


@router.get("/audit-log")
def audit_log(limit: int = Query(default=200, ge=1, le=1000)) -> dict[str, Any]:
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """select l.id, l.candidate_event_id, l.workflow_action_id, l.action,
                          l.actor, l.details, l.created_at,
                          e.event_type, e.site, e.vendor_code, e.raw_text
                   from event_audit_log l
                   left join candidate_events e on e.id=l.candidate_event_id
                   order by l.created_at desc limit %s""",
                (limit,),
            )
            return {"items": cur.fetchall()}
