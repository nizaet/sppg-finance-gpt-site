from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
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


SOURCE_PRIORITY = {
    "INVENTORY_MASTER": 100,
    "PRICE": 80,
    "PLAN_ITEM": 75,
    "PLANNING_SNAPSHOT": 75,
    "RECIPE_INGREDIENT": 65,
    "GRAMASI": 40,
}


def load_item_matchers(cur, site: str | None = None) -> list[dict[str, Any]]:
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
    masters = []
    for row in cur.fetchall():
        masters.append({
            **row,
            "source_type": "INVENTORY_MASTER",
            "source_refs": [f"inventory:{row['code']}"],
            "priority": SOURCE_PRIORITY["INVENTORY_MASTER"],
        })

    catalog_params: list[Any] = []
    catalog_site_sql = ""
    if site in {"MAJA", "CEMPLANG"}:
        catalog_site_sql = " and site=%s"
        catalog_params.append(site)
    cur.execute(
        f"""
        select source_type,normalized_name,min(canonical_name) as canonical_name,
               max(category_code) filter (where category_code is not null) as category_code,
               max(unit) filter (where unit is not null) as base_unit,
               json_agg(distinct concat(source_type,':',source_document_key)) as source_refs
        from calculator_master_catalog
        where active=true and source_type in ('PRICE','GRAMASI','RECIPE_INGREDIENT','PLAN_ITEM')
        {catalog_site_sql}
        group by source_type,normalized_name
        """,
        catalog_params,
    )
    for row in cur.fetchall():
        source_type = str(row["source_type"])
        masters.append({
            "code": None,
            "canonical_name": row["canonical_name"],
            "normalized_canonical_name": row["normalized_name"],
            "category_code": row.get("category_code"),
            "base_unit": row.get("base_unit"),
            "aliases": [],
            "source_type": source_type,
            "source_refs": row.get("source_refs") or [],
            "priority": SOURCE_PRIORITY.get(source_type, 10),
        })

    planning_params: list[Any] = []
    planning_site_sql = ""
    if site in {"MAJA", "CEMPLANG"}:
        planning_site_sql = " and upper(ps.site)=%s"
        planning_params.append(site)
    cur.execute(
        f"""
        select lower(regexp_replace(trim(psi.item_name),'[^a-zA-Z0-9]+',' ','g')) as normalized_name,
               min(psi.item_name) as canonical_name,
               max(psi.category_code) filter (where psi.category_code is not null) as category_code,
               max(psi.unit) filter (where psi.unit is not null) as base_unit,
               json_agg(distinct concat('planning:',ps.site,':',ps.distribution_date)) as source_refs
        from planning_snapshot_items psi
        join planning_snapshots ps on ps.id=psi.planning_snapshot_id
        where ps.status='ACTIVE' {planning_site_sql}
        group by lower(regexp_replace(trim(psi.item_name),'[^a-zA-Z0-9]+',' ','g'))
        """,
        planning_params,
    )
    for row in cur.fetchall():
        masters.append({
            "code": None,
            "canonical_name": row["canonical_name"],
            "normalized_canonical_name": normalize_name(row["canonical_name"]),
            "category_code": row.get("category_code"),
            "base_unit": row.get("base_unit"),
            "aliases": [],
            "source_type": "PLANNING_SNAPSHOT",
            "source_refs": row.get("source_refs") or [],
            "priority": SOURCE_PRIORITY["PLANNING_SNAPSHOT"],
        })
    return masters


