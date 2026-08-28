"""Runtime fixes for finance sync and vendor payment ledger rows.

This patch is installed after the backend package has mounted its routers.

Why this exists:
- MAJA uses Firestore's default database. In the Railway production path the
  gRPC request can arrive with ``%28default%29`` interpreted as the database id.
  CEMPLANG uses a named database and is already healthy. MAJA finance writes
  therefore use Firestore REST while CEMPLANG keeps the existing SDK path.
- Older reconciled vendor invoices can lack persisted ``vendor_invoice_items``.
  Their payments must still be expanded from receiving/PO detail rather than
  falling back to one aggregate expense row.
- Vendor expense categories must match the accountant application's canonical
  category labels.
"""

from __future__ import annotations

import math
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from functools import lru_cache
from typing import Any
from urllib.parse import quote

from google.auth.transport.requests import AuthorizedSession

from backend import google_services


CANONICAL_VENDOR_EXPENSE_CATEGORIES = {
    "HOLIL": "Bahan Baku (Sayur/Buah)",
    "WIKIAN": "Bahan Baku (Lauk)",
    "RUMAH_DUTA_PANGAN": "Bahan Baku (Lauk)",
    "HAJI_BADRI": "Bahan Baku (Lauk)",
    "DEDE": "Bahan Baku (Sembako/Bumbu)",
    "KOPERASI": "Bahan Baku (Sembako/Bumbu)",
    "HERU": "Operasional (Utilitas)",
}

_original_upsert = google_services.upsert_finance_transaction
_original_update = google_services.update_existing_finance_transaction
_original_assert = google_services.assert_finance_transaction_exists


