from __future__ import annotations

from datetime import date, timedelta
import re
from typing import Any

from backend import po_reminder_v4_api as reminder
from backend import purchase_order_workflow_api as workflow
from backend.inventory_projection_v2_api import inventory_balances_v2
from backend.item_taxonomy import item_family, normalize_item_text, vendor_for_item

_INSTALLED = False
_ORIGINAL_FORMATTER = workflow.format_purchase_order_whatsapp
_ORIGINAL_PROJECTION_LOOKUP = reminder._projection_lookup
_ORIGINAL_RULE_RESOLVER = reminder._resolve_procurement_rule

_RULE_CATEGORY_HINT = {
    "EGG": "TELUR",
    "TEMPE": "TEMPE",
    "TOFU": "TAHU",
    "DRY_GOODS": "BAHAN_KERING",
    "CHICKEN": "AYAM",
    "FISH": "IKAN",
    "RICE": "BERAS",
    "GAS": "GAS",
    "PRODUCE": "SAYUR_BUAH",
}

_FAMILY_RULE_TOKENS = {
    "EGG": ("TELUR", "EGG"),
    "TEMPE": ("TEMPE",),
    "TOFU": ("TAHU", "TOFU"),
    "DRY_GOODS": ("BAHAN_KERING", "DRY_GOODS", "SEMBAKO", "KERING", "PACKAGING"),
    "CHICKEN": ("AYAM", "CHICKEN"),
    "FISH": ("IKAN", "DORI", "FISH"),
    "RICE": ("BERAS", "RICE"),
    "GAS": ("GAS", "LPG"),
    "PRODUCE": ("SAYUR", "BUAH", "BUMBU", "PRODUCE"),
}


def _intrinsic_family(row: dict[str, Any]) -> str:
    """Trust the ingredient name before a stale calculator category label."""
    family = item_family(row.get("item_name"), None)
    if family != "UNKNOWN":
        return family
    return item_family(row.get("item_name"), row.get("category_code"))


def _rule_category_score(rule_category: Any, family: str) -> int | None:
    category = reminder._norm(rule_category)
    if not category:
        return None
    tokens = _FAMILY_RULE_TOKENS.get(family) or ()
    if not tokens:
        return None
    if category in tokens:
        return 360
    if any(token in category for token in tokens):
        return 320
    return None


def _database_rule_for_item(
    rules: list[dict[str, Any]],
    row: dict[str, Any],
    family: str,
    fallback_vendor: str | None,
) -> dict[str, Any] | None:
    """Pick the active effective-dated category rule across all vendors.

    This makes vendor_rules the editable source of truth. Exact item-family rules
    beat stale preferred_vendor/category values copied into an old planning row.
    When legacy duplicate rules exist, the normal taxonomy vendor is only used as
    a tie-breaker until the operator saves a new assignment from Vendor Master.
    """
    site = str(row.get("site") or "").upper().strip()
    cook = row.get("cooking_date")
    if not isinstance(cook, date):
        return None

    scored: list[tuple[int, date, int, dict[str, Any]]] = []
    for rule in rules:
        rule_site = str(rule.get("site_code") or "").upper().strip()
        if rule_site not in {"", site}:
            continue
        if rule.get("effective_from") and rule["effective_from"] > cook:
            continue
        if rule.get("effective_to") and rule["effective_to"] < cook:
            continue
        category_score = _rule_category_score(rule.get("category_code"), family)
        if category_score is None:
            continue
        vendor = str(rule.get("vendor_code") or "").upper().strip()
        score = category_score
        if rule_site == site:
            score += 40
        if fallback_vendor and vendor == fallback_vendor:
            score += 5
        effective_from = rule.get("effective_from") or date.min
        scored.append((score, effective_from, int(rule.get("id") or 0), rule))

    if not scored:
        return None
    scored.sort(key=lambda value: (value[0], value[1], value[2]), reverse=True)
    return scored[0][3]


