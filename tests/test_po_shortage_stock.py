from __future__ import annotations

import unittest

from backend.po_shortage_stock_api import _actual_balance_lookup, _correction_direction, _source_key


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


if __name__ == "__main__":
    unittest.main()