def _rest_value(value: Any) -> dict[str, Any]:
    if value is None:
        return {"nullValue": None}
    if isinstance(value, bool):
        return {"booleanValue": value}
    if isinstance(value, int) and not isinstance(value, bool):
        return {"integerValue": str(value)}
    if isinstance(value, (float, Decimal)):
        number = float(value)
        return {"doubleValue": number if math.isfinite(number) else 0.0}
    if isinstance(value, datetime):
        stamp = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return {"timestampValue": stamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")}
    if isinstance(value, date):
        return {"stringValue": value.isoformat()}
    if isinstance(value, dict):
        return {"mapValue": {"fields": {str(key): _rest_value(item) for key, item in value.items()}}}
    if isinstance(value, (list, tuple, set)):
        return {"arrayValue": {"values": [_rest_value(item) for item in value]}}
    return {"stringValue": str(value)}


@lru_cache(maxsize=1)
def _rest_session() -> AuthorizedSession:
    return AuthorizedSession(google_services.google_credentials())


def _maja_document_parts(transaction_id: str) -> tuple[str, str]:
    target = google_services.SITE_TARGETS["MAJA"]
    project = google_services.google_project_id()
    relative_path = f"gpt_sites/{target['site_id']}/ledger/meta/transactions/{transaction_id}"
    encoded_project = quote(str(project), safe="")
    encoded_path = quote(relative_path, safe="/")
    url = (
        "https://firestore.googleapis.com/v1/"
        f"projects/{encoded_project}/databases/(default)/documents/{encoded_path}"
    )
    return relative_path, url


def _raise_rest_error(response: Any, action: str) -> None:
    if response.ok:
        return
    detail = ""
    try:
        detail = str((response.json().get("error") or {}).get("message") or "")
    except Exception:
        detail = str(getattr(response, "text", "") or "")
    message = detail.strip() or f"HTTP {response.status_code}"
    raise RuntimeError(f"Firestore REST {action} failed: {response.status_code} {message}")


def _rest_request(method: str, url: str, **kwargs: Any) -> Any:
    session = _rest_session()
    last_response = None
    for attempt in range(3):
        response = session.request(method, url, timeout=30, **kwargs)
        last_response = response
        if response.ok or response.status_code not in {429, 500, 502, 503, 504}:
            return response
        time.sleep(0.35 * (attempt + 1))
    return last_response


def _rest_upsert_maja(transaction_id: str, data: dict[str, Any]) -> str:
    relative_path, url = _maja_document_parts(transaction_id)
    payload = dict(data)
    payload["id"] = transaction_id
    payload["updatedAt"] = datetime.now(timezone.utc)
    fields = {str(key): _rest_value(value) for key, value in payload.items()}
    params = [("updateMask.fieldPaths", key) for key in fields]
    response = _rest_request("PATCH", url, params=params, json={"fields": fields})
    _raise_rest_error(response, "upsert")
    return relative_path


def _rest_assert_maja(transaction_id: str) -> str:
    relative_path, url = _maja_document_parts(transaction_id)
    response = _rest_request("GET", url)
    if response.status_code == 404:
        raise google_services.FirestoreDocumentNotFound(
            f"finance transaction not found in MAJA: {transaction_id}"
        )
    _raise_rest_error(response, "read")
    return relative_path


def _rest_update_maja(transaction_id: str, data: dict[str, Any]) -> str:
    _rest_assert_maja(transaction_id)
    return _rest_upsert_maja(transaction_id, data)


def _upsert_finance_transaction(site: str, transaction_id: str, data: dict[str, Any]) -> str:
    if str(site or "").upper().strip() == "MAJA":
        return _rest_upsert_maja(transaction_id, data)
    return _original_upsert(site, transaction_id, data)


def _update_existing_finance_transaction(site: str, transaction_id: str, data: dict[str, Any]) -> str:
    if str(site or "").upper().strip() == "MAJA":
        return _rest_update_maja(transaction_id, data)
    return _original_update(site, transaction_id, data)


def _assert_finance_transaction_exists(site: str, transaction_id: str) -> str:
    if str(site or "").upper().strip() == "MAJA":
        return _rest_assert_maja(transaction_id)
    return _original_assert(site, transaction_id)


def _allocate_item_rows(rows: list[dict[str, Any]], payment_amount: float) -> list[dict[str, Any]]:
    usable = [dict(row) for row in rows if float(row.get("line_total") or 0) > 0]
    total = round(sum(float(row.get("line_total") or 0) for row in usable), 2)
    amount_total = round(float(payment_amount or 0), 2)
    if not usable or total <= 0 or amount_total <= 0:
        return []
    factor = min(1.0, round(amount_total / total, 10))
    allocated: list[dict[str, Any]] = []
    remaining = amount_total
    for index, row in enumerate(usable):
        if index < len(usable) - 1:
            amount = round(float(row.get("line_total") or 0) * factor, 2)
            amount = min(max(0.0, amount), remaining)
        else:
            amount = max(0.0, remaining)
        remaining = round(remaining - amount, 2)
        item_qty = float(row.get("payable_qty") or 0)
        allocated.append(
            {
                **row,
                "allocated_amount": amount,
                "allocated_qty": round(item_qty * factor, 4),
            }
        )
    return [row for row in allocated if float(row.get("allocated_amount") or 0) > 0]


def _legacy_invoice_item_rows(cur: Any, invoice: dict[str, Any], payment_amount: float) -> list[dict[str, Any]]:
    invoice_id = invoice.get("id")
    if not invoice_id:
        return []

    purchase_order_id = invoice.get("purchase_order_id")
    goods_receipt_id = invoice.get("goods_receipt_id")
    if purchase_order_id is None or goods_receipt_id is None:
        cur.execute(
            "select purchase_order_id,goods_receipt_id from vendor_invoices where id=%s",
            (invoice_id,),
        )
        refs = cur.fetchone()
        if refs:
            purchase_order_id = purchase_order_id or refs.get("purchase_order_id")
            goods_receipt_id = goods_receipt_id or refs.get("goods_receipt_id")

    rows: list[dict[str, Any]] = []
    if goods_receipt_id:
        cur.execute(
            """
            select gri.id as id,poi.item_code,poi.item_name,
                   coalesce(gri.accepted_qty,gri.received_qty,poi.po_qty,poi.planned_qty,0) as payable_qty,
                   coalesce(nullif(gri.unit,''),nullif(poi.unit,''),'item') as unit,
                   coalesce(nullif(poi.po_price,0),nullif(poi.planning_price,0),0) as vendor_cost_price,
                   coalesce(gri.accepted_qty,gri.received_qty,poi.po_qty,poi.planned_qty,0)
                     * coalesce(nullif(poi.po_price,0),nullif(poi.planning_price,0),0) as line_total
            from goods_receipt_items gri
            join purchase_order_items poi on poi.id=gri.purchase_order_item_id
            where gri.goods_receipt_id=%s
            order by gri.id
            """,
            (goods_receipt_id,),
        )
        rows = [dict(row) for row in cur.fetchall()]

    if not any(float(row.get("line_total") or 0) > 0 for row in rows) and purchase_order_id:
        cur.execute(
            """
            select poi.id as id,poi.item_code,poi.item_name,
                   coalesce(nullif(poi.po_qty,0),poi.planned_qty,0) as payable_qty,
                   coalesce(nullif(poi.unit,''),'item') as unit,
                   coalesce(nullif(poi.po_price,0),nullif(poi.planning_price,0),0) as vendor_cost_price,
                   coalesce(nullif(poi.po_qty,0),poi.planned_qty,0)
                     * coalesce(nullif(poi.po_price,0),nullif(poi.planning_price,0),0) as line_total
            from purchase_order_items poi
            where poi.purchase_order_id=%s
            order by poi.id
            """,
            (purchase_order_id,),
        )
        rows = [dict(row) for row in cur.fetchall()]

    return _allocate_item_rows(rows, payment_amount)


def install() -> None:
    """Install finance fixes once for the production process."""

    from backend import accountant_ledger_sync
    from backend import gpt_bridge_api
    from backend import vendor_payment_override_api
    from backend import vendor_workflow_api

    # MAJA writes use REST to avoid Railway/gRPC default-database corruption.
    google_services.upsert_finance_transaction = _upsert_finance_transaction
    google_services.update_existing_finance_transaction = _update_existing_finance_transaction
    google_services.assert_finance_transaction_exists = _assert_finance_transaction_exists

    # Modules imported the functions directly, so replace those bound globals too.
    accountant_ledger_sync.upsert_finance_transaction = _upsert_finance_transaction
    gpt_bridge_api.upsert_finance_transaction = _upsert_finance_transaction
    gpt_bridge_api.update_existing_finance_transaction = _update_existing_finance_transaction
    gpt_bridge_api.assert_finance_transaction_exists = _assert_finance_transaction_exists

    # Canonical categories must match the accountant dropdown exactly.
    vendor_workflow_api.VENDOR_EXPENSE_CATEGORIES.update(CANONICAL_VENDOR_EXPENSE_CATEGORIES)
    vendor_payment_override_api.VENDOR_EXPENSE_CATEGORIES.update(CANONICAL_VENDOR_EXPENSE_CATEGORIES)

    original_invoice_payment_items = vendor_payment_override_api._invoice_payment_items
    if not getattr(original_invoice_payment_items, "_sppg_legacy_fallback", False):

        def invoice_payment_items_with_fallback(
            cur: Any,
            invoice: dict[str, Any] | None,
            payment_amount: float,
        ) -> list[dict[str, Any]]:
            rows = original_invoice_payment_items(cur, invoice, payment_amount)
            if rows or not invoice:
                return rows
            return _legacy_invoice_item_rows(cur, dict(invoice), payment_amount)

        invoice_payment_items_with_fallback._sppg_legacy_fallback = True  # type: ignore[attr-defined]
        vendor_payment_override_api._invoice_payment_items = invoice_payment_items_with_fallback
