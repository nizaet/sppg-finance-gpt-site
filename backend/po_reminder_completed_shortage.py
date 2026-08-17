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


def apply_completed_po_shortage_semantics(
    payload: dict[str, Any],
    completed_lookup: dict[tuple[str, str, date], dict[str, Any]],
) -> dict[str, Any]:
    """Move residual shortage after a completed PO into a review-only state.

    ``shortage_reminder_status`` preserves the original timing state for audit,
    while ``reminder_status=SHORTAGE_REVIEW`` removes the row from the actual
    ordering backlog. A SENT PO therefore cannot simultaneously be shown as
    "Terlambat" or "Kirim hari ini" merely because planning later sees a gap.
    """
    items = payload.get("items") or []
    changed = False
    shortage_count = 0
    enriched_items: list[dict[str, Any]] = []

    for original in items:
        item = dict(original)
        reminder_status = str(item.get("reminder_status") or "").upper()
        dates = _distribution_dates(item)
        missing_names = sorted({str(name).strip() for name in (item.get("missing_item_names") or []) if str(name).strip()})
        remaining_qty = _remaining_qty(item)

        if reminder_status in SHORTAGE_REMINDER_STATUSES and dates and (missing_names or remaining_qty > EPSILON):
            site = str(item.get("site") or "").upper().strip()
            vendor = str(item.get("vendor_code") or "").upper().strip()
            matching_pos = [completed_lookup.get((site, vendor, value)) for value in dates]
            completed_po = _latest_po([po for po in matching_pos if po])
            if completed_po:
                item.update({
                    "purchase_order_id": completed_po.get("id"),
                    "po_code": completed_po.get("po_code"),
                    "po_status": completed_po.get("status"),
                    "po_created_at": completed_po.get("created_at"),
                    "po_sent_at": completed_po.get("sent_at"),
                    "po_workflow_status": "DONE",
                    "po_already_done": True,
                    "shortage_only": True,
                    "shortage_reminder_status": reminder_status,
                    "reminder_status": "SHORTAGE_REVIEW",
                    "shortage_item_names": missing_names,
                    "shortage_distribution_dates": sorted({
                        _as_date(value) for value in (item.get("missing_distribution_dates") or dates)
                        if _as_date(value) is not None
                    }),
                    "shortage_qty_total": remaining_qty,
                    "po_coverage_dates": completed_po.get("po_coverage_dates") or [],
                    "reminder_message": (
                        "PO sudah dilakukan. Sisa kebutuhan dikeluarkan dari antrean PO dan hanya perlu dicek: "
                        "biarkan jika pengurangan memang disengaja, atau koreksi stok dapur bila SO belum terisi."
                    ),
                })
                shortage_count += 1
                changed = True

        enriched_items.append(item)

    if not changed:
        return payload

    result = dict(payload)
    result["items"] = enriched_items
    result["shortageAfterCompletedPoCount"] = shortage_count
    return _recount_ordering(result)


def enrich_completed_po_shortages(payload: dict[str, Any], site: str) -> dict[str, Any]:
    candidates = _shortage_candidates(payload)
    if not candidates:
        return payload

    distribution_dates = sorted({value for item in candidates for value in _distribution_dates(item)})
    lookup = _completed_po_lookup(site, distribution_dates)
    if not lookup:
        return payload
    return apply_completed_po_shortage_semantics(payload, lookup)
