from __future__ import annotations

import unittest

from backend.po_shortage_stock_api import (
    _actual_balance_lookup,
    _correction_direction,
    _fresh_requirement_lookup,
    _source_key,
)


class PoShortageStockHelperTests(unittest.TestCase):
    def test_actual_balance_lookup_uses_stock_type_and_canonical_unit(self):
        lookup = _actual_balance_lookup([
            {
                "item_name": "Tempe",
                "stock_type_code": "TEMPE",
                "unit": "KG",
                "actual_balance": 7.5,
                "inventory_item_code": "TEMPE",
            }
        ])
        row = lookup[("TEMPE", "kg")]
        self.assertEqual(7.5, row["actual_balance"])

    def test_positive_delta_adds_to_kitchen_and_negative_delta_removes(self):
        self.assertEqual(("MANUAL_CORRECTION", "MAJA"), _correction_direction("MAJA", 4.0))
        self.assertEqual(("CEMPLANG", "MANUAL_CORRECTION"), _correction_direction("CEMPLANG", -2.0))

    def test_source_key_is_idempotent_for_same_observation_but_changes_when_balance_changes(self):
        first = _source_key("POREM-12345678", "TEMPE", "kg", 5.0, 10.0)
        retry = _source_key("POREM-12345678", "TEMPE", "kg", 5.0, 10.0)
        later = _source_key("POREM-12345678", "TEMPE", "kg", 7.0, 10.0)
        self.assertEqual(first, retry)
        self.assertNotEqual(first, later)

    def test_fresh_requirement_uses_remaining_after_existing_po_coverage(self):
        lookup = _fresh_requirement_lookup({
            "po_code": "PO-MAJA-20260914-HOLIL",
            "requirement_details": [
                {
                    "distribution_date": "2026-09-14",
                    "item_names": ["Bawang Putih"],
                    "stock_type_code": "BAWANG_PUTIH",
                    "unit": "kg",
                    "recommended_po_qty": 6,
                    "covered_po_qty": 4,
                    "remaining_po_qty": 2,
                }
            ],
        })
        row = lookup[("BAWANG_PUTIH", "kg")]
        self.assertEqual(6.0, row["recommended_po_qty"])
        self.assertEqual(4.0, row["covered_po_qty"])
        self.assertEqual(2.0, row["remaining_po_qty"])
        self.assertIn("PO-MAJA-20260914-HOLIL", row["po_codes"])

    def test_fully_covered_requirement_has_zero_remaining(self):
        lookup = _fresh_requirement_lookup({
            "partial_po_codes": ["PO-CEMPLANG-20260914-HOLIL"],
            "requirement_details": [
                {
                    "distribution_date": "2026-09-14",
                    "item_names": ["Bawang Putih"],
                    "stock_type_code": "BAWANG_PUTIH",
                    "unit": "kg",
                    "recommended_po_qty": 6,
                    "covered_po_qty": 6,
                    "remaining_po_qty": 0,
                }
            ],
        })
        self.assertEqual(0.0, lookup[("BAWANG_PUTIH", "kg")]["remaining_po_qty"])

    def test_garlic_powder_never_merges_with_fresh_garlic(self):
        lookup = _fresh_requirement_lookup({
            "requirement_details": [
                {
                    "distribution_date": "2026-09-14",
                    "item_names": ["Bawang Putih"],
                    "stock_type_code": "BAWANG_PUTIH",
                    "unit": "kg",
                    "recommended_po_qty": 6,
                    "covered_po_qty": 2,
                    "remaining_po_qty": 4,
                },
                {
                    "distribution_date": "2026-09-14",
                    "item_names": ["Bawang Putih Bubuk"],
                    "stock_type_code": "BAWANG_PUTIH_BUBUK",
                    "unit": "kg",
                    "recommended_po_qty": 3,
                    "covered_po_qty": 3,
                    "remaining_po_qty": 0,
                },
            ],
        })
        self.assertEqual(4.0, lookup[("BAWANG_PUTIH", "kg")]["remaining_po_qty"])
        self.assertEqual(0.0, lookup[("BAWANG_PUTIH_BUBUK", "kg")]["remaining_po_qty"])


if __name__ == "__main__":
    unittest.main()
