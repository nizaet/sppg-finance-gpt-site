from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from backend import inventory_api as inv
from backend.stock_opname_parser import normalize_name

_INSTALLED = False
_ORIGINAL_PARSE = inv.parse_stock_opname_text
_ORIGINAL_LOAD_MATCHERS = inv.load_item_matchers
_ORIGINAL_CLASSIFY = inv.classify_item

# Explicit operational corrections already confirmed by the owner. These are
# conservative aliases/conversions, not fuzzy guesses.
_ALIAS_REDIRECTS = {
    "mie telor ayam": "mie",
    "mie telur ayam": "mie",
    "bombay": "bawang bombay",
    "langkuas": "lengkuas",
    "telor": "telur",
    "kuyit bubuk": "kunyit bubuk",
    "mayonnese": "mayonnaise",
    "barbeque": "barbeque sauce",
    "minyak": "minyak goreng",
}
_DEFAULT_UNITS = {
    "sapu": "pcs",
    "pel": "pcs",
    "kain pel": "pcs",
}
_WEEKDAY = r"(?:senin|selasa|rabu|kamis|jumat|jum'at|sabtu|minggu)"


def _is_header_line(line: str) -> bool:
    raw = str(line or "").strip().strip("*_#- ")
    normalized = normalize_name(raw)
    if not normalized:
        return False
    # Header styles seen in operational WhatsApp SO reports. A date/header must
    # never become an inventory item simply because it contains a number.
    if re.fullmatch(r"so(?:\s+barang)?(?:\s+(?:maja|cemplang|koperasi))?\s+\d{4}-\d{2}-\d{2}", raw, re.IGNORECASE):
        return True
    if re.fullmatch(rf"{_WEEKDAY}\s+\d{{1,2}}\s+[a-z]+\s+\d{{4}}", raw, re.IGNORECASE):
        return True
    if re.fullmatch(rf"{_WEEKDAY}\s+\d{{4}}-\d{{2}}-\d{{2}}", raw, re.IGNORECASE):
        return True
    return False


def _clean_headers(text: str) -> str:
    return "\n".join(line for line in str(text or "").splitlines() if not _is_header_line(line))


