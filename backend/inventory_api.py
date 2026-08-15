from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.db import connection, database_ready
from backend.stock_opname_parser import canonical_unit, normalize_name, parse_stock_opname_text

router = APIRouter(prefix="/v1", tags=["inventory"])


def require_db() -> None:
    if not database_ready():
        raise HTTPException(503, "database unavailable")


def norm(value: str) -> str:
    return " ".join((value or "").lower().strip().split())


LOCATION_VALUES = {"KOPERASI", "MAJA", "CEMPLANG"}


def normalize_location(value: str) -> str:
    location = value.upper().strip()
    if location not in LOCATION_VALUES:
        raise HTTPException(400, "location must be KOPERASI, MAJA, or CEMPLANG")
    return location


def load_item_matchers(cur) -> list[dict[str, Any]]:
    cur.execute(
        """
        select m.code,m.canonical_name,m.normalized_canonical_name,m.category_code,m.base_unit,
               coalesce(json_agg(a.normalized_alias) filter (where a.id is not null),'[]'::json) as aliases
        from inventory_item_master m
        left join inventory_item_aliases a on a.inventory_item_code=m.code
        where m.active=true
        group by m.code
        order by length(m.normalized_canonical_name) desc,m.canonical_name
        """
    )
    return cur.fetchall()


def classify_item(raw_name: str, masters: list[dict[str, Any]]) -> dict[str, Any]:
    normalized = normalize_name(raw_name)
    exact: list[tuple[dict[str, Any], str]] = []
    contained: list[tuple[int, dict[str, Any], str]] = []
    for master in masters:
        candidates = [(master["normalized_canonical_name"], "CANONICAL_EXACT")]
        candidates.extend((str(alias), "ALIAS_EXACT") for alias in (master.get("aliases") or []))
        for candidate, method in candidates:
            if not candidate:
                continue
            if normalized == candidate:
                exact.append((master, method))
            elif len(candidate) >= 4 and re.search(rf"(?:^| ){re.escape(candidate)}(?: |$)", normalized):
                contained.append((len(candidate), master, "TYPE_IN_RAW_NAME"))

    if exact:
        matches = exact
    elif contained:
        longest = max(row[0] for row in contained)
        matches = [(master, method) for length, master, method in contained if length == longest]
    else:
        matches = []
    unique = {row[0]["code"]: row for row in matches}
    if len(unique) == 1:
        master, method = next(iter(unique.values()))
        return {
            "inventoryItemCode": master["code"],
            "canonicalItemName": master["canonical_name"],
            "knownAliases": master.get("aliases") or [],
            "categoryCode": master.get("category_code"),
            "baseUnit": master.get("base_unit"),
            "classificationStatus": "MATCHED",
            "classificationMethod": method,
            "classificationConfidence": 1.0 if exact else 0.9,
        }
    if len(unique) > 1:
        return {
            "inventoryItemCode": None,
            "canonicalItemName": raw_name,
            "knownAliases": [],
            "categoryCode": None,
            "baseUnit": None,
            "classificationStatus": "AMBIGUOUS",
            "classificationMethod": "MULTIPLE_TYPE_MATCHES",
            "classificationConfidence": 0.0,
        }
    return {
        "inventoryItemCode": None,
        "canonicalItemName": raw_name,
        "knownAliases": [],
        "categoryCode": None,
        "baseUnit": None,
        "classificationStatus": "UNMAPPED",
        "classificationMethod": "RAW_NAME_FALLBACK",
        "classificationConfidence": 0.5,
    }


def stock_balance(cur, site: str, item_name: str) -> float:
    cur.execute(
        """
        select coalesce(sum(
          case
            when upper(coalesce(to_location,''))=upper(%s) then qty
            when upper(coalesce(from_location,''))=upper(%s) then -qty
            else 0
          end
        ),0) as balance
        from inventory_movements
        where lower(trim(item_name))=lower(trim(%s))
          and (upper(coalesce(to_location,''))=upper(%s) or upper(coalesce(from_location,''))=upper(%s))
        """,
        (site, site, item_name, site, site),
    )
    return float(cur.fetchone()["balance"] or 0)


class ReceiptToStockIn(BaseModel):
    site: Literal["MAJA", "CEMPLANG"]
    goods_receipt_id: int
    commit: bool = False


