from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from backend.db import connection, database_ready

router = APIRouter(tags=["control-tower"])

SITE_DEFS = [
    {"siteId": "sppg-maja-gpt-site", "siteLabel": "SPPG MAJA BARU", "dbSite": "MAJA"},
    {"siteId": "sppg-cemplang2-gpt-site", "siteLabel": "SPPG CEMPLANG 2", "dbSite": "CEMPLANG"},
]

DONE_PO = ("RECEIVED", "CANCELLED", "CANCELED", "SUPERSEDED", "CLOSED")
DONE_PAYABLE = ("PAID", "RECONCILED", "CLOSED", "CANCELLED", "CANCELED")


def empty_site(site: dict[str, str]) -> dict[str, Any]:
    return {
        "siteId": site["siteId"],
        "siteLabel": site["siteLabel"],
        "summary": {
            "poDueToday": 0,
            "poOverdue": 0,
            "paymentsDue": 0,
            "reviewQueue": 0,
        },
        "lanes": {
            "procurement": [],
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


@router.get("/control-tower-v2")
def control_tower_v2(
    target_date: date = Query(alias="date"),
    site: str = "",
) -> dict[str, Any]:
    """Read-only operational control tower built from committed domain state.

    Metrics intentionally use actual PO/payable/accountant/BGN records. Planning
    estimates are not rewritten or inferred here, and historical-import POs do
    not become permanent overdue work items. The optional site filter is used by
    MAJA/CEMPLANG role sessions so the UI does not request the other site's data.
    """
    definitions = _site_defs(site)
    sites = [empty_site(x) for x in definitions]
    if not database_ready():
        return {"date": target_date.isoformat(), "databaseReady": False, "sites": sites}

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

                    cur.execute(
                        """select
                               count(*) filter (where pc.distribution_date=%s) as due_today,
                               count(*) filter (where pc.distribution_date<%s) as overdue
                           from purchase_orders po
                           join production_cycles pc on pc.id=po.production_cycle_id
                           where upper(coalesce(po.site,''))=%s
                             and coalesce(po.historical_import,false)=false
                             and upper(coalesce(po.status,'')) <> all(%s)""",
                        (target_date, target_date, db_site, list(DONE_PO)),
                    )
                    po_counts = cur.fetchone()
                    out["summary"]["poDueToday"] = int(po_counts["due_today"] or 0)
                    out["summary"]["poOverdue"] = int(po_counts["overdue"] or 0)

                    cur.execute(
                        """select po.id,po.po_code,po.vendor_code,po.status,pc.distribution_date
                           from purchase_orders po
                           join production_cycles pc on pc.id=po.production_cycle_id
                           where upper(coalesce(po.site,''))=%s
                             and coalesce(po.historical_import,false)=false
                             and pc.distribution_date<=%s
                             and upper(coalesce(po.status,'')) <> all(%s)
                           order by (pc.distribution_date<%s) desc,pc.distribution_date,po.created_at desc
                           limit 8""",
                        (db_site, target_date, list(DONE_PO), target_date),
                    )
                    for row in cur.fetchall():
                        overdue = row["distribution_date"] < target_date
                        out["lanes"]["procurement"].append({
                            "id": row["id"],
                            "title": f"{row['vendor_code']} · {row['po_code']}",
                            "subtitle": f"Distribusi {row['distribution_date'].isoformat()} · status {row['status']}",
                            "status": "TERLAMBAT" if overdue else "HARI INI",
                            "severity": "warning" if overdue else "info",
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

                    cur.execute(
                        """select s.id,s.accountant_code,s.sent_at,s.status,pc.distribution_date
                           from accountant_submissions s
                           left join production_cycles pc on pc.id=s.production_cycle_id
                           where upper(coalesce(s.site,''))=%s
                             and not exists (
                               select 1 from accountant_invoices i where i.accountant_submission_id=s.id
                             )
                           order by s.created_at desc limit 8""",
                        (db_site,),
                    )
                    for row in cur.fetchall():
                        cycle = row["distribution_date"].isoformat() if row["distribution_date"] else "tanpa cycle"
                        out["lanes"]["accountant"].append({
                            "id": row["id"],
                            "title": f"{row['accountant_code']} · {cycle}",
                            "subtitle": f"Excel/submission {row['status']} · invoice belum diterima",
                            "status": "MENUNGGU INVOICE",
                            "severity": "info",
                        })

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
                             and (coalesce(upper(a.status),'PENDING') <> 'APPROVED'
                                  or not exists(select 1 from bgn_receipts r where r.bgn_maker_id=m.id))
                           order by m.created_at desc limit 8""",
                        (db_site,),
                    )
                    for row in cur.fetchall():
                        approval = str(row["approval_status"] or "BELUM DIMINTA")
                        has_receipt = bool(row["has_receipt"])
                        if approval == "APPROVED" and not has_receipt:
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

        return {"date": target_date.isoformat(), "databaseReady": True, "sites": sites}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"control tower query failed: {type(exc).__name__}") from exc
