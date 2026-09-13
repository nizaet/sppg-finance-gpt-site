from __future__ import annotations

"""Final, per-kitchen warehouse check for PO reminders.

The PO engine already uses projected stock while drafting a PO.  This small
post-check closes the timing gap between that calculation and an operator
opening the reminder screen: it reads the selected kitchen's latest warehouse
balance for each distribution date.  It never borrows stock from another
kitchen or from Koperasi, and it never treats a merely similar item as stock.
Similar names are returned only as operator references.
"""

from copy import deepcopy
from datetime import date, datetime
from difflib import SequenceMatcher
import re
from typing import Any

from backend.inventory_projection_v2_api import inventory_balances_v2
from backend.item_taxonomy import stock_type
from backend.stock_opname_parser import canonical_unit


EPSILON = 0.0001
_OPEN_STATUSES = {"OVERDUE", "DUE_TODAY", "UPCOMING", "SHORTAGE_REVIEW"}


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _names(row: dict[str, Any]) -> list[str]:
    values = [row.get("item_name"), *(row.get("raw_item_names") or [])]
    return list(dict.fromkeys(value for value in (_norm(raw) for raw in values) if value))


def _convert(quantity: float, from_unit: Any, to_unit: Any) -> float | None:
    source = canonical_unit(from_unit) or ""
    target = canonical_unit(to_unit) or ""
    if source == target:
        return quantity
    if source == "gr" and target == "kg":
        return quantity / 1000.0
    if source == "kg" and target == "gr":
        return quantity * 1000.0
    return None


def _match_kind(detail: dict[str, Any], candidate: dict[str, Any]) -> tuple[str, float]:
    requested_names = {_norm(value) for value in (detail.get("item_names") or []) if _norm(value)}
    candidate_names = set(_names(candidate))
    if requested_names & candidate_names:
        return "EXACT_NAME", 1.0

    requested_type = str(detail.get("stock_type_code") or "").upper().strip()
    candidate_type = str(candidate.get("stock_type_code") or stock_type(candidate.get("item_name"))["code"]).upper().strip()
    if requested_type and not requested_type.startswith("RAW_") and requested_type == candidate_type:
        return "EXACT_TYPE", 0.98

    best = 0.0
    for left in requested_names:
        for right in candidate_names:
            left_words, right_words = set(left.split()), set(right.split())
            overlap = len(left_words & right_words) / max(len(left_words | right_words), 1)
            score = max(overlap, SequenceMatcher(None, left, right).ratio())
            best = max(best, score)
    return ("NEAR_NAME", best) if best >= 0.45 else ("UNRELATED", best)


