from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import patch

from backend.item_taxonomy import vendor_for_item
from backend.po_reminder_v4_api import (
    _coverage_stage,
    _group_stage,
    _projection_lookup,
    _resolve_procurement_rule,
    _strict_cemplang_tempe_rule,
)


class StrictCoverageRegressionTests(unittest.TestCase):
    def _po(self, po_id: int, status: str, code: str | None = None):
        return {
            "id": po_id,
            "status": status,
            "po_code": code or f"PO-{po_id}",
            "created_at": f"2026-08-16T0{po_id}:00:00+07:00",
            "revision_no": 1,
        }

    def test_same_vendor_sent_po_for_wrong_distribution_does_not_cover_tomorrow(self):
        """Regression: today's same-vendor PO must not attach to tomorrow's need."""
        sent = self._po(1, "SENT", "PO-MAJA-20260818-KOPERASI")
        exact_qty = {(1, date(2026, 8, 18), "TEMPE", "kg"): 100.0}
        result = _coverage_stage(
            [sent], exact_qty, date(2026, 8, 20), "TEMPE", "kg", 50.0
        )
        self.assertEqual(result["stage"], "OPEN")
        self.assertEqual(result["covered_qty"], 0.0)
        self.assertEqual(result["remaining_qty"], 50.0)
        self.assertIsNone(result["action_po"])
        self.assertEqual(result["contributors"], [])

    def test_sent_exact_distribution_item_unit_and_qty_is_done(self):
        sent = self._po(2, "SENT")
        exact_qty = {(2, date(2026, 8, 20), "TEMPE", "kg"): 50.0}
        result = _coverage_stage(
            [sent], exact_qty, date(2026, 8, 20), "TEMPE", "kg", 50.0
        )
        self.assertEqual(result["stage"], "DONE")
        self.assertEqual(result["remaining_qty"], 0.0)
        self.assertEqual(result["action_po"]["id"], 2)

    def test_sent_exact_but_insufficient_qty_remains_open_and_has_no_action_po(self):
        sent = self._po(3, "SENT")
        exact_qty = {(3, date(2026, 8, 20), "TEMPE", "kg"): 20.0}
        result = _coverage_stage(
            [sent], exact_qty, date(2026, 8, 20), "TEMPE", "kg", 50.0
        )
        self.assertEqual(result["stage"], "OPEN")
        self.assertEqual(result["covered_qty"], 20.0)
        self.assertEqual(result["remaining_qty"], 30.0)
        self.assertIsNone(result["action_po"])
        self.assertEqual([po["id"] for po in result["contributors"]], [3])

    def test_finalized_exact_coverage_requires_send(self):
        po = self._po(4, "FINALIZED")
        result = _coverage_stage(
            [po], {(4, date(2026, 8, 20), "TEMPE", "kg"): 50.0},
            date(2026, 8, 20), "TEMPE", "kg", 50.0,
        )
        self.assertEqual(result["stage"], "READY_TO_SEND")
        self.assertEqual(result["action_po"]["id"], 4)

    def test_draft_exact_coverage_requires_finalize(self):
        po = self._po(5, "DRAFT")
        result = _coverage_stage(
            [po], {(5, date(2026, 8, 20), "TEMPE", "kg"): 50.0},
            date(2026, 8, 20), "TEMPE", "kg", 50.0,
        )
        self.assertEqual(result["stage"], "DRAFT_NEEDS_FINAL")
        self.assertEqual(result["action_po"]["id"], 5)

    def test_open_group_uses_due_date_not_unrelated_po_status(self):
        self.assertEqual(
            _group_stage(["OPEN"], date(2026, 8, 15), date(2026, 8, 16)),
            "OVERDUE",
        )
        self.assertEqual(
            _group_stage(["OPEN"], date(2026, 8, 17), date(2026, 8, 16)),
            "UPCOMING",
        )


