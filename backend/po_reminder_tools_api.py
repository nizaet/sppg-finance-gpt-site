from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.db import connection, database_ready
from backend.operational_api import PurchaseOrderCreateIn, PurchaseOrderCoverageIn, normalize_site, require_db
from backend.stock_opname_parser import canonical_unit

router = APIRouter(tags=["po-reminder-tools"])

ACTIVE_PO_STATUSES = {"DRAFT", "FINALIZED", "SENT", "ACKNOWLEDGED", "PARTIAL_RECEIVED", "RECEIVED"}
OVERRIDE_RESOLUTIONS = {"SUFFICIENT", "MANUAL_PO", "CHECKED"}


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _date_text(value: Any) -> str:
    parsed = _as_date(value)
    return parsed.isoformat() if parsed else ""


def reminder_key_for(item: dict[str, Any]) -> str:
    """Stable identity for one operational reminder row.

    Quantity and current status are deliberately excluded.  A manual resolution
    therefore survives harmless recalculation, while a new item/date produces a
    different key and cannot be silently hidden by an old override.
    """
    requirements = []
    for detail in item.get("requirement_details") or []:
        requirements.append({
            "distribution_date": _date_text(detail.get("distribution_date")),
            "stock_type_code": str(detail.get("stock_type_code") or "").upper().strip(),
            "unit": canonical_unit(detail.get("unit")) or "",
            "item_names": sorted({str(name).strip() for name in (detail.get("item_names") or []) if str(name).strip()}),
        })
    requirements.sort(key=lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True))
    identity = {
        "site": str(item.get("site") or "").upper().strip(),
        "vendor_code": str(item.get("vendor_code") or "").upper().strip(),
        "po_date": _date_text(item.get("po_date")),
        "procurement_bucket": str(item.get("procurement_bucket") or "DEFAULT").upper().strip(),
        "distribution_dates": sorted({_date_text(value) for value in (item.get("distribution_dates") or [item.get("distribution_date")]) if _date_text(value)}),
        "item_names": sorted({str(name).strip() for name in (item.get("item_names") or []) if str(name).strip()}),
        "requirements": requirements,
    }
    raw = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "POREM-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def decorate_reminder_keys(payload: dict[str, Any]) -> dict[str, Any]:
    items = payload.get("items") or []
    if not items:
        return payload
    result = dict(payload)
    result["items"] = [{**item, "reminder_key": reminder_key_for(item)} for item in items]
    return result


def _recount(payload: dict[str, Any], target: date) -> dict[str, Any]:
    result = dict(payload)
    items = result.get("items") or []
    actionable = {"OVERDUE", "DUE_TODAY", "DRAFT_NEEDS_FINAL", "READY_TO_SEND"}
    future_actionable = actionable | {"UPCOMING"}
    tomorrow = target + timedelta(days=1)
    result["dueCount"] = sum(
        1 for item in items
        if (_as_date(item.get("po_date")) or date.max) <= target
        and str(item.get("reminder_status") or "").upper() in actionable
    )
    result["tomorrowCount"] = sum(
        1 for item in items
        if _as_date(item.get("po_date")) == tomorrow
        and str(item.get("reminder_status") or "").upper() in future_actionable
    )
    result["overdueCount"] = sum(
        1 for item in items
        if (_as_date(item.get("po_date")) or date.max) < target
        and str(item.get("reminder_status") or "").upper() == "OVERDUE"
    )
    result["shortageReviewCount"] = sum(
        1 for item in items
        if str(item.get("reminder_status") or "").upper() == "SHORTAGE_REVIEW"
    )
    return result