@router.post("/inventory/from-receipt")
def inventory_from_receipt(payload: ReceiptToStockIn) -> dict[str, Any]:
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """select gr.id,gr.received_at,po.site,po.vendor_code,po.production_cycle_id,po.po_code
                   from goods_receipts gr join purchase_orders po on po.id=gr.purchase_order_id
                   where gr.id=%s""",
                (payload.goods_receipt_id,),
            )
            receipt = cur.fetchone()
            if not receipt:
                raise HTTPException(404, "goods receipt not found")
            if str(receipt["site"]).upper() != payload.site.upper():
                raise HTTPException(400, "site does not match goods receipt")
            cur.execute(
                """select gri.id as receipt_item_id,coalesce(gri.accepted_qty,gri.received_qty,0) as qty,
                          gri.unit,poi.item_code,coalesce(poi.item_name,gri.reported_item_name) as item_name
                   from goods_receipt_items gri
                   left join purchase_order_items poi on poi.id=gri.purchase_order_item_id
                   where gri.goods_receipt_id=%s order by gri.id""",
                (payload.goods_receipt_id,),
            )
            rows = cur.fetchall()
            preview = []
            for row in rows:
                key = f"goods-receipt-stock:{payload.goods_receipt_id}:{row['receipt_item_id']}"
                preview.append({
                    "sourceKey": key,
                    "itemName": row["item_name"],
                    "qty": float(row["qty"] or 0),
                    "unit": row["unit"],
                    "fromLocation": "KOPERASI" if str(receipt["vendor_code"]).upper() == "KOPERASI" else f"VENDOR:{receipt['vendor_code']}",
                    "toLocation": payload.site,
                })
            if not payload.commit:
                return {"committed": False, "canCommit": bool(preview), "goodsReceiptId": payload.goods_receipt_id, "items": preview}

            inserted = 0
            duplicates = 0
            for row, item in zip(rows, preview):
                cur.execute("select id from inventory_movements where source_key=%s", (item["sourceKey"],))
                if cur.fetchone():
                    duplicates += 1
                    continue
                cur.execute(
                    """insert into inventory_movements(
                         movement_type,item_code,item_name,qty,unit,from_location,to_location,production_cycle_id,
                         occurred_at,source_type,source_key,source_ref,notes
                       ) values ('PURCHASE_RECEIPT',%s,%s,%s,%s,%s,%s,%s,coalesce(%s,now()),'GOODS_RECEIPT',%s,%s,%s)""",
                    (
                        row["item_code"], row["item_name"], row["qty"], row["unit"],
                        item["fromLocation"], payload.site, receipt["production_cycle_id"], receipt["received_at"],
                        item["sourceKey"], f"receipt:{payload.goods_receipt_id}", f"PO {receipt['po_code']}",
                    ),
                )
                inserted += 1
            conn.commit()
            return {
                "committed": True,
                "goodsReceiptId": payload.goods_receipt_id,
                "inserted": inserted,
                "duplicates": duplicates,
                "items": preview,
            }


class InventoryMasterItemIn(BaseModel):
    code: str | None = None
    canonical_name: str = Field(min_length=1)
    category_code: str | None = None
    base_unit: str | None = None
    aliases: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    commit: bool = False


def default_item_code(name: str) -> str:
    value = re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_")
    return (value or "ITEM")[:80]


@router.get("/inventory/items")
def inventory_items(search: str = "", limit: int = Query(default=500, ge=1, le=1000)) -> dict[str, Any]:
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            sql = """
                select m.code,m.canonical_name,m.category_code,m.base_unit,m.active,m.metadata,
                       coalesce(json_agg(a.alias_text order by a.alias_text) filter (where a.id is not null),'[]'::json) as aliases
                from inventory_item_master m
                left join inventory_item_aliases a on a.inventory_item_code=m.code
                where true
            """
            params: list[Any] = []
            if search.strip():
                sql += " and (m.canonical_name ilike %s or a.alias_text ilike %s)"
                params.extend([f"%{search.strip()}%", f"%{search.strip()}%"])
            sql += " group by m.code order by m.canonical_name limit %s"
            params.append(limit)
            cur.execute(sql, params)
            rows = cur.fetchall()
    return {"items": rows, "count": len(rows)}