def _resolve_procurement_rule(
    rules: list[dict[str, Any]],
    vendor_names: dict[str, str],
    row: dict[str, Any],
) -> tuple[str | None, dict[str, Any] | None, str]:
    site = str(row.get("site") or "").upper().strip()
    family = _intrinsic_family(row)
    cook = row.get("cooking_date")

    # Name-based family prevents e.g. Tahu/Bawang Putih from inheriting a stale
    # BAHAN_KERING/KOPERASI category stored in the Calculator snapshot.
    fallback_vendor = vendor_for_item(
        row.get("item_name"),
        None if family != "UNKNOWN" else row.get("category_code"),
        site,
        row.get("preferred_vendor_code"),
    )

    specific = _database_rule_for_item(rules, row, family, fallback_vendor)
    if specific:
        rule = dict(specific)
        vendor = str(rule.get("vendor_code") or "").upper().strip()
        rule["vendor_name"] = rule.get("vendor_name") or vendor_names.get(vendor, vendor)
        bucket = "TEMPE" if family == "TEMPE" else ("TOFU" if family == "TOFU" else "DEFAULT")
        return vendor, rule, bucket

    if family == "UNKNOWN":
        return _ORIGINAL_RULE_RESOLVER(rules, vendor_names, row)

    vendor = fallback_vendor
    if not vendor or not isinstance(cook, date):
        return vendor, None, family

    # Preserve the dedicated Cemplang Tempe safety rule when there is no active
    # database assignment for TEMPE.
    if family == "TEMPE" and site == "CEMPLANG" and vendor == "KOPERASI":
        rule = reminder._strict_cemplang_tempe_rule(rules, cook)
    else:
        hint = _RULE_CATEGORY_HINT.get(family, row.get("category_code"))
        rule = reminder._rule_for_item(rules, vendor, site, hint, row.get("item_name"), cook)
    if rule:
        rule = dict(rule)
        rule["vendor_name"] = rule.get("vendor_name") or vendor_names.get(vendor, vendor)
    bucket = "TEMPE" if family == "TEMPE" else ("TOFU" if family == "TOFU" else "DEFAULT")
    return vendor, rule, bucket


def _warehouse_projection_lookup(distribution_date: date) -> tuple[dict[tuple[str, str], float], str]:
    try:
        payload = inventory_balances_v2(
            site="KOPERASI",
            search="",
            limit=1000,
            for_date=distribution_date,
        )
    except Exception:
        return {}, "KOPERASI_PROJECTION_UNAVAILABLE"

    lookup: dict[tuple[str, str], float] = {}
    for item in payload.get("items") or []:
        key = reminder._stock_key(item.get("item_name"), item.get("unit"))
        raw_available = item.get("available_for_po")
        if raw_available is None:
            raw_available = item.get("balance")
        available = max(0.0, float(raw_available or 0))
        lookup[key] = max(lookup.get(key, 0.0), available)
    return lookup, str(payload.get("projectionModel") or "KOPERASI_INVENTORY_PROJECTION_V2")


def _projection_lookup(site: str, distribution_date: date) -> tuple[dict[tuple[str, str], float], str]:
    """Use stock at the dapur plus stock still available in Gudang Koperasi."""
    site_lookup, site_basis = _ORIGINAL_PROJECTION_LOOKUP(site, distribution_date)
    warehouse_lookup, warehouse_basis = _warehouse_projection_lookup(distribution_date)

    if not warehouse_lookup:
        return site_lookup, site_basis
    if not site_lookup:
        return warehouse_lookup, f"{site_basis}+{warehouse_basis}"

    merged = dict(site_lookup)
    for key, amount in warehouse_lookup.items():
        merged[key] = max(0.0, float(merged.get(key, 0.0))) + max(0.0, float(amount or 0.0))
    return merged, f"{site_basis}+{warehouse_basis}"


def _protein_next_day(item_name: Any) -> bool:
    text = normalize_item_text(item_name)
    return re.search(r"\b(ayam|chicken|ikan|fish|dori|daging|sapi|beef)\b", text) is not None


