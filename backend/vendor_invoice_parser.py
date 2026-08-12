from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any


ALIASES = {
    "tw merah": "Cabai Merah TW",
    "cabai merah tw": "Cabai Merah TW",
    "daun bw": "Daun Bawang",
    "daun bawang": "Daun Bawang",
    "daun jruk": "Daun Jeruk",
    "daun jeruk": "Daun Jeruk",
    "jruk medan": "Jeruk Medan",
    "jeruk medan": "Jeruk Medan",
    "kmbang kol": "Kembang Kol",
    "kembang kol": "Kembang Kol",
    "jagung kupas": "Jagung Kupas",
    "wortel": "Wortel",
    "tomat": "Tomat",
    "sereh": "Sereh",
    "serai": "Sereh",
    "kol": "Kol Putih",
    "kol putih": "Kol Putih",
}


def norm(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def canonical_item(value: str) -> str:
    n = norm(value)
    return ALIASES.get(n, " ".join(x.capitalize() for x in n.split()))


def parse_num(value: str) -> float:
    s = value.strip().replace("Rp", "").replace("rp", "").replace(" ", "")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        left, right = s.rsplit(",", 1)
        if len(right) <= 2:
            s = left.replace(".", "") + "." + right
        else:
            s = s.replace(",", "")
    elif "." in s:
        parts = s.split(".")
        if len(parts) > 1 and all(len(x) == 3 for x in parts[1:]):
            s = "".join(parts)
    return float(s)


def fmt_qty(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return (f"{value:.4f}".rstrip("0").rstrip(".")).replace(".", ",")


def fmt_idr(value: float) -> str:
    return f"{int(round(value)):,}".replace(",", ".")


LINE_RE = re.compile(
    r"^\s*(?P<item>.+?)\s+(?P<qty>\d+(?:[\.,]\d+)?)\s*[xX×]\s*(?P<price>\d[\d\.,]*)\s*=\s*(?:Rp\.?\s*)?(?P<total>\d[\d\.,]*)\s*$",
    re.IGNORECASE,
)
TOTAL_RE = re.compile(r"^\s*total\s*(?:rp\.?\s*)?(?P<total>\d[\d\.,]*)\s*$", re.IGNORECASE)
REJECT_RE = re.compile(
    r"\b(?:riject|reject|rijek|rejek)\b\s*(?:\d+\s+)?(?P<item>[a-zA-Z][a-zA-Z\s\[\]-]*?)\s+(?P<qty>\d+(?:[\.,]\d+)?)\s*(?P<unit>kg|gr|gram|pcs|pc|buah|ikat|pack|papan)\b",
    re.IGNORECASE,
)


def _best_item_match(reject_name: str, items: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, float]:
    needle = norm(canonical_item(reject_name))
    best = None
    best_rank: tuple[float, int, float] = (0.0, 0, 0.0)
    for item in items:
        candidate = norm(str(item["item_name"]))
        score = SequenceMatcher(None, needle, candidate).ratio()
        if needle in candidate or candidate in needle:
            score = max(score, 0.95)
        # Prefer a primary-name match ("jeruk" -> "Jeruk Medan") over a
        # modifier match ("jeruk" -> "Daun Jeruk"). When still tied, prefer
        # the larger invoice quantity because reject reports normally refer to
        # the actual bulk line being inspected.
        primary = 1 if candidate == needle or candidate.startswith(needle + " ") else 0
        qty = float(item.get("invoiced_qty") or 0)
        rank = (score, primary, qty)
        if rank > best_rank:
            best = item
            best_rank = rank
    return best, best_rank[0]


def parse_vendor_invoice_text(text: str, vendor_code: str | None = None, site: str | None = None) -> dict[str, Any]:
    lines: list[dict[str, Any]] = []
    declared_total: float | None = None
    warnings: list[str] = []

    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        m = LINE_RE.match(stripped)
        if m:
            qty = parse_num(m.group("qty"))
            price = parse_num(m.group("price"))
            declared_line_total = parse_num(m.group("total"))
            computed = round(qty * price, 2)
            item = {
                "reported_item_name": m.group("item").strip(),
                "item_name": canonical_item(m.group("item")),
                "invoiced_qty": qty,
                "unit": "kg",
                "vendor_cost_price": price,
                "declared_line_total": declared_line_total,
                "computed_line_total": computed,
                "line_total_matches": abs(declared_line_total - computed) <= 1,
                "rejected_qty": 0.0,
                "reject_amount": 0.0,
                "payable_qty": qty,
                "net_line_total": computed,
            }
            if not item["line_total_matches"]:
                warnings.append(f"Line total mismatch: {item['item_name']}")
            lines.append(item)
            continue
        t = TOTAL_RE.match(stripped)
        if t:
            declared_total = parse_num(t.group("total"))

    for rm in REJECT_RE.finditer(text):
        reject_qty = parse_num(rm.group("qty"))
        matched, score = _best_item_match(rm.group("item"), lines)
        if matched is None or score < 0.70:
            warnings.append(f"Rijek tidak dapat dicocokkan: {rm.group(0).strip()}")
            continue
        if reject_qty > float(matched["invoiced_qty"]):
            warnings.append(f"Rijek melebihi qty invoice: {matched['item_name']}")
            continue
        matched["rejected_qty"] = reject_qty
        matched["reject_match_confidence"] = round(score, 5)
        matched["reject_amount"] = round(reject_qty * float(matched["vendor_cost_price"]), 2)
        matched["payable_qty"] = round(float(matched["invoiced_qty"]) - reject_qty, 4)
        matched["net_line_total"] = round(float(matched["computed_line_total"]) - float(matched["reject_amount"]), 2)

    gross = round(sum(float(x["computed_line_total"]) for x in lines), 2)
    reject_total = round(sum(float(x["reject_amount"]) for x in lines), 2)
    net = round(gross - reject_total, 2)
    if declared_total is not None and abs(declared_total - gross) > 1:
        warnings.append(f"Declared total Rp {fmt_idr(declared_total)} berbeda dari hasil hitung Rp {fmt_idr(gross)}")

    return {
        "vendorCode": vendor_code,
        "site": site,
        "items": lines,
        "declaredTotal": declared_total,
        "grossAmount": gross,
        "rejectDeduction": reject_total,
        "netAmount": net,
        "warnings": warnings,
        "canCommit": bool(lines) and not any("mismatch" in x.lower() or "berbeda" in x.lower() for x in warnings),
    }


def payment_draft(parsed: dict[str, Any], vendor_label: str, account_label: str, invoice_date_label: str) -> str:
    out = [
        "📌 *RANCANGAN PEMBAYARAN VENDOR*",
        f"👤 *Vendor:* {vendor_label}",
        f"📦 *Akun:* {account_label}",
        f"📅 *Tanggal Tagihan:* {invoice_date_label}",
        "",
        "*1. RINCIAN BARANG:*",
        "",
    ]
    for x in parsed["items"]:
        out.append(
            f"- {x['item_name']} ({fmt_qty(float(x['invoiced_qty']))} {x['unit']} x {fmt_idr(float(x['vendor_cost_price']))}) : Rp {fmt_idr(float(x['computed_line_total']))}"
        )
    out.extend(["", f"💰 *TOTAL BRUTO: Rp {fmt_idr(float(parsed['grossAmount']))}*"])
    rejects = [x for x in parsed["items"] if float(x.get("rejected_qty") or 0) > 0]
    if rejects:
        out.extend(["", "*2. POTONGAN RIJEK:*", ""])
        for x in rejects:
            out.append(
                f"- {x['item_name']} Rijek ({fmt_qty(float(x['rejected_qty']))} {x['unit']} x {fmt_idr(float(x['vendor_cost_price']))}) : (Rp {fmt_idr(float(x['reject_amount']))})"
            )
        out.extend(["", f"📉 *TOTAL POTONGAN: Rp {fmt_idr(float(parsed['rejectDeduction']))}*"])
    out.extend(["", f"✅ *TOTAL NETTO DIBAYARKAN: Rp {fmt_idr(float(parsed['netAmount']))}*"])
    return "\n".join(out)
