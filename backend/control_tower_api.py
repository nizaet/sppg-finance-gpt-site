from __future__ import annotations

import os
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from backend.accountant_bgn_flow_api import accountant_flow, bgn_flow
from backend.db import connection, database_ready
from backend.google_services import SITE_TARGETS, firestore_client
from backend.po_reminder_v3_api import po_reminders_v3

router = APIRouter(tags=["control-tower"])

SITE_DEFS = [
    {"siteId": "sppg-maja-gpt-site", "siteLabel": "SPPG MAJA BARU", "dbSite": "MAJA"},
    {"siteId": "sppg-cemplang2-gpt-site", "siteLabel": "SPPG CEMPLANG 2", "dbSite": "CEMPLANG"},
]

DONE_PAYABLE = ("PAID", "RECONCILED", "CLOSED", "CANCELLED", "CANCELED")


def empty_site(site: dict[str, str]) -> dict[str, Any]:
    return {
        "siteId": site["siteId"],
        "siteLabel": site["siteLabel"],
        "summary": {
            "poDueToday": 0,
            "poOverdue": 0,
            "poShortage": 0,
            "receiptsToday": 0,
            "receivingIssues": 0,
            "paymentsDue": 0,
            "reviewQueue": 0,
        },
        "lanes": {
            "procurement": [],
            "receiving": [],
            "payments": [],
            "accountant": [],
            "bgn": [],
        },
    }


def _money(value: Any) -> str:
    try:
        return f"Rp{float(value or 0):,.0f}".replace(",", ".")
    except (TypeError, ValueError):
        return "Rp0"


def _site_defs(site: str) -> list[dict[str, str]]:
    value = (site or "").upper().strip()
    if not value:
        return SITE_DEFS
    if value not in {"MAJA", "CEMPLANG"}:
        raise HTTPException(400, "site must be MAJA or CEMPLANG")
    return [x for x in SITE_DEFS if x["dbSite"] == value]


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _short_date_list(item: dict[str, Any], plural_key: str, singular_key: str) -> str:
    values = [str(x) for x in (item.get(plural_key) or []) if x]
    if values:
        return ", ".join(values)
    value = item.get(singular_key)
    return str(value) if value else "-"


def _procurement_view(reminder_payload: dict[str, Any], target_date: date) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """Translate the authoritative PO-reminder state into Control Tower rows.

    Ordering work and receiving work are intentionally separate. A SENT,
    ACKNOWLEDGED, PARTIAL_RECEIVED or RECEIVED PO is not an overdue *ordering*
    task. If planning later reveals a residual shortage, it is shown amber as
    CEK SISA rather than red as if no PO had ever been sent.
    """
    summary = {"poDueToday": 0, "poOverdue": 0, "poShortage": 0}
    lanes: list[tuple[int, date, dict[str, Any]]] = []

    for index, item in enumerate(reminder_payload.get("items") or []):
        status = str(item.get("reminder_status") or "").upper()
        po_date = _as_date(item.get("po_date")) or date.max
        shortage_after_po = bool(item.get("po_already_done") and item.get("shortage_only"))
        is_done = status == "DONE" or bool(item.get("reminder_override"))

        if shortage_after_po and not is_done:
            summary["poShortage"] += 1
            badge = "CEK SISA"
            severity = "warning"
            priority = 1
        elif is_done:
            badge = "SELESAI"
            severity = "success"
            priority = 6
        else:
            overdue = status == "OVERDUE" or (
                status in {"DRAFT_NEEDS_FINAL", "READY_TO_SEND"} and po_date < target_date
            )
            due_today = status == "DUE_TODAY" or (
                status in {"DRAFT_NEEDS_FINAL", "READY_TO_SEND"} and po_date == target_date
            )
            if overdue:
                summary["poOverdue"] += 1
                badge = "TERLAMBAT"
                severity = "warning"
                priority = 0
            elif due_today:
                summary["poDueToday"] += 1
                badge = "HARI INI"
                severity = "info"
                priority = 2
            elif status == "DRAFT_NEEDS_FINAL":
                badge = "FINALISASI"
                severity = "warning"
                priority = 3
            elif status == "READY_TO_SEND":
                badge = "KIRIM PO"
                severity = "info"
                priority = 3
            elif status == "LEAD_TIME_MISSING":
                badge = "LEAD TIME?"
                severity = "warning"
                priority = 4
            else:
                badge = "AKAN DATANG"
                severity = "info"
                priority = 5

        vendor = item.get("vendor_name") or item.get("vendor_code") or "Vendor"
        po_code = item.get("po_code")
        po_status = str(item.get("po_status") or "").upper()
        missing_names = item.get("missing_item_names") or item.get("item_names") or []
        item_text = ", ".join(str(x) for x in missing_names[:4] if x)
        if len(missing_names) > 4:
            item_text += f" +{len(missing_names) - 4}"
        distribution_text = _short_date_list(item, "distribution_dates", "distribution_date")
        cooking_text = _short_date_list(item, "cooking_dates", "cooking_date")
        po_text = f" · {po_code} ({po_status})" if po_code else ""
        shortage_text = " · masih ada sisa kebutuhan" if shortage_after_po else ""
        detail_text = f" · {item_text}" if item_text else ""

        lane = {
            "id": item.get("purchase_order_id") or item.get("reminder_key") or f"reminder-{index}",
            "title": f"{vendor}{po_text}",
            "subtitle": (
                f"Pesan {item.get('po_date') or '-'} · Masak {cooking_text} · "
                f"Distribusi {distribution_text}{detail_text}{shortage_text}"
            ),
            "status": badge,
            "severity": severity,
            "reminderStatus": status,
            "purchaseOrderId": item.get("purchase_order_id"),
            "poCode": po_code,
            "poStatus": po_status or None,
            "shortageOnly": shortage_after_po,
            "reminderOverride": bool(item.get("reminder_override")),
        }
        lanes.append((priority, po_date, lane))

    lanes.sort(key=lambda row: (row[0], row[1], str(row[2].get("title") or "")))
    # Keep active/problem rows visible first, but retain a few green completed
    # rows so the operator can see that the tower is actually synchronized.
    return summary, [row[2] for row in lanes[:12]]


