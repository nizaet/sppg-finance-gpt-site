from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from backend import operational_api as _operational

_ORIGINAL_EXTRACT_RECEIPT_ITEMS = _operational.extract_receipt_items
_ORIGINAL_CANDIDATE_POS = _operational.candidate_pos
_PATCH_INSTALLED = False


def _to_number(value: str | None, default: float = 0.0) -> float:
    try:
        return float(str(value or "").replace(",", ".").strip())
    except Exception:
        return default


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
        # Skip the conversion fragment in strings like "1 papan = 144 pcs".
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


def extract_receipt_items(text: str) -> list[dict[str, Any]]:
    base_items = _ORIGINAL_EXTRACT_RECEIPT_ITEMS(text)
    tahu_item = _extract_tahu_board_item(text)
    if not tahu_item:
        return base_items

    filtered: list[dict[str, Any]] = []
    ratio = float(tahu_item.get("conversion_ratio") or 144.0)
    for item in base_items:
        unit = str(item.get("unit") or "").lower()
        name = str(item.get("reported_item_name") or "").lower()
        qty = float(item.get("received_qty") or 0)
        if unit == "papan":
            continue
        if unit == "pcs" and abs(qty - ratio) < 0.0001 and "papan" in name:
            continue
        filtered.append(item)

    return [tahu_item, *filtered]


def candidate_pos(cur: Any, site: str, vendor: str | None, limit: int = 12) -> list[dict[str, Any]]:
    # Receiving preview should not scan old PO history first. Use a short
    # operational window, then fall back to the legacy query only if the window
    # has no candidate. This keeps GPTS matching responsive without changing
    # stored PO/receipt data.
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
    sql += " order by pc.distribution_date desc nulls last, po.created_at desc limit %s"
    params.append(limit)
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
    _operational.candidate_pos = candidate_pos
    _PATCH_INSTALLED = True
