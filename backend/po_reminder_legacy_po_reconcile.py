from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from backend.db import connection, database_ready
from backend.item_taxonomy import stock_type
from backend.po_reminder_completed_shortage import _recount_ordering
from backend.stock_opname_parser import canonical_unit

DONE_STATUSES = {"SENT", "ACKNOWLEDGED", "PARTIAL_RECEIVED", "RECEIVED"}
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


def _type_key(name: Any, unit: Any) -> tuple[str, str]:
    return stock_type(name)["code"], canonical_unit(unit) or ""


def _detail_key(detail: dict[str, Any]) -> tuple[str, str]:
    return str(detail.get("stock_type_code") or "").upper().strip(), canonical_unit(detail.get("unit")) or ""


def _po_newer(candidate: dict[str, Any], current: dict[str, Any] | None) -> bool:
    if current is None:
        return True
    return (
        str(candidate.get("sent_at") or candidate.get("created_at") or ""),
        int(candidate.get("revision_no") or 0),
        int(candidate.get("id") or 0),
    ) >= (
        str(current.get("sent_at") or current.get("created_at") or ""),
        int(current.get("revision_no") or 0),
        int(current.get("id") or 0),
    )


def build_completed_coverage_index(
    pos: list[dict[str, Any]],
    coverage_rows: list[dict[str, Any]],
    direct_items: list[dict[str, Any]],
    coverage_items: list[dict[str, Any]],
) -> dict[tuple[str, date, str, str], dict[str, Any]]:
    """Build completed PO coverage with a safe legacy fallback.

    Explicit per-date coverage items remain authoritative. For old single-date
    completed POs only, a direct purchase_order_items line may fill a missing
    coverage-item row. Aggregate header lines from multi-date POs are never
    attributed to one date because that would duplicate quantities.
    """
    po_by_id = {
        int(po["id"]): dict(po)
        for po in pos
        if str(po.get("status") or "").upper() in DONE_STATUSES
    }
    dates_by_po: dict[int, set[date]] = {}
    for po_id, po in po_by_id.items():
        base = _as_date(po.get("base_distribution_date"))
        if base:
            dates_by_po[po_id] = {base}

    explicit_po_ids: set[int] = set()
    for row in coverage_rows:
        po_id = int(row["purchase_order_id"])
        if po_id not in po_by_id:
            continue
        distribution_date = _as_date(row.get("distribution_date"))
        if distribution_date is None:
            continue
        if po_id not in explicit_po_ids:
            dates_by_po[po_id] = set()
            explicit_po_ids.add(po_id)
        dates_by_po[po_id].add(distribution_date)

    exact_by_po: dict[tuple[int, date, str, str], float] = {}
    for row in coverage_items:
        po_id = int(row["purchase_order_id"])
        if po_id not in po_by_id:
            continue
        distribution_date = _as_date(row.get("distribution_date"))
        if distribution_date is None:
            continue
        type_code, unit = _type_key(row.get("item_name"), row.get("unit"))
        key = (po_id, distribution_date, type_code, unit)
        exact_by_po[key] = round(
            exact_by_po.get(key, 0.0) + max(0.0, float(row.get("po_qty") or 0.0)),
            4,
        )

    direct_by_po: dict[tuple[int, str, str], float] = {}
    for row in direct_items:
        po_id = int(row["purchase_order_id"])
        if po_id not in po_by_id:
            continue
        type_code, unit = _type_key(row.get("item_name"), row.get("unit"))
        key = (po_id, type_code, unit)
        direct_by_po[key] = round(
            direct_by_po.get(key, 0.0) + max(0.0, float(row.get("po_qty") or 0.0)),
            4,
        )

    index: dict[tuple[str, date, str, str], dict[str, Any]] = {}

    def add(
        po_id: int,
        distribution_date: date,
        type_code: str,
        unit: str,
        qty: float,
        basis: str,
    ) -> None:
        if qty <= EPSILON:
            return
        po = po_by_id[po_id]
        key = (
            str(po.get("vendor_code") or "").upper().strip(),
            distribution_date,
            type_code,
            unit,
        )
        row = index.setdefault(key, {"qty": 0.0, "po": None, "basis": set()})
        row["qty"] = round(float(row["qty"]) + qty, 4)
        row["basis"].add(basis)
        if _po_newer(po, row.get("po")):
            row["po"] = po

    for (po_id, distribution_date, type_code, unit), qty in exact_by_po.items():
        add(po_id, distribution_date, type_code, unit, qty, "EXPLICIT_COVERAGE_ITEM")

    for (po_id, type_code, unit), qty in direct_by_po.items():
        po_dates = sorted(dates_by_po.get(po_id) or [])
        if len(po_dates) != 1:
            continue
        distribution_date = po_dates[0]
        if exact_by_po.get((po_id, distribution_date, type_code, unit), 0.0) > EPSILON:
            continue
        add(
            po_id,
            distribution_date,
            type_code,
            unit,
            qty,
            "LEGACY_SINGLE_DATE_DIRECT_ITEM",
        )

    for value in index.values():
        value["basis"] = sorted(value["basis"])
    return index


