from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from datetime import date as DateType, datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from backend.db import connection, database_ready
from backend.google_services import (
    FirestoreDocumentNotFound,
    GoogleServicesNotConfigured,
    assert_finance_transaction_exists,
    update_existing_finance_transaction,
    upsert_finance_transaction,
    upload_text_to_drive,
)

router = APIRouter(prefix="/v1/gpt", tags=["gpt-bridge"])
bearer = HTTPBearer(auto_error=False)


class FinanceTransactionItemIn(BaseModel):
    transaction_id: str | None = None
    date: DateType
    description: str = Field(min_length=1)
    type: Literal["income", "expense"]
    category: str = Field(min_length=1)
    amount: float = Field(ge=0)
    qty: float | None = None
    unit: str | None = None
    unit_price: float | None = Field(default=None, ge=0)
    order_by: str | None = None
    is_debt: bool = False
    payment_status: Literal["paid", "unpaid", "partial"] = "paid"
    paid_amount: float | None = Field(default=None, ge=0)
    paid_date: DateType | None = None
    classification_confidence: float = Field(default=1.0, ge=0, le=1)
    classification_reason: str = ""
    note: str = ""


class FinanceTransactionBatchIn(BaseModel):
    site: Literal["MAJA", "CEMPLANG"]
    source_ref: str = Field(min_length=1, max_length=240)
    raw_text: str = ""
    actor: str = "chatgpt"
    archive_raw_text: bool = True
    items: list[FinanceTransactionItemIn] = Field(min_length=1, max_length=100)


class FinanceTransactionPatchIn(BaseModel):
    date: DateType | None = None
    description: str | None = None
    category: str | None = None
    amount: float | None = Field(default=None, ge=0)
    qty: float | None = None
    unit: str | None = None
    unit_price: float | None = Field(default=None, ge=0)
    order_by: str | None = None
    is_debt: bool | None = None
    payment_status: Literal["paid", "unpaid", "partial"] | None = None
    paid_amount: float | None = Field(default=None, ge=0)
    paid_date: DateType | None = None
    category_override_reason: str | None = None
    note: str | None = None
    actor: str = "chatgpt"


def require_gpt_auth(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> None:
    expected = os.getenv("SPPG_GPT_API_KEY", "").strip()
    if not expected:
        raise HTTPException(503, "SPPG_GPT_API_KEY is not configured")
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(401, "Bearer token required")
    if not hmac.compare_digest(credentials.credentials, expected):
        raise HTTPException(403, "Invalid API key")


def _clean_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip())
    return cleaned[:120] or "tx"


def _normalized_payment(item: FinanceTransactionItemIn | dict[str, Any]) -> tuple[bool, str, float, DateType | None]:
    getter = item.get if isinstance(item, dict) else lambda key, default=None: getattr(item, key, default)
    tx_type = str(getter("type") if not isinstance(item, dict) else getter("transaction_type", getter("type"))).lower()
    amount = float(getter("amount", 0) or 0)
    status = str(getter("payment_status", "paid") or "paid").lower()
    is_debt = bool(getter("is_debt", False))
    paid_amount_raw = getter("paid_amount", None)
    paid_date = getter("paid_date", None)

    if tx_type == "income":
        return False, "paid", amount, paid_date

    if status == "paid" and not is_debt:
        return False, "paid", amount, paid_date
    if status == "partial":
        paid_amount = min(amount, max(0.0, float(paid_amount_raw or 0)))
        if paid_amount >= amount:
            return False, "paid", amount, paid_date
        return True, "partial", paid_amount, paid_date
    return True, "unpaid", 0.0, None


def _idempotency_key(site: str, source_ref: str, index: int, item: FinanceTransactionItemIn) -> str:
    canonical = {
        "site": site,
        "source_ref": source_ref,
        "index": index,
        "date": item.date.isoformat(),
        "description": item.description.strip(),
        "type": item.type,
        "category": item.category.strip(),
        "amount": round(float(item.amount), 2),
        "qty": item.qty,
        "unit": item.unit,
        "unit_price": item.unit_price,
        "order_by": item.order_by,
    }
    raw = json.dumps(canonical, sort_keys=True, ensure_ascii=False)
    return "fin:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _transaction_id(site: str, item: FinanceTransactionItemIn, idem: str) -> str:
    if item.transaction_id:
        return _clean_id(item.transaction_id)
    return f"gpt_{site.lower()}_{idem.split(':', 1)[1][:24]}"


