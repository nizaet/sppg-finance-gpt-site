from __future__ import annotations

import unittest
from datetime import date

from backend.po_reminder_operational_reconcile import (
    apply_tempe_configured_leads,
    apply_wikian_batch_fifo,
)


TARGET = date(2026, 8, 16)


def chicken_reminder(po_date: date, distribution_date: date, name: str, recommended: float, *, covered: float = 0.0):
    remaining = max(0.0, recommended - min(recommended, covered))
    if remaining == 0:
        status = "DONE"
    elif po_date < TARGET:
        status = "OVERDUE"
    elif po_date == TARGET:
        status = "DUE_TODAY"
    else:
        status = "UPCOMING"
    return {
        "site": "MAJA",
        "vendor_code": "WIKIAN",
        "vendor_name": "Wikian",
        "po_date": po_date,
        "distribution_date": distribution_date,
        "distribution_dates": [distribution_date],
        "cooking_date": distribution_date.replace(day=distribution_date.day - 1),
        "cooking_dates": [distribution_date.replace(day=distribution_date.day - 1)],
        "item_names": [name],
        "item_families": ["CHICKEN"],
        "item_count": 1 if remaining > 0 else 0,
        "missing_item_names": [name] if remaining > 0 else [],
        "missing_distribution_dates": [distribution_date] if remaining > 0 else [],
        "reminder_status": status,
        "requirement_details": [{
            "distribution_date": distribution_date,
            "cooking_dates": [distribution_date.replace(day=distribution_date.day - 1)],
            "item_names": [name],
            "item_families": ["CHICKEN"],
            "stock_type_code": name.upper().replace(" ", "_"),
            "unit": "kg",
            "planned_qty": recommended,
            "projected_stock_qty": 0.0,
            "recommended_po_qty": recommended,
            "covered_po_qty": covered,
            "remaining_po_qty": remaining,
            "coverage_stage": "DONE" if remaining == 0 else "OPEN",
        }],
    }


def sent_po(qty: float):
    po = {
        "id": 77,
        "po_code": "PO-MAJA-20260820-WIKIAN",
        "revision_no": 2,
        "site": "MAJA",
        "vendor_code": "WIKIAN",
        "status": "SENT",
        "created_at": "2026-08-16T01:50:00+07:00",
        "sent_at": "2026-08-16T01:59:27+07:00",
        "effective_date": TARGET,
    }
    direct = [{
        "purchase_order_id": 77,
        "item_name": "Daging Ayam",
        "po_qty": qty,
        "unit": "kg",
    }]
    coverage = [{
        "purchase_order_id": 77,
        "distribution_date": date(2026, 8, 20),
        "item_name": "Daging Ayam",
        "po_qty": qty,
        "unit": "kg",
    }]
    return [po], direct, coverage


class ConfiguredTempeLeadTests(unittest.TestCase):
    def test_maja_tempe_uses_edited_lead_instead_of_hardcoded_h4(self):
        payload = {
            "items": [{
                "site": "MAJA",
                "vendor_code": "KOPERASI",
                "procurement_bucket": "TEMPE",
                "item_families": ["TEMPE"],
                "po_date": date(2026, 8, 15),
                "cooking_date": date(2026, 8, 19),
                "cooking_dates": [date(2026, 8, 19)],
                "distribution_date": date(2026, 8, 20),
                "reminder_status": "OVERDUE",
                "lead_time_days_before_cooking": 4,
            }],
            "dueCount": 1,
            "overdueCount": 1,
            "tomorrowCount": 0,
        }
        result = apply_tempe_configured_leads(
            payload,
            TARGET,
            {date(2026, 8, 19): 2},
        )
        item = result["items"][0]
        self.assertEqual(item["po_date"], date(2026, 8, 17))
        self.assertEqual(item["lead_time_days_before_cooking"], 2)
        self.assertEqual(item["reminder_status"], "UPCOMING")
        self.assertEqual(result["overdueCount"], 0)
        self.assertEqual(result["tomorrowCount"], 1)


class WikianBatchReconcileTests(unittest.TestCase):
    def _payload(self):
        return {
            "items": [
                chicken_reminder(date(2026, 8, 14), date(2026, 8, 18), "Daging Ayam", 100.0),
                chicken_reminder(date(2026, 8, 15), date(2026, 8, 19), "Daging Ayam Fillet Dada (Frozen)", 100.0),
                # v4 exact coverage sees the whole single-date PO on Aug 20.
                chicken_reminder(date(2026, 8, 16), date(2026, 8, 20), "Daging Ayam", 105.0, covered=305.0),
            ],
            "dueCount": 2,
            "overdueCount": 2,
            "tomorrowCount": 0,
        }

    def test_305kg_single_date_po_reserves_today_then_closes_backlog_fifo(self):
        pos, direct, coverage = sent_po(305.0)
        result = apply_wikian_batch_fifo(self._payload(), TARGET, pos, direct, coverage)
        by_date = {item["distribution_date"]: item for item in result["items"]}
        self.assertEqual(by_date[date(2026, 8, 18)]["reminder_status"], "DONE")
        self.assertEqual(by_date[date(2026, 8, 19)]["reminder_status"], "DONE")
        self.assertEqual(by_date[date(2026, 8, 20)]["reminder_status"], "DONE")
        self.assertEqual(result["overdueCount"], 0)
        self.assertEqual(result["dueCount"], 0)
        self.assertEqual(by_date[date(2026, 8, 19)]["po_code"], "PO-MAJA-20260820-WIKIAN")
        self.assertTrue(by_date[date(2026, 8, 19)]["wikian_batch_reconciled"])

    def test_insufficient_surplus_leaves_only_true_residual_shortage(self):
        pos, direct, coverage = sent_po(250.0)
        result = apply_wikian_batch_fifo(self._payload(), TARGET, pos, direct, coverage)
        by_date = {item["distribution_date"]: item for item in result["items"]}
        self.assertEqual(by_date[date(2026, 8, 18)]["reminder_status"], "DONE")
        self.assertEqual(by_date[date(2026, 8, 19)]["reminder_status"], "OVERDUE")
        detail_19 = by_date[date(2026, 8, 19)]["requirement_details"][0]
        self.assertEqual(detail_19["remaining_po_qty"], 55.0)
        self.assertEqual(by_date[date(2026, 8, 19)]["missing_item_names"], ["Daging Ayam Fillet Dada (Frozen)"])
        self.assertEqual(result["overdueCount"], 1)

    def test_surplus_does_not_cover_implicit_not_yet_due_requirement(self):
        payload = self._payload()
        payload["items"].append(
            chicken_reminder(date(2026, 8, 17), date(2026, 8, 21), "Daging Ayam", 100.0)
        )
        pos, direct, coverage = sent_po(400.0)
        result = apply_wikian_batch_fifo(payload, TARGET, pos, direct, coverage)
        by_date = {item["distribution_date"]: item for item in result["items"]}
        future = by_date[date(2026, 8, 21)]
        self.assertEqual(future["reminder_status"], "UPCOMING")
        self.assertEqual(future["requirement_details"][0]["remaining_po_qty"], 100.0)
        self.assertFalse(future.get("wikian_batch_reconciled", False))


if __name__ == "__main__":
    unittest.main()