def apply_completed_coverage_index(
    payload: dict[str, Any],
    coverage_index: dict[tuple[str, date, str, str], dict[str, Any]],
) -> dict[str, Any]:
    if not payload.get("items") or not coverage_index:
        return payload

    changed = False
    enriched_items: list[dict[str, Any]] = []

    for original in payload.get("items") or []:
        item = dict(original)
        vendor = str(item.get("vendor_code") or "").upper().strip()
        details: list[dict[str, Any]] = []
        latest_po: dict[str, Any] | None = None

        for original_detail in item.get("requirement_details") or []:
            detail = dict(original_detail)
            distribution_date = _as_date(detail.get("distribution_date"))
            type_code, unit = _detail_key(detail)
            match = (
                coverage_index.get((vendor, distribution_date, type_code, unit))
                if distribution_date
                else None
            )
            if match:
                completed_qty = max(
                    float(detail.get("completed_po_qty") or 0.0),
                    float(match.get("qty") or 0.0),
                )
                covered_qty = max(
                    float(detail.get("covered_po_qty") or 0.0),
                    completed_qty,
                )
                recommended = max(0.0, float(detail.get("recommended_po_qty") or 0.0))
                remaining = max(0.0, round(recommended - covered_qty, 4))
                po = match.get("po") or {}
                detail.update({
                    "completed_po_qty": round(completed_qty, 4),
                    "covered_po_qty": round(covered_qty, 4),
                    "remaining_po_qty": remaining,
                    "coverage_stage": "DONE" if remaining <= EPSILON else detail.get("coverage_stage") or "OPEN",
                    "ordering_state": "COVERED" if remaining <= EPSILON else "ORDERED_PARTIAL",
                    "completed_purchase_order_id": po.get("id"),
                    "completed_po_code": po.get("po_code"),
                    "completed_po_status": po.get("status"),
                    "completed_po_created_at": po.get("created_at"),
                    "completed_po_sent_at": po.get("sent_at"),
                    "legacy_po_reconcile_basis": match.get("basis") or [],
                })
                if _po_newer(po, latest_po):
                    latest_po = po
                changed = True
            details.append(detail)

        item["requirement_details"] = details
        if details:
            open_details = [
                detail
                for detail in details
                if float(detail.get("remaining_po_qty") or 0.0) > EPSILON
            ]
            item["missing_item_names"] = sorted({
                str(name).strip()
                for detail in open_details
                for name in (detail.get("item_names") or [])
                if str(name).strip()
            })
            item["missing_distribution_dates"] = sorted({
                value
                for value in (_as_date(detail.get("distribution_date")) for detail in open_details)
                if value is not None
            })
            if not open_details:
                item["reminder_status"] = "DONE"
                item["po_workflow_status"] = "DONE"
                item["po_already_done"] = True
                item["shortage_only"] = False
                if latest_po:
                    item.update({
                        "purchase_order_id": latest_po.get("id"),
                        "po_code": latest_po.get("po_code"),
                        "po_status": latest_po.get("status"),
                        "po_created_at": latest_po.get("created_at"),
                        "po_sent_at": latest_po.get("sent_at"),
                    })
                item["reminder_message"] = (
                    "Kebutuhan sudah tercakup PO aktual. Tidak ada pekerjaan PO tersisa."
                )
        enriched_items.append(item)

    if not changed:
        return payload
    result = dict(payload)
    result["items"] = enriched_items
    result["legacyCompletedPoReconciled"] = True
    return _recount_ordering(result)