def _firestore_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "date": row["transaction_date"].isoformat() if hasattr(row["transaction_date"], "isoformat") else str(row["transaction_date"]),
        "desc": row["description"],
        "type": row["transaction_type"],
        "category": row["category"],
        "amount": float(row["amount"] or 0),
        "qty": float(row["qty"]) if row.get("qty") is not None else 0,
        "unit": row.get("unit") or "",
        "unitPrice": float(row["unit_price"]) if row.get("unit_price") is not None else 0,
        "orderBy": row.get("order_by") or "-",
        "isDebt": bool(row.get("is_debt")),
        "paymentStatus": row.get("payment_status") or "paid",
        "paidAmount": float(row.get("paid_amount") or 0),
        "paidDate": row["paid_date"].isoformat() if row.get("paid_date") else "",
        "source": row.get("source") or "chatgpt_bridge",
        "classificationConfidence": float(row.get("classification_confidence") or 0),
        "classificationReason": row.get("classification_reason") or "",
        "note": row.get("note") or "",
        "createdAtClient": row["created_at"].isoformat() if row.get("created_at") else datetime.now(timezone.utc).isoformat(),
    }


def _fetch_tx(transaction_id: str) -> dict[str, Any] | None:
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("select * from finance_transactions where transaction_id=%s", (transaction_id,))
            return cur.fetchone()


def _firestore_target(row: dict[str, Any]) -> tuple[str, bool]:
    if str(row.get("source") or "") == "firestore_backfill":
        original_id = str(row.get("firestore_doc_id") or "").strip()
        if not original_id:
            raise FirestoreDocumentNotFound(
                f"Backfilled transaction {row.get('transaction_id')} has no original firestore_doc_id"
            )
        return original_id, True
    return str(row["transaction_id"]), False


def _sync_row(row: dict[str, Any]) -> tuple[str, str | None, str | None, str | None]:
    try:
        target_id, must_exist = _firestore_target(row)
        if must_exist:
            path = update_existing_finance_transaction(row["site"], target_id, _firestore_payload(row))
        else:
            path = upsert_finance_transaction(row["site"], target_id, _firestore_payload(row))
        return "SYNCED", path, target_id, None
    except GoogleServicesNotConfigured as exc:
        return "NOT_CONFIGURED", None, None, str(exc)
    except Exception as exc:
        return "ERROR", None, None, f"{type(exc).__name__}: {exc}"[:1500]


def _update_sync_status(transaction_id: str, status: str, doc_id: str | None, error: str | None, evidence_uri: str | None = None) -> None:
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """update finance_transactions
                   set firestore_sync_status=%s,
                       firestore_doc_id=coalesce(%s, firestore_doc_id),
                       firestore_sync_error=%s,
                       evidence_uri=coalesce(%s, evidence_uri),
                       updated_at=now()
                   where transaction_id=%s""",
                (status, doc_id, error, evidence_uri, transaction_id),
            )
        conn.commit()


def _archive_batch(payload: FinanceTransactionBatchIn) -> tuple[str | None, str | None]:
    if not payload.archive_raw_text or not payload.raw_text.strip():
        return None, None
    folder_id = os.getenv("SPPG_DRIVE_RAW_CHAT_FOLDER_ID", "").strip()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = hashlib.sha256(payload.source_ref.encode("utf-8")).hexdigest()[:10]
    filename = f"{stamp}_{payload.site}_{suffix}.txt"
    body = (
        payload.raw_text.rstrip()
        + "\n\n--- PARSED TRANSACTIONS ---\n"
        + json.dumps(payload.model_dump(mode="json", exclude={"raw_text"}), ensure_ascii=False, indent=2)
    )
    try:
        return upload_text_to_drive(folder_id, filename, body), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"[:1500]