def apply_reminder_overrides(payload: dict[str, Any], site: str, target: date) -> dict[str, Any]:
    """Apply operator resolution metadata after strict reminder calculation."""
    decorated = decorate_reminder_keys(payload)
    items = decorated.get("items") or []
    keys = [str(item.get("reminder_key") or "") for item in items if item.get("reminder_key")]
    normalized_site = str(site or decorated.get("site") or "").upper().strip()
    if not keys or normalized_site not in {"MAJA", "CEMPLANG"} or not database_ready():
        return _recount(decorated, target)

    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select reminder_key, resolution, note, metadata, created_at, updated_at
                    from po_reminder_overrides
                    where upper(site)=%s and active=true and reminder_key=any(%s)
                    """,
                    (normalized_site, keys),
                )
                overrides = {str(row["reminder_key"]): dict(row) for row in cur.fetchall()}
    except Exception:
        # Keep reminder reads available during a rolling deploy before migration
        # has completed. The migration is still required for writes.
        return _recount(decorated, target)

    if not overrides:
        return _recount(decorated, target)

    changed = False
    enriched: list[dict[str, Any]] = []
    for original in items:
        item = dict(original)
        override = overrides.get(str(item.get("reminder_key") or ""))
        if not override:
            enriched.append(item)
            continue
        resolution = str(override.get("resolution") or "").upper()
        original_status = str(item.get("reminder_status") or "").upper()
        if resolution == "SUFFICIENT":
            label = "Sudah mencukupi (override)"
            message = "Operator mengonfirmasi kebutuhan sudah mencukupi. Reminder ditutup tanpa mengubah stok atau PO."
        elif resolution == "CHECKED":
            label = "Sudah dicek / dibiarkan"
            message = "PO sudah dilakukan dan sisa kebutuhan telah dicek operator. Selisih diterima tanpa membuat PO atau stok fiktif."
        else:
            label = "PO manual sudah dilakukan"
            message = "Operator mengonfirmasi PO telah dilakukan di luar workflow aplikasi. Reminder ditutup tanpa membuat PO fiktif."
        item.update({
            "override_original_status": original_status,
            "reminder_status": "DONE",
            "po_workflow_status": "DONE_REVIEWED" if resolution == "CHECKED" else "DONE_MANUAL",
            "reminder_override": True,
            "reminder_override_resolution": resolution,
            "reminder_override_label": label,
            "reminder_override_note": override.get("note"),
            "reminder_override_created_at": override.get("created_at"),
            "reminder_override_updated_at": override.get("updated_at"),
            "reminder_message": message,
        })
        if resolution == "MANUAL_PO":
            item["po_already_done"] = True
            item["manual_po_confirmed"] = True
        changed = True
        enriched.append(item)

    if not changed:
        return decorated
    result = dict(decorated)
    result["items"] = enriched
    result["manualOverrideCount"] = sum(1 for item in enriched if item.get("reminder_override"))
    return _recount(result, target)


class ReminderOverrideIn(BaseModel):
    site: Literal["MAJA", "CEMPLANG"]
    reminder_key: str = Field(min_length=8, max_length=100)
    vendor_code: str = Field(min_length=1, max_length=100)
    resolution: Literal["SUFFICIENT", "MANUAL_PO", "CHECKED"]
    note: str | None = Field(default=None, max_length=500)
    metadata: dict[str, Any] = Field(default_factory=dict)


@router.post("/po-reminders/override")
def save_po_reminder_override(payload: ReminderOverrideIn) -> dict[str, Any]:
    require_db()
    site = normalize_site(payload.site)
    vendor = payload.vendor_code.upper().strip()
    resolution = payload.resolution.upper().strip()
    if resolution not in OVERRIDE_RESOLUTIONS:
        raise HTTPException(400, "resolution tidak valid")
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("select 1 from entities where code=%s and active=true", (vendor,))
            if not cur.fetchone():
                raise HTTPException(404, "vendor tidak ditemukan")
            cur.execute(
                """
                insert into po_reminder_overrides(
                  reminder_key,site,vendor_code,resolution,note,metadata,active
                ) values (%s,%s,%s,%s,%s,%s::jsonb,true)
                on conflict (reminder_key) where active=true
                do update set
                  site=excluded.site,
                  vendor_code=excluded.vendor_code,
                  resolution=excluded.resolution,
                  note=excluded.note,
                  metadata=excluded.metadata,
                  updated_at=now()
                returning id,reminder_key,site,vendor_code,resolution,note,created_at,updated_at
                """,
                (
                    payload.reminder_key, site, vendor, resolution, payload.note,
                    json.dumps(payload.metadata, ensure_ascii=False),
                ),
            )
            row = dict(cur.fetchone())
        conn.commit()
    return {**row, "saved": True}


@router.delete("/po-reminders/override/{reminder_key}")
def clear_po_reminder_override(reminder_key: str) -> dict[str, Any]:
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update po_reminder_overrides
                set active=false,updated_at=now()
                where reminder_key=%s and active=true
                returning id
                """,
                (reminder_key,),
            )
            row = cur.fetchone()
        conn.commit()
    return {"reminderKey": reminder_key, "cleared": bool(row)}


