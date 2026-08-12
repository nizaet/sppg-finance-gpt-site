from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.db import connection, database_ready

router = APIRouter(tags=["operational-history"])


def require_db() -> None:
    if not database_ready():
        raise HTTPException(503, "database unavailable")


def norm(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())


class HistoricalPoLineIn(BaseModel):
    item_name: str = Field(min_length=1)
    po_qty: float = Field(ge=0)
    unit: str | None = None
    item_code: str | None = None
    planned_qty: float | None = Field(default=None, ge=0)
    planning_price: float | None = Field(default=None, ge=0)
    po_price: float | None = Field(default=None, ge=0)
    notes: str | None = None


class HistoricalReceiptLineIn(BaseModel):
    item_name: str = Field(min_length=1)
    received_qty: float | None = Field(default=None, ge=0)
    rejected_qty: float = Field(default=0, ge=0)
    accepted_qty: float | None = Field(default=None, ge=0)
    unit: str | None = None
    notes: str | None = None


class HistoricalOperationalImportIn(BaseModel):
    site: Literal["MAJA", "CEMPLANG"]
    vendor_code: str = Field(min_length=1)
    distribution_date: date
    po_code: str | None = None
    source_type: str = Field(min_length=1)
    source_external_id: str | None = None
    source_uri: str | None = None
    source_raw_text: str | None = None
    received_at: datetime | None = None
    po_lines: list[HistoricalPoLineIn] = Field(min_length=1)
    receipt_lines: list[HistoricalReceiptLineIn] = Field(default_factory=list)
    commit: bool = False


def canonical_payload(payload: HistoricalOperationalImportIn) -> dict[str, Any]:
    return {
        "site": payload.site,
        "vendor_code": payload.vendor_code.upper().strip(),
        "distribution_date": payload.distribution_date.isoformat(),
        "po_code": payload.po_code,
        "source_type": payload.source_type.upper().strip(),
        "source_external_id": payload.source_external_id,
        "source_uri": payload.source_uri,
        "source_raw_text": payload.source_raw_text,
        "po_lines": [x.model_dump(mode="json") for x in payload.po_lines],
        "receipt_lines": [x.model_dump(mode="json") for x in payload.receipt_lines],
    }


