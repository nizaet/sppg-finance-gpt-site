from __future__ import annotations

from datetime import date, datetime
from typing import Any

from backend.db import connection, database_ready


def _as_date_text(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip()
    return text[:10] if text else ""


def _upper(value: Any) -> str:
    return str(value or "").upper().strip()


def _names(value: Any) -> set[str]:
    if isinstance(value, list):
        return {str(x).lower().strip() for x in value if str(x).strip()}
    if isinstance(value, str) and value.strip():
        return {value.lower().strip()}
    return set()


def _item_names(item: dict[str, Any]) -> set[str]:
    result = _names(item.get("item_names")) | _names(item.get("missing_item_names"))
    for detail in item.get("requirement_details") or []:
        result |= _names(detail.get("item_names"))
    return result


def _dates(item: dict[str, Any]) -> set[str]:
    values = item.get("distribution_dates") or [item.get("distribution_date")]
    result = {_as_date_text(value) for value in values if _as_date_text(value)}
    for detail in item.get("requirement_details") or []:
        text = _as_date_text(detail.get("distribution_date"))
        if text:
            result.add(text)
    return result


def _mark_done(item: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    resolution = _upper(override.get("resolution")) or "CHECKED"
    if resolution == "SUFFICIENT":
        label = "Sudah mencukupi (override)"
        message = "Operator mengonfirmasi kebutuhan sudah mencukupi. Reminder ditutup tanpa mengubah stok atau PO."
    elif resolution == "MANUAL_PO":
        label = "PO manual sudah dilakukan"
        message = "Operator mengonfirmasi PO telah dilakukan di luar workflow aplikasi. Reminder ditutup tanpa membuat PO fiktif."
    else:
        label = "Sudah dicek / dibiarkan"
        message = "PO sudah dilakukan dan sisa kebutuhan telah dicek operator. Selisih diterima tanpa membuat PO atau stok fiktif."
    updated = dict(item)
    updated.update({
        "override_original_status": _upper(item.get("reminder_status")),
        "reminder_status": "DONE",
        "po_workflow_status": "DONE_REVIEWED" if resolution == "CHECKED" else "DONE_MANUAL",
        "reminder_override": True,
        "reminder_override_resolution": resolution,
        "reminder_override_label": label,
        "reminder_override_note": override.get("note"),
        "reminder_override_created_at": override.get("created_at"),
        "reminder_override_updated_at": override.get("updated_at"),
        "reminder_override_fallback": True,
        "reminder_message": message,
    })
    if resolution == "MANUAL_PO":
        updated["po_already_done"] = True
        updated["manual_po_confirmed"] = True
    return updated


def apply_fallback_reminder_overrides(payload: dict[str, Any], site: str, target: date) -> dict[str, Any]:
    """Close rows when a prior manual confirmation used an older reminder key.

    Reminder keys include item/date identity, but legacy/repair reconciliation can
    change requirement detail composition after a PO is edited or additional PO is
    created. This fallback never guesses across vendor/date; it only reuses active
    overrides whose metadata matches the same site + vendor + PO date + at least
    one distribution date, and if both sides have item names, at least one item
    name must overlap.
    """
    items = payload.get("items") or []
    normalized_site = _upper(site or payload.get("site"))
    if not items or normalized_site not in {"MAJA", "CEMPLANG"} or not database_ready():
        return payload

    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select reminder_key, site, vendor_code, resolution, note, metadata, created_at, updated_at
                    from po_reminder_overrides
                    where upper(site)=%s and active=true
                    order by updated_at desc, created_at desc
                    """,
                    (normalized_site,),
                )
                overrides = [dict(row) for row in cur.fetchall()]
    except Exception:
        return payload

    if not overrides:
        return payload

    changed = False
    next_items: list[dict[str, Any]] = []
    for item in items:
        if item.get("reminder_override") or _upper(item.get("reminder_status")) == "DONE":
            next_items.append(item)
            continue
        item_vendor = _upper(item.get("vendor_code"))
        item_po_date = _as_date_text(item.get("po_date"))
        item_dates = _dates(item)
        item_names = _item_names(item)
        matched_override = None
        for override in overrides:
            if _upper(override.get("vendor_code")) != item_vendor:
                continue
            metadata = override.get("metadata") or {}
            if isinstance(metadata, str):
                metadata = {}
            meta_po_date = _as_date_text(metadata.get("po_date"))
            if meta_po_date and item_po_date and meta_po_date != item_po_date:
                continue
            meta_dates = {_as_date_text(value) for value in (metadata.get("distribution_dates") or []) if _as_date_text(value)}
            if meta_dates and item_dates and not (meta_dates & item_dates):
                continue
            meta_names = _names(metadata.get("item_names"))
            if meta_names and item_names and not (meta_names & item_names):
                continue
            matched_override = override
            break
        if matched_override:
            next_items.append(_mark_done(item, matched_override))
            changed = True
        else:
            next_items.append(item)

    if not changed:
        return payload
    result = dict(payload)
    result["items"] = next_items
    result["fallbackOverrideCount"] = sum(1 for item in next_items if item.get("reminder_override_fallback"))
    return result
