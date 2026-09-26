from __future__ import annotations

from datetime import date
from typing import Any

from backend.db import connection, database_ready
from google.api_core.exceptions import Conflict

from backend.google_services import firestore_transaction_doc

LEDGER_START_DATE = date(2026, 8, 24)

INCOME_CATEGORY_BY_INVOICE = {
    "SEWA_MITRA": "Pemasukan: Insentif Sewa",
    "BAHAN_BAKU": "Pemasukan: Dana Bahan Baku",
}


def _income_category(invoice_category: Any) -> str:
    return INCOME_CATEGORY_BY_INVOICE.get(
        str(invoice_category or "").upper().strip(),
        "Pemasukan: Dana Operasional",
    )


def sync_paid_makers_to_accountant_ledger(site: str | None = None, maker_ids: list[int] | None = None) -> dict[str, Any]:
    """Mirror paid Accountant -> Maker -> BGN invoices to the matching site ledger.

    The Firestore document id is derived from Maker id. Existing documents are
    skipped to preserve manual corrections in the accountant application.
    """
    if maker_ids is not None:
        maker_ids = sorted({int(value) for value in maker_ids if int(value) > 0})
        if not maker_ids:
            return {"site": site.upper() if site else None, "attempted": 0, "synced": 0, "failed": 0, "skipped": 0, "errors": []}
    if not database_ready():
        return {"attempted": 0, "synced": 0, "failed": 0, "skipped": 0, "errors": ["database unavailable"]}

    with connection() as conn:
        with conn.cursor() as cur:
            sql = """
                select m.id as maker_id,m.site,m.reference_number,m.amount as maker_amount,
                       i.id as invoice_id,i.invoice_number,i.invoice_category,i.invoice_amount,
                       i.accountant_submission_id,
                       coalesce(i.invoice_date,r.received_at::date,a.approved_at::date) as ledger_date,
                       coalesce(r.received_at,a.approved_at,now()) as paid_at,
                       a.evidence_uri
                from bgn_makers m
                join accountant_invoices i on i.id=m.accountant_invoice_id
                left join lateral (
                  select * from bgn_approvals x where x.bgn_maker_id=m.id
                  order by x.created_at desc,x.id desc limit 1
                ) a on true
                left join lateral (
                  select * from bgn_receipts x where x.bgn_maker_id=m.id
                  order by x.created_at desc,x.id desc limit 1
                ) r on true
                where upper(coalesce(m.status,''))='PAID'
                  and upper(coalesce(a.status,''))='APPROVED'
                  and coalesce(i.invoice_date,r.received_at::date,a.approved_at::date) >= %s
            """
            params: list[Any] = [LEDGER_START_DATE]
            if site:
                sql += " and upper(m.site)=upper(%s)"
                params.append(site)
            if maker_ids is not None:
                sql += " and m.id = any(%s)"
                params.append(maker_ids)
            sql += " order by coalesce(i.invoice_date,r.received_at::date,a.approved_at::date),m.id"
            cur.execute(sql, params)
            rows = [dict(row) for row in cur.fetchall()]

    summary: dict[str, Any] = {
        "site": site.upper() if site else None,
        "fromDate": LEDGER_START_DATE.isoformat(),
        "attempted": len(rows),
        "synced": 0,
        "failed": 0,
        "skipped": 0,
        "errors": [],
    }
    for row in rows:
        maker_id = int(row["maker_id"])
        target_site = str(row.get("site") or "").upper()
        if target_site not in {"MAJA", "CEMPLANG"} or not row.get("ledger_date"):
            summary["skipped"] += 1
            continue
        invoice_number = str(row.get("invoice_number") or row.get("reference_number") or f"Maker #{maker_id}")
        invoice_category = ("BAHAN_BAKU" if row.get("accountant_submission_id") is not None
                            else str(row.get("invoice_category") or "OPERASIONAL_LAIN").upper())
        amount = float(row.get("maker_amount") or row.get("invoice_amount") or 0)
        if amount <= 0:
            summary["skipped"] += 1
            continue
        transaction_id = f"bgn_maker_{maker_id}"
        payload = {
            "date": row["ledger_date"].isoformat(),
            "desc": f"BGN {invoice_category.replace('_', ' ')} · {invoice_number}",
            "amount": amount,
            "qty": 1,
            "unit": "invoice",
            "unitPrice": amount,
            "type": "income",
            "category": _income_category(invoice_category),
            "orderBy": "BGN",
            "isDebt": False,
            "paymentStatus": "paid",
            "paidAmount": amount,
            "paidDate": row["paid_at"].date().isoformat() if row.get("paid_at") else row["ledger_date"].isoformat(),
            "source": "accountant_bgn_paid",
            "sourceMakerId": maker_id,
            "sourceInvoiceId": int(row["invoice_id"]),
            "sourceInvoiceNumber": invoice_number,
            "sourceInvoiceCategory": invoice_category,
            "approvalEvidenceUri": row.get("evidence_uri") or "",
            "note": "Otomatis dari Invoice Akuntan → Maker → BGN setelah PAID.",
        }
        try:
            doc_ref = firestore_transaction_doc(target_site, transaction_id)
            doc_ref.create({**payload, "id": transaction_id})
            summary["synced"] += 1
        except Conflict:
            summary["skipped"] += 1
        except Exception as exc:
            summary["failed"] += 1
            if len(summary["errors"]) < 10:
                summary["errors"].append(f"Maker #{maker_id}: {type(exc).__name__}: {exc}"[:500])
    return summary
