from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import patch

from backend.po_reminder_tools_api import apply_reminder_overrides, reminder_key_for


class _Cursor:
    def execute(self, *_args, **_kwargs):
        return None

    def fetchall(self):
        return [
            {
                "reminder_key": self.key,
                "resolution": self.resolution,
                "note": "sudah dicek",
                "metadata": {},
                "created_at": "2026-08-17T07:00:00+07:00",
                "updated_at": "2026-08-17T07:00:00+07:00",
            }
        ]

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _Connection:
    def __init__(self, key, resolution="MANUAL_PO"):
        self.cursor_obj = _Cursor()
        self.cursor_obj.key = key
        self.cursor_obj.resolution = resolution

    def cursor(self):
        return self.cursor_obj

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class ReminderToolsTest(unittest.TestCase):
    def _item(self):
        return {
            "site": "MAJA",
            "vendor_code": "KOPERASI",
            "po_date": date(2026, 8, 16),
            "procurement_bucket": "TEMPE",
            "distribution_date": date(2026, 8, 20),
            "distribution_dates": [date(2026, 8, 20)],
            "item_names": ["Tempe"],
            "reminder_status": "OVERDUE",
            "requirement_details": [
                {
                    "distribution_date": date(2026, 8, 20),
                    "stock_type_code": "TEMPE",
                    "unit": "kg",
                    "item_names": ["Tempe"],
                    "recommended_po_qty": 40,
                    "remaining_po_qty": 40,
                }
            ],
        }

    def test_key_ignores_qty_and_status_but_not_identity(self):
        first = self._item()
        key = reminder_key_for(first)
        second = self._item()
        second["reminder_status"] = "DUE_TODAY"
        second["requirement_details"][0]["remaining_po_qty"] = 5
        self.assertEqual(key, reminder_key_for(second))

        changed = self._item()
        changed["item_names"] = ["Telur Ayam"]
        changed["requirement_details"][0]["item_names"] = ["Telur Ayam"]
        changed["requirement_details"][0]["stock_type_code"] = "TELUR"
        self.assertNotEqual(key, reminder_key_for(changed))

    def test_manual_po_override_turns_action_green_done_without_mutating_requirements(self):
        item = self._item()
        key = reminder_key_for(item)
        payload = {
            "site": "MAJA",
            "date": date(2026, 8, 17),
            "dueCount": 1,
            "overdueCount": 1,
            "tomorrowCount": 0,
            "items": [item],
        }
        with patch("backend.po_reminder_tools_api.database_ready", return_value=True), patch(
            "backend.po_reminder_tools_api.connection", return_value=_Connection(key)
        ):
            result = apply_reminder_overrides(payload, "MAJA", date(2026, 8, 17))

        row = result["items"][0]
        self.assertEqual("DONE", row["reminder_status"])
        self.assertEqual("OVERDUE", row["override_original_status"])
        self.assertTrue(row["manual_po_confirmed"])
        self.assertEqual("PO manual sudah dilakukan", row["reminder_override_label"])
        self.assertEqual(40, row["requirement_details"][0]["remaining_po_qty"])
        self.assertEqual(0, result["dueCount"])
        self.assertEqual(0, result["overdueCount"])

    def test_checked_shortage_review_closes_review_without_claiming_manual_po(self):
        item = self._item()
        item["reminder_status"] = "SHORTAGE_REVIEW"
        item["po_already_done"] = True
        item["po_status"] = "SENT"
        key = reminder_key_for(item)
        payload = {
            "site": "MAJA",
            "date": date(2026, 8, 17),
            "dueCount": 1,
            "overdueCount": 1,
            "tomorrowCount": 0,
            "items": [item],
        }
        with patch("backend.po_reminder_tools_api.database_ready", return_value=True), patch(
            "backend.po_reminder_tools_api.connection", return_value=_Connection(key, resolution="CHECKED")
        ):
            result = apply_reminder_overrides(payload, "MAJA", date(2026, 8, 17))

        row = result["items"][0]
        self.assertEqual("DONE", row["reminder_status"])
        self.assertEqual("DONE_REVIEWED", row["po_workflow_status"])
        self.assertEqual("Sudah dicek / dibiarkan", row["reminder_override_label"])
        self.assertFalse(row.get("manual_po_confirmed", False))
        self.assertEqual(0, result["shortageReviewCount"])
        self.assertEqual(0, result["overdueCount"])

    def test_shortage_review_is_not_counted_as_ordering_when_override_db_unavailable(self):
        item = self._item()
        item["reminder_status"] = "SHORTAGE_REVIEW"
        payload = {
            "site": "MAJA",
            "date": date(2026, 8, 17),
            "dueCount": 1,
            "overdueCount": 1,
            "tomorrowCount": 1,
            "items": [item],
        }
        with patch("backend.po_reminder_tools_api.database_ready", return_value=False):
            result = apply_reminder_overrides(payload, "MAJA", date(2026, 8, 17))
        self.assertEqual(0, result["dueCount"])
        self.assertEqual(0, result["overdueCount"])
        self.assertEqual(0, result["tomorrowCount"])
        self.assertEqual(1, result["shortageReviewCount"])


if __name__ == "__main__":
    unittest.main()