def _build_info() -> dict[str, Any]:
    return {
        "commit": os.getenv("RAILWAY_GIT_COMMIT_SHA") or os.getenv("GIT_COMMIT_SHA") or None,
        "branch": os.getenv("RAILWAY_GIT_BRANCH") or os.getenv("GIT_BRANCH") or None,
        "service": os.getenv("RAILWAY_SERVICE_NAME") or None,
    }


def _flow_rows(loader: Any) -> list[dict[str, Any]]:
    """Use the schema-tolerant Accountant/BGN readers as a Control Tower fallback.

    These readers already support the older database variants used by the live
    application.  Control Tower previously queried newer columns directly,
    which left its Accountant and Maker lanes empty even while the same records
    were visible on their own pages.
    """
    try:
        result = loader()
        return list(result.get("items") or []) if isinstance(result, dict) else []
    except Exception:
        return []


def _append_accountant_flow_fallback(out: dict[str, Any], rows: list[dict[str, Any]], site: str) -> None:
    if out["lanes"]["accountant"]:
        return
    for row in rows:
        if str(row.get("site") or "").upper() != site:
            continue
        invoice_id = row.get("invoice_id")
        maker_id = row.get("maker_id")
        maker_status = str(row.get("maker_status") or "").upper()
        if invoice_id:
            paid = maker_status == "PAID"
            status = "PAID" if paid else "PENDING APPROVAL" if maker_id else "BELUM MAKER"
            severity = "success" if paid else "warning" if maker_id else "info"
            title = row.get("invoice_number") or f"Invoice #{invoice_id}"
            subtitle = f"BAHAN_BAKU · {_money(row.get('invoice_amount'))} · {row.get('received_at') or '-'}"
        else:
            title = f"{row.get('accountant_code') or 'Akuntan'} · {row.get('source_distribution_date') or '-'}"
            subtitle = f"Excel {row.get('submission_status') or row.get('status') or 'READY'} · invoice belum diterima"
            status, severity = "MENUNGGU INVOICE", "info"
        out["lanes"]["accountant"].append({
            "id": f"accountant-{row.get('submission_id') or invoice_id}", "title": title,
            "subtitle": subtitle, "status": status, "severity": severity,
        })
        if len(out["lanes"]["accountant"]) >= 8:
            break


def _append_bgn_flow_fallback(out: dict[str, Any], rows: list[dict[str, Any]], site: str) -> None:
    if out["lanes"]["bgn"]:
        return
    for row in rows:
        if str(row.get("site") or "").upper() != site:
            continue
        approval = str(row.get("approval_status") or "PENDING").upper()
        paid = bool(row.get("receipt_id")) or str(row.get("maker_status") or "").upper() == "PAID"
        if paid:
            status, severity = "PAID", "success"
        elif approval == "APPROVED":
            status, severity = "MENUNGGU DANA", "info"
        elif approval == "REJECTED":
            status, severity = "DITOLAK", "warning"
        else:
            status, severity = "PENDING APPROVAL", "warning"
        out["lanes"]["bgn"].append({
            "id": f"maker-{row.get('maker_id')}",
            "title": row.get("reference_number") or f"Maker #{row.get('maker_id')}",
            "subtitle": f"{_money(row.get('maker_amount'))} · approver {row.get('approver_code') or '-'} · {approval}",
            "status": status, "severity": severity,
        })
        if len(out["lanes"]["bgn"]) >= 8:
            break


