from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.db import connection, database_ready

router = APIRouter(prefix="/v1", tags=["operational"])

SITE_VALUES = {"MAJA", "CEMPLANG"}
UNIT_ALIASES = {
    "kgs": "kg", "kilogram": "kg", "kilograms": "kg",
    "ltr": "liter", "lt": "liter", "l": "liter",
    "pc": "pcs", "piece": "pcs", "pieces": "pcs",
    "btl": "botol", "btg": "batang",
}
VENDOR_PATTERNS = {
    "HOLIL": [r"\bholil\b", r"\bhaji holil\b"],
    "WIKIAN": [r"\bwikian\b"],
    "RUMAH_DUTA_PANGAN": [r"\brumah duta pangan\b", r"\bduta pangan\b"],
    "HERU": [r"\bheru\b", r"\bgas\b"],
    "DEDE": [r"\bdede\b"],
    "HAJI_BADRI": [r"\bhaji badri\b", r"\bbadri\b"],
    "MUNGKI": [r"\bmungki\b"],
    "KOPERASI": [r"\bkoperasi\b", r"\bindogrosir\b"],
}


def require_db() -> None:
    if not database_ready():
        raise HTTPException(503, "database unavailable")


def normalize_site(site: str) -> str:
    value = site.upper().strip()
    if value not in SITE_VALUES:
        raise HTTPException(400, "site must be MAJA or CEMPLANG")
    return value


def normalize_text(value: str) -> str:
    text = value.lower().strip()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    stop = {
        "sudah", "udah", "barang", "datang", "sampai", "diterima", "terima", "lengkap", "total", "vendor",
        "maja", "cemplang", "holil", "haji", "wikian", "dede", "heru", "badri", "mungki", "koperasi",
        "rumah", "duta", "pangan",
    }
    words = [word for word in text.split() if word not in stop]
    return " ".join(words)


def infer_vendor(text: str) -> str | None:
    for vendor, patterns in VENDOR_PATTERNS.items():
        if any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns):
            return vendor
    return None


def canonical_unit(unit: str | None) -> str | None:
    if not unit:
        return None
    value = unit.lower().strip().rstrip(".")
    return UNIT_ALIASES.get(value, value)


RECEIPT_ITEM_PATTERN = re.compile(
    r"(?P<name>[A-Za-z][A-Za-z /()._\-]{1,70}?)\s*(?:[:=\-]|\bx\b)?\s*"
    r"(?P<qty>\d+(?:[\.,]\d+)?)\s*"
    r"(?P<unit>kg|kgs|kilogram|gram|gr|pcs|pc|pack|dus|box|liter|ltr|lt|l|butir|papan|ikat|botol|btl|batang|btg|pouch|rol|roll)\b",
    re.IGNORECASE,
)