class TempeProcurementRegressionTests(unittest.TestCase):
    def _plan(self, site: str):
        return {
            "site": site,
            "item_name": "Tempe",
            "category_code": "TEMPE_TAHU",
            "preferred_vendor_code": None,
            "cooking_date": date(2026, 8, 19),
        }

    def test_tempe_vendor_is_koperasi_at_both_sites(self):
        self.assertEqual(vendor_for_item("Tempe", "TEMPE_TAHU", "MAJA"), "KOPERASI")
        self.assertEqual(vendor_for_item("Tempe", "TEMPE_TAHU", "CEMPLANG"), "KOPERASI")

    def test_maja_tempe_is_h4_and_separate_bucket(self):
        vendor, rule, bucket = _resolve_procurement_rule([], {"KOPERASI": "Koperasi"}, self._plan("MAJA"))
        self.assertEqual(vendor, "KOPERASI")
        self.assertEqual(rule["lead_time_days_before_cooking"], 4)
        self.assertEqual(rule["category_code"], "TEMPE")
        self.assertEqual(bucket, "TEMPE")

    def test_cemplang_tempe_without_dedicated_rule_is_missing_not_inferred(self):
        vendor, rule, bucket = _resolve_procurement_rule([], {"KOPERASI": "Koperasi"}, self._plan("CEMPLANG"))
        self.assertEqual(vendor, "KOPERASI")
        self.assertIsNone(rule)
        self.assertEqual(bucket, "TEMPE")

    def test_cemplang_combined_tahu_tempe_rule_is_rejected(self):
        rules = [{
            "id": 10,
            "vendor_code": "KOPERASI",
            "site_code": "CEMPLANG",
            "category_code": "TEMPE_TAHU_CASH_FLOW",
            "lead_time_days_before_cooking": 2,
            "effective_from": date(2026, 1, 1),
            "effective_to": None,
        }]
        self.assertIsNone(_strict_cemplang_tempe_rule(rules, date(2026, 8, 19)))

    def test_cemplang_dedicated_tempe_rule_is_accepted(self):
        rules = [{
            "id": 11,
            "vendor_code": "KOPERASI",
            "site_code": "CEMPLANG",
            "category_code": "TEMPE",
            "lead_time_days_before_cooking": 3,
            "effective_from": date(2026, 8, 16),
            "effective_to": None,
        }]
        rule = _strict_cemplang_tempe_rule(rules, date(2026, 8, 19))
        self.assertIsNotNone(rule)
        self.assertEqual(rule["lead_time_days_before_cooking"], 3)


class ProjectionRegressionTests(unittest.TestCase):
    def test_zero_available_for_po_is_not_replaced_by_physical_balance(self):
        payload = {
            "projectionModel": "TEST",
            "items": [{
                "item_name": "Tempe",
                "unit": "kg",
                "available_for_po": 0,
                "balance": 100,
            }],
        }
        with patch("backend.po_reminder_v4_api.inventory_balances_v2", return_value=payload):
            lookup, basis = _projection_lookup("MAJA", date(2026, 8, 20))
        self.assertEqual(basis, "TEST")
        self.assertEqual(lookup[("TEMPE", "kg")], 0.0)


class CompatibilityRegressionTests(unittest.TestCase):
    def test_v3_endpoint_delegates_to_strict_engine(self):
        from backend import po_reminder_v3_api

        sentinel = {"items": [{"reminder_status": "STRICT"}]}
        with patch.object(po_reminder_v3_api, "po_reminders_v4", return_value=sentinel) as delegated:
            result = po_reminder_v3_api.po_reminders_v3(
                site="MAJA", as_of=date(2026, 8, 16), horizon_days=2
            )
        self.assertEqual(result, sentinel)
        delegated.assert_called_once_with(
            site="MAJA", as_of=date(2026, 8, 16), horizon_days=2
        )

    def test_force_refresh_bypasses_short_v4_cache(self):
        from backend import po_reminder_v3_api

        po_reminder_v3_api._v4_cache.clear()
        po_reminder_v3_api._v4_key_locks.clear()
        with patch.object(
            po_reminder_v3_api,
            "po_reminders_v4",
            side_effect=[{"value": 1}, {"value": 2}],
        ) as delegated:
            first, first_hit, _ = po_reminder_v3_api._cached_v4_payload(
                "MAJA", date(2026, 8, 22), 2
            )
            cached, cached_hit, _ = po_reminder_v3_api._cached_v4_payload(
                "MAJA", date(2026, 8, 22), 2
            )
            refreshed, refreshed_hit, _ = po_reminder_v3_api._cached_v4_payload(
                "MAJA", date(2026, 8, 22), 2, force_refresh=True
            )

        self.assertEqual(first["value"], 1)
        self.assertFalse(first_hit)
        self.assertEqual(cached["value"], 1)
        self.assertTrue(cached_hit)
        self.assertEqual(refreshed["value"], 2)
        self.assertFalse(refreshed_hit)
        self.assertEqual(delegated.call_count, 2)


if __name__ == "__main__":
    unittest.main()
