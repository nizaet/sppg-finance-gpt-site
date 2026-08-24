from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta
from typing import Any

from backend.db import connection, database_ready
from backend.item_taxonomy import item_family
from backend.stock_opname_parser import canonical_unit

DONE_PO_STATUSES = {"SENT", "ACKNOWLEDGED", "PARTIAL_RECEIVED", "RECEIVED"}
TIMING_STATUSES = {"OVERDUE", "DUE_TODAY", "UPCOMING"}
EPSILON = 0.0001


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


def _timing_status(po_date: date, target: date) -> str:
    if po_date < target:
        return "OVERDUE"
    if po_date == target:
        return "DUE_TODAY"
    return "UPCOMING"


def _wikian_key(name: Any, unit: Any) -> tuple[str, str]:
    """WIKIAN pools chicken cuts by family, but never across different units."""
    return item_family(name, None), canonical_unit(unit) or ""


def _recount(payload: dict[str, Any], target: date) -> dict[str, Any]:
    result = dict(payload)
    items = result.get("items") or []
    actionable = {"OVERDUE", "DUE_TODAY", "DRAFT_NEEDS_FINAL", "READY_TO_SEND"}
    tomorrow = target + timedelta(days=1)
    result["dueCount"] = sum(
        1
        for item in items
        if _as_date(item.get("po_date")) is not None
        and _as_date(item.get("po_date")) <= target
        and str(item.get("reminder_status") or "").upper() in actionable
    )
    result["tomorrowCount"] = sum(
        1
        for item in items
        if _as_date(item.get("po_date")) == tomorrow
        and str(item.get("reminder_status") or "").upper() != "DONE"
    )
    result["overdueCount"] = sum(
        1
        for item in items
        if _as_date(item.get("po_date")) is not None
        and _as_date(item.get("po_date")) < target
        and str(item.get("reminder_status") or "").upper() == "OVERDUE"
    )
    return result


def apply_tempe_configured_leads(
    payload: dict[str, Any],
    target: date,
    lead_by_cooking_date: dict[date, int],
) -> dict[str, Any]:
    """Use the operator-edited dedicated TEMPE lead instead of the legacy H-4."""
    result = deepcopy(payload)
    changed = False
    for item in result.get("items") or []:
        families = {str(value or "").upper() for value in (item.get("item_families") or [])}
        is_tempe = "TEMPE" in families or str(item.get("procurement_bucket") or "").upper() == "TEMPE"
        if not is_tempe:
            continue
        cooking_dates = sorted(
            value
            for value in (_as_date(raw) for raw in (item.get("cooking_dates") or [item.get("cooking_date")]))
            if value is not None
        )
        if not cooking_dates:
            continue
        cooking_date = cooking_dates[0]
        lead = lead_by_cooking_date.get(cooking_date)
        if lead is None:
            continue
        new_po_date = cooking_date - timedelta(days=int(lead))
        old_po_date = _as_date(item.get("po_date"))
        if old_po_date == new_po_date and item.get("lead_time_days_before_cooking") == int(lead):
            continue
        item["po_date"] = new_po_date
        item["lead_time_days_before_cooking"] = int(lead)
        item["lead_time_source"] = "CONFIGURED_VENDOR_RULE"
        status = str(item.get("reminder_status") or "").upper()
        if status in TIMING_STATUSES:
            item["reminder_status"] = _timing_status(new_po_date, target)
        item["lead_time_reconciled"] = True
        changed = True
    if not changed:
        return payload
    return _recount(result, target)


def _requirement_nodes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for parent in payload.get("items") or []:
        if str(parent.get("vendor_code") or "").upper() != "WIKIAN":
            continue
        parent_po_date = _as_date(parent.get("po_date"))
        if parent_po_date is None:
            continue
        parent_families = {str(value or "").upper() for value in (parent.get("item_families") or [])}
        for detail in parent.get("requirement_details") or []:
            recommended = max(0.0, float(detail.get("recommended_po_qty") or 0.0))
            if recommended <= EPSILON:
                continue
            detail_families = {str(value or "").upper() for value in (detail.get("item_families") or [])}
            family = "CHICKEN" if "CHICKEN" in (detail_families | parent_families) else ""
            unit = canonical_unit(detail.get("unit")) or ""
            distribution_date = _as_date(detail.get("distribution_date"))
            if family != "CHICKEN" or distribution_date is None:
                continue
            nodes.append({
                "parent": parent,
                "detail": detail,
                "po_date": parent_po_date,
                "distribution_date": distribution_date,
                "family": family,
                "unit": unit,
                "recommended": recommended,
                "allocated_done": 0.0,
                "contributors": [],
            })
    nodes.sort(key=lambda node: (node["po_date"], node["distribution_date"], node["family"], node["unit"]))
    return nodes


