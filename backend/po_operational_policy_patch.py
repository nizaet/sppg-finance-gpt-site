from __future__ import annotations

from datetime import date, datetime, timedelta
import re
from typing import Any

from backend import inventory_projection_v2_api as inventory_projection
from backend import planning_api as planning
from backend import po_reminder_v4_api as reminder
from backend import purchase_order_workflow_api as workflow
from backend.db import connection
from backend.item_taxonomy import item_family, normalize_item_text, vendor_for_item
from backend.stock_opname_parser import canonical_unit

_INSTALLED = False
_ORIGINAL_FORMATTER = workflow.format_purchase_order_whatsapp
_ORIGINAL_PROJECTION_LOOKUP = reminder._projection_lookup
_ORIGINAL_RULE_RESOLVER = reminder._resolve_procurement_rule
_ORIGINAL_INVENTORY_BALANCES_V2 = inventory_projection.inventory_balances_v2
_ORIGINAL_GET_PLANNING_SNAPSHOT = planning.get_planning_snapshot

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

    vendor_rules is the editable source of truth. Exact item-family rules beat
    stale preferred_vendor/category values copied into an older planning row.
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


def _stock_key(name: Any, unit: Any) -> tuple[str, str]:
    return reminder._stock_key(name, canonical_unit(unit) or unit)


def _available(item: dict[str, Any]) -> float:
    value = item.get("available_for_po")
    if value is None:
        value = item.get("balance")
    return max(0.0, float(value or 0))


def _warehouse_projection_lookup(distribution_date: date) -> tuple[dict[tuple[str, str], float], str]:
    try:
        payload = _ORIGINAL_INVENTORY_BALANCES_V2(
            site="KOPERASI",
            search="",
            limit=1000,
            for_date=distribution_date,
        )
    except Exception:
        return {}, "KOPERASI_PROJECTION_UNAVAILABLE"

    lookup: dict[tuple[str, str], float] = {}
    for item in payload.get("items") or []:
        key = _stock_key(item.get("item_name"), item.get("unit"))
        lookup[key] = max(lookup.get(key, 0.0), _available(item))
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


def _merge_stock_rows(site_items: list[dict[str, Any]], warehouse_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Expose Gudang Koperasi stock to the PO planner as usable stock.

    This is intentionally additive. The planner already computes PO Qty as
    planning minus available_for_po, so feeding the combined availability makes
    stock that is ready in Gudang Koperasi suppress unnecessary vendor ordering.
    """
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in site_items:
        item = dict(raw)
        key = _stock_key(item.get("item_name"), item.get("unit"))
        item["site_available_for_po"] = _available(item)
        item["warehouse_available_for_po"] = 0.0
        merged[key] = item

    for raw in warehouse_items:
        warehouse = dict(raw)
        key = _stock_key(warehouse.get("item_name"), warehouse.get("unit"))
        warehouse_available = _available(warehouse)
        if key not in merged:
            item = warehouse
            item["site_available_for_po"] = 0.0
            item["warehouse_available_for_po"] = warehouse_available
            item["available_for_po"] = warehouse_available
            item["balance"] = warehouse_available
            item["stock_basis"] = "GUDANG_KOPERASI_AVAILABLE_FOR_SITE_PO"
            areas = list(item.get("area_codes") or [])
            if "KOPERASI" not in areas:
                areas.append("KOPERASI")
            item["area_codes"] = areas
            merged[key] = item
            continue

        item = merged[key]
        site_available = _available(item)
        total_available = round(site_available + warehouse_available, 4)
        item["site_available_for_po"] = site_available
        item["warehouse_available_for_po"] = warehouse_available
        item["available_for_po"] = total_available
        item["balance"] = total_available
        item["projected_balance"] = round(float(item.get("projected_balance") or 0) + float(warehouse.get("projected_balance") or warehouse_available), 4)
        item["actual_balance"] = round(float(item.get("actual_balance") or 0) + float(warehouse.get("actual_balance") or warehouse_available), 4)
        item["stock_basis"] = f"{item.get('stock_basis') or 'SITE'}+GUDANG_KOPERASI"
        item["raw_item_names"] = list(dict.fromkeys([
            *(item.get("raw_item_names") or []),
            warehouse.get("item_name"),
            *(warehouse.get("raw_item_names") or []),
        ]))
        areas = list(dict.fromkeys([*(item.get("area_codes") or []), "KOPERASI"]))
        item["area_codes"] = areas

    return list(merged.values())


def inventory_balances_v2_with_warehouse(
    site: str,
    search: str = "",
    limit: int = 300,
    for_date: date | None = None,
) -> dict[str, Any]:
    normalized_site = str(site or "").upper().strip()
    if normalized_site not in {"MAJA", "CEMPLANG"}:
        return _ORIGINAL_INVENTORY_BALANCES_V2(site=site, search=search, limit=limit, for_date=for_date)

    base = _ORIGINAL_INVENTORY_BALANCES_V2(site=site, search="", limit=1000, for_date=for_date)
    try:
        warehouse = _ORIGINAL_INVENTORY_BALANCES_V2(site="KOPERASI", search="", limit=1000, for_date=for_date)
        combined = _merge_stock_rows(base.get("items") or [], warehouse.get("items") or [])
    except Exception as exc:
        base["warehouseStockIncluded"] = False
        base["warehouseStockError"] = type(exc).__name__
        return base

    needle = search.strip().lower()
    if needle:
        combined = [
            item for item in combined
            if needle in " ".join([
                str(item.get("item_name") or ""),
                *(str(value) for value in item.get("raw_item_names") or []),
            ]).lower()
        ]
    combined.sort(key=lambda item: str(item.get("item_name") or "").lower())
    base["items"] = combined[:limit]
    base["count"] = len(base["items"])
    base["warehouseStockIncluded"] = True
    base["warehouseStockSite"] = "KOPERASI"
    base["projectionModel"] = f"{base.get('projectionModel') or 'SITE'} + Gudang Koperasi available stock"
    return base


def _snapshot_cooking_date(snapshot: dict[str, Any]) -> date | None:
    raw = snapshot.get("cooking_at")
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if isinstance(raw, str):
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            pass
    distribution = workflow.as_date(snapshot.get("distribution_date"))
    return distribution - timedelta(days=1) if distribution else None


def _active_rules_for_snapshot(site: str, cook: date) -> tuple[list[dict[str, Any]], dict[str, str]]:
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select vr.*, e.name vendor_name
                from vendor_rules vr
                join entities e on e.code=vr.vendor_code
                where (vr.site_code is null or upper(vr.site_code)=upper(%s))
                  and vr.effective_from <= %s
                  and (vr.effective_to is null or vr.effective_to >= %s)
                """,
                (site, cook, cook),
            )
            rules = [dict(row) for row in cur.fetchall()]
            cur.execute("select upper(code) code,name from entities where active=true")
            names = {str(row["code"]).upper(): str(row.get("name") or row["code"]) for row in cur.fetchall()}
    return rules, names


