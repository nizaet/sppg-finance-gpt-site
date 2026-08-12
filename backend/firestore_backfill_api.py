from __future__ import annotations

import hashlib
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.db import connection, database_ready
from backend.google_services import SITE_TARGETS, firestore_client
from backend.gpt_bridge_api import require_gpt_auth

router = APIRouter(prefix="/v1/gpt", tags=["gpt-backfill"])


class FirestoreBackfillIn(BaseModel):
    site: Literal["MAJA", "CEMPLANG"]
    dry_run: bool = True
    limit: int = Field(default=10000, ge=1, le=50000)
    actor: str = "chatgpt"


def _parse_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _number(value: Any, default: Decimal | None = None) -> Decimal | None:
    if value is None or value == "":
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default


def _normalize_type(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if text in {"income", "pemasukan", "masuk"}:
        return "income"
    if text in {"expense", "pengeluaran", "keluar"}:
        return "expense"
    return None


def _normalize_payment(tx_type: str, amount: Decimal, data: dict[str, Any]) -> tuple[bool, str, Decimal, date | None]:
    if tx_type == "income":
        return False, "paid", amount, _parse_date(data.get("paidDate"))

    status = str(data.get("paymentStatus") or "").strip().lower()
    is_debt = bool(data.get("isDebt", False))
    paid_amount = _number(data.get("paidAmount"), Decimal("0")) or Decimal("0")
    paid_date = _parse_date(data.get("paidDate"))

    if status == "partial" or (is_debt and Decimal("0") < paid_amount < amount):
        return True, "partial", min(amount, max(Decimal("0"), paid_amount)), paid_date
    if status in {"unpaid", "hutang"} or is_debt:
        return True, "unpaid", Decimal("0"), None
    return False, "paid", amount, paid_date


def _collection(site: str):
    target = SITE_TARGETS[site]
    client = firestore_client(target["database_id"])
    return (
        client.collection("gpt_sites")
        .document(target["site_id"])
        .collection("ledger")
        .document("meta")
        .collection("transactions")
    )


def _target_transaction_id(site: str, firestore_id: str) -> str:
    if firestore_id.startswith("gpt_"):
        return firestore_id
    digest = hashlib.sha256(firestore_id.encode("utf-8")).hexdigest()[:8]
    clean = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in firestore_id)[:72]
    return f"fs_{site.lower()}_{clean}_{digest}"


def _idempotency_key(site: str, firestore_id: str) -> str:
    return f"firestore:{site.lower()}:{hashlib.sha256(firestore_id.encode('utf-8')).hexdigest()}"


def _prepare(site: str, firestore_id: str, data: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    tx_date = _parse_date(data.get("date"))
    tx_type = _normalize_type(data.get("type"))
    amount = _number(data.get("amount"))
    description = str(data.get("desc") or data.get("description") or "").strip()
    category = str(data.get("category") or "").strip()

    if not tx_date:
        return None, "invalid or missing date"
    if tx_type is None:
        return None, "invalid or missing type"
    if amount is None or amount < 0:
        return None, "invalid or missing amount"
    if not description:
        return None, "missing description"
    if not category:
        return None, "missing category"

    is_debt, payment_status, paid_amount, paid_date = _normalize_payment(tx_type, amount, data)
    return {
        "transaction_id": _target_transaction_id(site, firestore_id),
        "idempotency_key": _idempotency_key(site, firestore_id),
        "site": site,
        "transaction_date": tx_date,
        "description": description,
        "transaction_type": tx_type,
        "category": category,
        "amount": amount,
        "qty": _number(data.get("qty")),
        "unit": str(data.get("unit") or "") or None,
        "unit_price": _number(data.get("unitPrice")),
        "order_by": str(data.get("orderBy") or "") or None,
        "is_debt": is_debt,
        "payment_status": payment_status,
        "paid_amount": paid_amount,
        "paid_date": paid_date,
        "source_ref": f"firestore:{site}:{firestore_id}",
        "classification_confidence": _number(data.get("classificationConfidence")),
        "classification_reason": str(data.get("classificationReason") or ""),
        "note": str(data.get("note") or ""),
        "firestore_doc_id": firestore_id,
    }, None


@router.post("/backfill-firestore", dependencies=[Depends(require_gpt_auth)])
def backfill_firestore(payload: FirestoreBackfillIn) -> dict[str, Any]:
    if not database_ready():
        raise HTTPException(503, "database unavailable")

    docs = list(_collection(payload.site).limit(payload.limit).stream())
    summary = {
        "site": payload.site,
        "dryRun": payload.dry_run,
        "firestoreRead": len(docs),
        "importable": 0,
        "alreadyPresent": 0,
        "inserted": 0,
        "invalid": 0,
        "errors": [],
        "sample": [],
    }

    with connection() as conn:
        with conn.cursor() as cur:
            for snap in docs:
                data = snap.to_dict() or {}
                row, error = _prepare(payload.site, snap.id, data)
                if error or row is None:
                    summary["invalid"] += 1
                    if len(summary["errors"]) < 20:
                        summary["errors"].append({"firestoreId": snap.id, "reason": error})
                    continue

                cur.execute(
                    "select transaction_id from finance_transactions where transaction_id=%s or idempotency_key=%s limit 1",
                    (row["transaction_id"], row["idempotency_key"]),
                )
                existing = cur.fetchone()
                if existing:
                    summary["alreadyPresent"] += 1
                    continue

                summary["importable"] += 1
                if len(summary["sample"]) < 10:
                    summary["sample"].append({
                        "firestoreId": snap.id,
                        "date": row["transaction_date"].isoformat(),
                        "description": row["description"],
                        "category": row["category"],
                        "amount": float(row["amount"]),
                    })

                if payload.dry_run:
                    continue

                cur.execute(
                    """insert into finance_transactions(
                         transaction_id,idempotency_key,site,transaction_date,description,transaction_type,
                         category,amount,qty,unit,unit_price,order_by,is_debt,payment_status,paid_amount,
                         paid_date,source,source_ref,classification_confidence,classification_reason,note,
                         firestore_doc_id,firestore_sync_status
                       ) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                                 'firestore_backfill',%s,%s,%s,%s,%s,%s,'SOURCE_IMPORTED')
                       on conflict do nothing
                       returning transaction_id""",
                    (
                        row["transaction_id"], row["idempotency_key"], row["site"], row["transaction_date"],
                        row["description"], row["transaction_type"], row["category"], row["amount"], row["qty"],
                        row["unit"], row["unit_price"], row["order_by"], row["is_debt"], row["payment_status"],
                        row["paid_amount"], row["paid_date"], row["source_ref"], row["classification_confidence"],
                        row["classification_reason"], row["note"], row["firestore_doc_id"],
                    ),
                )
                inserted = cur.fetchone()
                if inserted:
                    summary["inserted"] += 1
                    cur.execute(
                        """insert into finance_bridge_audit_log(transaction_id,action,actor,details)
                           values (%s,'FIRESTORE_BACKFILL',%s,jsonb_build_object('firestore_doc_id',%s,'site',%s))""",
                        (inserted["transaction_id"], payload.actor, snap.id, payload.site),
                    )

        if payload.dry_run:
            conn.rollback()
        else:
            conn.commit()

    return summary
