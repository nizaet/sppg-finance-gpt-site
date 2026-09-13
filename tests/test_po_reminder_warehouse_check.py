from datetime import date
import unittest
from unittest.mock import patch

from backend.po_reminder_warehouse_check import apply_warehouse_stock_check


def reminder_with_detail(*, projected=5, remaining=5, item_name="Bawang Bombay"):
    return {
        "items": [{
            "site": "CEMPLANG",
            "reminder_status": "DUE_TODAY",
            "requirement_details": [{
                "distribution_date": date(2026, 9, 12),
                "item_names": [item_name],
                "stock_type_code": "BAWANG_BOMBAY",
                "unit": "kg",
                "planned_qty": 10,
                "projected_stock_qty": projected,
                "remaining_po_qty": remaining,
            }],
            "missing_item_names": [item_name],
        }]
    }


class WarehouseCheckTests(unittest.TestCase):
    def test_existing_stock_is_not_counted_twice_against_po_shortage(self):
        payload = reminder_with_detail()
        balances = {"items": [{
            "item_name": "Bawang Bombay", "unit": "kg", "stock_type_code": "BAWANG_BOMBAY",
            "actual_balance": 5, "available_for_po": 5,
        }]}
        with patch("backend.po_reminder_warehouse_check.inventory_balances_v2", return_value=balances) as mocked:
            result = apply_warehouse_stock_check(payload, "CEMPLANG")

        detail = result["items"][0]["requirement_details"][0]
        self.assertEqual(detail["remaining_po_qty"], 5)
        self.assertEqual(detail["warehouse_stock_check"]["fresh_exact_qty"], 0)
        self.assertEqual(result["items"][0]["reminder_status"], "DUE_TODAY")
        self.assertEqual(mocked.call_args.kwargs["site"], "CEMPLANG")

    def test_only_stock_newer_than_projection_can_reduce_reminder(self):
        payload = reminder_with_detail()
        balances = {"items": [{
            "item_name": "Bawang Bombay", "unit": "kg", "stock_type_code": "BAWANG_BOMBAY",
            "actual_balance": 7, "available_for_po": 7,
        }]}
        with patch("backend.po_reminder_warehouse_check.inventory_balances_v2", return_value=balances):
            result = apply_warehouse_stock_check(payload, "CEMPLANG")

        detail = result["items"][0]["requirement_details"][0]
        self.assertEqual(detail["warehouse_stock_check"]["fresh_exact_qty"], 2)
        self.assertEqual(detail["remaining_po_qty"], 3)
        self.assertEqual(result["items"][0]["reminder_status"], "DUE_TODAY")

    def test_similar_name_is_reference_not_automatic_stock(self):
        payload = reminder_with_detail(item_name="Bawang Bombay")
        balances = {"items": [{
            "item_name": "Bawang Bambu", "unit": "kg", "stock_type_code": "RAW_BAWANG_BAMBU",
            "actual_balance": 20, "available_for_po": 20,
        }]}
        with patch("backend.po_reminder_warehouse_check.inventory_balances_v2", return_value=balances):
            result = apply_warehouse_stock_check(payload, "CEMPLANG")

        detail = result["items"][0]["requirement_details"][0]
        check = detail["warehouse_stock_check"]
        self.assertEqual(detail["remaining_po_qty"], 5)
        self.assertEqual(check["status"], "REFERENCE_AVAILABLE")
        self.assertFalse(check["candidates"][0]["is_exact_match"])


if __name__ == "__main__":
    unittest.main()
