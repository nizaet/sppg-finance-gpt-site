from datetime import date
from pathlib import Path

import pytest

from backend.purchase_order_workflow_api import (
    format_purchase_order_whatsapp,
    normalize_whatsapp_phone,
    router,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0812-3456-7890", "6281234567890"),
        ("+62 812 3456 7890", "6281234567890"),
        ("81234567890", "6281234567890"),
    ],
)
def test_normalize_whatsapp_phone(raw, expected):
    assert normalize_whatsapp_phone(raw) == expected


def test_normalize_whatsapp_phone_rejects_missing_or_short_number():
    with pytest.raises(ValueError):
        normalize_whatsapp_phone("123")


def test_purchase_order_whatsapp_message_is_canonical_and_uses_po_qty():
    po = {
        "site": "MAJA",
        "po_code": "PO-MAJA-20260817-HOLIL",
        "revision_no": 2,
        "distribution_date": date(2026, 8, 17),
        "items": [
            {"item_name": "Bawang Merah", "planned_qty": 20, "po_qty": 12.5, "unit": "kg"},
            {"item_name": "Wortel", "planned_qty": 10, "po_qty": 0, "unit": "kg"},
        ],
    }

    message = format_purchase_order_whatsapp(po, "Haji Holil")

    assert "🛒 *PO SPPG MAJA*" in message
    assert "👤 *Vendor:* Haji Holil" in message
    assert "Senin, 17 Agustus 2026" in message
    assert "PO-MAJA-20260817-HOLIL / Rev 2" in message
    assert "12,5 kg" in message
    assert "Wortel" not in message
    assert "planned_qty" not in message


def test_purchase_order_whatsapp_message_explains_multi_day_coverage():
    po = {
        "site": "MAJA",
        "po_code": "PO-MAJA-20260818-20260819-WIKIAN",
        "revision_no": 1,
        "distribution_date": date(2026, 8, 18),
        "coverage_dates": [date(2026, 8, 18), date(2026, 8, 19)],
        "items": [
            {"item_name": "Ayam Fillet", "po_qty": 60, "unit": "kg"},
            {"item_name": "Ayam Potong", "po_qty": 100, "unit": "kg"},
        ],
    }

    message = format_purchase_order_whatsapp(po, "Wikian")

    assert "Selasa, 18 Agustus 2026 s.d. Rabu, 19 Agustus 2026" in message
    assert "Cakupan:* 2 hari distribusi" in message
    assert "DAFTAR PESANAN GABUNGAN" in message
    assert "60 kg" in message
    assert "100 kg" in message


def test_purchase_order_routes_support_edit_delete_revision_and_cancel():
    methods_by_path = {}
    for route in router.routes:
        methods_by_path.setdefault(route.path, set()).update(route.methods or [])
    assert "PATCH" in methods_by_path["/purchase-orders/{purchase_order_id}"]
    assert "DELETE" in methods_by_path["/purchase-orders/{purchase_order_id}"]
    assert "POST" in methods_by_path["/purchase-orders/{purchase_order_id}/revise"]
    assert "POST" in methods_by_path["/purchase-orders/{purchase_order_id}/cancel"]


def test_purchase_order_coverage_migration_preserves_daily_breakdown():
    sql = (Path(__file__).parents[1] / "schema" / "purchase_order_coverage_v024.sql").read_text()
    assert "create table if not exists purchase_order_coverage" in sql
    assert "unique(purchase_order_id, distribution_date)" in sql
    assert "create table if not exists purchase_order_coverage_items" in sql