def _insert_split_po(cur: Any, payload: PurchaseOrderCreateIn, site: str, vendor: str) -> tuple[int, int, list[date]]:
    coverage_dates = [row.distribution_date for row in payload.coverage] or [payload.distribution_date]
    if len(set(coverage_dates)) != len(coverage_dates):
        raise HTTPException(400, "tanggal cakupan PO tidak boleh duplikat")
    if min(coverage_dates) != payload.distribution_date:
        raise HTTPException(400, "distribution_date PO harus tanggal pertama dalam cakupan")

    cur.execute("select 1 from entities where code=%s and active=true", (vendor,))
    if not cur.fetchone():
        raise HTTPException(404, "vendor tidak ditemukan")

    # Split PO intentionally allows the same vendor + distribution date.  Only an
    # exact active PO code is treated as duplicate, preventing double-clicks while
    # allowing Telur H-1 and dry goods H-0 to be separate KOPERASI orders.
    cur.execute(
        """
        select id,po_code,revision_no,status
        from purchase_orders
        where po_code=%s and upper(status)=any(%s)
        order by revision_no desc,created_at desc
        limit 1
        """,
        (payload.po_code, sorted(ACTIVE_PO_STATUSES)),
    )
    existing = cur.fetchone()
    if existing:
        raise HTTPException(409, f"split PO {existing['po_code']} rev {existing['revision_no']} sudah aktif ({existing['status']})")

    cycle_code = f"{site}-{payload.distribution_date.strftime('%Y%m%d')}"
    cur.execute(
        """
        insert into production_cycles(cycle_code,site,distribution_date,cooking_at,status)
        values (%s,%s,%s,%s,'PLANNING')
        on conflict (cycle_code) do update
          set cooking_at=coalesce(production_cycles.cooking_at,excluded.cooking_at)
        returning id
        """,
        (cycle_code, site, payload.distribution_date, payload.cooking_at),
    )
    cycle_id = int(cur.fetchone()["id"])
    cur.execute("select coalesce(max(revision_no),0)+1 as revision from purchase_orders where po_code=%s", (payload.po_code,))
    revision = int(cur.fetchone()["revision"])
    cur.execute(
        """
        insert into purchase_orders(
          po_code,revision_no,production_cycle_id,site,vendor_code,status,
          source_planning_snapshot_id
        ) values (%s,%s,%s,%s,%s,'DRAFT',%s)
        returning id
        """,
        (payload.po_code, revision, cycle_id, site, vendor, payload.source_planning_snapshot_id),
    )
    po_id = int(cur.fetchone()["id"])

    for item in payload.items:
        cur.execute(
            """
            insert into purchase_order_items(
              purchase_order_id,item_code,item_name,planning_snapshot_item_id,planned_qty,po_qty,unit,
              planning_price,po_price,item_aliases,notes
            ) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
            """,
            (
                po_id, item.item_code, item.item_name.strip(), item.planning_snapshot_item_id,
                item.planned_qty, item.po_qty, canonical_unit(item.unit), item.planning_price,
                item.po_price, json.dumps(item.aliases, ensure_ascii=False), item.notes,
            ),
        )

    coverage_rows = payload.coverage or [PurchaseOrderCoverageIn(
        distribution_date=payload.distribution_date,
        cooking_date=payload.cooking_at.date() if payload.cooking_at else None,
        source_planning_snapshot_id=payload.source_planning_snapshot_id,
        items=payload.items,
    )]
    for coverage in coverage_rows:
        cur.execute(
            """
            insert into purchase_order_coverage(
              purchase_order_id,distribution_date,cooking_date,planning_snapshot_id
            ) values (%s,%s,%s,%s) returning id
            """,
            (po_id, coverage.distribution_date, coverage.cooking_date, coverage.source_planning_snapshot_id),
        )
        coverage_id = int(cur.fetchone()["id"])
        for item in coverage.items:
            cur.execute(
                """
                insert into purchase_order_coverage_items(
                  purchase_order_coverage_id,planning_snapshot_item_id,item_code,item_name,
                  planned_qty,po_qty,unit
                ) values (%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    coverage_id, item.planning_snapshot_item_id, item.item_code,
                    item.item_name.strip(), item.planned_qty, item.po_qty, canonical_unit(item.unit),
                ),
            )
    return po_id, revision, sorted(coverage_dates)


@router.post("/purchase-orders/split")
def create_split_purchase_order(payload: PurchaseOrderCreateIn) -> dict[str, Any]:
    """Create one intentionally separate DRAFT PO for selected items only."""
    require_db()
    if str(payload.status or "DRAFT").upper() != "DRAFT":
        raise HTTPException(400, "split PO harus dibuat sebagai DRAFT")
    site = normalize_site(payload.site)
    vendor = payload.vendor_code.upper().strip()
    if not payload.items or not any(float(item.po_qty or 0) > 0 for item in payload.items):
        raise HTTPException(400, "split PO harus memiliki minimal satu item qty > 0")
    with connection() as conn:
        with conn.cursor() as cur:
            po_id, revision, coverage_dates = _insert_split_po(cur, payload, site, vendor)
        conn.commit()
    return {
        "alreadyExists": False,
        "splitOrder": True,
        "purchaseOrderId": po_id,
        "poCode": payload.po_code,
        "revisionNo": revision,
        "status": "DRAFT",
        "itemCount": len(payload.items),
        "coverageDates": coverage_dates,
        "coverageDayCount": len(coverage_dates),
    }
