from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from backend import operational_api as op

_INSTALLED = False
_MIN_SCORE = 0.62
_AMBIGUITY_MARGIN = 0.035
_ACTIVE = ("DRAFT", "FINALIZED", "SENT", "ACKNOWLEDGED", "PARTIAL_RECEIVED")


def _target_date(payload: op.WhatsAppReceiptIn) -> date:
    if payload.received_at:
        value = payload.received_at
        if value.tzinfo is not None:
            return value.astimezone(ZoneInfo("Asia/Jakarta")).date()
        return value.date()
    return datetime.now(ZoneInfo("Asia/Jakarta")).date()


def _candidate_pos(cur: Any, payload: op.WhatsAppReceiptIn, vendor: str | None) -> list[dict[str, Any]]:
    if payload.purchase_order_id:
        po, _ = op.load_po_items(cur, payload.purchase_order_id)
        if str(po.get("site") or "").upper() != payload.site.upper():
            raise HTTPException(400, "purchase order site does not match receipt site")
        if vendor and str(po.get("vendor_code") or "").upper() != vendor:
            raise HTTPException(400, "purchase order vendor does not match receipt vendor")
        return [po]

    target = _target_date(payload)
    start, end = target - timedelta(days=4), target + timedelta(days=7)
    sql = """
        select po.*,pc.distribution_date
        from purchase_orders po
        left join production_cycles pc on pc.id=po.production_cycle_id
        where upper(po.site)=upper(%s)
          and upper(po.status)=any(%s)
          and (
            pc.distribution_date between %s and %s
            or exists (
              select 1 from purchase_order_coverage poc
              where poc.purchase_order_id=po.id
                and poc.distribution_date between %s and %s
            )
          )
    """
    params: list[Any] = [payload.site, list(_ACTIVE), start, end, start, end]
    if vendor:
        sql += " and upper(po.vendor_code)=upper(%s)"
        params.append(vendor)
    sql += """
        order by case when pc.distribution_date is null then 1 else 0 end,
                 abs(pc.distribution_date-%s) asc nulls last,
                 pc.distribution_date asc nulls last,po.created_at asc,po.id asc
        limit 40
    """
    params.append(target)
    cur.execute(sql, params)
    rows = cur.fetchall()
    return rows or op.candidate_pos(cur, payload.site, vendor, 40)