def _allocate(node: dict[str, Any], amount: float, po: dict[str, Any]) -> float:
    remaining = max(0.0, node["recommended"] - node["allocated_done"])
    used = min(max(0.0, amount), remaining)
    if used <= EPSILON:
        return 0.0
    node["allocated_done"] = round(node["allocated_done"] + used, 4)
    node["contributors"].append(po)
    return used


def apply_wikian_batch_fifo(
    payload: dict[str, Any],
    target: date,
    completed_pos: list[dict[str, Any]],
    direct_items: list[dict[str, Any]],
    coverage_items: list[dict[str, Any]],
) -> dict[str, Any]:
    """Use genuine surplus from completed WIKIAN POs to close older due needs.

    Exact dated coverage is reserved first. Only aggregate qty left after satisfying
    those explicit dates is treated as surplus. That surplus is applied FIFO to
    older chicken requirements whose PO date was already due when the PO was sent.
    Daging Ayam and chicken-cut labels are pooled as CHICKEN when the unit matches.
    This changes reminder semantics only; PO, receiving and inventory rows stay intact.
    """
    if not completed_pos:
        return payload
    result = deepcopy(payload)
    nodes = _requirement_nodes(result)
    if not nodes:
        return payload

    direct_totals: dict[int, dict[tuple[str, str], float]] = {}
    for item in direct_items:
        po_id = int(item["purchase_order_id"])
        key = _wikian_key(item.get("item_name"), item.get("unit"))
        if key[0] != "CHICKEN":
            continue
        bucket = direct_totals.setdefault(po_id, {})
        bucket[key] = round(bucket.get(key, 0.0) + max(0.0, float(item.get("po_qty") or 0.0)), 4)

    coverage_totals: dict[int, dict[tuple[str, str, date], float]] = {}
    for item in coverage_items:
        po_id = int(item["purchase_order_id"])
        distribution_date = _as_date(item.get("distribution_date"))
        key = _wikian_key(item.get("item_name"), item.get("unit"))
        if distribution_date is None or key[0] != "CHICKEN":
            continue
        cov_key = (key[0], key[1], distribution_date)
        bucket = coverage_totals.setdefault(po_id, {})
        bucket[cov_key] = round(bucket.get(cov_key, 0.0) + max(0.0, float(item.get("po_qty") or 0.0)), 4)

    pos = sorted(
        completed_pos,
        key=lambda po: (
            _as_date(po.get("effective_date")) or date.min,
            str(po.get("sent_at") or po.get("created_at") or ""),
            int(po.get("revision_no") or 0),
            int(po.get("id") or 0),
        ),
    )

    for po in pos:
        po_id = int(po["id"])
        effective_date = _as_date(po.get("effective_date") or po.get("sent_at") or po.get("created_at"))
        if effective_date is None or effective_date > target:
            continue
        for (family, unit), raw_total in direct_totals.get(po_id, {}).items():
            pool = max(0.0, float(raw_total))
            if pool <= EPSILON:
                continue

            explicit = [
                (distribution_date, qty)
                for (cov_family, cov_unit, distribution_date), qty in coverage_totals.get(po_id, {}).items()
                if (cov_family, cov_unit) == (family, unit)
            ]
            explicit.sort(key=lambda row: row[0])
            for distribution_date, raw_explicit_qty in explicit:
                if pool <= EPSILON:
                    break
                explicit_qty = min(pool, max(0.0, float(raw_explicit_qty)))
                matching = [
                    node
                    for node in nodes
                    if node["distribution_date"] == distribution_date
                    and (node["family"], node["unit"]) == (family, unit)
                ]
                for node in matching:
                    if explicit_qty <= EPSILON or pool <= EPSILON:
                        break
                    used = _allocate(node, min(explicit_qty, pool), po)
                    explicit_qty -= used
                    pool -= used

            if pool > EPSILON:
                eligible = [
                    node
                    for node in nodes
                    if (node["family"], node["unit"]) == (family, unit)
                    and node["po_date"] <= effective_date
                    and node["allocated_done"] + EPSILON < node["recommended"]
                ]
                for node in eligible:
                    if pool <= EPSILON:
                        break
                    used = _allocate(node, pool, po)
                    pool -= used

    changed = False
    parents_touched: dict[int, dict[str, Any]] = {}
    for node in nodes:
        allocated = min(node["recommended"], node["allocated_done"])
        if allocated <= EPSILON:
            continue
        detail = node["detail"]
        original_covered = min(node["recommended"], max(0.0, float(detail.get("covered_po_qty") or 0.0)))
        effective_covered = max(original_covered, allocated)
        new_remaining = max(0.0, round(node["recommended"] - effective_covered, 4))
        detail["covered_po_qty"] = round(effective_covered, 4)
        detail["remaining_po_qty"] = new_remaining
        detail["batch_completed_po_qty"] = round(allocated, 4)
        detail["batch_coverage_basis"] = "WIKIAN_SENT_SURPLUS_FIFO_CHICKEN_FAMILY"
        if allocated + EPSILON >= node["recommended"]:
            detail["coverage_stage"] = "DONE"
        parent = node["parent"]
        parents_touched[id(parent)] = parent
        parent.setdefault("_wikian_contributors", []).extend(node["contributors"])
        changed = True

    if not changed:
        return payload

    for parent in parents_touched.values():
        details = parent.get("requirement_details") or []
        remaining_details = [detail for detail in details if float(detail.get("remaining_po_qty") or 0.0) > EPSILON]
        contributors = parent.pop("_wikian_contributors", [])
        latest_po = None
        if contributors:
            latest_po = max(
                contributors,
                key=lambda po: (
                    _as_date(po.get("effective_date")) or date.min,
                    str(po.get("sent_at") or po.get("created_at") or ""),
                    int(po.get("revision_no") or 0),
                    int(po.get("id") or 0),
                ),
            )
        if latest_po:
            parent.update({
                "purchase_order_id": latest_po.get("id"),
                "po_code": latest_po.get("po_code"),
                "po_status": latest_po.get("status"),
                "po_created_at": latest_po.get("created_at"),
                "po_sent_at": latest_po.get("sent_at"),
                "po_workflow_status": "DONE",
                "po_already_done": True,
                "wikian_batch_reconciled": True,
            })

        if not remaining_details:
            parent["reminder_status"] = "DONE"
            parent["missing_item_names"] = []
            parent["missing_distribution_dates"] = []
            parent["item_count"] = 0
            parent["shortage_only"] = False
            parent["reminder_message"] = "PO WIKIAN yang sudah SENT telah menutup kebutuhan ayam yang jatuh tempo."
        else:
            missing_names = sorted({
                str(name).strip()
                for detail in remaining_details
                for name in (detail.get("item_names") or [])
                if str(name).strip()
            })
            missing_dates = sorted({
                value
                for value in (_as_date(detail.get("distribution_date")) for detail in remaining_details)
                if value is not None
            })
            parent["missing_item_names"] = missing_names
            parent["missing_distribution_dates"] = missing_dates
            parent["item_count"] = len(missing_names)
            parent["shortage_only"] = bool(latest_po)
            if latest_po:
                parent["shortage_reminder_status"] = str(parent.get("reminder_status") or "").upper()
                parent["reminder_message"] = "PO WIKIAN sudah dilakukan; hanya sisa qty yang belum tertutup yang masih perlu ditindaklanjuti."

    result = _recount(result, target)
    result["wikianBatchReconciled"] = True
    return result