def extract_receipt_items(text: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    # Split on message/list separators. A sentence prefix may still be captured by the item regex,
    # therefore we also keep only the final sentence fragment of the captured name below.
    segments = re.split(r"[\n;,]+", text)
    for segment in segments:
        clean_segment = re.sub(r"^[\-•*\s]+", "", segment.strip())
        if not clean_segment:
            continue
        for match in RECEIPT_ITEM_PATTERN.finditer(clean_segment):
            raw_name = match.group("name").strip(" :-")
            # Example: "Barang Holil Maja sudah datang. Wortel diterima" -> "Wortel diterima".
            if "." in raw_name:
                raw_name = raw_name.rsplit(".", 1)[-1].strip()
            # Remove common receipt prefixes while retaining the actual item name.
            raw_name = re.sub(
                r"^(?:maja|cemplang|barang|kiriman|pesanan|po|dari|vendor|sudah|udah|datang|diterima|terima)\s+",
                "",
                raw_name,
                flags=re.IGNORECASE,
            ).strip()
            qty = float(match.group("qty").replace(",", "."))
            if qty < 0:
                continue
            items.append({
                "reported_item_name": raw_name,
                "received_qty": qty,
                "unit": canonical_unit(match.group("unit")),
            })
    return items


def name_similarity(reported: str, po_item: dict[str, Any]) -> tuple[float, str]:
    target = normalize_text(str(po_item.get("item_name") or ""))
    candidates = [(target, "item_name")]
    aliases = po_item.get("item_aliases") or []
    if isinstance(aliases, str):
        try:
            aliases = json.loads(aliases)
        except Exception:
            aliases = []
    if isinstance(aliases, list):
        for alias in aliases:
            if alias:
                candidates.append((normalize_text(str(alias)), "alias"))
    source = normalize_text(reported)
    best_score = 0.0
    best_method = "item_name"
    for candidate, method in candidates:
        if not source or not candidate:
            continue
        score = SequenceMatcher(None, source, candidate).ratio()
        if source in candidate or candidate in source:
            score = max(score, min(len(source), len(candidate)) / max(len(source), len(candidate)))
        source_tokens, candidate_tokens = set(source.split()), set(candidate.split())
        if source_tokens and candidate_tokens:
            token_score = len(source_tokens & candidate_tokens) / len(source_tokens | candidate_tokens)
            score = max(score, token_score)
        if score > best_score:
            best_score, best_method = score, method
    return round(best_score, 5), best_method


def match_items(reported_items: list[dict[str, Any]], po_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    used: set[int] = set()
    for reported in reported_items:
        ranked: list[tuple[float, dict[str, Any], str]] = []
        for po_item in po_items:
            if po_item["id"] in used:
                continue
            score, method = name_similarity(reported["reported_item_name"], po_item)
            # Unit agreement is useful but never overrides a very poor name match.
            reported_unit = canonical_unit(reported.get("unit"))
            po_unit = canonical_unit(po_item.get("unit"))
            if reported_unit and po_unit and reported_unit == po_unit:
                score = min(1.0, score + 0.08)
            ranked.append((score, po_item, method))
        ranked.sort(key=lambda x: x[0], reverse=True)
        if ranked:
            score, best, method = ranked[0]
            matched = score >= 0.58
        else:
            score, best, method, matched = 0.0, None, "none", False
        if matched and best:
            used.add(best["id"])
        po_qty = float(best.get("po_qty") or 0) if matched and best else None
        received_qty = float(reported["received_qty"])
        result.append({
            **reported,
            "purchase_order_item_id": best["id"] if matched and best else None,
            "po_item_name": best["item_name"] if matched and best else None,
            "po_qty": po_qty,
            "variance_qty": round(received_qty - po_qty, 4) if po_qty is not None else None,
            "match_confidence": round(score, 5),
            "match_method": method if matched else "unmatched",
            "matched": bool(matched),
        })
    return result


class PurchaseOrderItemIn(BaseModel):
    item_code: str | None = None
    item_name: str = Field(min_length=1)
    planning_snapshot_item_id: int | None = None
    planned_qty: float | None = None
    po_qty: float = Field(ge=0)
    unit: str | None = None
    planning_price: float | None = Field(default=None, ge=0)
    po_price: float | None = Field(default=None, ge=0)
    aliases: list[str] = Field(default_factory=list)
    notes: str | None = None


class PurchaseOrderCreateIn(BaseModel):
    po_code: str = Field(min_length=1)
    site: Literal["MAJA", "CEMPLANG"]
    vendor_code: str = Field(min_length=1)
    distribution_date: date
    cooking_at: datetime | None = None
    source_planning_snapshot_id: int | None = None
    status: Literal["DRAFT", "FINALIZED", "SENT", "ACKNOWLEDGED"] = "DRAFT"
    items: list[PurchaseOrderItemIn] = Field(min_length=1)


@router.post("/purchase-orders")
def create_purchase_order(payload: PurchaseOrderCreateIn) -> dict[str, Any]:
    require_db()
    site = normalize_site(payload.site)
    vendor = payload.vendor_code.upper().strip()
    cycle_code = f"{site}-{payload.distribution_date.strftime('%Y%m%d')}"
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """insert into production_cycles(cycle_code,site,distribution_date,cooking_at,status)
                   values (%s,%s,%s,%s,'PLANNING')
                   on conflict (cycle_code) do update set cooking_at=coalesce(excluded.cooking_at,production_cycles.cooking_at)
                   returning id""",
                (cycle_code, site, payload.distribution_date, payload.cooking_at),
            )
            cycle_id = cur.fetchone()["id"]
            cur.execute("select coalesce(max(revision_no),0)+1 as revision from purchase_orders where po_code=%s", (payload.po_code,))
            revision = cur.fetchone()["revision"]
            finalized_at = datetime.now(timezone.utc) if payload.status != "DRAFT" else None
            cur.execute(
                """insert into purchase_orders(
                     po_code,revision_no,production_cycle_id,site,vendor_code,status,finalized_at,source_planning_snapshot_id
                   ) values (%s,%s,%s,%s,%s,%s,%s,%s) returning id""",
                (payload.po_code, revision, cycle_id, site, vendor, payload.status, finalized_at, payload.source_planning_snapshot_id),
            )
            po_id = cur.fetchone()["id"]
            for item in payload.items:
                cur.execute(
                    """insert into purchase_order_items(
                         purchase_order_id,item_code,item_name,planning_snapshot_item_id,planned_qty,po_qty,unit,
                         planning_price,po_price,item_aliases,notes
                       ) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)""",
                    (po_id, item.item_code, item.item_name.strip(), item.planning_snapshot_item_id,
                     item.planned_qty, item.po_qty, canonical_unit(item.unit), item.planning_price,
                     item.po_price, json.dumps(item.aliases, ensure_ascii=False), item.notes),
                )
            conn.commit()
    return {"purchaseOrderId": po_id, "poCode": payload.po_code, "revisionNo": revision, "status": payload.status, "itemCount": len(payload.items)}


@router.get("/purchase-orders")
def list_purchase_orders(
    site: str = "",
    vendor: str = "",
    status: str = "",
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    require_db()
    sql = """
        select po.id, po.po_code, po.revision_no, po.site, po.vendor_code, po.status,
               po.sent_at, po.acknowledged_at, po.finalized_at, po.created_at,
               pc.distribution_date, count(poi.id) as item_count,
               coalesce(sum(poi.po_qty * coalesce(poi.po_price,0)),0) as po_total
        from purchase_orders po
        left join production_cycles pc on pc.id=po.production_cycle_id
        left join purchase_order_items poi on poi.purchase_order_id=po.id
        where true
    """
    params: list[Any] = []
    if site:
        sql += " and upper(po.site)=upper(%s)"
        params.append(site)
    if vendor:
        sql += " and upper(po.vendor_code)=upper(%s)"
        params.append(vendor)
    if status:
        sql += " and upper(po.status)=upper(%s)"
        params.append(status)
    sql += " group by po.id,pc.id order by pc.distribution_date desc nulls last, po.created_at desc limit %s"
    params.append(limit)
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return {"items": cur.fetchall()}


@router.get("/purchase-orders/{purchase_order_id}")
def get_purchase_order(purchase_order_id: int) -> dict[str, Any]:
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """select po.*,pc.distribution_date,pc.cooking_at
                   from purchase_orders po left join production_cycles pc on pc.id=po.production_cycle_id
                   where po.id=%s""",
                (purchase_order_id,),
            )
            po = cur.fetchone()
            if not po:
                raise HTTPException(404, "purchase order not found")
            cur.execute("select * from purchase_order_items where purchase_order_id=%s order by id", (purchase_order_id,))
            po["items"] = cur.fetchall()
            return po


class WhatsAppReceiptIn(BaseModel):
    site: Literal["MAJA", "CEMPLANG"]
    text: str = Field(min_length=1)
    vendor_code: str | None = None
    purchase_order_id: int | None = None
    received_at: datetime | None = None
    source_external_id: str | None = None
    source_uri: str | None = None
    reporter: str | None = None
    commit: bool = False


def load_po_items(cur, po_id: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    cur.execute(
        """select po.*,pc.distribution_date from purchase_orders po
           left join production_cycles pc on pc.id=po.production_cycle_id where po.id=%s""",
        (po_id,),
    )
    po = cur.fetchone()
    if not po:
        raise HTTPException(404, "purchase order not found")
    cur.execute("select * from purchase_order_items where purchase_order_id=%s order by id", (po_id,))
    return po, cur.fetchall()


def candidate_pos(cur, site: str, vendor: str | None, limit: int = 12) -> list[dict[str, Any]]:
    sql = """
        select po.*,pc.distribution_date from purchase_orders po
        left join production_cycles pc on pc.id=po.production_cycle_id
        where upper(po.site)=upper(%s)
          and upper(po.status) in ('DRAFT','FINALIZED','SENT','ACKNOWLEDGED','PARTIAL_RECEIVED')
    """
    params: list[Any] = [site]
    if vendor:
        sql += " and upper(po.vendor_code)=upper(%s)"
        params.append(vendor)
    sql += " order by pc.distribution_date desc nulls last, po.created_at desc limit %s"
    params.append(limit)
    cur.execute(sql, params)
    return cur.fetchall()


def choose_po(cur, payload: WhatsAppReceiptIn, reported_items: list[dict[str, Any]], vendor: str | None) -> tuple[dict[str, Any] | None, list[dict[str, Any]], float, list[dict[str, Any]]]:
    if payload.purchase_order_id:
        po, po_items = load_po_items(cur, payload.purchase_order_id)
        if po["site"].upper() != payload.site.upper():
            raise HTTPException(400, "purchase order site does not match receipt site")
        matches = match_items(reported_items, po_items)
        score = sum(x["match_confidence"] for x in matches) / len(matches) if matches else 0.0
        return po, matches, round(score, 5), []

    candidates = candidate_pos(cur, payload.site, vendor)
    ranked: list[dict[str, Any]] = []
    for po in candidates:
        _, po_items = load_po_items(cur, po["id"])
        matches = match_items(reported_items, po_items)
        item_score = sum(x["match_confidence"] for x in matches) / len(matches) if matches else 0.0
        matched_ratio = sum(1 for x in matches if x["matched"]) / len(matches) if matches else 0.0
        vendor_bonus = 0.08 if vendor and po["vendor_code"].upper() == vendor.upper() else 0.0
        score = min(1.0, item_score * 0.75 + matched_ratio * 0.17 + vendor_bonus)
        ranked.append({"po": po, "matches": matches, "score": round(score, 5)})
    ranked.sort(key=lambda x: x["score"], reverse=True)
    if not ranked:
        return None, [], 0.0, []
    best = ranked[0]
    alternatives = [
        {"purchase_order_id": x["po"]["id"], "po_code": x["po"]["po_code"], "vendor_code": x["po"]["vendor_code"], "score": x["score"]}
        for x in ranked[:5]
    ]
    return best["po"], best["matches"], best["score"], alternatives


def source_key(payload: WhatsAppReceiptIn, vendor: str | None) -> str:
    canonical = {
        "site": payload.site,
        "vendor": vendor,
        "external_id": payload.source_external_id,
        "text": payload.text.strip(),
    }
    return "wa-receipt:" + hashlib.sha256(json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


@router.post("/receiving/whatsapp")
def receive_from_whatsapp(payload: WhatsAppReceiptIn) -> dict[str, Any]:
    require_db()
    site = normalize_site(payload.site)
    reported_items = extract_receipt_items(payload.text)
    if not reported_items:
        return {
            "committed": False,
            "canCommit": False,
            "site": site,
            "vendorCode": payload.vendor_code or infer_vendor(payload.text),
            "reason": "no quantity items could be extracted",
            "reportedItems": [],
            "matches": [],
        }
    vendor = (payload.vendor_code or infer_vendor(payload.text) or "").upper().strip() or None

    with connection() as conn:
        with conn.cursor() as cur:
            po, matches, po_score, alternatives = choose_po(cur, payload, reported_items, vendor)
            all_matched = bool(matches) and all(x["matched"] and x["match_confidence"] >= 0.62 for x in matches)
            candidate_clear = payload.purchase_order_id is not None or (
                po_score >= 0.66 and (len(alternatives) < 2 or po_score - alternatives[1]["score"] >= 0.06)
            )
            can_commit = bool(po and all_matched and candidate_clear)
            result = {
                "committed": False,
                "canCommit": can_commit,
                "site": site,
                "vendorCode": vendor,
                "purchaseOrderId": po["id"] if po else None,
                "poCode": po["po_code"] if po else None,
                "poMatchConfidence": po_score,
                "reportedItems": reported_items,
                "matches": matches,
                "alternatives": alternatives,
                "requiresConfirmation": True,
            }
            if not payload.commit:
                return result
            if not can_commit:
                raise HTTPException(409, detail={"message": "receipt match is not safe to commit", **result})

            key = source_key(payload, vendor)
            cur.execute("select id from goods_receipts where source_key=%s", (key,))
            duplicate = cur.fetchone()
            if duplicate:
                result.update({"committed": True, "duplicate": True, "receiptId": duplicate["id"]})
                return result

            min_confidence = min(x["match_confidence"] for x in matches)
            cur.execute(
                """insert into goods_receipts(
                     purchase_order_id,receipt_code,received_at,source_type,source_external_id,source_key,
                     reporter,raw_text,match_status,match_confidence,confirmed_at
                   ) values (%s,%s,coalesce(%s,now()),'WHATSAPP',%s,%s,%s,%s,'CONFIRMED',%s,now()) returning id""",
                (po["id"], None, payload.received_at, payload.source_external_id, key,
                 payload.reporter, payload.text, min_confidence),
            )
            receipt_id = cur.fetchone()["id"]
            for item in matches:
                cur.execute(
                    """insert into goods_receipt_items(
                         goods_receipt_id,purchase_order_item_id,received_qty,rejected_qty,accepted_qty,unit,
                         quality_status,notes,reported_item_name,po_qty_snapshot,variance_qty,match_confidence,match_method
                       ) values (%s,%s,%s,0,%s,%s,'ACCEPTED',null,%s,%s,%s,%s,%s)""",
                    (receipt_id, item["purchase_order_item_id"], item["received_qty"], item["received_qty"],
                     item["unit"], item["reported_item_name"], item["po_qty"], item["variance_qty"],
                     item["match_confidence"], item["match_method"]),
                )

            # Determine status from cumulative accepted receipts; PO quantity itself is never overwritten.
            cur.execute(
                """select poi.id,poi.po_qty,coalesce(sum(gri.accepted_qty),0) as received_total
                   from purchase_order_items poi
                   left join goods_receipt_items gri on gri.purchase_order_item_id=poi.id
                   where poi.purchase_order_id=%s
                   group by poi.id order by poi.id""",
                (po["id"],),
            )
            totals = cur.fetchall()
            complete = bool(totals) and all(float(x["received_total"] or 0) >= float(x["po_qty"] or 0) for x in totals)
            new_status = "RECEIVED" if complete else "PARTIAL_RECEIVED"
            cur.execute("update purchase_orders set status=%s,updated_at=now() where id=%s", (new_status, po["id"]))
            conn.commit()
            result.update({"committed": True, "duplicate": False, "receiptId": receipt_id, "purchaseOrderStatus": new_status})
            return result


@router.get("/receiving/variance")
def receiving_variance(site: str = "", limit: int = Query(default=200, ge=1, le=1000)) -> dict[str, Any]:
    require_db()
    sql = """
        select gr.id as receipt_id,gr.received_at,gr.source_type,gr.reporter,gr.match_confidence,
               po.id as purchase_order_id,po.po_code,po.site,po.vendor_code,po.status as po_status,
               gri.id as receipt_item_id,gri.reported_item_name,poi.item_name as po_item_name,
               gri.po_qty_snapshot,gri.received_qty,gri.accepted_qty,gri.rejected_qty,gri.variance_qty,
               gri.unit,gri.match_confidence as item_match_confidence,gri.match_method
        from goods_receipt_items gri
        join goods_receipts gr on gr.id=gri.goods_receipt_id
        join purchase_orders po on po.id=gr.purchase_order_id
        left join purchase_order_items poi on poi.id=gri.purchase_order_item_id
        where true
    """
    params: list[Any] = []
    if site:
        sql += " and upper(po.site)=upper(%s)"
        params.append(site)
    sql += " order by gr.received_at desc nulls last,gr.id desc,gri.id limit %s"
    params.append(limit)
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return {"items": cur.fetchall()}