def source_hash(payload: HistoricalOperationalImportIn) -> str:
    raw = json.dumps(canonical_payload(payload), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "hist-op:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def internal_po_code(payload: HistoricalOperationalImportIn, digest: str) -> str:
    if payload.po_code and payload.po_code.strip():
        return payload.po_code.strip()
    return f"HIST-{payload.site}-{payload.vendor_code.upper().strip()}-{payload.distribution_date.strftime('%Y%m%d')}-{digest[-8:].upper()}"


def best_po_line_match(name: str, po_lines: list[HistoricalPoLineIn]) -> tuple[int | None, float]:
    needle = norm(name)
    best_idx: int | None = None
    best_score = 0.0
    for idx, line in enumerate(po_lines):
        candidate = norm(line.item_name)
        score = SequenceMatcher(None, needle, candidate).ratio()
        if needle == candidate:
            score = 1.0
        elif needle in candidate or candidate in needle:
            score = max(score, 0.94)
        if score > best_score:
            best_idx, best_score = idx, score
    return best_idx, round(best_score, 5)


def build_preview(payload: HistoricalOperationalImportIn) -> dict[str, Any]:
    digest = source_hash(payload)
    code = internal_po_code(payload, digest)
    warnings: list[dict[str, Any]] = []
    receipt_preview: list[dict[str, Any]] = []

    for line in payload.receipt_lines:
        idx, score = best_po_line_match(line.item_name, payload.po_lines)
        if idx is None or score < 0.70:
            warnings.append({
                "code": "RECEIPT_ITEM_NOT_MATCHED_TO_PO",
                "item": line.item_name,
                "message": "Receipt item tidak cukup aman untuk dicocokkan ke PO.",
            })
            continue
        po_line = payload.po_lines[idx]
        if line.received_qty is None:
            warnings.append({
                "code": "RECEIVED_QTY_UNKNOWN_NOT_IMPORTED",
                "item": line.item_name,
                "rejected_qty": line.rejected_qty,
                "message": "Bukti tanpa received_qty tidak akan dibuat menjadi goods receipt; qty tidak diarang.",
            })
            continue
        if line.rejected_qty > line.received_qty + 1e-9:
            warnings.append({
                "code": "REJECT_EXCEEDS_RECEIVED",
                "item": line.item_name,
                "received_qty": line.received_qty,
                "rejected_qty": line.rejected_qty,
                "message": "Rejected qty melebihi received qty.",
            })
            continue
        accepted = line.accepted_qty
        calculated = round(line.received_qty - line.rejected_qty, 4)
        if accepted is None:
            accepted = calculated
        elif abs(accepted - calculated) > 0.0001:
            warnings.append({
                "code": "ACCEPTED_QTY_MISMATCH",
                "item": line.item_name,
                "provided": accepted,
                "calculated": calculated,
                "message": "accepted_qty tidak sama dengan received_qty - rejected_qty.",
            })
            continue
        receipt_preview.append({
            "reported_item_name": line.item_name,
            "matched_po_item_name": po_line.item_name,
            "match_confidence": score,
            "po_qty": po_line.po_qty,
            "received_qty": line.received_qty,
            "rejected_qty": line.rejected_qty,
            "accepted_qty": accepted,
            "variance_qty": round(float(accepted) - float(po_line.po_qty), 4),
            "unit": line.unit or po_line.unit,
            "notes": line.notes,
            "po_line_index": idx,
        })

    blocking = {
        "RECEIPT_ITEM_NOT_MATCHED_TO_PO",
        "REJECT_EXCEEDS_RECEIVED",
        "ACCEPTED_QTY_MISMATCH",
    }
    return {
        "committed": False,
        "duplicate": False,
        "canCommit": not any(x["code"] in blocking for x in warnings),
        "historicalImport": True,
        "site": payload.site,
        "vendorCode": payload.vendor_code.upper().strip(),
        "distributionDate": payload.distribution_date.isoformat(),
        "poCode": code,
        "poCodeGenerated": not bool(payload.po_code and payload.po_code.strip()),
        "sourceType": payload.source_type.upper().strip(),
        "sourceHash": digest,
        "poLines": [x.model_dump(mode="json") for x in payload.po_lines],
        "receiptLinesEligible": receipt_preview,
        "receiptLinesSkipped": len(payload.receipt_lines) - len(receipt_preview),
        "warnings": warnings,
        "financeTransactionCreated": False,
    }


@router.post("/operations/history/import")
def import_operational_history(payload: HistoricalOperationalImportIn) -> dict[str, Any]:
    """Preview/commit historical operational PO and receipt evidence; never creates finance."""
    require_db()
    result = build_preview(payload)
    digest = result["sourceHash"]

    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """select id,po_code,revision_no,site,vendor_code,status,historical_import
                   from purchase_orders where source_hash=%s""",
                (digest,),
            )
            existing = cur.fetchone()
            if existing:
                result.update({
                    "duplicate": True,
                    "purchaseOrderId": existing["id"],
                    "poCode": existing["po_code"],
                    "status": existing["status"],
                    "committed": bool(payload.commit),
                    "canCommit": True,
                })
                cur.execute(
                    "select id as goodsReceiptId,received_at from goods_receipts where purchase_order_id=%s and historical_import=true order by id",
                    (existing["id"],),
                )
                result["existingReceipts"] = cur.fetchall()
                return result

            cur.execute(
                """select po.id,po.po_code,po.revision_no,po.status,po.historical_import
                   from purchase_orders po
                   left join production_cycles pc on pc.id=po.production_cycle_id
                   where upper(po.site)=upper(%s) and upper(po.vendor_code)=upper(%s)
                     and pc.distribution_date=%s
                   order by po.created_at desc""",
                (payload.site, payload.vendor_code, payload.distribution_date),
            )
            collisions = cur.fetchall()
            if collisions:
                result["warnings"].append({
                    "code": "EXISTING_PO_SAME_SITE_VENDOR_DATE",
                    "message": "Sudah ada PO lain untuk site/vendor/tanggal ini; import baru diblok agar tidak menduplikasi histori.",
                    "existing": collisions,
                })
                result["canCommit"] = False

            if not payload.commit:
                return result
            if not result["canCommit"]:
                raise HTTPException(409, detail={"message": "historical import is not safe to commit", **result})

            cycle_code = f"{payload.site}-{payload.distribution_date.strftime('%Y%m%d')}"
            cur.execute(
                """insert into production_cycles(cycle_code,site,distribution_date,status)
                   values (%s,%s,%s,'HISTORICAL_IMPORTED')
                   on conflict (cycle_code) do update set site=excluded.site
                   returning id""",
                (cycle_code, payload.site, payload.distribution_date),
            )
            cycle_id = cur.fetchone()["id"]

            code = result["poCode"]
            cur.execute("select coalesce(max(revision_no),0)+1 as revision from purchase_orders where po_code=%s", (code,))
            revision = cur.fetchone()["revision"]
            cur.execute(
                """insert into purchase_orders(
                     po_code,revision_no,production_cycle_id,site,vendor_code,status,finalized_at,
                     source_type,source_external_id,source_uri,source_hash,source_raw_text,historical_import
                   ) values (%s,%s,%s,%s,%s,'HISTORICAL_IMPORTED',null,%s,%s,%s,%s,%s,true)
                   returning id""",
                (
                    code, revision, cycle_id, payload.site, payload.vendor_code.upper().strip(),
                    payload.source_type.upper().strip(), payload.source_external_id, payload.source_uri,
                    digest, payload.source_raw_text,
                ),
            )
            po_id = cur.fetchone()["id"]
            po_item_ids: list[int] = []
            for line in payload.po_lines:
                cur.execute(
                    """insert into purchase_order_items(
                         purchase_order_id,item_code,item_name,planned_qty,po_qty,unit,planning_price,po_price,notes
                       ) values (%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id""",
                    (
                        po_id, line.item_code, line.item_name.strip(), line.planned_qty, line.po_qty,
                        line.unit, line.planning_price, line.po_price, line.notes,
                    ),
                )
                po_item_ids.append(cur.fetchone()["id"])

            receipt_id: int | None = None
            eligible = result["receiptLinesEligible"]
            if eligible:
                receipt_key = digest + ":receipt"
                cur.execute(
                    """insert into goods_receipts(
                         purchase_order_id,received_at,source_type,source_external_id,source_key,
                         source_uri,raw_text,match_status,match_confidence,confirmed_at,historical_import
                       ) values (%s,%s,%s,%s,%s,%s,%s,'HISTORICAL_IMPORTED',1.0,%s,true)
                       returning id""",
                    (
                        po_id, payload.received_at or datetime.now(timezone.utc),
                        payload.source_type.upper().strip(), payload.source_external_id, receipt_key,
                        payload.source_uri, payload.source_raw_text, datetime.now(timezone.utc),
                    ),
                )
                receipt_id = cur.fetchone()["id"]
                for line in eligible:
                    idx = int(line["po_line_index"])
                    cur.execute(
                        """insert into goods_receipt_items(
                             goods_receipt_id,purchase_order_item_id,received_qty,rejected_qty,accepted_qty,unit,
                             quality_status,notes,reported_item_name,po_qty_snapshot,variance_qty,
                             match_confidence,match_method
                           ) values (%s,%s,%s,%s,%s,%s,'HISTORICAL_IMPORTED',%s,%s,%s,%s,%s,'HISTORICAL_EXACT_OR_FUZZY')""",
                        (
                            receipt_id, po_item_ids[idx], line["received_qty"], line["rejected_qty"],
                            line["accepted_qty"], line["unit"], line["notes"], line["reported_item_name"],
                            line["po_qty"], line["variance_qty"], line["match_confidence"],
                        ),
                    )

                cur.execute(
                    """select poi.po_qty,coalesce(sum(gri.accepted_qty),0) as accepted_total
                       from purchase_order_items poi
                       left join goods_receipt_items gri on gri.purchase_order_item_id=poi.id
                       where poi.purchase_order_id=%s group by poi.id order by poi.id""",
                    (po_id,),
                )
                totals = cur.fetchall()
                complete = bool(totals) and all(float(x["accepted_total"] or 0) >= float(x["po_qty"] or 0) for x in totals)
                status = "RECEIVED" if complete else "PARTIAL_RECEIVED"
                cur.execute("update purchase_orders set status=%s,updated_at=now() where id=%s", (status, po_id))
            else:
                status = "HISTORICAL_IMPORTED"

            conn.commit()
            result.update({
                "committed": True,
                "duplicate": False,
                "purchaseOrderId": po_id,
                "goodsReceiptId": receipt_id,
                "revisionNo": revision,
                "status": status,
            })
            return result
