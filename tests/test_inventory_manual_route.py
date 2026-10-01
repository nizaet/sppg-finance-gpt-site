from __future__ import annotations

import unittest

from backend.app import app
from backend.inventory_manual_api import build_adjustment_movements


class ManualInventoryRouteTests(unittest.TestCase):
    def test_manual_adjustment_is_mounted_once_under_v1(self):
        post_paths = {
            route.path
            for route in app.routes
            if "POST" in (getattr(route, "methods", set()) or set())
        }
        self.assertIn("/v1/inventory/manual-adjustment", post_paths)
        self.assertNotIn("/v1/v1/inventory/manual-adjustment", post_paths)

    def test_changing_unit_moves_old_balance_out_and_new_balance_in(self):
        movements = build_adjustment_movements("CEMPLANG", "pcs", "botol", 5, 2, -3, True)
        self.assertEqual(len(movements), 2)
        self.assertEqual((movements[0]["qty"], movements[0]["unit"], movements[0]["from_location"]), (5, "pcs", "CEMPLANG"))
        self.assertEqual((movements[1]["qty"], movements[1]["unit"], movements[1]["to_location"]), (2, "botol", "CEMPLANG"))

    def test_same_unit_adjustment_keeps_delta_behavior(self):
        movements = build_adjustment_movements("MAJA", "kg", "kg", 5, 3, -2, False)
        self.assertEqual(len(movements), 1)
        self.assertEqual((movements[0]["qty"], movements[0]["unit"], movements[0]["to_location"]), (2, "kg", "MANUAL_ADJUSTMENT"))

    def test_unit_change_from_zero_only_adds_new_balance(self):
        movements = build_adjustment_movements("MAJA", "pcs", "kg", 0, 1.5, 1.5, True)
        self.assertEqual(len(movements), 1)
        self.assertEqual((movements[0]["qty"], movements[0]["unit"], movements[0]["to_location"]), (1.5, "kg", "MAJA"))


if __name__ == "__main__":
    unittest.main()