@router.post("/inventory/items")
def upsert_inventory_item(payload: InventoryMasterItemIn) -> dict[str, Any]:
    require_db()
    code = (payload.code or default_item_code(payload.canonical_name)).upper().strip()
    aliases = list(dict.fromkeys([payload.canonical_name.strip(), *[x.strip() for x in payload.aliases if x.strip()]]))
    preview = {
        "committed": False,
        "code": code,
        "canonicalName": payload.canonical_name.strip(),
        "categoryCode": payload.category_code,
        "baseUnit": canonical_unit(payload.base_unit),
        "aliases": aliases,
    }
    if not payload.commit:
        return preview
    with connection() as conn:
        with conn.cursor() as cur:
            for alias in aliases:
                cur.execute(
                    "select inventory_item_code from inventory_item_aliases where normalized_alias=%s and inventory_item_code<>%s",
                    (normalize_name(alias), code),
                )
                conflict = cur.fetchone()
                if conflict:
                    raise HTTPException(409, f"alias '{alias}' already belongs to {conflict['inventory_item_code']}")
            cur.execute(
                """
                insert into inventory_item_master(code,canonical_name,normalized_canonical_name,category_code,base_unit,metadata)
                values (%s,%s,%s,%s,%s,%s::jsonb)
                on conflict (code) do update set canonical_name=excluded.canonical_name,
                  normalized_canonical_name=excluded.normalized_canonical_name,category_code=excluded.category_code,
                  base_unit=excluded.base_unit,metadata=excluded.metadata,active=true,updated_at=now()
                """,
                (code, payload.canonical_name.strip(), normalize_name(payload.canonical_name), payload.category_code,
                 canonical_unit(payload.base_unit), json.dumps(payload.metadata, ensure_ascii=False)),
            )
            for alias in aliases:
                cur.execute(
                    """
                    insert into inventory_item_aliases(inventory_item_code,alias_text,normalized_alias)
                    values (%s,%s,%s) on conflict (normalized_alias) do update set
                      alias_text=excluded.alias_text,inventory_item_code=excluded.inventory_item_code
                    """,
                    (code, alias, normalize_name(alias)),
                )
            conn.commit()
    preview["committed"] = True
    return preview


class StockOpnameWhatsAppIn(BaseModel):
    location: Literal["KOPERASI", "MAJA", "CEMPLANG"]
    text: str = Field(min_length=1)
    stock_date: date | None = None
    source_external_id: str | None = None
    reporter: str | None = None
    actor: str = "operator"
    commit: bool = False


@router.post("/inventory/stock-opname/whatsapp")
def stock_opname_whatsapp(payload: StockOpnameWhatsAppIn) -> dict[str, Any]:
    require_db()
    location = normalize_location(payload.location)
    parsed = parse_stock_opname_text(payload.text)
    detected = date.fromisoformat(parsed["detectedStockDate"]) if parsed["detectedStockDate"] else None
    stock_date = payload.stock_date or detected
    if not stock_date:
        raise HTTPException(400, "stock_date is required when no Indonesian date is detected in the message")
    parse_warnings = list(parsed["warnings"])
    if payload.stock_date and detected and payload.stock_date != detected:
        parse_warnings.append(
            f"Tanggal input {payload.stock_date.isoformat()} berbeda dari tanggal dalam chat {detected.isoformat()}. Tanggal input akan dipakai."
        )

    with connection() as conn:
        with conn.cursor() as cur:
            masters = load_item_matchers(cur)
            items = []
            unmapped = 0
            ambiguous = 0
            for item in parsed["items"]:
                classification = classify_item(item["itemName"], masters)
                if classification["classificationStatus"] == "UNMAPPED":
                    unmapped += 1
                elif classification["classificationStatus"] == "AMBIGUOUS":
                    ambiguous += 1
                items.append({**item, **classification})

            canonical = {
                "location": location,
                "stock_date": stock_date.isoformat(),
                "source_external_id": payload.source_external_id,
                "text": payload.text,
            }
            source_key = "stock-opname:" + hashlib.sha256(
                json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode("utf-8")
            ).hexdigest()
            result = {
                "committed": False,
                "canCommit": bool(items),
                "location": location,
                "site": None if location == "KOPERASI" else location,
                "stockDate": stock_date.isoformat(),
                "detectedStockDate": parsed["detectedStockDate"],
                "sourceKey": source_key,
                "itemCount": len(items),
                "readyCount": parsed["readyCount"],
                "reviewCount": parsed["reviewCount"],
                "unmappedCount": unmapped,
                "ambiguousCount": ambiguous,
                "warnings": parse_warnings,
                "items": items,
            }
            if not payload.commit:
                return result
            if not items:
                raise HTTPException(400, "no stock items were parsed")
            cur.execute("select id from stock_opnames where source_key=%s", (source_key,))
            duplicate = cur.fetchone()
            if duplicate:
                result.update({"committed": True, "duplicate": True, "stockOpnameId": duplicate["id"]})
                return result
            cur.execute(
                """
                insert into stock_opnames(location_code,site,stock_date,source_type,source_external_id,
                  source_key,reporter,raw_text,warning_count,created_by)
                values (%s,%s,%s,'WHATSAPP',%s,%s,%s,%s,%s,%s) returning id
                """,
                (location, None if location == "KOPERASI" else location, stock_date, payload.source_external_id,
                 source_key, payload.reporter, payload.text, len(parse_warnings), payload.actor),
            )
            opname_id = cur.fetchone()["id"]
            for item in items:
                cur.execute(
                    """
                    insert into stock_opname_items(stock_opname_id,area_code,inventory_item_code,canonical_item_name,
                      raw_item_name,normalized_raw_name,qty,unit,classification_status,classification_method,
                      classification_confidence,parse_status,raw_line,warnings)
                    values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                    """,
                    (opname_id, item["areaCode"], item["inventoryItemCode"], item["canonicalItemName"],
                     item["itemName"], item["normalizedItemName"], item["qty"], item["unit"] or None,
                     item["classificationStatus"], item["classificationMethod"], item["classificationConfidence"],
                     item["parseStatus"], item["rawLine"], json.dumps(item["warnings"], ensure_ascii=False)),
                )
            conn.commit()
            result.update({"committed": True, "duplicate": False, "stockOpnameId": opname_id})
            return result