def classify_item(raw_name: str, masters: list[dict[str, Any]]) -> dict[str, Any]:
    normalized = normalize_name(raw_name)
    exact: list[tuple[dict[str, Any], str, str]] = []
    contained: list[tuple[int, dict[str, Any], str, str]] = []
    for master in masters:
        candidates = [(master["normalized_canonical_name"], "CANONICAL_EXACT")]
        candidates.extend((str(alias), "ALIAS_EXACT") for alias in (master.get("aliases") or []))
        for candidate, method in candidates:
            if not candidate:
                continue
            if normalized == candidate:
                exact.append((master, method, candidate))
            elif (
                str(master.get("source_type") or "") != "GRAMASI"
                and len(candidate) >= 4
                and re.search(rf"(?:^| ){re.escape(candidate)}(?: |$)", normalized)
            ):
                contained.append((len(candidate), master, "TYPE_IN_RAW_NAME", candidate))

    if exact:
        matches = exact
    elif contained:
        longest = max(row[0] for row in contained)
        matches = [(master, method, candidate) for length, master, method, candidate in contained if length == longest]
    else:
        matches = []

    if matches:
        highest_priority = max(int(row[0].get("priority") or 0) for row in matches)
        preferred = [row for row in matches if int(row[0].get("priority") or 0) == highest_priority]
        unique: dict[str, tuple[dict[str, Any], str, str]] = {}
        for master, method, candidate in preferred:
            identity = str(master.get("code") or master.get("normalized_canonical_name") or candidate)
            unique[identity] = (master, method, candidate)
    else:
        unique = {}

    if len(unique) == 1:
        master, method, _ = next(iter(unique.values()))
        source_type = str(master.get("source_type") or "INVENTORY_MASTER")
        all_sources: list[str] = []
        canonical_norm = str(master.get("normalized_canonical_name") or "")
        for candidate_master, _, _ in matches:
            if str(candidate_master.get("normalized_canonical_name") or "") != canonical_norm:
                continue
            for source in candidate_master.get("source_refs") or []:
                if source not in all_sources:
                    all_sources.append(source)
        return {
            "inventoryItemCode": master["code"],
            "canonicalItemName": master["canonical_name"],
            "knownAliases": master.get("aliases") or [],
            "categoryCode": master.get("category_code"),
            "baseUnit": master.get("base_unit"),
            "classificationStatus": "MATCHED",
            "classificationMethod": method if source_type == "INVENTORY_MASTER" else f"{source_type}_{method}",
            "classificationConfidence": 1.0 if exact else 0.9,
            "classificationSources": all_sources,
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
            "classificationSources": sorted({source for master, _, _ in matches for source in (master.get("source_refs") or [])}),
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
        "classificationSources": [],
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


def commit_receipt_stock(cur, goods_receipt_id: int, expected_site: str | None = None) -> dict[str, Any]:
    """Idempotently add accepted receipt quantities to the operational ledger."""
    cur.execute(
        """select gr.id,gr.received_at,po.site,po.vendor_code,po.production_cycle_id,po.po_code
           from goods_receipts gr join purchase_orders po on po.id=gr.purchase_order_id
           where gr.id=%s""",
        (goods_receipt_id,),
    )
    receipt = cur.fetchone()
    if not receipt:
        raise HTTPException(404, "goods receipt not found")
    site = str(receipt["site"] or "").upper()
    if expected_site and site != str(expected_site).upper():
        raise HTTPException(400, "site does not match goods receipt")
    cur.execute(
        """select gri.id as receipt_item_id,coalesce(gri.accepted_qty,gri.received_qty,0) as qty,
                  gri.unit,poi.item_code,coalesce(poi.item_name,gri.reported_item_name) as item_name
           from goods_receipt_items gri
           left join purchase_order_items poi on poi.id=gri.purchase_order_item_id
           where gri.goods_receipt_id=%s order by gri.id""",
        (goods_receipt_id,),
    )
    rows = cur.fetchall()
    preview: list[dict[str, Any]] = []
    inserted = 0
    duplicates = 0
    for row in rows:
        amount = float(row["qty"] or 0)
        if amount <= 0:
            continue
        key = f"goods-receipt-stock:{goods_receipt_id}:{row['receipt_item_id']}"
        is_koperasi_transfer = str(receipt["vendor_code"]).upper() == "KOPERASI"
        item = {
            "sourceKey": key,
            "itemName": row["item_name"],
            "qty": amount,
            "unit": row["unit"],
            "fromLocation": "KOPERASI" if is_koperasi_transfer else f"VENDOR:{receipt['vendor_code']}",
            "toLocation": site,
            "movementType": "KOPERASI_STOCK_TRANSFER" if is_koperasi_transfer else "PURCHASE_RECEIPT",
        }
        preview.append(item)
        cur.execute("select id from inventory_movements where source_key=%s", (key,))
        if cur.fetchone():
            duplicates += 1
            continue
        cur.execute(
            """insert into inventory_movements(
                 movement_type,item_code,item_name,qty,unit,from_location,to_location,production_cycle_id,
                 occurred_at,source_type,source_key,source_ref,notes
               ) values (%s,%s,%s,%s,%s,%s,%s,%s,coalesce(%s,now()),'GOODS_RECEIPT',%s,%s,%s)""",
            (
                item["movementType"], row["item_code"], row["item_name"], row["qty"], row["unit"], item["fromLocation"], site,
                receipt["production_cycle_id"], receipt["received_at"], key,
                f"receipt:{goods_receipt_id}", f"Pengiriman Gudang Koperasi → {site}; PO {receipt['po_code']}" if is_koperasi_transfer else f"PO {receipt['po_code']}",
            ),
        )
        inserted += 1
    return {
        "goodsReceiptId": goods_receipt_id,
        "site": site,
        "inserted": inserted,
        "duplicates": duplicates,
        "items": preview,
    }


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

            committed = commit_receipt_stock(cur, payload.goods_receipt_id, payload.site)
            conn.commit()
            return {
                "committed": True,
                **committed,
            }


@router.get("/inventory/koperasi-transfers")
def koperasi_transfer_history(
    from_date: date | None = Query(default=None, alias="fromDate"),
    to_date: date | None = Query(default=None, alias="toDate"),
    destination: str = "",
    limit: int = Query(default=1000, ge=1, le=5000),
) -> dict[str, Any]:
    """Read-only delivery ledger from Gudang Koperasi to each kitchen.

    A KOPERASI receipt is a physical inter-warehouse transfer, not an expense.
    The same movement is negative in KOPERASI stock and positive in the target
    kitchen. Old rows used PURCHASE_RECEIPT; retain them in the history.
    """
    require_db()
    target = destination.upper().strip()
    if target and target not in {"MAJA", "CEMPLANG"}:
        raise HTTPException(400, "destination must be MAJA or CEMPLANG")
    sql = """
        select im.id as movement_id,im.movement_type,im.item_code,im.item_name,im.qty,im.unit,
               im.from_location,im.to_location,im.occurred_at,im.created_at,im.source_key,im.source_ref,im.notes,
               gr.id as goods_receipt_id,gr.receipt_code,gr.reporter,
               po.id as purchase_order_id,po.po_code,po.site as po_site,po.vendor_code
        from inventory_movements im
        left join goods_receipts gr
          on im.source_type='GOODS_RECEIPT' and im.source_ref=('receipt:' || gr.id::text)
        left join purchase_orders po on po.id=gr.purchase_order_id
        where upper(coalesce(im.from_location,''))='KOPERASI'
          and upper(coalesce(im.to_location,'')) in ('MAJA','CEMPLANG')
          and upper(coalesce(im.movement_type,'')) in ('KOPERASI_STOCK_TRANSFER','PURCHASE_RECEIPT')
    """
    params: list[Any] = []
    if from_date:
        sql += " and date(coalesce(im.occurred_at,im.created_at)) >= %s"
        params.append(from_date)
    if to_date:
        sql += " and date(coalesce(im.occurred_at,im.created_at)) <= %s"
        params.append(to_date)
    if target:
        sql += " and upper(im.to_location)=%s"
        params.append(target)
    sql += " order by coalesce(im.occurred_at,im.created_at) desc,im.id desc limit %s"
    params.append(limit)
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            items = [dict(row) for row in cur.fetchall()]
    for item in items:
        occurred = item.get("occurred_at") or item.get("created_at")
        item["transfer_date"] = occurred.date().isoformat() if occurred else None
    return {"fromLocation": "KOPERASI", "items": items, "count": len(items)}


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


class StockOpnameReviewedItemIn(BaseModel):
    client_key: str | None = None
    include: bool = True
    area_code: str | None = None
    raw_item_name: str | None = None
    canonical_item_name: str | None = None
    inventory_item_code: str | None = None
    qty: float = Field(ge=0)
    unit: str | None = None
    raw_line: str | None = None


class StockOpnameWhatsAppIn(BaseModel):
    location: Literal["KOPERASI", "MAJA", "CEMPLANG"]
    text: str = Field(min_length=1)
    stock_date: date | None = None
    source_external_id: str | None = None
    reporter: str | None = None
    actor: str = "operator"
    reviewed_items: list[StockOpnameReviewedItemIn] | None = None
    commit: bool = False


def _replacement_source_ids(source_external_id: str | None) -> list[int]:
    """Return evidence rows replaced by an operator correction/consolidation.

    The marker is generated only by the Operations UI.  Keeping this parser
    deliberately narrow prevents an arbitrary source ID from suppressing SO
    evidence in the active stock calculation.
    """
    source = str(source_external_id or "").strip()
    correction = re.fullmatch(r"correction:(\d+)", source)
    if correction:
        return [int(correction.group(1))]
    consolidated = re.fullmatch(r"consolidated:\d{4}-\d{2}-\d{2}:(\d+(?:-\d+)*)", source)
    if consolidated:
        return [int(value) for value in consolidated.group(1).split("-")]
    return []


def _compact_stock_opname_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep GPT Action previews below the response-size limit."""
    return [
        {
            "clientKey": item.get("clientKey"),
            "selected": bool(item.get("selected", True)),
            "areaCode": item.get("areaCode"),
            "itemName": item.get("itemName"),
            "canonicalItemName": item.get("canonicalItemName"),
            "inventoryItemCode": item.get("inventoryItemCode"),
            "qty": item.get("qty"),
            "unit": item.get("unit"),
            "classificationStatus": item.get("classificationStatus"),
            "classificationMethod": item.get("classificationMethod"),
            "classificationConfidence": item.get("classificationConfidence"),
            "parseStatus": item.get("parseStatus"),
            "warnings": list(item.get("warnings") or [])[:3],
        }
        for item in items
    ]


@router.post("/inventory/stock-opname/whatsapp")
def stock_opname_whatsapp(payload: StockOpnameWhatsAppIn) -> dict[str, Any]:
    require_db()
    location = normalize_location(payload.location)
    parsed = parse_stock_opname_text(payload.text)
    detected = date.fromisoformat(parsed["detectedStockDate"]) if parsed["detectedStockDate"] else None
    parse_warnings = list(parsed["warnings"])
    if detected:
        stock_date = payload.stock_date or detected
    elif payload.stock_date and payload.actor.strip().lower() != "chatgpt":
        stock_date = payload.stock_date
    else:
        stock_date = datetime.now(ZoneInfo("Asia/Jakarta")).date()
        if payload.stock_date:
            parse_warnings.append(
                f"Tanggal {payload.stock_date.isoformat()} dari GPT diabaikan karena tidak ada tanggal di teks; memakai tanggal Jakarta: {stock_date.isoformat()}."
            )
        else:
            parse_warnings.append(
                f"Tanggal tidak disebutkan; memakai tanggal Jakarta saat pencatatan: {stock_date.isoformat()}."
            )
    if payload.stock_date and detected and payload.stock_date != detected:
        parse_warnings.append(
            f"Tanggal input {payload.stock_date.isoformat()} berbeda dari tanggal dalam chat {detected.isoformat()}. Tanggal input akan dipakai."
        )

    with connection() as conn:
        with conn.cursor() as cur:
            masters = load_item_matchers(cur, None if location == "KOPERASI" else location)
            items = []
            unmapped = 0
            ambiguous = 0
            for index, item in enumerate(parsed["items"]):
                classification = classify_item(item["itemName"], masters)
                if classification["classificationStatus"] == "UNMAPPED":
                    unmapped += 1
                elif classification["classificationStatus"] == "AMBIGUOUS":
                    ambiguous += 1
                items.append({"clientKey": str(index), "selected": True, **item, **classification})

            if payload.reviewed_items is not None:
                reviewed: list[dict[str, Any]] = []
                for review_index, supplied in enumerate(payload.reviewed_items):
                    if not supplied.include:
                        continue
                    parsed_item = parsed["items"][review_index] if review_index < len(parsed["items"]) else {}
                    raw_name = str(
                        supplied.raw_item_name
                        or parsed_item.get("itemName")
                        or supplied.canonical_item_name
                        or ""
                    ).strip()
                    if not raw_name:
                        raise HTTPException(400, "reviewed_items membutuhkan nama item atau teks laporan yang dapat diparsing")
                    unit = canonical_unit(supplied.unit)
                    classification = classify_item(supplied.canonical_item_name or raw_name, masters)
                    if supplied.inventory_item_code:
                        cur.execute(
                            """select code,canonical_name,category_code,base_unit
                               from inventory_item_master where code=%s and active=true""",
                            (supplied.inventory_item_code.upper().strip(),),
                        )
                        master = cur.fetchone()
                        if not master:
                            raise HTTPException(400, f"Master Item {supplied.inventory_item_code} tidak ditemukan")
                        classification.update({
                            "inventoryItemCode": master["code"],
                            "canonicalItemName": master["canonical_name"],
                            "categoryCode": master["category_code"],
                            "baseUnit": master["base_unit"],
                            "classificationStatus": "MATCHED",
                            "classificationMethod": "USER_SELECTED_MASTER",
                            "classificationConfidence": 1.0,
                            "classificationSources": [f"inventory:{master['code']}"],
                        })
                    elif supplied.canonical_item_name:
                        classification.update({
                            "canonicalItemName": supplied.canonical_item_name.strip(),
                            "classificationStatus": "USER_REVIEWED",
                            "classificationMethod": "USER_EDITED_CANONICAL_NAME",
                            "classificationConfidence": 1.0,
                        })
                    warnings = [] if unit else ["Satuan belum ditetapkan oleh pengguna."]
                    reviewed.append({
                        "clientKey": supplied.client_key or str(review_index),
                        "selected": True,
                        "areaCode": supplied.area_code or "UNSPECIFIED",
                        "itemName": raw_name,
                        "normalizedItemName": normalize_name(raw_name),
                        "qty": float(supplied.qty),
                        "unit": unit,
                        "parseStatus": "READY" if unit else "REVIEW",
                        "rawLine": supplied.raw_line or parsed_item.get("rawLine") or raw_name,
                        "warnings": warnings,
                        **classification,
                    })
                items = reviewed
                unmapped = sum(1 for item in items if item["classificationStatus"] == "UNMAPPED")
                ambiguous = sum(1 for item in items if item["classificationStatus"] == "AMBIGUOUS")

            canonical = {
                "location": location,
                "stock_date": stock_date.isoformat(),
                "source_external_id": payload.source_external_id,
                "text": payload.text,
                "reviewed_items": [
                    {
                        "key": item["clientKey"], "name": item["canonicalItemName"],
                        "raw": item["itemName"], "qty": item["qty"], "unit": item["unit"],
                        "master": item["inventoryItemCode"], "area": item["areaCode"],
                    }
                    for item in items
                ],
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
                "readyCount": sum(1 for item in items if item["parseStatus"] == "READY"),
                "reviewCount": sum(1 for item in items if item["parseStatus"] != "READY"),
                "unmappedCount": unmapped,
                "ambiguousCount": ambiguous,
                "warnings": parse_warnings[:10],
                "items": _compact_stock_opname_items(items),
            }
            if not payload.commit:
                return result
            if not items:
                raise HTTPException(400, "no stock items were parsed")
            cur.execute("select id,status from stock_opnames where source_key=%s", (source_key,))
            duplicate = cur.fetchone()
            if duplicate:
                if str(duplicate.get("status") or "ACTIVE").upper() == "VOIDED":
                    cur.execute(
                        """
                        update stock_opnames
                        set status='ACTIVE', voided_at=null, void_reason=null
                        where id=%s
                        """,
                        (duplicate["id"],),
                    )
                    conn.commit()
                    result.update({"committed": True, "duplicate": False, "restored": True, "stockOpnameId": duplicate["id"]})
                    return result
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
            replaced_ids = _replacement_source_ids(payload.source_external_id)
            if replaced_ids:
                cur.execute(
                    """
                    update stock_opnames
                    set status='SUPERSEDED', superseded_by_stock_opname_id=%s
                    where id = any(%s) and id <> %s
                      and location_code=%s and stock_date=%s
                      and coalesce(status,'ACTIVE')='ACTIVE'
                    """,
                    (opname_id, replaced_ids, opname_id, location, stock_date),
                )
            conn.commit()
            result.update({
                "committed": True,
                "duplicate": False,
                "stockOpnameId": opname_id,
                "supersededStockOpnameIds": replaced_ids,
            })
            return result


@router.get("/inventory/stock-opnames")
def stock_opnames(
    location: str = "",
    limit: int = Query(default=50, ge=1, le=250),
    include_archived: bool = Query(default=False, alias="includeArchived"),
) -> dict[str, Any]:
    require_db()
    sql = """
        select so.id,so.location_code,so.site,so.stock_date,so.source_type,so.source_external_id,
               so.reporter,so.warning_count,so.created_by,so.created_at,
               coalesce(so.status,'ACTIVE') as status,so.superseded_by_stock_opname_id,
               so.voided_at,so.void_reason,count(soi.id) as item_count
        from stock_opnames so left join stock_opname_items soi on soi.stock_opname_id=so.id where true
    """
    params: list[Any] = []
    if location.strip():
        sql += " and so.location_code=%s"
        params.append(normalize_location(location))
    if not include_archived:
        sql += " and coalesce(so.status,'ACTIVE')='ACTIVE'"
    sql += " group by so.id order by so.stock_date desc,so.created_at desc limit %s"
    params.append(limit)
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    return {"items": rows, "count": len(rows)}


@router.get("/inventory/stock-opnames/{stock_opname_id}")
def stock_opname_detail(stock_opname_id: int) -> dict[str, Any]:
    """Return immutable SO evidence plus the editable canonical item snapshot."""
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select id,location_code,site,stock_date,source_type,source_external_id,source_key,
                       reporter,raw_text,warning_count,created_by,created_at,
                       coalesce(status,'ACTIVE') as status,superseded_by_stock_opname_id,voided_at,void_reason
                from stock_opnames where id=%s
                """,
                (stock_opname_id,),
            )
            opname = cur.fetchone()
            if not opname:
                raise HTTPException(404, "stock opname not found")
            cur.execute(
                """
                select id,stock_opname_id,area_code,inventory_item_code,canonical_item_name,
                       raw_item_name,normalized_raw_name,qty,unit,classification_status,
                       classification_method,classification_confidence,parse_status,raw_line,
                       warnings,created_at
                from stock_opname_items where stock_opname_id=%s order by id
                """,
                (stock_opname_id,),
            )
            items = cur.fetchall()
    return {"stockOpname": opname, "items": items, "itemCount": len(items)}


