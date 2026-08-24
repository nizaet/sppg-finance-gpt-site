from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import patch

from backend.po_reminder_completed_shortage import (
    apply_completed_po_shortage_semantics,
    enrich_completed_po_shortages,
)


class CompletedPoShortageSemanticsTests(unittest.TestCase):
    def _detail(self, name="Daging Ayam", completed=250.0, covered=250.0, remaining=50.0, po_id=10):
        return {
            "distribution_date": date(2026, 8, 18),
            "item_names": [name],
            "stock_type_code": "DAGING_AYAM",
            "unit": "kg",
            "recommended_po_qty": 300.0,
            "covered_po_qty": covered,
            "completed_po_qty": completed,
            "remaining_po_qty": remaining,
            "completed_purchase_order_id": po_id if completed > 0 else None,
            "completed_po_code": "PO-CEMPLANG-20260818-WIKIAN" if completed > 0 else None,
            "completed_po_status": "SENT" if completed > 0 else None,
            "completed_po_created_at": "2026-08-16T04:00:00+07:00" if completed > 0 else None,
            "completed_po_sent_at": "2026-08-16T04:13:25+07:00" if completed > 0 else None,
        }

    def _open_payload(self, details=None):
        details = details or [self._detail()]
        names = sorted({name for detail in details for name in detail.get("item_names", [])})
        return {
            "date": date(2026, 8, 17),
            "dueCount": 1,
            "overdueCount": 1,
            "tomorrowCount": 0,
            "items": [{
                "site": "CEMPLANG",
                "vendor_code": "WIKIAN",
                "vendor_name": "Wikian",
                "po_date": date(2026, 8, 16),
                "distribution_date": date(2026, 8, 18),
                "distribution_dates": [date(2026, 8, 18)],
                "coverage_dates": [date(2026, 8, 18)],
                "reminder_status": "OVERDUE",
                "missing_item_names": names,
                "missing_distribution_dates": [date(2026, 8, 18)],
                "requirement_details": details,
                "purchase_order_id": None,
                "po_code": None,
                "po_status": None,
            }],
        }

    def test_exact_completed_item_with_remaining_qty_becomes_shortage_review(self):
        result = apply_completed_po_shortage_semantics(self._open_payload())
        item = result["items"][0]
        detail = item["requirement_details"][0]

        self.assertEqual("ORDERED_PARTIAL", detail["ordering_state"])
        self.assertEqual("SHORTAGE_REVIEW", item["reminder_status"])
        self.assertEqual("OVERDUE", item["shortage_reminder_status"])
        self.assertEqual("DONE", item["po_workflow_status"])
        self.assertTrue(item["po_already_done"])
        self.assertTrue(item["shortage_only"])
        self.assertEqual(10, item["purchase_order_id"])
        self.assertEqual("SENT", item["po_status"])
        self.assertEqual(["Daging Ayam"], item["partial_shortage_item_names"])
        self.assertEqual(50.0, item["shortage_qty_total"])
        self.assertEqual(0, result["overdueCount"])
        self.assertEqual(1, result["shortageAfterCompletedPoCount"])

    def test_same_vendor_date_po_does_not_hide_item_never_ordered(self):
        detail = self._detail(name="Telur Ayam", completed=0, covered=0, remaining=30, po_id=None)
        payload = self._open_payload([detail])
        bogus_broad_lookup = {
            ("CEMPLANG", "WIKIAN", date(2026, 8, 18)): {
                "id": 999,
                "po_code": "UNRELATED-PO",
                "status": "SENT",
            }
        }

        result = apply_completed_po_shortage_semantics(payload, bogus_broad_lookup)
        item = result["items"][0]
        detail = item["requirement_details"][0]

        self.assertEqual("NOT_ORDERED", detail["ordering_state"])
        self.assertEqual("OVERDUE", item["reminder_status"])
        self.assertEqual(["Telur Ayam"], item["not_ordered_item_names"])
        self.assertEqual(1, item["not_ordered_count"])
        self.assertFalse(item["shortage_only"])
        self.assertIsNone(item["purchase_order_id"])
        self.assertNotIn("po_workflow_status", item)
        self.assertEqual(1, result["overdueCount"])

    def test_mixed_partial_and_never_ordered_stays_in_ordering_queue(self):
        partial = self._detail(name="Daging Ayam", completed=250, covered=250, remaining=50)
        missing = self._detail(name="Telur Ayam", completed=0, covered=0, remaining=30, po_id=None)
        result = apply_completed_po_shortage_semantics(self._open_payload([partial, missing]))
        item = result["items"][0]

        self.assertEqual("OVERDUE", item["reminder_status"])
        self.assertEqual(1, item["partial_shortage_count"])
        self.assertEqual(1, item["not_ordered_count"])
        self.assertEqual(["Daging Ayam"], item["partial_shortage_item_names"])
        self.assertEqual(["Telur Ayam"], item["not_ordered_item_names"])
        self.assertEqual("NEEDS_ORDERING", item["ordering_state_summary"])

    def test_wikian_batch_completed_qty_counts_as_ordered_partial(self):
        detail = self._detail(completed=0, covered=250, remaining=50, po_id=None)
        detail["batch_completed_po_qty"] = 250
        payload = self._open_payload([detail])
        payload["items"][0].update({
            "purchase_order_id": 88,
            "po_code": "PO-CEMPLANG-20260818-20260819-WIKIAN",
            "po_status": "SENT",
            "po_sent_at": "2026-08-16T04:13:25+07:00",
        })

        result = apply_completed_po_shortage_semantics(payload)
        item = result["items"][0]
        self.assertEqual("ORDERED_PARTIAL", item["requirement_details"][0]["ordering_state"])
        self.assertEqual("SHORTAGE_REVIEW", item["reminder_status"])
        self.assertEqual(88, item["purchase_order_id"])

    def test_done_requirement_is_left_untouched(self):
        payload = {
            "items": [{
                "site": "CEMPLANG",
                "vendor_code": "WIKIAN",
                "reminder_status": "DONE",
                "requirement_details": [{"remaining_po_qty": 0.0}],
                "purchase_order_id": 10,
                "po_status": "SENT",
            }]
        }
        result = apply_completed_po_shortage_semantics(payload)
        self.assertIs(result, payload)

    def test_enricher_no_longer_uses_broad_vendor_date_db_lookup(self):
        payload = self._open_payload()
        with patch("backend.po_reminder_completed_shortage._completed_po_lookup") as finder:
            result = enrich_completed_po_shortages(payload, "CEMPLANG")
        finder.assert_not_called()
        self.assertEqual("SHORTAGE_REVIEW", result["items"][0]["reminder_status"])


if __name__ == "__main__":
    unittest.main()