@router.get("/inventory/stock-opnames")
def stock_opnames(location: str = "", limit: int = Query(default=50, ge=1, le=250)) -> dict[str, Any]:
    require_db()
    sql = """
        select so.id,so.location_code,so.site,so.stock_date,so.source_type,so.source_external_id,
               so.reporter,so.warning_count,so.created_by,so.created_at,count(soi.id) as item_count
        from stock_opnames so left join stock_opname_items soi on soi.stock_opname_id=so.id where true
    """
    params: list[Any] = []
    if location.strip():
        sql += " and so.location_code=%s"
        params.append(normalize_location(location))
    sql += " group by so.id order by so.stock_date desc,so.created_at desc limit %s"
    params.append(limit)
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    return {"items": rows, "count": len(rows)}


class UsageIn(BaseModel):
    site: Literal["MAJA", "CEMPLANG"]
    item_name: str = Field(min_length=1)
    qty: float = Field(gt=0)
    unit: str
    occurred_at: datetime | None = None
    source_ref: str | None = None
    commit: bool = False


@router.post("/inventory/usage")
def inventory_usage(payload: UsageIn) -> dict[str, Any]:
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            before = stock_balance(cur, payload.site, payload.item_name)
            after = before - payload.qty
            result = {
                "committed": False,
                "site": payload.site,
                "itemName": payload.item_name,
                "balanceBefore": before,
                "usageQty": payload.qty,
                "balanceAfter": after,
                "unit": payload.unit,
                "stockWarning": after < 0,
            }
            if not payload.commit:
                return result
            canonical = {
                "site": payload.site,
                "item": norm(payload.item_name),
                "qty": payload.qty,
                "unit": payload.unit,
                "occurred_at": (payload.occurred_at or datetime.now(timezone.utc)).isoformat(),
                "source_ref": payload.source_ref,
            }
            key = "inventory-usage:" + hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()
            cur.execute("select id from inventory_movements where source_key=%s", (key,))
            duplicate = cur.fetchone()
            if duplicate:
                result.update({"committed": True, "duplicate": True, "movementId": duplicate["id"]})
                return result
            cur.execute(
                """insert into inventory_movements(
                     movement_type,item_name,qty,unit,from_location,to_location,occurred_at,
                     source_type,source_key,source_ref
                   ) values ('PRODUCTION_USAGE',%s,%s,%s,%s,'PRODUCTION',coalesce(%s,now()),'ACTUAL_USAGE',%s,%s)
                   returning id""",
                (payload.item_name, payload.qty, payload.unit, payload.site, payload.occurred_at, key, payload.source_ref),
            )
            movement_id = cur.fetchone()["id"]
            conn.commit()
            result.update({"committed": True, "duplicate": False, "movementId": movement_id})
            return result


@router.get("/inventory/balance")
def inventory_balance(site: str, item: str = Query(min_length=1)) -> dict[str, Any]:
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            return {"site": site.upper(), "itemName": item, "balance": stock_balance(cur, site, item)}


@router.get("/inventory/requirement-preview")
def inventory_requirement_preview(
    site: str,
    item: str = Query(min_length=1),
    plannedQty: float = Query(ge=0),
    unit: str = "kg",
) -> dict[str, Any]:
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            available = stock_balance(cur, site, item)
    purchase_needed = max(float(plannedQty) - max(available, 0), 0)
    return {
        "site": site.upper(),
        "itemName": item,
        "plannedQty": float(plannedQty),
        "stockAvailable": available,
        "purchaseNeeded": purchase_needed,
        "unit": unit,
        "financeTransactionCreated": False,
    }
