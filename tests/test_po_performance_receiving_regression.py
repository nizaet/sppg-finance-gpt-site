from __future__ import annotations

import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from unittest.mock import patch

from backend import po_delivery_receipt_reconcile_patch as delivery_patch
from backend import po_reminder_projection_cache_patch as projection_patch


class ProjectionCacheRegressionTests(unittest.TestCase):
    def setUp(self):
        with projection_patch._LOCK:
            projection_patch._CACHE.clear()
            projection_patch._KEY_LOCKS.clear()

    def tearDown(self):
        with projection_patch._LOCK:
            projection_patch._CACHE.clear()
            projection_patch._KEY_LOCKS.clear()

    def test_identical_site_date_projection_is_reused_without_mutating_result(self):
        calls = []

        def fake_lookup(site, distribution_date):
            calls.append((site, distribution_date))
            return {("RICE", "kg"): 125.0}, "TEST_PROJECTION"

        target = date(2026, 8, 20)
        with patch.object(projection_patch, "_ORIGINAL_PROJECTION_LOOKUP", side_effect=fake_lookup):
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
        with patch.object(projection_patch, "_ORIGINAL_PROJECTION_LOOKUP", side_effect=fake_lookup):
            projection_patch.projection_lookup("MAJA", d1)
            projection_patch.projection_lookup("CEMPLANG", d1)
            projection_patch.projection_lookup("MAJA", d2)

        self.assertEqual(len(calls), 3)

    def test_concurrent_identical_requests_use_one_projection(self):
        calls = []
        calls_lock = threading.Lock()

        def slow_lookup(site, distribution_date):
            with calls_lock:
                calls.append((site, distribution_date))
            time.sleep(0.08)
            return {("TEST", "kg"): 1.0}, "TEST"

        target = date(2026, 8, 20)
        with patch.object(projection_patch, "_ORIGINAL_PROJECTION_LOOKUP", side_effect=slow_lookup):
            with ThreadPoolExecutor(max_workers=4) as executor:
                results = list(executor.map(
                    lambda _: projection_patch.projection_lookup("MAJA", target),
                    range(4),
                ))

        self.assertEqual(calls, [("MAJA", target)])
        self.assertTrue(all(result == results[0] for result in results))

    def test_exact_lookup_does_not_prefetch_unrequested_dates(self):
        calls = []

        def fake_lookup(site, distribution_date):
            calls.append((site, distribution_date))
            return {("TEST", "kg"): 1.0}, "TEST"

        target = date(2026, 8, 20)
        with patch.object(projection_patch, "_ORIGINAL_PROJECTION_LOOKUP", side_effect=fake_lookup):
            projection_patch.projection_lookup("MAJA", target)

        self.assertEqual(calls, [("MAJA", target)])


class DeliveryAlertReconciliationRegressionTests(unittest.TestCase):
    def _alert_payload(self, accepted_qty: float = 0.0):
        return {
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
                    "acceptedQty": accepted_qty,
                    "remainingReceiveQty": 144.0 - accepted_qty,
                    "unit": "pcs",
                }],
            }],
        }

    def test_direct_positive_receipt_removes_not_arrived_alert(self):
        original = self._alert_payload(accepted_qty=20.0)
        with patch.object(delivery_patch, "_ORIGINAL_PO_DELIVERY_ALERTS", return_value=original), \
             patch.object(delivery_patch, "_resolved_po_ids", return_value=set()), \
             patch.object(delivery_patch, "_arrival_evidence", return_value=set()):
            result = delivery_patch.po_delivery_alerts(
                site="CEMPLANG", alert_date=date(2026, 8, 18), minimum_hour=0
            )

        self.assertEqual(result["count"], 0)
        self.assertEqual(result["items"], [])
        self.assertEqual(result["receivedItemsHidden"], 1)

    def test_cross_receipt_evidence_removes_not_arrived_alert(self):
        original = self._alert_payload()
        with patch.object(delivery_patch, "_ORIGINAL_PO_DELIVERY_ALERTS", return_value=original), \
             patch.object(delivery_patch, "_resolved_po_ids", return_value=set()), \
             patch.object(delivery_patch, "_arrival_evidence", return_value={1001}):
            result = delivery_patch.po_delivery_alerts(
                site="CEMPLANG", alert_date=date(2026, 8, 18), minimum_hour=0
            )

        self.assertEqual(result["count"], 0)
        self.assertEqual(result["items"], [])
        self.assertEqual(result["receivedItemsHidden"], 1)

    def test_item_without_receipt_evidence_stays_visible(self):
        original = self._alert_payload()
        with patch.object(delivery_patch, "_ORIGINAL_PO_DELIVERY_ALERTS", return_value=original), \
             patch.object(delivery_patch, "_resolved_po_ids", return_value=set()), \
             patch.object(delivery_patch, "_arrival_evidence", return_value=set()):
            result = delivery_patch.po_delivery_alerts(
                site="CEMPLANG", alert_date=date(2026, 8, 18), minimum_hour=0
            )

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["items"][0]["items"][0]["purchaseOrderItemId"], 1001)
        self.assertEqual(result["receivedItemsHidden"], 0)

    def test_operator_resolved_po_is_hidden_before_receipt_lookup(self):
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
             patch.object(delivery_patch, "_resolved_po_ids", return_value={101}), \
             patch.object(delivery_patch, "_arrival_evidence") as arrival_evidence:
            result = delivery_patch.po_delivery_alerts(
                site="CEMPLANG", alert_date=date(2026, 8, 18), minimum_hour=0
            )

        self.assertEqual(result["count"], 0)
        self.assertEqual(result["items"], [])
        self.assertTrue(result["resolutionGuardApplied"])
        arrival_evidence.assert_not_called()


if __name__ == "__main__":
    unittest.main()
