from __future__ import annotations

import json
from datetime import date, datetime, time
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.db import connection
from backend.inventory_api import commit_receipt_stock
from backend.operational_api import require_db

router = APIRouter(tags=["po-delivery-alerts"])

_OPEN_DELIVERY_STATUSES = ("FINALIZED", "SENT", "ACKNOWLEDGED", "PARTIAL_RECEIVED")
_CLOSING_ACTIONS = ("ARRIVED_MATCH", "ARRIVED_MISMATCH", "SUPPRESS_ALERT")


def _now_jakarta() -> datetime:
    return datetime.now(ZoneInfo("Asia/Jakarta"))


def _ensure_resolution_table(cur: Any) -> None:
    cur.execute(
        """
        create table if not exists po_delivery_alert_resolutions (
          id bigserial primary key,
          alert_key text not null unique,
          purchase_order_id bigint not null,
          site text not null,
          action text not null,
          note text,
          payload jsonb not null default '{}'::jsonb,
          created_by text,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now()
        )
        """
    )
    cur.execute(
        """
        create index if not exists idx_po_delivery_alert_resolutions_po
        on po_delivery_alert_resolutions(purchase_order_id, action)
        """
    )


def _alert_key(purchase_order_id: int, target: date) -> str:
    return f"po-delivery:{purchase_order_id}:{target.isoformat()}"


@router.get("/po-delivery-alerts")
def po_delivery_alerts(
    site: str = "",
    alert_date: date | None = Query(default=None, alias="date"),
    minimum_hour: int = Query(default=17, ge=0, le=23, alias="minimumHour"),
) -> dict[str, Any]:
    """Warn after 17:00 when ordered ingredients for today's cooking have not arrived.

    Operator confirmations are stored as audit-only delivery-alert resolutions.
    ARRIVED_MATCH may be created by the explicit confirm endpoint and records a
    goods receipt; ARRIVED_MISMATCH/SUPPRESS_ALERT hide the red alert while
    preserving a note for review. SENT_CONFIRMED never hides the not-arrived
    alert by itself because a sent PO is not the same as received stock.
    """
    require_db()
    now = _now_jakarta()
    target = alert_date or now.date()
    active = now.time() >= time(minimum_hour, 0) if target == now.date() else True
    normalized_site = site.upper().strip()

    sql = """
      with po_base as (
        select po.id,po.po_code,po.site,po.vendor_code,po.status,po.sent_at,po.created_at,
               pc.distribution_date,
               coalesce(
                 (select min(poc.cooking_date) from purchase_order_coverage poc where poc.purchase_order_id=po.id),
                 date(pc.cooking_at),
                 pc.distribution_date - interval '1 day'
               )::date as cooking_date
        from purchase_orders po
        left join production_cycles pc on pc.id=po.production_cycle_id
        where upper(coalesce(po.status,''))=any(%s)
      ), item_totals as (
        select pb.id purchase_order_id,pb.po_code,pb.site,pb.vendor_code,pb.status,pb.sent_at,pb.created_at,
               pb.distribution_date,pb.cooking_date,
               poi.id purchase_order_item_id,poi.item_name,poi.po_qty,poi.unit,
               coalesce(sum(gri.accepted_qty),0) as accepted_qty
        from po_base pb
        join purchase_order_items poi on poi.purchase_order_id=pb.id
        left join goods_receipt_items gri on gri.purchase_order_item_id=poi.id
        where pb.cooking_date=%s
        group by pb.id,pb.po_code,pb.site,pb.vendor_code,pb.status,pb.sent_at,pb.created_at,
                 pb.distribution_date,pb.cooking_date,poi.id,poi.item_name,poi.po_qty,poi.unit
      )
      select * from item_totals
      where coalesce(po_qty,0) > coalesce(accepted_qty,0)
        and not exists (
          select 1 from po_delivery_alert_resolutions r
          where r.purchase_order_id=item_totals.purchase_order_id
            and upper(r.action)=any(%s)
            and coalesce(r.payload->>'alertDate','')=%s
        )
    """
    params: list[Any] = [list(_OPEN_DELIVERY_STATUSES), target, list(_CLOSING_ACTIONS), target.isoformat()]
    if normalized_site:
        sql += " and upper(site)=upper(%s)"
        params.append(normalized_site)
    sql += " order by cooking_date,vendor_code,po_code,item_name"

    grouped: dict[int, dict[str, Any]] = {}
    with connection() as conn:
        with conn.cursor() as cur:
            _ensure_resolution_table(cur)
            cur.execute(sql, params)
            for row in cur.fetchall():
                po_id = int(row["purchase_order_id"])
                item = grouped.setdefault(po_id, {
                    "purchaseOrderId": po_id,
                    "poCode": row["po_code"],
                    "site": row["site"],
                    "vendorCode": row["vendor_code"],
                    "status": row["status"],
                    "sentAt": row["sent_at"],
                    "createdAt": row["created_at"],
                    "distributionDate": row["distribution_date"],
                    "cookingDate": row["cooking_date"],
                    "alertKey": _alert_key(po_id, target),
                    "items": [],
                })
                remaining = round(float(row.get("po_qty") or 0) - float(row.get("accepted_qty") or 0), 4)
                item["items"].append({
                    "purchaseOrderItemId": row["purchase_order_item_id"],
                    "itemName": row["item_name"],
                    "poQty": float(row.get("po_qty") or 0),
                    "acceptedQty": float(row.get("accepted_qty") or 0),
                    "remainingReceiveQty": remaining,
                    "unit": row.get("unit"),
                    "message": f"{row['item_name']} belum datang/cukup: kurang {remaining:g} {row.get('unit') or ''}".strip(),
                })
            conn.commit()

    items = list(grouped.values()) if active else []
    for row in items:
        row["warningLevel"] = "CRITICAL_AFTER_17" if active else "PENDING_TIME_WINDOW"
        row["message"] = (
            f"Barang PO {row['poCode']} untuk masak {row['cookingDate']} belum datang lengkap. "
            "Risiko bahan tidak cukup untuk masak hari ini."
        )
    return {
        "site": normalized_site,
        "date": target,
        "timezone": "Asia/Jakarta",
        "active": active,
        "minimumHour": minimum_hour,
        "count": len(items),
        "items": items,
    }