def _candidate_items(cur: Any, pos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ids = [int(row["id"]) for row in pos]
    if not ids:
        return []
    cur.execute(
        """
        select poi.*,po.po_code,po.vendor_code,po.status as po_status,pc.distribution_date,
               coalesce(sum(gri.accepted_qty),0) as received_total
        from purchase_order_items poi
        join purchase_orders po on po.id=poi.purchase_order_id
        left join production_cycles pc on pc.id=po.production_cycle_id
        left join goods_receipt_items gri on gri.purchase_order_item_id=poi.id
        where poi.purchase_order_id=any(%s)
        group by poi.id,po.po_code,po.vendor_code,po.status,pc.distribution_date
        order by pc.distribution_date asc nulls last,poi.purchase_order_id,poi.id
        """,
        (ids,),
    )
    return cur.fetchall()


def _score(reported: dict[str, Any], item: dict[str, Any]) -> tuple[float, str]:
    score, method = op.name_similarity(str(reported.get("reported_item_name") or ""), item)
    source = op.normalize_text(str(reported.get("reported_item_name") or ""))
    target = op.normalize_text(str(item.get("item_name") or ""))
    st, tt = set(source.split()), set(target.split())
    if source and source == target:
        score, method = 1.0, "exact_normalized_name"
    elif st and tt and (st.issubset(tt) or tt.issubset(st)):
        score, method = max(score, 0.82), "token_containment"
    ru, pu = op.canonical_unit(reported.get("unit")), op.canonical_unit(item.get("unit"))
    if ru and pu:
        score = min(1.0, score + 0.08) if ru == pu else max(0.0, score - 0.20)
    return round(score, 5), method


def _same_family(source_name: str, left_name: str, right_name: str) -> bool:
    source = set(op.normalize_text(source_name).split())
    left = set(op.normalize_text(left_name).split())
    right = set(op.normalize_text(right_name).split())
    if not left or not right:
        return False
    return left == right or (source and source.issubset(left) and source.issubset(right)) or left.issubset(right) or right.issubset(left)


def _order(item: dict[str, Any], target: date) -> tuple[Any, ...]:
    dist = item.get("distribution_date")
    distance = abs((dist - target).days) if dist else 9999
    outstanding = max(float(item.get("po_qty") or 0) - float(item.get("received_total") or 0), 0.0)
    return (0 if outstanding > 0.00005 else 1, distance, dist or date.max, int(item["purchase_order_id"]), int(item["id"]))


def _resolve_line(reported: dict[str, Any], items: list[dict[str, Any]], target: date) -> dict[str, Any]:
    ranked = []
    for item in items:
        score, method = _score(reported, item)
        ranked.append({"score": score, "method": method, "item": item})
    ranked.sort(key=lambda row: (row["score"], -_order(row["item"], target)[1]), reverse=True)
    if not ranked or ranked[0]["score"] < _MIN_SCORE:
        return {**reported, "matched": False, "match_confidence": ranked[0]["score"] if ranked else 0.0,
                "match_method": "unmatched", "purchase_order_item_id": None, "po_item_name": None,
                "po_qty": None, "variance_qty": None, "allocations": [], "ambiguity": None}

    best = ranked[0]
    second = ranked[1] if len(ranked) > 1 else None
    if second and second["score"] >= _MIN_SCORE and best["score"] - second["score"] < _AMBIGUITY_MARGIN and not _same_family(
        str(reported.get("reported_item_name") or ""), str(best["item"].get("item_name") or ""), str(second["item"].get("item_name") or "")
    ):
        return {**reported, "matched": False, "match_confidence": best["score"], "match_method": "ambiguous_item_family",
                "purchase_order_item_id": None, "po_item_name": None, "po_qty": None, "variance_qty": None, "allocations": [],
                "ambiguity": {"reason": "two different PO item families have nearly equal scores", "candidates": [
                    {"purchaseOrderId": int(best["item"]["purchase_order_id"]), "purchaseOrderItemId": int(best["item"]["id"]), "itemName": best["item"]["item_name"], "score": best["score"]},
                    {"purchaseOrderId": int(second["item"]["purchase_order_id"]), "purchaseOrderItemId": int(second["item"]["id"]), "itemName": second["item"]["item_name"], "score": second["score"]},
                ]}}

    family = [row for row in ranked if row["score"] >= _MIN_SCORE and _same_family(
        str(reported.get("reported_item_name") or ""), str(best["item"].get("item_name") or ""), str(row["item"].get("item_name") or "")
    )]
    family.sort(key=lambda row: _order(row["item"], target))
    remaining = round(float(reported.get("received_qty") or 0), 4)
    allocations: list[dict[str, Any]] = []
    for row in family:
        if remaining <= 0.00005:
            break
        item = row["item"]
        po_qty = float(item.get("po_qty") or 0)
        received = float(item.get("received_total") or 0)
        outstanding = max(po_qty - received, 0.0)
        if outstanding <= 0.00005:
            continue
        qty = min(remaining, outstanding)
        allocations.append({
            "purchase_order_id": int(item["purchase_order_id"]), "po_code": item.get("po_code"),
            "purchase_order_item_id": int(item["id"]), "po_item_name": item.get("item_name"),
            "unit": op.canonical_unit(reported.get("unit")) or op.canonical_unit(item.get("unit")),
            "allocated_qty": round(qty, 4), "po_qty": round(po_qty, 4), "received_before": round(received, 4),
            "outstanding_before": round(outstanding, 4), "outstanding_after": round(max(outstanding - qty, 0.0), 4),
            "match_confidence": row["score"], "match_method": row["method"], "distribution_date": item.get("distribution_date"),
            "over_receipt": False,
        })
        remaining = round(remaining - qty, 4)

    if remaining > 0.00005:
        item = best["item"]
        item_id = int(item["id"])
        already = sum(float(row.get("allocated_qty") or 0) for row in allocations if int(row["purchase_order_item_id"]) == item_id)
        allocations.append({
            "purchase_order_id": int(item["purchase_order_id"]), "po_code": item.get("po_code"),
            "purchase_order_item_id": item_id, "po_item_name": item.get("item_name"),
            "unit": op.canonical_unit(reported.get("unit")) or op.canonical_unit(item.get("unit")),
            "allocated_qty": round(remaining, 4), "po_qty": round(float(item.get("po_qty") or 0), 4),
            "received_before": round(float(item.get("received_total") or 0) + already, 4),
            "outstanding_before": 0.0, "outstanding_after": 0.0, "match_confidence": best["score"],
            "match_method": best["method"] + "_over_receipt", "distribution_date": item.get("distribution_date"), "over_receipt": True,
        })

    first = allocations[0] if allocations else None
    return {**reported, "matched": bool(allocations),
            "match_confidence": min((x["match_confidence"] for x in allocations), default=best["score"]),
            "match_method": "multi_po_allocation" if len({x["purchase_order_id"] for x in allocations}) > 1 else (first["match_method"] if first else "unmatched"),
            "purchase_order_item_id": first["purchase_order_item_id"] if first else None,
            "po_item_name": first["po_item_name"] if first else None,
            "po_qty": round(sum(float(x["outstanding_before"]) for x in allocations), 4) if allocations else None,
            "variance_qty": round(float(reported.get("received_qty") or 0) - sum(float(x["outstanding_before"]) for x in allocations), 4) if allocations else None,
            "allocations": allocations, "ambiguity": None}


def _source_key(payload: op.WhatsAppReceiptIn, vendor: str | None) -> str:
    raw = json.dumps({"site": payload.site.upper(), "vendor": vendor, "external_id": payload.source_external_id,
                      "received_at": payload.received_at.isoformat() if payload.received_at else None, "text": payload.text.strip()},
                     sort_keys=True, ensure_ascii=False)
    return "wa-receipt-v2:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _update_po_status(cur: Any, po_id: int) -> str:
    cur.execute("""
        select poi.id,poi.po_qty,coalesce(sum(gri.accepted_qty),0) as received_total
        from purchase_order_items poi
        left join goods_receipt_items gri on gri.purchase_order_item_id=poi.id
        where poi.purchase_order_id=%s group by poi.id order by poi.id
    """, (po_id,))
    totals = cur.fetchall()
    complete = bool(totals) and all(float(row.get("received_total") or 0) >= float(row.get("po_qty") or 0) - 0.00005 for row in totals)
    status = "RECEIVED" if complete else "PARTIAL_RECEIVED"
    cur.execute("update purchase_orders set status=%s,updated_at=now() where id=%s", (status, po_id))
    return status


def receive_from_whatsapp_v2(payload: op.WhatsAppReceiptIn) -> dict[str, Any]:
    op.require_db()
    site = op.normalize_site(payload.site)
    reported = op.extract_receipt_items(payload.text)
    vendor = (payload.vendor_code or op.infer_vendor(payload.text) or "").upper().strip() or None
    if not reported:
        return {"committed": False, "canCommit": False, "site": site, "vendorCode": vendor, "reason": "no quantity items could be extracted",
                "reportedItems": [], "matches": [], "requiresConfirmation": True, "resolverVersion": "multi-po-v2"}

    with op.connection() as conn:
        with conn.cursor() as cur:
            pos = _candidate_pos(cur, payload, vendor)
            items = _candidate_items(cur, pos)
            target = _target_date(payload)
            matches = [_resolve_line(row, items, target) for row in reported]
            candidate_vendors = sorted({str(po.get("vendor_code") or "").upper().strip() for po in pos if str(po.get("vendor_code") or "").strip()})
            vendor_clear = vendor is not None or len(candidate_vendors) == 1
            resolved_vendor = vendor or (candidate_vendors[0] if len(candidate_vendors) == 1 else None)
            all_resolved = bool(matches) and all(row.get("matched") and float(row.get("match_confidence") or 0) >= _MIN_SCORE and not row.get("ambiguity") for row in matches)
            allocation_rows = [alloc for row in matches for alloc in row.get("allocations", [])]
            po_ids = sorted({int(row["purchase_order_id"]) for row in allocation_rows})
            po_codes = [next((row.get("po_code") for row in allocation_rows if int(row["purchase_order_id"]) == po_id), None) for po_id in po_ids]
            can_commit = bool(all_resolved and po_ids and vendor_clear)
            result: dict[str, Any] = {
                "committed": False, "canCommit": can_commit, "site": site, "vendorCode": resolved_vendor,
                "vendorAmbiguity": None if vendor_clear else {"candidates": candidate_vendors},
                "purchaseOrderId": po_ids[0] if len(po_ids) == 1 else None, "poCode": po_codes[0] if len(po_codes) == 1 else None,
                "purchaseOrderIds": po_ids, "poCodes": po_codes, "multiPo": len(po_ids) > 1,
                "poMatchConfidence": min((float(row.get("match_confidence") or 0) for row in matches), default=0.0),
                "reportedItems": reported, "matches": matches,
                "alternatives": [{"purchase_order_id": int(po["id"]), "po_code": po.get("po_code"), "vendor_code": po.get("vendor_code"), "distribution_date": po.get("distribution_date")} for po in pos[:10]],
                "requiresConfirmation": not can_commit, "resolverVersion": "multi-po-v2",
            }
            if not payload.commit:
                return result
            if not can_commit:
                raise HTTPException(409, detail={"message": "receipt has a real unresolved business ambiguity", **result})

            grouped: dict[int, list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
            for match in matches:
                for allocation in match["allocations"]:
                    grouped[int(allocation["purchase_order_id"])].append((match, allocation))

            base_key = _source_key(payload, resolved_vendor)
            receipt_ids: list[int] = []
            receipts: list[dict[str, Any]] = []
            stock_inserted = stock_duplicates = 0
            all_duplicate = True
            for po_id in sorted(grouped):
                source_key = f"{base_key}:po:{po_id}"
                cur.execute("select id from goods_receipts where source_key=%s", (source_key,))
                existing = cur.fetchone()
                if existing:
                    receipt_id, duplicate = int(existing["id"]), True
                else:
                    all_duplicate = False
                    rows = grouped[po_id]
                    confidence = min(float(alloc["match_confidence"]) for _, alloc in rows)
                    cur.execute("""
                        insert into goods_receipts(purchase_order_id,receipt_code,received_at,source_type,source_external_id,source_key,
                          reporter,raw_text,match_status,match_confidence,confirmed_at)
                        values (%s,null,coalesce(%s,now()),'WHATSAPP',%s,%s,%s,%s,'CONFIRMED',%s,now()) returning id
                    """, (po_id, payload.received_at, payload.source_external_id, source_key, payload.reporter, payload.text, confidence))
                    receipt_id = int(cur.fetchone()["id"])
                    for match, allocation in rows:
                        qty = float(allocation["allocated_qty"])
                        outstanding = float(allocation["outstanding_before"])
                        notes = ["resolver=multi-po-v2", f"source_report_qty={float(match.get('received_qty') or 0):g}"]
                        if allocation.get("over_receipt"):
                            notes.append("OVER_RECEIPT")
                        cur.execute("""
                            insert into goods_receipt_items(goods_receipt_id,purchase_order_item_id,received_qty,rejected_qty,accepted_qty,unit,
                              quality_status,notes,reported_item_name,po_qty_snapshot,variance_qty,match_confidence,match_method)
                            values (%s,%s,%s,0,%s,%s,'ACCEPTED',%s,%s,%s,%s,%s,%s)
                        """, (receipt_id, allocation["purchase_order_item_id"], qty, qty, allocation.get("unit"), " | ".join(notes),
                              match.get("reported_item_name"), outstanding, round(qty - outstanding, 4), allocation["match_confidence"], allocation["match_method"]))
                    duplicate = False

                stock = op.commit_receipt_stock(cur, receipt_id, site)
                stock_inserted += int(stock.get("inserted") or 0)
                stock_duplicates += int(stock.get("duplicates") or 0)
                po_status = _update_po_status(cur, po_id)
                receipt_ids.append(receipt_id)
                receipts.append({"purchaseOrderId": po_id, "poCode": next((alloc.get("po_code") for _, alloc in grouped[po_id]), None),
                                 "receiptId": receipt_id, "duplicate": duplicate, "purchaseOrderStatus": po_status})

            conn.commit()
            result.update({"committed": True, "duplicate": all_duplicate, "receiptId": receipt_ids[0] if receipt_ids else None,
                           "receiptIds": receipt_ids, "receipts": receipts, "stockCommitted": True,
                           "stockInserted": stock_inserted, "stockDuplicates": stock_duplicates, "requiresConfirmation": False})
            return result


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    found = False
    for route in op.router.routes:
        if getattr(route, "path", "") == "/v1/receiving/whatsapp" and "POST" in (getattr(route, "methods", set()) or set()):
            route.endpoint = receive_from_whatsapp_v2
            if getattr(route, "dependant", None) is not None:
                route.dependant.call = receive_from_whatsapp_v2
            found = True
            break
    if not found:
        raise RuntimeError("receiving/whatsapp route not found; refusing unsafe patch install")
    op.receive_from_whatsapp = receive_from_whatsapp_v2
    _INSTALLED = True