def _merge_same_line_components(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Handle arithmetic rows such as `10,20 + 3,38 kg` as one physical count."""
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        grouped[(str(item.get("normalizedItemName") or ""), str(item.get("rawLine") or ""))].append(item)

    output: list[dict[str, Any]] = []
    consumed: set[int] = set()
    for group in grouped.values():
        if len(group) <= 1:
            continue
        units = {str(row.get("unit") or "") for row in group if str(row.get("unit") or "")}
        if len(units) != 1 or "+" not in str(group[0].get("rawLine") or ""):
            continue
        unit = next(iter(units))
        for row in group:
            if not row.get("unit"):
                row["unit"] = unit
                row["parseStatus"] = "READY"
                row["warnings"] = [w for w in (row.get("warnings") or []) if "Satuan tidak tertulis" not in w]
        if any(str(row.get("unit") or "") != unit for row in group):
            continue
        first = dict(group[0])
        first["qty"] = round(sum(float(row.get("qty") or 0) for row in group), 4)
        first["unit"] = unit
        first["parseStatus"] = "READY"
        first["warnings"] = [w for w in (first.get("warnings") or []) if "Duplikat" not in w and "Satuan tidak tertulis" not in w]
        first["warnings"].append(f"Komponen penjumlahan pada baris yang sama digabung dalam satuan {unit}.")
        output.append(first)
        consumed.update(id(row) for row in group)

    for item in items:
        if id(item) not in consumed:
            output.append(item)
    return output


def _consolidate_known_packages(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply only confirmed package conversions, then consolidate compatible rows."""
    by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        by_name[str(item.get("normalizedItemName") or "")].append(item)

    output: list[dict[str, Any]] = []
    consumed: set[int] = set()
    for name, group in by_name.items():
        rule: tuple[str, str, float] | None = None
        if re.search(r"\bberas\b", name):
            rule = ("karung", "kg", 25.0)
        elif re.search(r"\bminyak(?: goreng)?\b", name):
            rule = ("dus", "liter", 12.0)
        if not rule:
            continue

        source_unit, target_unit, factor = rule
        compatible = [row for row in group if str(row.get("unit") or "") in {source_unit, target_unit}]
        if not compatible or not any(str(row.get("unit") or "") == source_unit for row in compatible):
            continue
        first = compatible[0]
        total = 0.0
        raw_lines: list[str] = []
        for row in compatible:
            amount = float(row.get("qty") or 0)
            total += amount * factor if str(row.get("unit") or "") == source_unit else amount
            raw = str(row.get("rawLine") or "").strip()
            if raw and raw not in raw_lines:
                raw_lines.append(raw)
            consumed.add(id(row))
        merged = dict(first)
        merged["qty"] = round(total, 4)
        merged["unit"] = target_unit
        merged["parseStatus"] = "READY"
        merged["rawLine"] = " | ".join(raw_lines) or str(first.get("rawLine") or "")
        merged["warnings"] = [
            w for w in (first.get("warnings") or [])
            if "Duplikat" not in w and "Satuan tidak tertulis" not in w
        ]
        merged["warnings"].append(
            f"Konversi operasional terkonfirmasi: 1 {source_unit} = {factor:g} {target_unit}; komponen digabung."
        )
        output.append(merged)

    for item in items:
        if id(item) not in consumed:
            output.append(item)
    return output


def learned_parse_stock_opname_text(text: str) -> dict[str, Any]:
    parsed = _ORIGINAL_PARSE(_clean_headers(text))
    items = [dict(row) for row in (parsed.get("items") or [])]

    for row in items:
        normalized = str(row.get("normalizedItemName") or normalize_name(row.get("itemName") or ""))
        default_unit = _DEFAULT_UNITS.get(normalized)
        if default_unit and not row.get("unit"):
            row["unit"] = default_unit
            row["parseStatus"] = "READY"
            row["warnings"] = [w for w in (row.get("warnings") or []) if "Satuan tidak tertulis" not in w]
            row.setdefault("warnings", []).append(f"Satuan operasional terkonfirmasi: {default_unit}.")

    items = _merge_same_line_components(items)
    items = _consolidate_known_packages(items)

    warnings: list[str] = []
    for row in items:
        for warning in row.get("warnings") or []:
            if warning not in warnings:
                warnings.append(warning)
    parsed["items"] = items
    parsed["itemCount"] = len(items)
    parsed["readyCount"] = sum(1 for row in items if row.get("parseStatus") == "READY")
    parsed["reviewCount"] = sum(1 for row in items if row.get("parseStatus") != "READY")
    parsed["warnings"] = warnings
    parsed["canCommit"] = bool(items)
    return parsed


def learned_load_item_matchers(cur: Any, site: str | None = None) -> list[dict[str, Any]]:
    masters = _ORIGINAL_LOAD_MATCHERS(cur, site)
    by_code = {str(row.get("code")): row for row in masters if row.get("code")}
    if not by_code:
        return masters

    try:
        params: list[Any] = []
        site_sql = ""
        if site in {"MAJA", "CEMPLANG"}:
            site_sql = " and upper(so.location_code)=%s"
            params.append(site)
        cur.execute(
            f"""
            select soi.inventory_item_code,soi.normalized_raw_name,min(soi.raw_item_name) as raw_item_name,
                   max(so.stock_date) as last_seen
            from stock_opname_items soi
            join stock_opnames so on so.id=soi.stock_opname_id
            where soi.inventory_item_code is not null
              and coalesce(soi.classification_confidence,0) >= 0.99
              and coalesce(so.status,'ACTIVE')='ACTIVE'
              {site_sql}
            group by soi.inventory_item_code,soi.normalized_raw_name
            order by max(so.stock_date) desc
            limit 1000
            """,
            params,
        )
        for row in cur.fetchall():
            master = by_code.get(str(row.get("inventory_item_code") or ""))
            alias = str(row.get("normalized_raw_name") or "").strip()
            if not master or not alias:
                continue
            aliases = list(master.get("aliases") or [])
            if alias not in aliases and alias != str(master.get("normalized_canonical_name") or ""):
                aliases.append(alias)
                master["aliases"] = aliases
            source = f"stock-opname-history:{row.get('last_seen')}"
            refs = list(master.get("source_refs") or [])
            if source not in refs:
                refs.append(source)
                master["source_refs"] = refs
    except Exception:
        # Historical learning must never make stock preview unavailable when an
        # older database has not yet received the lifecycle columns.
        pass
    return masters


def learned_classify_item(raw_name: str, masters: list[dict[str, Any]]) -> dict[str, Any]:
    normalized = normalize_name(raw_name)
    redirect = _ALIAS_REDIRECTS.get(normalized)
    if redirect:
        result = _ORIGINAL_CLASSIFY(redirect, masters)
        if result.get("classificationStatus") == "MATCHED":
            result = dict(result)
            result["classificationMethod"] = "CONFIRMED_OPERATIONAL_ALIAS"
            result["classificationConfidence"] = 1.0
            sources = list(result.get("classificationSources") or [])
            marker = f"runtime-rule:{normalized}->{redirect}"
            if marker not in sources:
                sources.append(marker)
            result["classificationSources"] = sources
            return result
    return _ORIGINAL_CLASSIFY(raw_name, masters)


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    inv.parse_stock_opname_text = learned_parse_stock_opname_text
    inv.load_item_matchers = learned_load_item_matchers
    inv.classify_item = learned_classify_item
    _INSTALLED = True