@router.get("/status", dependencies=[Depends(require_gpt_auth)])
def gpt_bridge_status() -> dict[str, Any]:
    return {
        "databaseReady": database_ready(),
        "googleCredentialsConfigured": bool(os.getenv("SPPG_GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()),
        "rawChatFolderConfigured": bool(os.getenv("SPPG_DRIVE_RAW_CHAT_FOLDER_ID", "").strip()),
        "firestoreProject": os.getenv("SPPG_FIRESTORE_PROJECT_ID", "sppg-finance-gpt"),
    }


@router.post("/finance-transactions", dependencies=[Depends(require_gpt_auth)])
def create_finance_transactions(payload: FinanceTransactionBatchIn) -> dict[str, Any]:
    if not database_ready():
        raise HTTPException(503, "DATABASE_URL is not configured or database is unavailable")

    evidence_uri, archive_error = _archive_batch(payload)
    results: list[dict[str, Any]] = []

    for index, item in enumerate(payload.items):
        idem = _idempotency_key(payload.site, payload.source_ref, index, item)
        transaction_id = _transaction_id(payload.site, item, idem)
        is_debt, payment_status, paid_amount, paid_date = _normalized_payment(item)

        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """insert into finance_transactions(
                         transaction_id,idempotency_key,site,transaction_date,description,transaction_type,
                         category,amount,qty,unit,unit_price,order_by,is_debt,payment_status,paid_amount,
                         paid_date,source,source_ref,raw_text,classification_confidence,
                         classification_reason,note,evidence_uri
                       ) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                                 'chatgpt_bridge',%s,%s,%s,%s,%s,%s)
                       on conflict (idempotency_key) do nothing
                       returning transaction_id""",
                    (
                        transaction_id, idem, payload.site, item.date, item.description.strip(), item.type,
                        item.category.strip(), item.amount, item.qty, item.unit, item.unit_price, item.order_by,
                        is_debt, payment_status, paid_amount, paid_date, payload.source_ref, payload.raw_text,
                        item.classification_confidence, item.classification_reason, item.note, evidence_uri,
                    ),
                )
                inserted = cur.fetchone()
                cur.execute("select * from finance_transactions where idempotency_key=%s", (idem,))
                row = cur.fetchone()
                if not row:
                    raise HTTPException(500, "finance transaction was not persisted")
                cur.execute(
                    """insert into finance_bridge_audit_log(transaction_id,action,actor,details)
                       values (%s,%s,%s,%s::jsonb)""",
                    (
                        row["transaction_id"],
                        "CREATE" if inserted else "IDEMPOTENT_REPLAY",
                        payload.actor,
                        json.dumps({"source_ref": payload.source_ref, "category": row["category"]}, ensure_ascii=False),
                    ),
                )
            conn.commit()

        sync_status, firestore_path, firestore_doc_id, sync_error = _sync_row(row)
        _update_sync_status(row["transaction_id"], sync_status, firestore_doc_id, sync_error, evidence_uri)
        results.append({
            "transactionId": row["transaction_id"],
            "inserted": bool(inserted),
            "firestoreSyncStatus": sync_status,
            "firestoreDocument": firestore_path,
            "syncError": sync_error,
        })

    return {
        "site": payload.site,
        "sourceRef": payload.source_ref,
        "evidenceUri": evidence_uri,
        "archiveError": archive_error,
        "count": len(results),
        "items": results,
    }


@router.get("/finance-transactions", dependencies=[Depends(require_gpt_auth)])
def list_finance_transactions(
    site: Literal["MAJA", "CEMPLANG"] | None = None,
    date_from: DateType | None = Query(default=None, alias="from"),
    date_to: DateType | None = Query(default=None, alias="to"),
    payment_status: Literal["paid", "unpaid", "partial"] | None = None,
    q: str = "",
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    if not database_ready():
        raise HTTPException(503, "database unavailable")
    sql = "select * from finance_transactions where true"
    params: list[Any] = []
    if site:
        sql += " and site=%s"
        params.append(site)
    if date_from:
        sql += " and transaction_date >= %s"
        params.append(date_from)
    if date_to:
        sql += " and transaction_date <= %s"
        params.append(date_to)
    if payment_status:
        sql += " and payment_status=%s"
        params.append(payment_status)
    if q.strip():
        sql += " and (description ilike %s or category ilike %s or coalesce(order_by,'') ilike %s or transaction_id ilike %s)"
        needle = f"%{q.strip()}%"
        params.extend([needle, needle, needle, needle])
    sql += " order by transaction_date desc, id desc limit %s"
    params.append(limit)
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    return {"items": rows}


@router.patch("/finance-transactions/{transaction_id}", dependencies=[Depends(require_gpt_auth)])
def patch_finance_transaction(transaction_id: str, payload: FinanceTransactionPatchIn) -> dict[str, Any]:
    if not database_ready():
        raise HTTPException(503, "database unavailable")
    existing = _fetch_tx(transaction_id)
    if not existing:
        raise HTTPException(404, "transaction not found")

    patch = payload.model_dump(exclude_unset=True)
    patch.pop("actor", None)
    if not patch:
        return {"transactionId": transaction_id, "changed": False}

    if str(existing.get("source") or "") == "firestore_backfill":
        original_id = str(existing.get("firestore_doc_id") or "").strip()
        if not original_id:
            raise HTTPException(409, "Backfilled transaction is missing original firestore_doc_id; no changes were made")
        try:
            assert_finance_transaction_exists(existing["site"], original_id)
        except FirestoreDocumentNotFound as exc:
            raise HTTPException(409, f"Original Firestore document not found; no changes were made: {exc}") from exc
        except GoogleServicesNotConfigured as exc:
            raise HTTPException(503, f"Firestore verification unavailable; no changes were made: {exc}") from exc

    allowed_map = {
        "date": "transaction_date",
        "description": "description",
        "category": "category",
        "amount": "amount",
        "qty": "qty",
        "unit": "unit",
        "unit_price": "unit_price",
        "order_by": "order_by",
        "is_debt": "is_debt",
        "payment_status": "payment_status",
        "paid_amount": "paid_amount",
        "paid_date": "paid_date",
        "note": "note",
    }

    merged = dict(existing)
    for api_key, column in allowed_map.items():
        if api_key in patch:
            merged[column] = patch[api_key]

    debt_input = {
        "transaction_type": merged["transaction_type"],
        "amount": merged["amount"],
        "is_debt": merged["is_debt"],
        "payment_status": merged["payment_status"],
        "paid_amount": merged["paid_amount"],
        "paid_date": merged["paid_date"],
    }
    is_debt, payment_status, paid_amount, paid_date = _normalized_payment(debt_input)
    merged.update({
        "is_debt": is_debt,
        "payment_status": payment_status,
        "paid_amount": paid_amount,
        "paid_date": paid_date,
    })

    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """update finance_transactions set
                     transaction_date=%s, description=%s, category=%s, amount=%s, qty=%s, unit=%s,
                     unit_price=%s, order_by=%s, is_debt=%s, payment_status=%s, paid_amount=%s,
                     paid_date=%s, note=%s, updated_at=now()
                   where transaction_id=%s returning *""",
                (
                    merged["transaction_date"], merged["description"], merged["category"], merged["amount"],
                    merged["qty"], merged["unit"], merged["unit_price"], merged["order_by"], merged["is_debt"],
                    merged["payment_status"], merged["paid_amount"], merged["paid_date"], merged["note"],
                    transaction_id,
                ),
            )
            row = cur.fetchone()
            cur.execute(
                """insert into finance_bridge_audit_log(transaction_id,action,actor,details)
                   values (%s,'PATCH',%s,%s::jsonb)""",
                (
                    transaction_id,
                    payload.actor,
                    json.dumps({"fields": sorted(patch.keys()), "category_override_reason": payload.category_override_reason}, ensure_ascii=False),
                ),
            )
        conn.commit()

    sync_status, firestore_path, firestore_doc_id, sync_error = _sync_row(row)
    _update_sync_status(transaction_id, sync_status, firestore_doc_id, sync_error)
    return {
        "transactionId": transaction_id,
        "changed": True,
        "firestoreSyncStatus": sync_status,
        "firestoreDocument": firestore_path,
        "syncError": sync_error,
    }