def _candidates(detail: dict[str, Any], balance_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    requested_unit = canonical_unit(detail.get("unit")) or ""
    rows: list[dict[str, Any]] = []
    for raw in balance_items:
        available = max(0.0, float(raw.get("available_for_po") if raw.get("available_for_po") is not None else raw.get("balance") or 0))
        converted_available = _convert(available, raw.get("unit"), requested_unit)
        kind, score = _match_kind(detail, raw)
        # A different or unknown unit is a useful visual reference, never an
        # automatic stock match. The operator can still open it and count it.
        is_exact = kind.startswith("EXACT") and converted_available is not None
        if kind == "UNRELATED":
            continue
        rows.append({
            "item_name": raw.get("item_name"),
            "inventory_item_code": raw.get("inventory_item_code"),
            "unit": canonical_unit(raw.get("unit")) or raw.get("unit") or "",
            "actual_balance": round(float(raw.get("actual_balance") or 0), 4),
            "available_for_po": round(available, 4),
            "available_in_requirement_unit": round(converted_available, 4) if converted_available is not None else None,
            "match_type": kind,
            "match_score": round(score, 3),
            "is_exact_match": is_exact,
            "raw_item_names": raw.get("raw_item_names") or [],
        })
    rows.sort(key=lambda row: (not row["is_exact_match"], -row["match_score"], -row["available_for_po"], str(row["item_name"] or "")))
    return rows[:5]


def apply_warehouse_stock_check(payload: dict[str, Any], requested_site: str) -> dict[str, Any]:
    """Add same-kitchen stock references and safely auto-cover exact stock only."""
    items = payload.get("items") or []
    cache: dict[tuple[str, date], list[dict[str, Any]]] = {}
    checked = 0
    auto_covered = 0
    enriched: list[dict[str, Any]] = []

    for original in items:
        item = deepcopy(original)
        status = str(item.get("reminder_status") or "").upper()
        site = str(item.get("site") or requested_site or "").upper().strip()
        details = [dict(detail) for detail in (item.get("requirement_details") or [])]
        if status not in _OPEN_STATUSES or site not in {"MAJA", "CEMPLANG"} or not details:
            enriched.append(item)
            continue

        changed = False
        for detail in details:
            remaining = max(0.0, float(detail.get("remaining_po_qty") or 0))
            distribution_date = _as_date(detail.get("distribution_date"))
            if remaining <= EPSILON or distribution_date is None:
                continue
            key = (site, distribution_date)
            if key not in cache:
                try:
                    cache[key] = inventory_balances_v2(site=site, search="", limit=1000, for_date=distribution_date).get("items") or []
                except Exception:
                    cache[key] = []
            candidates = _candidates(detail, cache[key])
            exact_available = sum(
                float(row.get("available_in_requirement_unit") or 0)
                for row in candidates if row.get("is_exact_match")
            )
            # v4 has already deducted ``projected_stock_qty`` when it produced
            # ``remaining_po_qty``. Counting that same stock one more time here
            # would incorrectly hide a real shortage (e.g. need 10 kg, stock 5
            # kg, PO shortage 5 kg). Only stock that appeared after that
            # projection, or that v4 could not classify into the requirement,
            # can reduce the reminder in this final check.
            already_accounted = max(0.0, float(detail.get("projected_stock_qty") or 0))
            fresh_exact_available = max(0.0, exact_available - already_accounted)
            covered = min(remaining, fresh_exact_available)
            next_remaining = round(max(0.0, remaining - covered), 4)
            detail["warehouse_stock_check"] = {
                "location": site,
                "distribution_date": distribution_date,
                "status": "COVERED" if next_remaining <= EPSILON else ("PARTIAL" if covered > EPSILON else ("REFERENCE_AVAILABLE" if candidates else "NO_MATCH")),
                "available_exact_qty": round(exact_available, 4),
                "already_accounted_qty": round(already_accounted, 4),
                "fresh_exact_qty": round(fresh_exact_available, 4),
                "covered_qty": round(covered, 4),
                "candidates": candidates,
            }
            checked += 1
            if covered > EPSILON:
                detail["remaining_po_qty"] = next_remaining
                detail["warehouse_stock_covered_qty"] = round(covered, 4)
                detail["ordering_state"] = "STOCK_COVERED" if next_remaining <= EPSILON else detail.get("ordering_state")
                changed = True

        if changed:
            remaining_details = [detail for detail in details if float(detail.get("remaining_po_qty") or 0) > EPSILON]
            remaining_names = sorted({
                str(name).strip() for detail in remaining_details for name in (detail.get("item_names") or []) if str(name).strip()
            })
            item["requirement_details"] = details
            item["missing_item_names"] = remaining_names
            item["shortage_qty_total"] = round(sum(float(detail.get("remaining_po_qty") or 0) for detail in remaining_details), 4)
            if not remaining_details:
                item.update({
                    "reminder_status": "DONE",
                    "po_workflow_status": "DONE_STOCK_COVERED",
                    "stock_auto_resolved": True,
                    "reminder_message": f"Stok Gudang Dapur {site} mencukupi; pengingat PO ditutup otomatis.",
                })
                auto_covered += 1
        else:
            item["requirement_details"] = details
        enriched.append(item)

    if not checked:
        return payload
    result = dict(payload)
    result["items"] = enriched
    result["warehouseStockCheckCount"] = checked
    result["warehouseStockAutoCoveredCount"] = auto_covered
    result["warehouseStockScope"] = "DAPUR_SAME_SITE_ONLY"
    return result
