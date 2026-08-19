from __future__ import annotations

import threading
import time
import unittest
from datetime import date
from unittest.mock import patch

from backend import po_delivery_receipt_reconcile_patch as delivery_patch
from backend import po_reminder_projection_cache_patch as projection_patch


class ProjectionCacheRegressionTests(unittest.TestCase):
    def setUp(self):
        with projection_patch._LOCK:
            projection_patch._CACHE.clear()
            projection_patch._KEY_LOCKS.clear()
            for future in projection_patch._INFLIGHT.values():
                future.cancel()
            projection_patch._INFLIGHT.clear()

    def test_identical_site_date_projection_is_reused_without_mutating_result(self):
        calls = []

        def fake_lookup(site, distribution_date):
            calls.append((site, distribution_date))
            return {("RICE", "kg"): 125.0}, "TEST_PROJECTION"

        target = date(2026, 8, 20)
        with patch.object(projection_patch, "_ORIGINAL_PROJECTION_LOOKUP", side_effect=fake_lookup), \
             patch.object(projection_patch, "_PREFETCH_DAYS", 0):
            first = projection_patch.projection_lookup("MAJA", target)
            first[0][("RICE", "kg")] = 1.0
            second = projection_patch.projection_lookup("MAJA", target)

        self.assertEqual(calls, [("MAJA", target)])
        self.assertEqual(second[0][("RICE", "kg")], 125.0)
        self.assertEqual(second[1], "TEST_PROJECTION")

    def test_cache_key_keeps_site_and_date_isolated(self):
        calls = []

        def fake_lookup(site, distribution_date):
            calls.append((site, distribution_date))
            return {("TEST", "kg"): float(len(calls))}, "TEST"

        d1 = date(2026, 8, 20)
        d2 = date(2026, 8, 21)
        with patch.object(projection_patch, "_ORIGINAL_PROJECTION_LOOKUP", side_effect=fake_lookup), \
             patch.object(projection_patch, "_PREFETCH_DAYS", 0):
            projection_patch.projection_lookup("MAJA", d1)
            projection_patch.projection_lookup("CEMPLANG", d1)
            projection_patch.projection_lookup("MAJA", d2)

        self.assertEqual(len(calls), 3)

    def test_prefetch_starts_nearby_dates_concurrently(self):
        started = set()
        lock = threading.Lock()

        def slow_lookup(site, distribution_date):
            with lock:
                started.add((site, distribution_date))
            time.sleep(0.08)
            return {("TEST", "kg"): 1.0}, "TEST"

        target = date(2026, 8, 20)
        with patch.object(projection_patch, "_ORIGINAL_PROJECTION_LOOKUP", side_effect=slow_lookup), \
             patch.object(projection_patch, "_PREFETCH_DAYS", 3):
            began = time.monotonic()
            projection_patch.projection_lookup("MAJA", target)
            elapsed = time.monotonic() - began
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                with projection_patch._LOCK:
                    if not projection_patch._INFLIGHT:
                        break
                time.sleep(0.01)

        expected = {("MAJA", date(2026, 8, day)) for day in (20, 21, 22, 23)}
        self.assertTrue(expected.issubset(started), started)
        # Four 80ms lookups should overlap under the bounded four-worker pool;
        # serial execution would take roughly 320ms before returning date 20.
        self.assertLess(elapsed, 0.22)


class DeliveryAlertReconciliationRegressionTests(unittest.TestCase):
    def _po_item(self, item_id: int, name: str, unit: str = "kg"):
        return {"id": item_id, "item_name": name, "unit": unit, "po_qty": 10.0}

    def test_unlinked_receipt_matches_only_unambiguous_item_inside_same_po(self):
        receipt = {"reported_item_name": "Tahu Putih", "unit": "pcs"}
        items = [
            self._po_item(11, "Tahu Putih", "pcs"),
            self._po_item(12, "Tempe", "kg"),
        ]
        matched = delivery_patch._pick_po_item(receipt, items)
        self.assertIsNotNone(matched)
        self.assertEqual(matched["id"], 11)

    def test_ambiguous_unlinked_receipt_does_not_close_any_po_item(self):
        receipt = {"reported_item_name": "Ayam", "unit": "kg"}
        items = [
            self._po_item(21, "Ayam Potong", "kg"),
            self._po_item(22, "Ayam Filet", "kg"),
        ]
        matched = delivery_patch._pick_po_item(receipt, items)
        self.assertIsNone(matched)

    def test_fallback_full_receipt_removes_alert_row(self):
        original = {
            "site": "CEMPLANG",
            "date": date(2026, 8, 18),
            "count": 1,
            "items": [{
                "purchaseOrderId": 101,
                "poCode": "PO-CEMPLANG-TEST",
                "items": [{
                    "purchaseOrderItemId": 1001,
                    "itemName": "Tahu Putih",
                    "poQty": 144.0,
                    "acceptedQty": 0.0,
                    "remainingReceiveQty": 144.0,
                    "unit": "pcs",
                }],
            }],
        }
        with patch.object(delivery_patch, "_ORIGINAL_PO_DELIVERY_ALERTS", return_value=original), \
             patch.object(delivery_patch, "_fallback_received_by_item", return_value={1001: 144.0}):
            result = delivery_patch.po_delivery_alerts(
                site="CEMPLANG", alert_date=date(2026, 8, 18), minimum_hour=0
            )

        self.assertEqual(result["count"], 0)
        self.assertEqual(result["items"], [])
        self.assertTrue(result["receiptLinkFallbackApplied"])
        self.assertEqual(result["receiptFallbackAcceptedQty"], 144.0)

    def test_fallback_partial_receipt_keeps_only_remaining_qty(self):
        original = {
            "count": 1,
            "items": [{
                "purchaseOrderId": 202,
                "poCode": "PO-MAJA-TEST",
                "items": [{
                    "purchaseOrderItemId": 2001,
                    "itemName": "Beras",
                    "poQty": 100.0,
                    "acceptedQty": 20.0,
                    "remainingReceiveQty": 80.0,
                    "unit": "kg",
                }],
            }],
        }
        with patch.object(delivery_patch, "_ORIGINAL_PO_DELIVERY_ALERTS", return_value=original), \
             patch.object(delivery_patch, "_fallback_received_by_item", return_value={2001: 30.0}):
            result = delivery_patch.po_delivery_alerts(
                site="MAJA", alert_date=date(2026, 8, 18), minimum_hour=0
            )

        self.assertEqual(result["count"], 1)
        item = result["items"][0]["items"][0]
        self.assertEqual(item["acceptedQty"], 50.0)
        self.assertEqual(item["remainingReceiveQty"], 50.0)
        self.assertTrue(item["receiptLinkFallbackApplied"])


if __name__ == "__main__":
    unittest.main()