def _load_tempe_leads(cur: Any, site: str, payload: dict[str, Any]) -> dict[date, int]:
    cooking_dates = sorted({
        value
        for item in (payload.get("items") or [])
        if (
            "TEMPE" in {str(family or "").upper() for family in (item.get("item_families") or [])}
            or str(item.get("procurement_bucket") or "").upper() == "TEMPE"
        )
        for value in (_as_date(raw) for raw in (item.get("cooking_dates") or [item.get("cooking_date")]))
        if value is not None
    })
    result: dict[date, int] = {}
    for cooking_date in cooking_dates:
        cur.execute(
            """
            select lead_time_days_before_cooking
            from vendor_rules
            where upper(vendor_code)='KOPERASI'
              and (site_code is null or upper(site_code)=upper(%s))
              and upper(trim(coalesce(category_code,'')))='TEMPE'
              and effective_from <= %s
              and (effective_to is null or effective_to >= %s)
            order by case when upper(coalesce(site_code,''))=upper(%s) then 1 else 0 end desc,
                     effective_from desc,id desc
            limit 1
            """,
            (site, cooking_date, cooking_date, site),
        )
        row = cur.fetchone()
        if row and row.get("lead_time_days_before_cooking") is not None:
            result[cooking_date] = int(row["lead_time_days_before_cooking"])
    return result


