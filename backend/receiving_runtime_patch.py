from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from backend import operational_api as _operational

_ORIGINAL_EXTRACT_RECEIPT_ITEMS = _operational.extract_receipt_items
_ORIGINAL_MATCH_ITEMS = _operational.match_items
_ORIGINAL_CANDIDATE_POS = _operational.candidate_pos
_PATCH_INSTALLED = False


def _to_number(value: str | None, default: float = 0.0) -> float:
    try:
        return float(str(value or "").replace(",", ".").strip())
    except Exception:
        return default


def _clean_item_name(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^[\s\-•*\u2060\u2007\u202f]*(?:\d{1,2}[\.)]?\s*)?", "", text)
    text = re.sub(r"\b(?:dari|vendor)\s+(?:haji\s+)?(?:holil|dede|wikian|heru|badri|mungki|koperasi)\b", "", text, flags=re.I)
    text = re.sub(r"^(?:barang|kiriman|pesanan|po|sudah|udah|datang|diterima|terima)\s+", "", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip(" :-=/()")


def _tahu_board_ratio(text: str) -> float:
    source = text or ""
    patterns = [
        r"\b1\s*papan\s*(?:=|:|x|isi|adalah)?\s*(\d+(?:[\.,]\d+)?)\s*pcs\b",
        r"\b1\s*papan\s*(?:=|:|x|isi|adalah)?\s*(\d+(?:[\.,]\d+)?)\s*pc\b",
        r"\b(\d+(?:[\.,]\d+)?)\s*pcs\s*(?:/|per)\s*papan\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, source, flags=re.IGNORECASE)
        if match:
            ratio = _to_number(match.group(1), 144.0)
            if ratio > 0:
                return ratio
    return 144.0


def _extract_tahu_board_item(text: str) -> dict[str, Any] | None:
    low = (text or "").lower()
    if "tahu" not in low or "papan" not in low:
        return None
    qty_papan: float | None = None
    for match in re.finditer(r"(\d+(?:[\.,]\d+)?)\s*papan\b", text or "", flags=re.IGNORECASE):
        tail = (text or "")[match.end(): match.end() + 8]
        if re.match(r"\s*(=|:|x|isi|adalah)", tail, flags=re.IGNORECASE):
            continue
        qty = _to_number(match.group(1), 0.0)
        if qty > 0:
            qty_papan = qty
            break
    if qty_papan is None:
        return None
    ratio = _tahu_board_ratio(text)
    pcs = qty_papan * ratio
    return {
        "reported_item_name": "Tahu Putih",
        "received_qty": round(pcs, 4),
        "unit": "pcs",
        "original_received_qty": qty_papan,
        "original_unit": "papan",
        "conversion_ratio": ratio,
        "conversion_note": f"{qty_papan:g} papan x {ratio:g} pcs = {pcs:g} pcs",
    }


def _structured_items(text: str) -> list[dict[str, Any]]:
    source = str(text or "")
    items: list[dict[str, Any]] = []

    # Jeruk receiving uses NET weight as stock. Gross is preserved only as audit metadata.
    net = re.search(r"total\s+berat\s+bersih\s+jeruk\D{0,20}(\d+(?:[\.,]\d+)?)\s*kg\b", source, re.I)
    gross = re.search(r"total\s+(?:berat|berak)\s+kotor\s+jeruk\D{0,20}(\d+(?:[\.,]\d+)?)\s*kg\b", source, re.I)
    if net:
        row = {"reported_item_name": "Jeruk", "received_qty": _to_number(net.group(1)), "unit": "kg"}
        if gross:
            row["gross_received_qty"] = _to_number(gross.group(1))
            row["quantity_basis"] = "NET_WEIGHT"
        items.append(row)

    # Numbered/equal-sign operational lists, including pasted WhatsApp text with unusual spaces.
    list_pattern = re.compile(
        r"(?:^|[\n\r]|\s{2,})(?:\d{1,2}[\.)]?\s*)?"
        r"(?P<name>[A-Za-z][A-Za-z ._\-/]{1,45}?)\s*(?:=|:)\s*"
        r"(?P<qty>\d+(?:[\.,]\d+)?)\s*"
        r"(?P<unit>kg|kgs|kilogram|gram|gr|pcs|pc|pack|dus|box|liter|ltr|lt|butir|papan|ikat|botol|btl|batang|btg|pouch|rol|roll)\b",
        re.I,
    )
    for match in list_pattern.finditer(source):
        name = _clean_item_name(match.group("name"))
        if not name or re.search(r"total\s+(?:berat|berak)\s+(?:kotor|bersih)\s+jeruk", name, re.I):
            continue
        items.append({"reported_item_name": name, "received_qty": _to_number(match.group("qty")), "unit": _operational.canonical_unit(match.group("unit"))})

    # Common compact messages such as "beras dari dede 200kg".
    rice = re.search(r"\bberas(?:\s+dari\s+(?:haji\s+)?[a-z]+)?\s*[:=\-]?\s*(\d+(?:[\.,]\d+)?)\s*kg\b", source, re.I)
    if rice:
        items.append({"reported_item_name": "Beras", "received_qty": _to_number(rice.group(1)), "unit": "kg"})

    return items


def _aggregate_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for original in items:
        item = dict(original)
        name = _clean_item_name(item.get("reported_item_name"))
        unit = _operational.canonical_unit(item.get("unit")) or ""
        qty = float(item.get("received_qty") or 0)
        if not name or qty <= 0:
            continue
        low = name.lower()
        if "total berat" in low or "total berak" in low or "rincian berat" in low:
            continue
        key = (_operational.normalize_text(name), unit)
        if not key[0]:
            continue
        if key not in grouped:
            grouped[key] = {**item, "reported_item_name": name, "received_qty": round(qty, 4), "unit": unit}
        else:
            grouped[key]["received_qty"] = round(float(grouped[key]["received_qty"]) + qty, 4)
            grouped[key]["aggregated_duplicate_lines"] = int(grouped[key].get("aggregated_duplicate_lines") or 1) + 1
    return list(grouped.values())


def extract_receipt_items(text: str) -> list[dict[str, Any]]:
    base_items = _ORIGINAL_EXTRACT_RECEIPT_ITEMS(text)
    structured = _structured_items(text)
    tahu_item = _extract_tahu_board_item(text)

    # Prefer structured extraction for names it recognizes; use legacy extraction as recall fallback.
    combined = [*structured]
    structured_keys = {(_operational.normalize_text(x.get("reported_item_name")), _operational.canonical_unit(x.get("unit")) or "") for x in structured}
    for item in base_items:
        name = _clean_item_name(item.get("reported_item_name"))
        unit = _operational.canonical_unit(item.get("unit")) or ""
        key = (_operational.normalize_text(name), unit)
        if key in structured_keys:
            continue
        if re.search(r"total\s+(?:berat|berak)\s+(?:kotor|bersih)\s+jeruk", name, re.I):
            continue
        # Do not turn conversion tails like "/1 ikat" into a second stock line.
        if unit == "ikat" and re.search(r"\d+(?:[\.,]\d+)?\s*kg\s*/\s*\d+(?:[\.,]\d+)?\s*ikat", text, re.I):
            continue
        combined.append({**item, "reported_item_name": name, "unit": unit})

    if tahu_item:
        combined = [x for x in combined if str(x.get("unit") or "").lower() != "papan"]
        combined.insert(0, tahu_item)
    return _aggregate_items(combined)


def match_items(reported_items: list[dict[str, Any]], po_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = _ORIGINAL_MATCH_ITEMS(reported_items, po_items)
    used = {int(x["purchase_order_item_id"]) for x in result if x.get("purchase_order_item_id")}
    for row in result:
        if row.get("matched"):
            continue
        source_tokens = set(_operational.normalize_text(row.get("reported_item_name")).split())
        if not source_tokens:
            continue
        candidates = []
        for po_item in po_items:
            if int(po_item["id"]) in used:
                continue
            target_tokens = set(_operational.normalize_text(po_item.get("item_name")).split())
            same_unit = not row.get("unit") or not po_item.get("unit") or _operational.canonical_unit(row.get("unit")) == _operational.canonical_unit(po_item.get("unit"))
            if same_unit and source_tokens.issubset(target_tokens):
                candidates.append(po_item)
        if len(candidates) != 1:
            continue
        best = candidates[0]
        po_qty = float(best.get("po_qty") or 0)
        received_qty = float(row.get("received_qty") or 0)
        row.update({
            "purchase_order_item_id": best["id"],
            "po_item_name": best["item_name"],
            "po_qty": po_qty,
            "variance_qty": round(received_qty - po_qty, 4),
            "match_confidence": 0.82,
            "match_method": "unique_po_token_containment",
            "matched": True,
        })
        used.add(int(best["id"]))
    return result


def candidate_pos(cur: Any, site: str, vendor: str | None, limit: int = 12) -> list[dict[str, Any]]:
    today = datetime.now(ZoneInfo("Asia/Jakarta")).date()
    window_start = today - timedelta(days=3)
    window_end = today + timedelta(days=7)
    sql = """
        select po.*,pc.distribution_date from purchase_orders po
        left join production_cycles pc on pc.id=po.production_cycle_id
        where upper(po.site)=upper(%s)
          and upper(po.status) in ('DRAFT','FINALIZED','SENT','ACKNOWLEDGED','PARTIAL_RECEIVED')
          and (
            pc.distribution_date between %s and %s
            or exists (
              select 1 from purchase_order_coverage poc
              where poc.purchase_order_id=po.id
                and poc.distribution_date between %s and %s
            )
          )
    """
    params: list[Any] = [site, window_start, window_end, window_start, window_end]
    if vendor:
        sql += " and upper(po.vendor_code)=upper(%s)"
        params.append(vendor)
    sql += " order by abs(pc.distribution_date-%s) asc nulls last, po.created_at desc limit %s"
    params.extend([today, limit])
    cur.execute(sql, params)
    rows = cur.fetchall()
    if rows:
        return rows
    return _ORIGINAL_CANDIDATE_POS(cur, site, vendor, limit)


def install() -> None:
    global _PATCH_INSTALLED
    if _PATCH_INSTALLED:
        return
    _operational.extract_receipt_items = extract_receipt_items
    _operational.match_items = match_items
    _operational.candidate_pos = candidate_pos
    _PATCH_INSTALLED = True
