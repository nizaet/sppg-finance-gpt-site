from datetime import date

import pytest

from backend.purchase_order_workflow_api import (
    format_purchase_order_whatsapp,
    normalize_whatsapp_phone,
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