def _delivery_dates(po: dict[str, Any]) -> tuple[list[date], bool, bool]:
    schedules = [row for row in (po.get("item_schedule") or []) if isinstance(row, dict)]
    dates: list[date] = []
    has_protein = False
    has_regular = False

    if schedules:
        for row in schedules:
            cook = workflow.as_date(row.get("cooking_date"))
            order_date = workflow.as_date(row.get("scheduled_order_date")) or workflow.as_date(po.get("scheduled_order_date"))
            if _protein_next_day(row.get("item_name")):
                has_protein = True
                delivery = order_date + timedelta(days=1) if order_date else cook
            else:
                has_regular = True
                delivery = cook
            if delivery:
                dates.append(delivery)
    else:
        cook = workflow.as_date(po.get("cooking_date"))
        order_date = workflow.as_date(po.get("scheduled_order_date"))
        items = [row for row in (po.get("items") or []) if isinstance(row, dict)]
        for row in items:
            try:
                included = float(row.get("po_qty") or 0) > 0
            except (TypeError, ValueError):
                included = False
            if not included:
                continue
            if _protein_next_day(row.get("item_name")):
                has_protein = True
                delivery = order_date + timedelta(days=1) if order_date else cook
            else:
                has_regular = True
                delivery = cook
            if delivery:
                dates.append(delivery)

    if not dates:
        fallback = workflow.as_date(po.get("cooking_date"))
        if fallback:
            dates.append(fallback)
            has_regular = True
    return sorted(set(dates)), has_protein, has_regular


def format_purchase_order_whatsapp(po: dict[str, Any], vendor_name: str) -> str:
    """Canonical PO copy: delivery date, cook date and distribution date."""
    revision = int(po.get("revision_no") or 1)
    po_label = str(po.get("po_code") or "-")
    if revision > 1:
        po_label += f" / Rev {revision}"

    coverage_dates = sorted({
        value for value in (workflow.as_date(item) for item in (po.get("coverage_dates") or [])) if value
    })
    if not coverage_dates and po.get("distribution_date"):
        distribution_date = workflow.as_date(po.get("distribution_date"))
        coverage_dates = [distribution_date] if distribution_date else []
    distribution_label = workflow._format_indonesian_date_range(coverage_dates)
    coverage_line = (
        f"🗓 *Cakupan:* {len(coverage_dates)} hari distribusi — dikirim dalam satu PO"
        if len(coverage_dates) > 1 else None
    )

    cooking_label = workflow._format_indonesian_date_range(po.get("cooking_dates") or [po.get("cooking_date")])
    delivery_dates, has_protein, has_regular = _delivery_dates(po)
    delivery_label = workflow._format_indonesian_date_range(delivery_dates)
    if has_protein and has_regular:
        delivery_note = " (ayam/daging/ikan H+1 setelah PO; lainnya hari masak)"
    elif has_protein:
        delivery_note = " (H+1 setelah PO untuk ayam/daging/ikan)"
    else:
        delivery_note = " (hari masak)"

    lines = [
        f"🛒 *PO SPPG {str(po.get('site') or '').upper()}*",
        f"👤 *Vendor:* {vendor_name}",
        f"🚚 *Kirim Barang:* {delivery_label}{delivery_note}",
        f"🍳 *Masak:* {cooking_label}",
        f"📅 *Untuk Distribusi:* {distribution_label}",
        f"🧾 *No. PO:* {po_label}",
    ]
    if coverage_line:
        lines.append(coverage_line)
    lines.extend(["", "📦 *DAFTAR PESANAN GABUNGAN*" if len(coverage_dates) > 1 else "📦 *DAFTAR PESANAN*", ""])
    included_items = []
    for item in po.get("items") or []:
        try:
            if float(item.get("po_qty") or 0) > 0:
                included_items.append(item)
        except (TypeError, ValueError):
            continue
    for index, item in enumerate(included_items, start=1):
        amount = workflow._format_qty(item.get("po_qty"))
        unit = str(item.get("unit") or "").strip()
        lines.append(f"   {index}. *{str(item.get('item_name') or '-').strip()}* : {amount}{f' {unit}' if unit else ''}")
    lines.extend([
        "",
        "Mohon dibantu disiapkan sesuai daftar di atas ya Pak. 🙏",
        "Mohon konfirmasi jika ada barang yang kosong atau harganya berubah.",
        "Terima kasih.",
    ])
    return "\n".join(lines)


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    workflow.format_purchase_order_whatsapp = format_purchase_order_whatsapp
    reminder._resolve_procurement_rule = _resolve_procurement_rule
    reminder._projection_lookup = _projection_lookup
    _INSTALLED = True