@router.delete("/inventory/stock-opnames/{stock_opname_id}")
def delete_stock_opname(
    stock_opname_id: int,
    reason: str = Query(default="", max_length=240),
) -> dict[str, Any]:
    """Remove an incorrect SO from the active stock calculation.

    This is intentionally a soft delete: raw WhatsApp evidence and the item
    snapshot remain available to audit, but the SO can no longer become the
    physical stock used by balance or PO calculations.
    """
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select id,location_code,stock_date,coalesce(status,'ACTIVE') as status
                from stock_opnames where id=%s
                """,
                (stock_opname_id,),
            )
            opname = cur.fetchone()
            if not opname:
                raise HTTPException(404, "stock opname not found")
            if str(opname["status"]).upper() != "ACTIVE":
                raise HTTPException(409, "stock opname is already archived and cannot be deleted again")
            cur.execute(
                """
                update stock_opnames
                set status='VOIDED', voided_at=now(), void_reason=%s
                where id=%s
                """,
                (reason.strip() or "Dihapus dari stok aktif melalui Pusat Operasional", stock_opname_id),
            )
        conn.commit()
    return {
        "deleted": True,
        "stockOpnameId": stock_opname_id,
        "location": opname["location_code"],
        "stockDate": opname["stock_date"],
        "message": "SO dikeluarkan dari stok aktif. Bukti mentah tetap tersimpan untuk audit.",
    }


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
