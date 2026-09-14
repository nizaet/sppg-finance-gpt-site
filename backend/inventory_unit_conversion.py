from __future__ import annotations

import json
from typing import Any

from backend.stock_opname_parser import canonical_unit


# Owner-confirmed operating conversions. These are intentionally narrow: no
# other pcs/botol/pack item is guessed without an inventory-master rule.
_CONFIRMED_OPERATIONAL_UNITS: dict[str, dict[str, Any]] = {
    "LADA_PUTIH": {"target": "kg", "factors": {"pcs": 1.0}},
    # Historical Calculator rows labelled Saori as liter. The owner confirmed
    # each Saori bottle is 1 kg, so the old numeric planning quantity is kept
    # while its operational unit is corrected to kg.
    "SAUS_TIRAM": {"target": "kg", "factors": {"botol": 1.0, "liter": 1.0}},
}


def _metadata(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            return {}
    return {}


def inventory_unit_conversion(
    match: dict[str, Any],
    source_unit: Any,
) -> tuple[str, float, str | None]:
    """Return target unit, multiplier, and an audit label.

    Conversions are either explicitly confirmed operating rules or opt-in per
    inventory master. A package name alone never proves its weight or volume,
    so unrelated pcs/botol/pack items are never silently treated as kg/liter.
    """
    source = canonical_unit(source_unit) or ""
    if not source:
        return source, 1.0, None

    type_code = str(match.get("stockTypeCode") or match.get("stock_type_code") or "").upper()
    confirmed = _CONFIRMED_OPERATIONAL_UNITS.get(type_code) or {}
    target = canonical_unit(confirmed.get("target")) or ""
    factor = (confirmed.get("factors") or {}).get(source)
    if target and source != target and factor is not None:
        multiplier = float(factor)
        return target, multiplier, f"1 {source} = {multiplier:g} {target} (aturan operasional)"

    base = canonical_unit(match.get("baseUnit") or match.get("base_unit")) or ""
    if not base or source == base:
        return source, 1.0, None

    metadata = _metadata(match.get("metadata"))
    conversions = metadata.get("unit_conversions") or metadata.get("unitConversions") or {}
    if not isinstance(conversions, dict):
        return source, 1.0, None

    raw_rule = conversions.get(source)
    factor: Any = raw_rule
    target = base
    if isinstance(raw_rule, dict):
        factor = raw_rule.get("factor")
        target = canonical_unit(raw_rule.get("to_unit") or raw_rule.get("toUnit")) or base
    try:
        multiplier = float(factor)
    except (TypeError, ValueError):
        return source, 1.0, None
    if multiplier <= 0 or target != base:
        return source, 1.0, None
    return base, multiplier, f"1 {source} = {multiplier:g} {base}"


def convert_inventory_quantity(
    quantity: Any,
    source_unit: Any,
    match: dict[str, Any],
) -> tuple[float, str, str | None]:
    target, multiplier, label = inventory_unit_conversion(match, source_unit)
    return float(quantity or 0) * multiplier, target, label