def get_planning_snapshot_with_vendor_policy(snapshot_id: int) -> dict[str, Any]:
    """Refresh preferred vendor from effective vendor rules before PO drafting."""
    snapshot = _ORIGINAL_GET_PLANNING_SNAPSHOT(snapshot_id)
    site = str(snapshot.get("site") or "").upper().strip()
    cook = _snapshot_cooking_date(snapshot)
    if site not in {"MAJA", "CEMPLANG"} or cook is None:
        return snapshot

    try:
        rules, vendor_names = _active_rules_for_snapshot(site, cook)
    except Exception:
        return snapshot

    corrected = []
    for raw in snapshot.get("items") or []:
        item = dict(raw)
        vendor, rule, _ = _resolve_procurement_rule(
            rules,
            vendor_names,
            {
                **item,
                "site": site,
                "cooking_date": cook,
            },
        )
        if vendor:
            previous = item.get("preferred_vendor_code")
            item["preferred_vendor_code"] = vendor
            item["vendor_assignment_source"] = "VENDOR_RULE_DATABASE" if rule else "ITEM_TAXONOMY"
            if previous and str(previous).upper() != vendor:
                item["previous_preferred_vendor_code"] = previous
        corrected.append(item)
    snapshot["items"] = corrected
    snapshot["vendorPolicyApplied"] = True
    return snapshot


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


def _patch_route(router: Any, suffix: str, endpoint: Any) -> bool:
    for route in router.routes:
        if str(getattr(route, "path", "")).endswith(suffix):
            route.endpoint = endpoint
            if getattr(route, "dependant", None) is not None:
                route.dependant.call = endpoint
            return True
    return False


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    workflow.format_purchase_order_whatsapp = format_purchase_order_whatsapp
    reminder._resolve_procurement_rule = _resolve_procurement_rule
    reminder._projection_lookup = _projection_lookup

    # The manual PO planner reads these API routes directly. Patching only the
    # reminder backend would leave stale vendor and warehouse stock in the UI.
    inventory_projection.inventory_balances_v2 = inventory_balances_v2_with_warehouse
    _patch_route(inventory_projection.router, "/inventory/balances-v2", inventory_balances_v2_with_warehouse)

    planning.get_planning_snapshot = get_planning_snapshot_with_vendor_policy
    _patch_route(planning.router, "/planning-snapshots/{snapshot_id}", get_planning_snapshot_with_vendor_policy)

    _INSTALLED = True