class DeliveryAlertConfirmIn(BaseModel):
    purchase_order_id: int = Field(gt=0)
    action: Literal["SENT_CONFIRMED", "ARRIVED_MATCH", "ARRIVED_MISMATCH", "SUPPRESS_ALERT"]
    note: str | None = Field(default=None, max_length=1000)
    actor: str | None = Field(default=None, max_length=100)


def _load_po(cur: Any, purchase_order_id: int) -> dict[str, Any]:
    cur.execute(
        """
        select po.id,po.po_code,po.site,po.vendor_code,po.status,po.sent_at,
               pc.distribution_date,
               coalesce(
                 (select min(poc.cooking_date) from purchase_order_coverage poc where poc.purchase_order_id=po.id),
                 date(pc.cooking_at),
                 pc.distribution_date - interval '1 day'
               )::date as cooking_date
        from purchase_orders po
        left join production_cycles pc on pc.id=po.production_cycle_id
        where po.id=%s
        """,
        (purchase_order_id,),
    )
    po = cur.fetchone()
    if not po:
        raise HTTPException(404, "purchase order not found")
    return dict(po)


def _remaining_items(cur: Any, purchase_order_id: int) -> list[dict[str, Any]]:
    cur.execute(
        """
        select poi.id purchase_order_item_id,poi.item_name,poi.po_qty,poi.unit,
               coalesce(sum(gri.accepted_qty),0) as accepted_qty
        from purchase_order_items poi
        left join goods_receipt_items gri on gri.purchase_order_item_id=poi.id
        where poi.purchase_order_id=%s
        group by poi.id,poi.item_name,poi.po_qty,poi.unit
        order by poi.id
        """,
        (purchase_order_id,),
    )
    items: list[dict[str, Any]] = []
    for row in cur.fetchall():
        remaining = round(float(row.get("po_qty") or 0) - float(row.get("accepted_qty") or 0), 4)
        if remaining > 0:
            item = dict(row)
            item["remaining_qty"] = remaining
            items.append(item)
    return items