def _append_firestore_finance_fallback(out: dict[str, Any], site: str) -> None:
    """Read the existing Finance ledger when it has not yet been backfilled.

    The original Finance pages read these Firestore records directly.  Showing
    an empty payment lane until a separate migration is run is misleading, so
    Control Tower reads them as a non-blocking fallback.
    """
    if out["lanes"]["payments"]:
        return
    try:
        target = SITE_TARGETS[site]
        collection = (
            firestore_client(target["database_id"])
            .collection("gpt_sites").document(target["site_id"])
            .collection("ledger").document("meta").collection("transactions")
        )
        rows = []
        for snapshot in collection.stream():
            item = snapshot.to_dict() or {}
            item["_id"] = snapshot.id
            rows.append(item)
        rows.sort(key=lambda row: str(row.get("date") or row.get("transaction_date") or ""), reverse=True)
        for row in rows[:8]:
            transaction_type = str(row.get("type") or row.get("transaction_type") or "").lower()
            status = str(row.get("paymentStatus") or row.get("payment_status") or "paid").upper()
            amount = row.get("amount") or 0
            title = str(row.get("desc") or row.get("description") or "Transaksi Finance")
            category = str(row.get("category") or "-")
            tx_date = str(row.get("date") or row.get("transaction_date") or "-")
            out["lanes"]["payments"].append({
                "id": f"firestore-finance-{row['_id']}",
                "title": title,
                "subtitle": f"{category} · {_money(amount)} · {tx_date}",
                "status": "MASUK" if transaction_type in {"income", "masuk", "pemasukan"} else status,
                "severity": "success" if transaction_type in {"income", "masuk", "pemasukan"} or status == "PAID" else "warning",
            })
    except Exception:
        # The database/PO/receipt lanes remain usable even when Firestore is
        # temporarily unavailable.
        return



WEEKLY_RECEIVED_PO_STATUSES = {"RECEIVED", "CLOSED"}


def _weekly_site_payload(site: dict[str, str], start_date: date) -> dict[str, Any]:
    days = []
    by_date: dict[date, dict[str, Any]] = {}
    for offset in range(7):
        day_date = date.fromordinal(start_date.toordinal() + offset)
        day = {
            "date": day_date.isoformat(),
            "planning": {"status": "NO_PLAN", "snapshotId": None, "itemCount": 0, "items": []},
            "procurement": {"poCount": 0, "notOrdered": 0, "draft": 0, "sent": 0,
                            "partial": 0, "received": 0, "notArrived": 0,
                            "purchaseOrders": []},
            "accountant": {"submissions": []},
            "maker": {"count": 0, "notCreated": 0, "pendingApproval": 0,
                      "approved": 0, "paid": 0, "rejected": 0, "items": []},
            "payments": {"due": 0, "overdue": 0, "items": []},
            "reviewCount": 0,
        }
        days.append(day)
        by_date[day_date] = day
    return {**site, "days": days, "_by_date": by_date}


