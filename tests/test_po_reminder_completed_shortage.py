from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import patch

from backend.po_reminder_completed_shortage import (
    apply_completed_po_shortage_semantics,
    enrich_completed_po_shortages,
)


class CompletedPoShortageSemanticsTests(unittest.TestCase):
    def _open_payload(self):
        return {
            "date": date(2026, 8, 16),
            "items": [{
                "site": "CEMPLANG",
                "vendor_code": "WIKIAN",
                "vendor_name": "Wikian",
                "po_date": date(2026, 8, 14),
                "distribution_date": date(2026, 8, 18),
                "distribution_dates": [date(2026, 8, 18)],
                "coverage_dates": [date(2026, 8, 18)],
                "reminder_status": "OVERDUE",
                "missing_item_names": ["Daging Ayam"],
                "missing_distribution_dates": [date(2026, 8, 18)],
                "requirement_details": [{
                    "distribution_date": date(2026, 8, 18),
                    "item_names": ["Daging Ayam"],
                    "recommended_po_qty": 300.0,
                    "covered_po_qty": 250.0,
                    "remaining_po_qty": 50.0,
                }],
                "purchase_order_id": None,
                "po_code": None,
                "po_status": None,
            }],
        }

    def _sent_po(self, po_id=10, distribution_date=date(2026, 8, 18)):
        return {
            "id": po_id,
            "po_code": "PO-CEMPLANG-20260818-WIKIAN",
            "revision_no": 1,
            "site": "CEMPLANG",
            "vendor_code": "WIKIAN",
            "status": "SENT",
            "created_at": "2026-08-16T04:00:00+07:00",
            "sent_at": "2026-08-16T04:13:25+07:00",
            "po_coverage_dates": [distribution_date],
        }

    def test_sent_po_leaves_ordering_queue_and_shortage_becomes_review(self):
        payload = self._open_payload()
        po = self._sent_po()
        lookup = {("CEMPLANG", "WIKIAN", date(2026, 8, 18)): po}

        result = apply_completed_po_shortage_semantics(payload, lookup)
        item = result["items"][0]

        # The ordering job is already done, therefore this must not stay red
        # OVERDUE/DUE_TODAY. Original timing is retained only for audit.
        self.assertEqual(item["reminder_status"], "SHORTAGE_REVIEW")
        self.assertEqual(item["shortage_reminder_status"], "OVERDUE")
        self.assertEqual(item["po_workflow_status"], "DONE")
        self.assertTrue(item["po_already_done"])
        self.assertTrue(item["shortage_only"])
        self.assertEqual(item["purchase_order_id"], 10)
        self.assertEqual(item["po_status"], "SENT")
        self.assertEqual(item["shortage_item_names"], ["Daging Ayam"])
        self.assertEqual(item["shortage_qty_total"], 50.0)
        self.assertEqual(result["shortageAfterCompletedPoCount"], 1)

    def test_wrong_distribution_po_is_not_attached(self):
        payload = self._open_payload()
        po = self._sent_po(distribution_date=date(2026, 8, 19))
        lookup = {("CEMPLANG", "WIKIAN", date(2026, 8, 19)): po}

        result = apply_completed_po_shortage_semantics(payload, lookup)
        item = result["items"][0]

        self.assertIs(result, payload)
        self.assertIsNone(item["purchase_order_id"])
        self.assertEqual(item["reminder_status"], "OVERDUE")
        self.assertNotIn("po_workflow_status", item)

    def test_done_requirement_is_left_untouched(self):
        payload = {
            "items": [{
                "site": "CEMPLANG",
                "vendor_code": "WIKIAN",
                "distribution_date": date(2026, 8, 18),
                "distribution_dates": [date(2026, 8, 18)],
                "reminder_status": "DONE",
                "missing_item_names": [],
                "requirement_details": [{"remaining_po_qty": 0.0}],
                "purchase_order_id": 10,
                "po_status": "SENT",
            }]
        }
        lookup = {("CEMPLANG", "WIKIAN", date(2026, 8, 18)): self._sent_po()}

        result = apply_completed_po_shortage_semantics(payload, lookup)
        self.assertIs(result, payload)
        self.assertNotIn("shortage_only", result["items"][0])

    def test_enricher_queries_only_when_shortage_candidate_exists(self):
        payload = self._open_payload()
        lookup = {("CEMPLANG", "WIKIAN", date(2026, 8, 18)): self._sent_po()}
        with patch(
            "backend.po_reminder_completed_shortage._completed_po_lookup",
            return_value=lookup,
        ) as finder:
            result = enrich_completed_po_shortages(payload, "CEMPLANG")

        finder.assert_called_once_with("CEMPLANG", [date(2026, 8, 18)])
        self.assertEqual(result["items"][0]["po_workflow_status"], "DONE")
        self.assertEqual(result["items"][0]["reminder_status"], "SHORTAGE_REVIEW")

    def test_enricher_does_not_touch_non_shortage_payload(self):
        payload = {"items": [{"reminder_status": "DONE"}]}
        with patch("backend.po_reminder_completed_shortage._completed_po_lookup") as finder:
            result = enrich_completed_po_shortages(payload, "CEMPLANG")
        self.assertIs(result, payload)
        finder.assert_not_called()


if __name__ == "__main__":
    unittest.main()