def _save_resolution(
    cur: Any,
    *,
    purchase_order_id: int,
    site: str,
    action: str,
    alert_date: date,
    note: str | None,
    actor: str | None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    key = _alert_key(purchase_order_id, alert_date) if action != "SENT_CONFIRMED" else f"po-delivery-sent:{purchase_order_id}:{alert_date.isoformat()}"
    data = {"alertDate": alert_date.isoformat(), **(payload or {})}
    cur.execute(
        """
        insert into po_delivery_alert_resolutions(
          alert_key,purchase_order_id,site,action,note,payload,created_by
        ) values (%s,%s,%s,%s,%s,%s::jsonb,%s)
        on conflict (alert_key) do update set
          action=excluded.action,
          note=excluded.note,
          payload=excluded.payload,
          created_by=excluded.created_by,
          updated_at=now()
        returning id, alert_key, purchase_order_id, site, action, note, payload, created_at, updated_at
        """,
        (
            key,
            purchase_order_id,
            site.upper(),
            action,
            note,
            json.dumps(data, ensure_ascii=False),
            actor,
        ),
    )
    return dict(cur.fetchone())


@router.post("/po-delivery-alerts/confirm")
def confirm_po_delivery_alert(payload: DeliveryAlertConfirmIn) -> dict[str, Any]:
    """Confirm one red delivery alert.

    SENT_CONFIRMED confirms/marks the PO as sent but does not close the not-arrived
    alert. ARRIVED_MATCH inserts a full receipt for the current remaining qty and
    commits stock. ARRIVED_MISMATCH/SUPPRESS_ALERT closes the red alert with an
    audit note but does not alter stock.
    """
    require_db()
    action = payload.action.upper().strip()
    if action in {"ARRIVED_MISMATCH", "SUPPRESS_ALERT"} and not (payload.note or "").strip():
        raise HTTPException(400, "alasan wajib diisi untuk barang tidak sesuai / alert ditutup manual")

    alert_date = _now_jakarta().date()
    with connection() as conn:
        with conn.cursor() as cur:
            _ensure_resolution_table(cur)
            po = _load_po(cur, payload.purchase_order_id)
            site = str(po["site"]).upper()
            result: dict[str, Any] = {
                "purchaseOrderId": po["id"],
                "poCode": po["po_code"],
                "site": site,
                "vendorCode": po["vendor_code"],
                "action": action,
            }

            if action == "SENT_CONFIRMED":
                status = str(po.get("status") or "").upper()
                if status == "DRAFT":
                    raise HTTPException(409, "PO masih DRAFT; finalkan dulu sebelum ditandai terkirim")
                if status in {"FINALIZED", "SENT", "ACKNOWLEDGED", "PARTIAL_RECEIVED"}:
                    cur.execute(
                        """
                        update purchase_orders
                        set status=case when upper(status)='FINALIZED' then 'SENT' else status end,
                            sent_at=coalesce(sent_at,now()),
                            updated_at=now()
                        where id=%s
                        returning status,sent_at
                        """,
                        (po["id"],),
                    )
                    updated = cur.fetchone()
                    result.update({"poStatus": updated["status"], "sentAt": updated["sent_at"]})
                resolution = _save_resolution(
                    cur,
                    purchase_order_id=po["id"],
                    site=site,
                    action=action,
                    alert_date=alert_date,
                    note=payload.note,
                    actor=payload.actor,
                )
                result.update({"saved": True, "resolution": resolution, "message": "PO dikonfirmasi sudah terkirim. Alert barang belum datang tetap aktif sampai penerimaan dicatat."})
                conn.commit()
                return result

            if action == "ARRIVED_MATCH":
                remaining = _remaining_items(cur, po["id"])
                if not remaining:
                    resolution = _save_resolution(
                        cur,
                        purchase_order_id=po["id"],
                        site=site,
                        action=action,
                        alert_date=alert_date,
                        note=payload.note,
                        actor=payload.actor,
                        payload={"remainingItems": []},
                    )
                    conn.commit()
                    return {**result, "saved": True, "receiptCreated": False, "resolution": resolution, "message": "Tidak ada sisa item yang perlu diterima."}

                source_key = f"delivery-alert-arrived-match:{po['id']}:{alert_date.isoformat()}"
                cur.execute("select id from goods_receipts where source_key=%s", (source_key,))
                duplicate = cur.fetchone()
                if duplicate:
                    receipt_id = int(duplicate["id"])
                    stock = commit_receipt_stock(cur, receipt_id, site)
                else:
                    cur.execute(
                        """
                        insert into goods_receipts(
                          purchase_order_id,receipt_code,received_at,source_type,source_external_id,source_key,
                          reporter,raw_text,match_status,match_confidence,confirmed_at
                        ) values (%s,%s,now(),'PO_DELIVERY_ALERT',%s,%s,%s,%s,'CONFIRMED',1,now())
                        returning id
                        """,
                        (
                            po["id"],
                            f"ALERT-{po['po_code']}-{alert_date.isoformat()}",
                            source_key,
                            source_key,
                            payload.actor,
                            payload.note or "Barang datang sesuai dari konfirmasi alert merah",
                        ),
                    )
                    receipt_id = int(cur.fetchone()["id"])
                    for item in remaining:
                        remaining_qty = float(item["remaining_qty"])
                        cur.execute(
                            """
                            insert into goods_receipt_items(
                              goods_receipt_id,purchase_order_item_id,received_qty,rejected_qty,accepted_qty,unit,
                              quality_status,notes,reported_item_name,po_qty_snapshot,variance_qty,match_confidence,match_method
                            ) values (%s,%s,%s,0,%s,%s,'ACCEPTED',%s,%s,%s,0,1,'delivery_alert_confirm')
                            """,
                            (
                                receipt_id,
                                item["purchase_order_item_id"],
                                remaining_qty,
                                remaining_qty,
                                item.get("unit"),
                                payload.note,
                                item.get("item_name"),
                                item.get("po_qty"),
                            ),
                        )
                    stock = commit_receipt_stock(cur, receipt_id, site)

                cur.execute(
                    """
                    select poi.id,poi.po_qty,coalesce(sum(gri.accepted_qty),0) as received_total
                    from purchase_order_items poi
                    left join goods_receipt_items gri on gri.purchase_order_item_id=poi.id
                    where poi.purchase_order_id=%s
                    group by poi.id,poi.po_qty
                    """,
                    (po["id"],),
                )
                totals = cur.fetchall()
                complete = bool(totals) and all(float(row["received_total"] or 0) >= float(row["po_qty"] or 0) for row in totals)
                new_status = "RECEIVED" if complete else "PARTIAL_RECEIVED"
                cur.execute("update purchase_orders set status=%s,updated_at=now() where id=%s", (new_status, po["id"]))
                resolution = _save_resolution(
                    cur,
                    purchase_order_id=po["id"],
                    site=site,
                    action=action,
                    alert_date=alert_date,
                    note=payload.note,
                    actor=payload.actor,
                    payload={"receiptId": receipt_id, "remainingItems": remaining, "purchaseOrderStatus": new_status},
                )
                conn.commit()
                return {
                    **result,
                    "saved": True,
                    "receiptCreated": True,
                    "receiptId": receipt_id,
                    "purchaseOrderStatus": new_status,
                    "stockCommitted": True,
                    "stockInserted": stock["inserted"],
                    "stockDuplicates": stock["duplicates"],
                    "resolution": resolution,
                    "message": "Barang datang sesuai dicatat sebagai penerimaan dan stok bertambah.",
                }

            resolution = _save_resolution(
                cur,
                purchase_order_id=po["id"],
                site=site,
                action=action,
                alert_date=alert_date,
                note=payload.note,
                actor=payload.actor,
            )
            conn.commit()
            return {
                **result,
                "saved": True,
                "receiptCreated": False,
                "resolution": resolution,
                "message": "Alert ditutup dengan catatan tidak sesuai. Stok tidak diubah.",
            }
