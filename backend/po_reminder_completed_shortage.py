from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from backend.db import connection, database_ready

# A reminder can still have a residual shortage while the original PO workflow
# itself is already completed. Those rows must not stay in the ordering queue
# (OVERDUE / DUE_TODAY), otherwise a SENT PO is presented as work that still
# needs to be ordered. They are moved to SHORTAGE_REVIEW instead.
DONE_PO_STATUSES = {"SENT", "ACKNOWLEDGED", "PARTIAL_RECEIVED", "RECEIVED"}
SHORTAGE_REMINDER_STATUSES = {"OVERDUE", "DUE_TODAY", "UPCOMING"}
EPSILON = 0.0001


def _as_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _distribution_dates(item: dict[str, Any]) -> list[date]:
    raw_dates = item.get("distribution_dates") or item.get("coverage_dates") or []
    if not raw_dates and item.get("distribution_date"):
        raw_dates = [item.get("distribution_date")]
    result = {_as_date(value) for value in raw_dates}
    return sorted(value for value in result if value is not None)


def _remaining_qty(item: dict[str, Any]) -> float:
    total = 0.0
    for detail in item.get("requirement_details") or []:
        total += max(0.0, float(detail.get("remaining_po_qty") or 0.0))
    return round(total, 4)


def _latest_po(pos: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not pos:
        return None
    return max(
        pos,
        key=lambda po: (
            str(po.get("sent_at") or po.get("created_at") or ""),
            int(po.get("revision_no") or 0),
            int(po.get("id") or 0),
        ),
    )


def _shortage_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for item in payload.get("items") or []:
        if str(item.get("reminder_status") or "").upper() not in SHORTAGE_REMINDER_STATUSES:
            continue
        missing_names = [name for name in (item.get("missing_item_names") or []) if str(name).strip()]
        if not missing_names and _remaining_qty(item) <= EPSILON:
            continue
        if not _distribution_dates(item):
            continue
        candidates.append(item)
    return candidates


def _recount_ordering(payload: dict[str, Any]) -> dict[str, Any]:
    """Recalculate only reminder counters affected by SHORTAGE_REVIEW.

    A review-only residual must not inflate overdue, due-today, or tomorrow
    ordering badges. Other statuses remain untouched.
    """
    target = _as_date(payload.get("date"))
    if target is None:
        return payload
    items = payload.get("items") or []
    actionable = {"OVERDUE", "DUE_TODAY", "DRAFT_NEEDS_FINAL", "READY_TO_SEND"}
    future_actionable = actionable | {"UPCOMING"}
    tomorrow = target + timedelta(days=1)
    result = dict(payload)
    result["dueCount"] = sum(
        1 for item in items
        if (_as_date(item.get("po_date")) or date.max) <= target
        and str(item.get("reminder_status") or "").upper() in actionable
    )
    result["overdueCount"] = sum(
        1 for item in items
        if (_as_date(item.get("po_date")) or date.max) < target
        and str(item.get("reminder_status") or "").upper() == "OVERDUE"
    )
    result["tomorrowCount"] = sum(
        1 for item in items
        if _as_date(item.get("po_date")) == tomorrow
        and str(item.get("reminder_status") or "").upper() in future_actionable
    )
    result["shortageReviewCount"] = sum(
        1 for item in items
        if str(item.get("reminder_status") or "").upper() == "SHORTAGE_REVIEW"
    )
    return result


def _completed_po_lookup(site: str, distribution_dates: list[date]) -> dict[tuple[str, str, date], dict[str, Any]]:
    """Return latest completed PO keyed by site + vendor + distribution date.

    This intentionally does not claim item/qty coverage. v4 already calculated the
    residual shortage. This lookup only answers a different question: "was a PO for
    this vendor and distribution date already actually done/sent?"
    """
    normalized_site = str(site or "").upper().strip()
    dates = sorted(set(distribution_dates))
    if normalized_site not in {"MAJA", "CEMPLANG"} or not dates or not database_ready():
        return {}

    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select po.id, po.po_code, po.revision_no,
                       upper(po.site) site, upper(po.vendor_code) vendor_code,
                       upper(po.status) status, po.created_at, po.sent_at,
                       pc.distribution_date base_distribution_date
                from purchase_orders po
                join production_cycles pc on pc.id=po.production_cycle_id
                where upper(po.site)=%s
                  and upper(coalesce(po.status,''))=any(%s)
                  and (
                    pc.distribution_date=any(%s)
                    or exists (
                      select 1
                      from purchase_order_coverage poc
                      where poc.purchase_order_id=po.id
                        and poc.distribution_date=any(%s)
                    )
                  )
                order by coalesce(po.sent_at, po.created_at) desc,
                         po.revision_no desc,
                         po.id desc
                """,
                (normalized_site, list(DONE_PO_STATUSES), dates, dates),
            )
            pos = [dict(row) for row in cur.fetchall()]

            po_ids = [int(po["id"]) for po in pos]
            coverage_by_po: dict[int, set[date]] = {}
            if po_ids:
                cur.execute(
                    """
                    select purchase_order_id, distribution_date
                    from purchase_order_coverage
                    where purchase_order_id=any(%s)
                    """,
                    (po_ids,),
                )
                for row in cur.fetchall():
                    coverage_by_po.setdefault(int(row["purchase_order_id"]), set()).add(row["distribution_date"])

    target_dates = set(dates)
    lookup: dict[tuple[str, str, date], dict[str, Any]] = {}
    for po in pos:
        po_id = int(po["id"])
        explicit_dates = coverage_by_po.get(po_id)
        po_dates = explicit_dates if explicit_dates is not None else {po.get("base_distribution_date")}
        po_dates = {value for value in po_dates if value in target_dates}
        if not po_dates:
            continue
        enriched_po = dict(po)
        enriched_po["po_coverage_dates"] = sorted(po_dates)
        for distribution_date in po_dates:
            key = (str(po.get("site") or "").upper(), str(po.get("vendor_code") or "").upper(), distribution_date)
            # SQL is already newest first; do not replace a newer completed PO.
            lookup.setdefault(key, enriched_po)
    return lookup


def _effective_completed_qty(detail: dict[str, Any]) -> float:
    return max(
        0.0,
        float(detail.get("completed_po_qty") or 0.0),
        float(detail.get("batch_completed_po_qty") or 0.0),
    )


def _detail_ordering_state(detail: dict[str, Any]) -> str:
    remaining = max(0.0, float(detail.get("remaining_po_qty") or 0.0))
    if remaining <= EPSILON:
        return "COVERED"
    completed = _effective_completed_qty(detail)
    if completed > EPSILON:
        return "ORDERED_PARTIAL"
    covered = max(0.0, float(detail.get("covered_po_qty") or 0.0))
    if covered > EPSILON:
        return "IN_APP_PARTIAL"
    return "NOT_ORDERED"


def _detail_names(details: list[dict[str, Any]], state: str) -> list[str]:
    return sorted({
        str(name).strip()
        for detail in details
        if str(detail.get("ordering_state") or "").upper() == state
        for name in (detail.get("item_names") or [])
        if str(name).strip()
    })


def _latest_exact_completed_po(details: list[dict[str, Any]]) -> dict[str, Any] | None:
    rows: list[dict[str, Any]] = []
    for detail in details:
        po_id = detail.get("completed_purchase_order_id")
        if not po_id:
            continue
        rows.append({
            "id": po_id,
            "po_code": detail.get("completed_po_code"),
            "status": detail.get("completed_po_status"),
            "created_at": detail.get("completed_po_created_at"),
            "sent_at": detail.get("completed_po_sent_at"),
            "revision_no": 0,
        })
    return _latest_po(rows)


def apply_completed_po_shortage_semantics(
    payload: dict[str, Any],
    completed_lookup: dict[tuple[str, str, date], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Use exact requirement coverage, not broad vendor/date PO existence.

    A completed KOPERASI PO that contains other lines must not turn an un-ordered
    Kecap/Telur/Tepung requirement into a completed-PO residual. Each requirement
    is classified from its exact item type + unit + distribution-date coverage.
    """
    del completed_lookup
    items = payload.get("items") or []
    changed = False
    shortage_count = 0
    enriched_items: list[dict[str, Any]] = []

    for original in items:
        item = dict(original)
        status = str(item.get("reminder_status") or "").upper()
        details = [dict(detail) for detail in (item.get("requirement_details") or [])]
        open_details: list[dict[str, Any]] = []
        for detail in details:
            detail["ordering_state"] = _detail_ordering_state(detail)
            if float(detail.get("remaining_po_qty") or 0.0) > EPSILON:
                open_details.append(detail)
        item["requirement_details"] = details

        if open_details:
            item["not_ordered_item_names"] = _detail_names(open_details, "NOT_ORDERED")
            item["partial_shortage_item_names"] = _detail_names(open_details, "ORDERED_PARTIAL")
            item["in_app_partial_item_names"] = _detail_names(open_details, "IN_APP_PARTIAL")
            item["not_ordered_count"] = sum(1 for d in open_details if d["ordering_state"] == "NOT_ORDERED")
            item["partial_shortage_count"] = sum(1 for d in open_details if d["ordering_state"] == "ORDERED_PARTIAL")
            item["in_app_partial_count"] = sum(1 for d in open_details if d["ordering_state"] == "IN_APP_PARTIAL")
            changed = True

        if status in SHORTAGE_REMINDER_STATUSES and open_details:
            all_completed_partial = all(d["ordering_state"] == "ORDERED_PARTIAL" for d in open_details)
            if all_completed_partial:
                exact_po = _latest_exact_completed_po(open_details)
                if exact_po:
                    item.update({
                        "purchase_order_id": exact_po.get("id"),
                        "po_code": exact_po.get("po_code"),
                        "po_status": exact_po.get("status"),
                        "po_created_at": exact_po.get("created_at"),
                        "po_sent_at": exact_po.get("sent_at"),
                    })
                item.update({
                    "po_workflow_status": "DONE",
                    "po_already_done": True,
                    "shortage_only": True,
                    "shortage_reminder_status": status,
                    "reminder_status": "SHORTAGE_REVIEW",
                    "shortage_item_names": sorted({
                        str(name).strip()
                        for detail in open_details
                        for name in (detail.get("item_names") or [])
                        if str(name).strip()
                    }),
                    "shortage_distribution_dates": sorted({
                        value
                        for value in (_as_date(detail.get("distribution_date")) for detail in open_details)
                        if value is not None
                    }),
                    "shortage_qty_total": round(sum(float(d.get("remaining_po_qty") or 0.0) for d in open_details), 4),
                    "ordering_state_summary": "ORDERED_PARTIAL",
                    "reminder_message": (
                        "Item sudah pernah masuk PO selesai/SENT tetapi qty masih kurang. "
                        "Buat PO Tambahan, Konfirmasi stok gudang, atau Sudah dicek / biarkan."
                    ),
                })
                shortage_count += 1
            else:
                item["shortage_only"] = False
                item["ordering_state_summary"] = "NEEDS_ORDERING"
                if item.get("not_ordered_count"):
                    item["reminder_message"] = (
                        "Masih ada item yang belum pernah dipesan untuk tanggal distribusi ini. "
                        "Buat PO, konfirmasi PO sudah dilakukan, atau Konfirmasi stok gudang."
                    )

        enriched_items.append(item)

    if not changed:
        return payload
    result = dict(payload)
    result["items"] = enriched_items
    result["shortageAfterCompletedPoCount"] = shortage_count
    return _recount_ordering(result)


def enrich_completed_po_shortages(payload: dict[str, Any], site: str) -> dict[str, Any]:
    # Public signature retained; exact item-level coverage is already in v4.
    del site
    return apply_completed_po_shortage_semantics(payload)