def _iso(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else (str(value) if value else None)


@router.get("/control-tower-weekly")
def control_tower_weekly(
    from_date: date = Query(alias="fromDate"),
    site: str = "",
) -> dict[str, Any]:
    """Seven-day read-only review built from the committed planning/PO/finance workflow tables."""
    definitions = _site_defs(site)
    end_date = date.fromordinal(from_date.toordinal() + 6)
    sites = [_weekly_site_payload(definition, from_date) for definition in definitions]
    if not database_ready():
        return {"fromDate": from_date.isoformat(), "throughDate": end_date.isoformat(),
                "databaseReady": False, "buildInfo": _build_info(),
                "sites": [{k: v for k, v in row.items() if k != "_by_date"} for row in sites]}

    try:
        with connection() as conn:
            with conn.cursor() as cur:
                for row in sites:
                    db_site = row["dbSite"]
                    by_date = row["_by_date"]

                    cur.execute(
                        """select distinct on (ps.distribution_date)
                                  ps.id,ps.distribution_date,ps.cooking_at,ps.payload,
                                  count(psi.id) filter(where coalesce(psi.planned_qty,0)>0) as item_count,
                                  coalesce(array_agg(distinct psi.item_name)
                                    filter(where coalesce(psi.planned_qty,0)>0),array[]::text[]) as item_names
                           from planning_snapshots ps
                           left join planning_snapshot_items psi on psi.planning_snapshot_id=ps.id
                           where upper(ps.site)=%s and ps.status='ACTIVE'
                             and ps.distribution_date between %s and %s
                           group by ps.id,ps.distribution_date,ps.cooking_at,ps.payload,ps.created_at
                           order by ps.distribution_date,ps.created_at desc,ps.id desc""",
                        (db_site, from_date, end_date),
                    )
                    for plan in cur.fetchall():
                        day = by_date.get(plan["distribution_date"])
                        if day is not None:
                            names = list(plan.get("item_names") or [])
                            day["planning"] = {
                                "status": "READY" if int(plan.get("item_count") or 0) else "EMPTY",
                                "snapshotId": int(plan["id"]),
                                "cookingAt": _iso(plan.get("cooking_at")),
                                "itemCount": int(plan.get("item_count") or 0),
                                "items": names[:5],
                                "moreItems": max(0, len(names) - 5),
                            }

                    cur.execute(
                        """with po_by_day as (
                             select po.id,upper(po.site) site,poc.distribution_date,
                                    po.po_code,upper(po.vendor_code) vendor_code,
                                    upper(po.status) status,count(distinct poci.id) item_count,
                                    coalesce(sum(poci.po_qty),0) ordered_qty
                             from purchase_orders po
                             join purchase_order_coverage poc on poc.purchase_order_id=po.id
                             left join purchase_order_coverage_items poci on poci.purchase_order_coverage_id=poc.id
                             where upper(po.site)=%s and poc.distribution_date between %s and %s
                               and upper(coalesce(po.status,'')) <> all(%s)
                             group by po.id,poc.distribution_date
                             union all
                             select po.id,upper(po.site) site,pc.distribution_date,
                                    po.po_code,upper(po.vendor_code) vendor_code,
                                    upper(po.status) status,count(distinct poi.id) item_count,
                                    coalesce(sum(poi.po_qty),0) ordered_qty
                             from purchase_orders po
                             join production_cycles pc on pc.id=po.production_cycle_id
                             left join purchase_order_items poi on poi.purchase_order_id=po.id
                             where upper(po.site)=%s and pc.distribution_date between %s and %s
                               and upper(coalesce(po.status,'')) <> all(%s)
                               and not exists(select 1 from purchase_order_coverage poc where poc.purchase_order_id=po.id)
                             group by po.id,pc.distribution_date
                           )
                           select p.*,coalesce(r.receipt_count,0) receipt_count
                           from po_by_day p
                           left join lateral (
                             select count(*) receipt_count from goods_receipts gr
                             where gr.purchase_order_id=p.id and gr.received_at is not null
                           ) r on true
                           order by p.distribution_date,p.vendor_code,p.po_code""",
                        (db_site, from_date, end_date, ["CANCELLED", "SUPERSEDED", "HISTORICAL_IMPORTED"],
                         db_site, from_date, end_date, ["CANCELLED", "SUPERSEDED", "HISTORICAL_IMPORTED"]),
                    )
                    for po in cur.fetchall():
                        day = by_date.get(po["distribution_date"])
                        if day is None:
                            continue
                        status = str(po.get("status") or "DRAFT").upper()
                        receipt_count = int(po.get("receipt_count") or 0)
                        procurement = day["procurement"]
                        procurement["poCount"] += 1
                        if status in {"DRAFT", "FINALIZED"}:
                            procurement["draft"] += 1
                        elif status == "PARTIAL_RECEIVED":
                            procurement["partial"] += 1
                            procurement["notArrived"] += 1
                        elif status in {"SENT", "ACKNOWLEDGED"}:
                            procurement["sent"] += 1
                            procurement["notArrived"] += 1
                        elif status in WEEKLY_RECEIVED_PO_STATUSES:
                            procurement["received"] += 1
                        procurement["purchaseOrders"].append({
                            "id": str(po["id"]), "code": po.get("po_code"),
                            "vendor": po.get("vendor_code"), "status": status,
                            "itemCount": int(po.get("item_count") or 0),
                            "orderedQty": float(po.get("ordered_qty") or 0),
                            "receiptCount": receipt_count,
                        })

                    cur.execute(
                        """select coalesce(pc.distribution_date,s.source_distribution_date) distribution_date,
                                  s.id,s.accountant_code,s.status submission_status,
                                  s.sent_at,s.drive_upload_status,
                                  i.id invoice_id,i.invoice_number,i.invoice_category,i.invoice_amount
                           from accountant_submissions s
                           left join production_cycles pc on pc.id=s.production_cycle_id
                           left join lateral(select * from accountant_invoices x
                                             where x.accountant_submission_id=s.id
                                             order by x.id desc limit 1) i on true
                           where upper(s.site)=%s
                             and coalesce(pc.distribution_date,s.source_distribution_date) between %s and %s
                           order by coalesce(pc.distribution_date,s.source_distribution_date),s.id""",
                        (db_site, from_date, end_date),
                    )
                    for flow in cur.fetchall():
                        day = by_date.get(flow["distribution_date"])
                        if day is None:
                            continue
                        day["accountant"]["submissions"].append({
                            "id": int(flow["id"]), "code": flow.get("accountant_code"),
                            "status": str(flow.get("submission_status") or "PENDING").upper(),
                            "invoiceNumber": flow.get("invoice_number"),
                            "invoiceCategory": flow.get("invoice_category"),
                            "invoiceAmount": float(flow.get("invoice_amount") or 0),
                            "driveStatus": flow.get("drive_upload_status"),
                        })

                    cur.execute(
                        """select coalesce(pc_m.distribution_date,pc_s.distribution_date,
                                           s.source_distribution_date,i.invoice_date) distribution_date,
                                  m.id,m.reference_number,m.amount,m.status maker_status,
                                  a.status approval_status,
                                  exists(select 1 from bgn_receipts r where r.bgn_maker_id=m.id) has_receipt
                           from bgn_makers m
                           left join accountant_invoices i on i.id=m.accountant_invoice_id
                           left join accountant_submissions s on s.id=i.accountant_submission_id
                           left join production_cycles pc_m on pc_m.id=m.production_cycle_id
                           left join production_cycles pc_s on pc_s.id=s.production_cycle_id
                           left join lateral(select * from bgn_approvals x where x.bgn_maker_id=m.id
                                             order by x.created_at desc,x.id desc limit 1) a on true
                           where upper(m.site)=%s
                             and coalesce(pc_m.distribution_date,pc_s.distribution_date,
                                          s.source_distribution_date,i.invoice_date) between %s and %s
                           order by coalesce(pc_m.distribution_date,pc_s.distribution_date,
                                             s.source_distribution_date,i.invoice_date),m.id""",
                        (db_site, from_date, end_date),
                    )
                    for maker in cur.fetchall():
                        day = by_date.get(maker["distribution_date"])
                        if day is None:
                            continue
                        approval = str(maker.get("approval_status") or "PENDING").upper()
                        maker_status = str(maker.get("maker_status") or "").upper()
                        has_receipt = bool(maker.get("has_receipt"))
                        paid = has_receipt or maker_status == "PAID"
                        day["maker"]["items"].append({
                            "id": int(maker["id"]),
                            "reference": maker.get("reference_number") or f"Maker #{maker['id']}",
                            "amount": float(maker.get("amount") or 0),
                            "makerStatus": maker_status or "CREATED",
                            "approvalStatus": approval,
                            "hasReceipt": has_receipt,
                            "status": "PAID" if paid else approval,
                        })

                    cur.execute(
                        """select vi.id,vi.vendor_code,vi.invoice_number,vi.net_amount,
                                  vi.payable_status,vi.due_date
                           from vendor_invoices vi
                                  vi.payable_status,vi.due_date
                           from vendor_invoices vi
                           where upper(coalesce(vi.site,''))=%s and vi.due_date between %s and %s
                             and upper(coalesce(vi.payable_status,'UNPAID')) <> all(%s)
                           order by vi.due_date,vi.id""",
                        (db_site, from_date, end_date, list(DONE_PAYABLE)),
                    )
                    for invoice in cur.fetchall():
                        day = by_date.get(invoice["due_date"])
                        if day is None:
                            continue
                        status = str(invoice.get("payable_status") or "UNPAID").upper()
                        day["payments"]["due"] += 1
                        day["payments"]["items"].append({
                            "id": int(invoice["id"]), "vendor": invoice.get("vendor_code"),
                            "invoiceNumber": invoice.get("invoice_number"),
                            "amount": float(invoice.get("net_amount") or 0),
                            "status": status,
                            "dueDate": invoice["due_date"].isoformat(),
                            "overdue": invoice["due_date"] < from_date,
                        })

                    cur.execute(
                        """select count(*) n from candidate_events
                           where upper(coalesce(site,''))=%s
                             and status='PENDING' and requires_confirmation=true""",
                        (db_site,),
                    )
                    review_count = int(cur.fetchone()["n"] or 0)
                    for day in by_date.values():
                        day["reviewCount"] = review_count
                        procurement = day["procurement"]
                        if day["planning"]["status"] == "READY":
                            procurement["notOrdered"] = max(0, 1 if procurement["poCount"] == 0 else 0)
                        maker_data = day["maker"]
                        maker_data["count"] = len(maker_data["items"])
                        maker_data["notCreated"] = int(day["planning"]["status"] == "READY" and maker_data["count"] == 0)
                        maker_data["paid"] = sum(1 for item in maker_data["items"] if item["status"] == "PAID")
                        maker_data["approved"] = sum(1 for item in maker_data["items"] if item["approvalStatus"] == "APPROVED" and item["status"] != "PAID")
                        maker_data["pendingApproval"] = sum(1 for item in maker_data["items"] if item["status"] != "PAID" and item["approvalStatus"] not in {"APPROVED", "REJECTED"})
                        maker_data["rejected"] = sum(1 for item in maker_data["items"] if item["approvalStatus"] == "REJECTED")
                        day["payments"]["overdue"] = int(day["date"] < from_date.isoformat()) * day["payments"]["due"]

        return {
            "fromDate": from_date.isoformat(),
            "throughDate": end_date.isoformat(),
            "databaseReady": True,
            "buildInfo": _build_info(),
            "sites": [{k: v for k, v in row.items() if k != "_by_date"} for row in sites],
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"weekly control tower query failed: {type(exc).__name__}") from exc


@router.get("/control-tower-v2")
def control_tower_v2(
    target_date: date = Query(alias="date"),
    site: str = "",
) -> dict[str, Any]:
    """Read-only control tower built from the same committed operational state.

    PO ordering uses the strict lead-time reminder engine, not distribution date.
    Receiving is read from the same goods_receipts tables used by GPTS and the
    Penerimaan page. Finance/accountant/BGN remain separate domain lanes.
    """
    definitions = _site_defs(site)
    sites = [empty_site(x) for x in definitions]
    build_info = _build_info()
    if not database_ready():
        return {
            "date": target_date.isoformat(),
            "databaseReady": False,
            "buildInfo": build_info,
            "sites": sites,
        }

    accountant_rows = _flow_rows(accountant_flow)
    bgn_rows = _flow_rows(bgn_flow)

    # Resolve procurement before the broad dashboard query so it uses exactly
    # the same v3 compatibility/override semantics as the PO reminder screen.
    for definition, out in zip(definitions, sites):
        try:
            reminders = po_reminders_v3(site=definition["dbSite"], as_of=target_date, horizon_days=7)
            procurement_summary, procurement_lane = _procurement_view(reminders, target_date)
            out["summary"].update(procurement_summary)
            out["lanes"]["procurement"] = procurement_lane
            out["poReminderDate"] = reminders.get("date")
            out["poReminderHorizonThrough"] = reminders.get("horizonThrough")
        except Exception as exc:
            # Other lanes must remain available if reminder reconciliation has a
            # temporary data issue. Expose the type, not sensitive internals.
            out["procurementError"] = type(exc).__name__

    try:
        with connection() as conn:
            with conn.cursor() as cur:
                for definition, out in zip(definitions, sites):
                    db_site = definition["dbSite"]

                    cur.execute(
                        """select count(*) as n from candidate_events
                           where upper(coalesce(site,''))=%s
                             and status='PENDING' and requires_confirmation=true""",
                        (db_site,),
                    )
                    out["summary"]["reviewQueue"] = int(cur.fetchone()["n"] or 0)

                    # Same tables written by /v1/receiving/whatsapp (GPTS) and
                    # /v1/goods-receipts (manual/domain). This makes receiving
                    # visible in the Control Tower instead of hiding it elsewhere.
                    cur.execute(
                        """
                        select
                          count(distinct gr.id) as receipts_today,
                          count(distinct gr.id) filter (
                            where exists (
                              select 1 from goods_receipt_items issue
                              where issue.goods_receipt_id=gr.id
                                and (coalesce(issue.rejected_qty,0)>0 or coalesce(issue.variance_qty,0)<0)
                            )
                          ) as receiving_issues
                        from goods_receipts gr
                        join purchase_orders po on po.id=gr.purchase_order_id
                        where upper(coalesce(po.site,''))=%s
                          and gr.received_at::date=%s
                        """,
                        (db_site, target_date),
                    )
                    receipt_counts = cur.fetchone() or {}
                    out["summary"]["receiptsToday"] = int(receipt_counts.get("receipts_today") or 0)
                    out["summary"]["receivingIssues"] = int(receipt_counts.get("receiving_issues") or 0)

                    cur.execute(
                        """
                        select gr.id,gr.receipt_code,gr.received_at,gr.source_type,
                               gr.source_external_id,gr.reporter,gr.match_status,gr.match_confidence,
                               po.id as purchase_order_id,po.po_code,po.vendor_code,po.status as po_status,
                               count(gri.id) as item_count,
                               coalesce(sum(gri.received_qty),0) as received_qty_total,
                               coalesce(sum(gri.accepted_qty),0) as accepted_qty_total,
                               coalesce(sum(gri.rejected_qty),0) as rejected_qty_total,
                               count(gri.id) filter (
                                 where coalesce(gri.rejected_qty,0)>0 or coalesce(gri.variance_qty,0)<0
                               ) as issue_item_count
                        from goods_receipts gr
                        join purchase_orders po on po.id=gr.purchase_order_id
                        left join goods_receipt_items gri on gri.goods_receipt_id=gr.id
                        where upper(coalesce(po.site,''))=%s
                        group by gr.id,po.id
                        order by gr.received_at desc nulls last,gr.id desc
                        limit 8
                        """,
                        (db_site,),
                    )
                    for row in cur.fetchall():
                        issues = int(row["issue_item_count"] or 0)
                        source = str(row["source_type"] or "MANUAL").upper()
                        reporter = str(row["reporter"] or "-")
                        when = row["received_at"].isoformat() if row["received_at"] else "-"
                        out["lanes"]["receiving"].append({
                            "id": row["id"],
                            "title": f"{row['vendor_code']} · {row['po_code']}",
                            "subtitle": (
                                f"Terima {when} · {row['item_count']} item · "
                                f"accepted {float(row['accepted_qty_total'] or 0):g} · "
                                f"source {source} · pelapor {reporter}"
                            ),
                            "status": "ADA SELISIH" if issues else "TERCATAT",
                            "severity": "warning" if issues else "success",
                            "sourceType": source,
                            "sourceExternalId": row["source_external_id"],
                            "purchaseOrderId": row["purchase_order_id"],
                            "poStatus": row["po_status"],
                            "matchStatus": row["match_status"],
                            "matchConfidence": row["match_confidence"],
                        })

                    # The reminder engine is deliberately strict and can be empty
                    # when there is no active Kalkulator plan.  The tower still
                    # needs to show committed PO work already in the application.
                    if not out["lanes"]["procurement"]:
                        cur.execute(
                            """select po.id,po.po_code,po.vendor_code,po.status,po.sent_at,
                                      pc.distribution_date,count(poi.id) as item_count
                               from purchase_orders po
                               left join production_cycles pc on pc.id=po.production_cycle_id
                               left join purchase_order_items poi on poi.purchase_order_id=po.id
                               where upper(coalesce(po.site,''))=%s
                               group by po.id,pc.distribution_date
                               order by coalesce(pc.distribution_date,po.created_at::date) desc,po.id desc
                               limit 8""",
                            (db_site,),
                        )
                        for row in cur.fetchall():
                            status = str(row["status"] or "DRAFT").upper()
                            done = status in {"SENT", "ACKNOWLEDGED", "PARTIAL_RECEIVED", "RECEIVED", "CLOSED"}
                            out["lanes"]["procurement"].append({
                                "id": row["id"], "title": f"{row['vendor_code']} · {row['po_code']}",
                                "subtitle": f"{row['item_count']} item · distribusi {row['distribution_date'] or '-'}",
                                "status": status, "severity": "success" if done else "info",
                            })

                    cur.execute(
                        """select count(*) as n from vendor_invoices vi
                           where upper(coalesce(vi.site,''))=%s
                             and upper(coalesce(vi.payable_status,'UNPAID')) <> all(%s)
                             and vi.due_date is not null and vi.due_date<=%s""",
                        (db_site, list(DONE_PAYABLE), target_date),
                    )
                    out["summary"]["paymentsDue"] = int(cur.fetchone()["n"] or 0)

                    cur.execute(
                        """select vi.id,vi.vendor_code,vi.invoice_number,vi.net_amount,
                                  vi.payable_status,vi.due_date,po.po_code
                           from vendor_invoices vi
                           left join purchase_orders po on po.id=vi.purchase_order_id
                           where upper(coalesce(vi.site,''))=%s
                             and upper(coalesce(vi.payable_status,'UNPAID')) <> all(%s)
                           order by vi.due_date asc nulls last,vi.created_at desc
                           limit 8""",
                        (db_site, list(DONE_PAYABLE)),
                    )
                    for row in cur.fetchall():
                        due = row["due_date"]
                        is_due = due is not None and due <= target_date
                        due_text = due.isoformat() if due else "belum ada jatuh tempo"
                        out["lanes"]["payments"].append({
                            "id": row["id"],
                            "title": f"{row['vendor_code']} · {row['invoice_number'] or row['po_code'] or 'Invoice'}",
                            "subtitle": f"Net {_money(row['net_amount'])} · jatuh tempo {due_text}",
                            "status": "JATUH TEMPO" if is_due else str(row["payable_status"] or "UNPAID"),
                            "severity": "warning" if is_due else "info",
                        })

                    # Many existing payments were entered through the Finance
                    # screen/GPTS before a vendor payable existed. Show them here
                    # as a fallback instead of presenting a misleading empty lane.
                    if not out["lanes"]["payments"]:
                        cur.execute(
                            """select id,description,category,amount,payment_status,transaction_date
                               from finance_transactions
                               where upper(coalesce(site,''))=%s and transaction_type='expense'
                               order by transaction_date desc,id desc limit 8""",
                            (db_site,),
                        )
                        for row in cur.fetchall():
                            status = str(row["payment_status"] or "unpaid").upper()
                            out["lanes"]["payments"].append({
                                "id": f"finance-{row['id']}", "title": row["description"],
                                "subtitle": f"{row['category']} · {_money(row['amount'])} · {row['transaction_date']}",
                                "status": status, "severity": "success" if status == "PAID" else "warning",
                            })
                    _append_firestore_finance_fallback(out, db_site)

                    cur.execute(
                        """select i.id,i.invoice_number,i.invoice_amount,i.invoice_category,i.invoice_date,
                                  s.accountant_code,m.id as maker_id,m.status as maker_status,
                                  a.status as approval_status,
                                  exists(select 1 from bgn_receipts r where r.bgn_maker_id=m.id) as has_receipt
                           from accountant_invoices i
                           left join accountant_submissions s on s.id=i.accountant_submission_id
                           left join lateral (select x.* from bgn_makers x where x.accountant_invoice_id=i.id order by x.id desc limit 1) m on true
                           left join lateral (select x.* from bgn_approvals x where x.bgn_maker_id=m.id order by x.id desc limit 1) a on true
                           where upper(coalesce(i.site,s.site,''))=%s
                           order by i.invoice_date desc nulls last,i.id desc limit 8""",
                        (db_site,),
                    )
                    for row in cur.fetchall():
                        maker_status = str(row["maker_status"] or "").upper()
                        paid = bool(row["has_receipt"]) or maker_status == "PAID"
                        badge = "PAID" if paid else "PENDING APPROVAL" if row["maker_id"] else "BELUM MAKER"
                        out["lanes"]["accountant"].append({
                            "id": row["id"], "title": row["invoice_number"] or f"Invoice #{row['id']}",
                            "subtitle": f"{row['invoice_category'] or 'OPERASIONAL_LAIN'} · {_money(row['invoice_amount'])} · {row['invoice_date'] or '-'}",
                            "status": badge, "severity": "success" if paid else "warning" if row["maker_id"] else "info",
                        })

                    if not out["lanes"]["accountant"]:
                        cur.execute(
                            """select s.id,s.accountant_code,s.sent_at,s.status,pc.distribution_date
                               from accountant_submissions s left join production_cycles pc on pc.id=s.production_cycle_id
                               where upper(coalesce(s.site,''))=%s and not exists (select 1 from accountant_invoices i where i.accountant_submission_id=s.id)
                               order by s.created_at desc limit 8""", (db_site,))
                        for row in cur.fetchall():
                            out["lanes"]["accountant"].append({"id": row["id"], "title": f"{row['accountant_code']} · {row['distribution_date'] or '-'}", "subtitle": f"Excel/submission {row['status']} · invoice belum diterima", "status":"MENUNGGU INVOICE", "severity":"info"})

                    cur.execute(
                        """select m.id,m.reference_number,m.amount,m.status as maker_status,
                                  a.approver_code,a.status as approval_status,a.requested_at,a.approved_at,
                                  exists(select 1 from bgn_receipts r where r.bgn_maker_id=m.id) as has_receipt
                           from bgn_makers m
                           left join lateral (
                             select x.* from bgn_approvals x
                             where x.bgn_maker_id=m.id order by x.created_at desc limit 1
                           ) a on true
                           where upper(coalesce(m.site,''))=%s
                           order by m.created_at desc limit 8""",
                        (db_site,),
                    )
                    for row in cur.fetchall():
                        approval = str(row["approval_status"] or "BELUM DIMINTA")
                        has_receipt = bool(row["has_receipt"])
                        is_paid = has_receipt or str(row["maker_status"] or "").upper() == "PAID"
                        if is_paid:
                            badge, severity = "PAID", "success"
                        elif approval == "APPROVED":
                            badge, severity = "MENUNGGU DANA", "info"
                        elif approval == "REJECTED":
                            badge, severity = "DITOLAK", "warning"
                        else:
                            badge, severity = "PENDING APPROVAL", "warning"
                        out["lanes"]["bgn"].append({
                            "id": row["id"],
                            "title": row["reference_number"] or f"Maker #{row['id']}",
                            "subtitle": f"{_money(row['amount'])} · approver {row['approver_code'] or '-'} · {approval}",
                            "status": badge,
                            "severity": severity,
                        })

                    _append_accountant_flow_fallback(out, accountant_rows, db_site)
                    _append_bgn_flow_fallback(out, bgn_rows, db_site)

        return {
            "date": target_date.isoformat(),
            "databaseReady": True,
            "buildInfo": build_info,
            "sites": sites,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"control tower query failed: {type(exc).__name__}") from exc
