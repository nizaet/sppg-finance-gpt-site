from __future__ import annotations

import unittest
from datetime import date

from backend.po_reminder_legacy_po_reconcile import (
    _correct_cemplang_tofu_vendor,
    apply_completed_coverage_index,
    build_completed_coverage_index,
)


class LegacyCompletedPoCoverageTests(unittest.TestCase):
    def _po(self, po_id: int, vendor: str = "HOLIL", status: str = "SENT") -> dict:
        return {
            "id": po_id,
            "po_code": f"PO-{po_id}",
            "revision_no": 1,
            "vendor_code": vendor,
            "status": status,
            "created_at": f"2026-08-16T0{po_id}:00:00+07:00",
            "sent_at": f"2026-08-16T0{po_id}:30:00+07:00",
            "base_distribution_date": date(2026, 8, 18),
        }

    def test_single_date_completed_po_can_use_direct_item_when_coverage_item_is_missing(self):
        po = self._po(1)
        index = build_completed_coverage_index(
            [po],
            [{"purchase_order_id": 1, "distribution_date": date(2026, 8, 18)}],
            [{"purchase_order_id": 1, "item_name": "Jeruk Medan", "po_qty": 40, "unit": "kg"}],
            [],
        )
        row = index[("HOLIL", date(2026, 8, 18), "JERUK_MEDAN", "kg")]
        self.assertEqual(row["qty"], 40.0)
        self.assertEqual(row["basis"], ["LEGACY_SINGLE_DATE_DIRECT_ITEM"])

    def test_explicit_coverage_item_wins_and_direct_header_is_not_double_counted(self):
        po = self._po(2)
        index = build_completed_coverage_index(
            [po],
            [{"purchase_order_id": 2, "distribution_date": date(2026, 8, 18)}],
            [{"purchase_order_id": 2, "item_name": "Jeruk Medan", "po_qty": 40, "unit": "kg"}],
            [{"purchase_order_id": 2, "distribution_date": date(2026, 8, 18), "item_name": "Jeruk Medan", "po_qty": 25, "unit": "kg"}],
        )
        row = index[("HOLIL", date(2026, 8, 18), "JERUK_MEDAN", "kg")]
        self.assertEqual(row["qty"], 25.0)
        self.assertEqual(row["basis"], ["EXPLICIT_COVERAGE_ITEM"])

    def test_multi_date_po_never_assigns_aggregate_direct_header_to_one_day(self):
        po = self._po(3, vendor="WIKIAN")
        index = build_completed_coverage_index(
            [po],
            [
                {"purchase_order_id": 3, "distribution_date": date(2026, 8, 18)},
                {"purchase_order_id": 3, "distribution_date": date(2026, 8, 19)},
            ],
            [{"purchase_order_id": 3, "item_name": "Daging Ayam", "po_qty": 305, "unit": "kg"}],
            [],
        )
        self.assertEqual(index, {})

    def test_completed_single_date_actual_po_closes_false_overdue(self):
        po = self._po(4)
        coverage_index = {
            ("HOLIL", date(2026, 8, 18), "JERUK_MEDAN", "kg"): {
                "qty": 40.0,
                "po": po,
                "basis": ["LEGACY_SINGLE_DATE_DIRECT_ITEM"],
            }
        }
        payload = {
            "date": date(2026, 8, 17),
            "items": [{
                "site": "MAJA",
                "vendor_code": "HOLIL",
                "po_date": date(2026, 8, 16),
                "reminder_status": "OVERDUE",
                "requirement_details": [{
                    "distribution_date": date(2026, 8, 18),
                    "stock_type_code": "JERUK_MEDAN",
                    "unit": "kg",
                    "item_names": ["Jeruk Medan"],
                    "recommended_po_qty": 40.0,
                    "covered_po_qty": 0.0,
                    "completed_po_qty": 0.0,
                    "remaining_po_qty": 40.0,
                }],
            }],
        }
        result = apply_completed_coverage_index(payload, coverage_index)
        item = result["items"][0]
        self.assertEqual(item["reminder_status"], "DONE")
        self.assertEqual(item["po_code"], "PO-4")
        self.assertEqual(item["missing_item_names"], [])
        self.assertEqual(item["requirement_details"][0]["remaining_po_qty"], 0.0)
        self.assertEqual(result["overdueCount"], 0)


class CemplangTofuVendorTests(unittest.TestCase):
    def test_tahu_name_overrides_stale_koperasi_category_and_uses_haji_badri_h1(self):
        payload = {
            "date": date(2026, 8, 17),
            "items": [{
                "site": "CEMPLANG",
                "vendor_code": "KOPERASI",
                "vendor_name": "Koperasi",
                "procurement_bucket": "TOFU",
                "po_date": date(2026, 8, 15),
                "reminder_status": "OVERDUE",
                "requirement_details": [{
                    "distribution_date": date(2026, 8, 19),
                    "cooking_dates": [date(2026, 8, 18)],
                    "stock_type_code": "TAHU",
                    "unit": "pcs",
                    "item_names": ["Tahu Putih"],
                    "item_families": ["DRY_GOODS"],
                    "recommended_po_qty": 100,
                    "remaining_po_qty": 100,
                }],
            }],
        }
        rules = [{
            "id": 99,
            "vendor_code": "HAJI_BADRI",
            "site_code": "CEMPLANG",
            "category_code": "TAHU",
            "lead_time_days_before_cooking": 1,
            "effective_from": date(2026, 8, 1),
            "effective_to": None,
        }]
        result = _correct_cemplang_tofu_vendor(payload, date(2026, 8, 17), rules, "Haji Badri")
        item = result["items"][0]
        self.assertEqual(item["vendor_code"], "HAJI_BADRI")
        self.assertEqual(item["lead_time_days_before_cooking"], 1)
        self.assertEqual(item["po_date"], date(2026, 8, 17))
        self.assertEqual(item["reminder_status"], "DUE_TODAY")
        self.assertEqual(item["requirement_details"][0]["item_families"], ["TOFU"])


if __name__ == "__main__":
    unittest.main()