def _correct_cemplang_tofu_vendor(
    payload: dict[str, Any],
    target: date,
    rules: list[dict[str, Any]],
    vendor_name: str,
) -> dict[str, Any]:
    changed = False
    items: list[dict[str, Any]] = []

    for original in payload.get("items") or []:
        item = dict(original)
        details = [dict(detail) for detail in (item.get("requirement_details") or [])]
        tofu_only = bool(details) and all(
            str(detail.get("stock_type_code") or "").upper() == "TAHU"
            for detail in details
        )
        if (
            str(item.get("site") or "").upper() == "CEMPLANG"
            and str(item.get("vendor_code") or "").upper() == "KOPERASI"
            and tofu_only
        ):
            cooking_dates = sorted({
                value
                for detail in details
                for value in (
                    _as_date(raw)
                    for raw in (detail.get("cooking_dates") or [])
                )
                if value is not None
            })
            candidates = []
            for rule in rules:
                if str(rule.get("vendor_code") or "").upper() != "HAJI_BADRI":
                    continue
                site_code = str(rule.get("site_code") or "").upper().strip()
                if site_code not in {"", "CEMPLANG"}:
                    continue
                category = str(rule.get("category_code") or "").upper()
                if category and "TAHU" not in category:
                    continue
                if cooking_dates:
                    cook = cooking_dates[0]
                    if rule.get("effective_from") and rule["effective_from"] > cook:
                        continue
                    if rule.get("effective_to") and rule["effective_to"] < cook:
                        continue
                candidates.append(rule)
            candidates.sort(
                key=lambda rule: (
                    str(rule.get("site_code") or "").upper() == "CEMPLANG",
                    "TAHU" in str(rule.get("category_code") or "").upper(),
                    rule.get("effective_from") or date.min,
                    int(rule.get("id") or 0),
                ),
                reverse=True,
            )
            rule = candidates[0] if candidates else None

            item["vendor_code"] = "HAJI_BADRI"
            item["vendor_name"] = vendor_name or "Haji Badri"
            item["procurement_bucket"] = "TOFU"
            for detail in details:
                detail["item_families"] = ["TOFU"]
            item["requirement_details"] = details

            if rule and rule.get("lead_time_days_before_cooking") is not None and cooking_dates:
                lead = int(rule["lead_time_days_before_cooking"])
                po_date = cooking_dates[0] - timedelta(days=lead)
                item["lead_time_days_before_cooking"] = lead
                item["po_date"] = po_date
                status = str(item.get("reminder_status") or "").upper()
                if status in {"OVERDUE", "DUE_TODAY", "UPCOMING"}:
                    item["reminder_status"] = (
                        "OVERDUE"
                        if po_date < target
                        else "DUE_TODAY"
                        if po_date == target
                        else "UPCOMING"
                    )

            item["vendor_reconciled_from"] = "KOPERASI"
            item["vendor_reconcile_basis"] = (
                "CEMPLANG_TAHU_NAME_OVERRIDES_STALE_CATEGORY"
            )
            changed = True
        items.append(item)

    if not changed:
        return payload
    result = dict(payload)
    result["items"] = items
    result["tofuVendorReconciled"] = True
    return _recount_ordering(result)


def reconcile_legacy_completed_pos(
    payload: dict[str, Any],
    site: str,
    target: date,
) -> dict[str, Any]:
    normalized_site = str(site or payload.get("site") or "").upper().strip()
    if normalized_site not in {"MAJA", "CEMPLANG"} or not database_ready():
        return payload

    requested_dates = sorted({
        value
        for item in (payload.get("items") or [])
        for detail in (item.get("requirement_details") or [])
        for value in [_as_date(detail.get("distribution_date"))]
        if value is not None
    })
    if not requested_dates:
        return payload

    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select vr.*
                from vendor_rules vr
                where vr.effective_from <= %s
                  and (vr.effective_to is null or vr.effective_to >= %s)
                """,
                (max(requested_dates), min(requested_dates) - timedelta(days=30)),
            )
            rules = [dict(row) for row in cur.fetchall()]
            cur.execute("select name from entities where code='HAJI_BADRI' limit 1")
            vendor_row = cur.fetchone()
            vendor_name = (
                str(vendor_row.get("name") or "Haji Badri")
                if vendor_row
                else "Haji Badri"
            )

    payload = _correct_cemplang_tofu_vendor(payload, target, rules, vendor_name)

    vendors = sorted({
        str(item.get("vendor_code") or "").upper().strip()
        for item in (payload.get("items") or [])
        if item.get("vendor_code")
    })
    if not vendors:
        return payload

    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select po.id, po.po_code, po.revision_no,
                       upper(po.vendor_code) vendor_code,
                       upper(po.status) status, po.created_at, po.sent_at,
                       pc.distribution_date base_distribution_date
                from purchase_orders po
                join production_cycles pc on pc.id=po.production_cycle_id
                where upper(po.site)=%s
                  and upper(po.vendor_code)=any(%s)
                  and upper(coalesce(po.status,''))=any(%s)
                  and coalesce(po.historical_import,false)=false
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
                (
                    normalized_site,
                    vendors,
                    sorted(DONE_STATUSES),
                    requested_dates,
                    requested_dates,
                ),
            )
            pos = [dict(row) for row in cur.fetchall()]
            po_ids = [int(po["id"]) for po in pos]
            if not po_ids:
                return payload

            cur.execute(
                """
                select purchase_order_id, distribution_date
                from purchase_order_coverage
                where purchase_order_id=any(%s)
                """,
                (po_ids,),
            )
            coverage_rows = [dict(row) for row in cur.fetchall()]

            cur.execute(
                """
                select purchase_order_id, item_name, po_qty, unit
                from purchase_order_items
                where purchase_order_id=any(%s)
                  and coalesce(po_qty,0)>0
                """,
                (po_ids,),
            )
            direct_items = [dict(row) for row in cur.fetchall()]

            cur.execute(
                """
                select poc.purchase_order_id, poc.distribution_date,
                       poci.item_name, poci.po_qty, poci.unit
                from purchase_order_coverage poc
                join purchase_order_coverage_items poci
                  on poci.purchase_order_coverage_id=poc.id
                where poc.purchase_order_id=any(%s)
                  and coalesce(poci.po_qty,0)>0
                """,
                (po_ids,),
            )
            coverage_items = [dict(row) for row in cur.fetchall()]

    index = build_completed_coverage_index(
        pos,
        coverage_rows,
        direct_items,
        coverage_items,
    )
    return apply_completed_coverage_index(payload, index)