def _load_wikian_completed(
    cur: Any,
    site: str,
    payload: dict[str, Any],
    target: date,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    distribution_dates = sorted({
        value
        for item in (payload.get("items") or [])
        if str(item.get("vendor_code") or "").upper() == "WIKIAN"
        for detail in (item.get("requirement_details") or [])
        for value in [_as_date(detail.get("distribution_date"))]
        if value is not None
    })
    if not distribution_dates:
        return [], [], []
    cur.execute(
        """
        select po.id,po.po_code,po.revision_no,upper(po.site) site,
               upper(po.vendor_code) vendor_code,upper(po.status) status,
               po.created_at,po.finalized_at,po.sent_at,
               date(coalesce(po.sent_at,po.finalized_at,po.created_at)) effective_date,
               pc.distribution_date base_distribution_date
        from purchase_orders po
        join production_cycles pc on pc.id=po.production_cycle_id
        where upper(po.site)=upper(%s)
          and upper(po.vendor_code)='WIKIAN'
          and upper(coalesce(po.status,''))=any(%s)
          and date(coalesce(po.sent_at,po.finalized_at,po.created_at)) <= %s
          and (
            pc.distribution_date=any(%s)
            or exists(
              select 1 from purchase_order_coverage poc
              where poc.purchase_order_id=po.id
                and poc.distribution_date=any(%s)
            )
          )
        order by effective_date,po.created_at,po.revision_no,po.id
        """,
        (site, list(DONE_PO_STATUSES), target, distribution_dates, distribution_dates),
    )
    pos = [dict(row) for row in cur.fetchall()]
    po_ids = [int(po["id"]) for po in pos]
    if not po_ids:
        return [], [], []
    cur.execute(
        """
        select purchase_order_id,item_name,po_qty,unit
        from purchase_order_items
        where purchase_order_id=any(%s) and coalesce(po_qty,0)>0
        order by purchase_order_id,id
        """,
        (po_ids,),
    )
    direct_items = [dict(row) for row in cur.fetchall()]
    cur.execute(
        """
        select poc.purchase_order_id,poc.distribution_date,
               poci.item_name,poci.po_qty,poci.unit
        from purchase_order_coverage poc
        join purchase_order_coverage_items poci
          on poci.purchase_order_coverage_id=poc.id
        where poc.purchase_order_id=any(%s) and coalesce(poci.po_qty,0)>0
        order by poc.purchase_order_id,poc.distribution_date,poci.id
        """,
        (po_ids,),
    )
    coverage_items = [dict(row) for row in cur.fetchall()]
    return pos, direct_items, coverage_items


def reconcile_operational_po_reminders(payload: dict[str, Any], site: str, target: date) -> dict[str, Any]:
    normalized_site = str(site or "").upper().strip()
    if normalized_site not in {"MAJA", "CEMPLANG"} or not database_ready():
        return payload
    with connection() as conn:
        with conn.cursor() as cur:
            tempe_leads = _load_tempe_leads(cur, normalized_site, payload)
            result = apply_tempe_configured_leads(payload, target, tempe_leads)
            pos, direct_items, coverage_items = _load_wikian_completed(cur, normalized_site, result, target)
    return apply_wikian_batch_fifo(result, target, pos, direct_items, coverage_items)
