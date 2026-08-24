from __future__ import annotations

import unittest

from backend.app import app


class ManualInventoryRouteTests(unittest.TestCase):
    def test_manual_adjustment_is_mounted_once_under_v1(self):
        post_paths = {
            route.path
            for route in app.routes
            if "POST" in (getattr(route, "methods", set()) or set())
        }
        self.assertIn("/v1/inventory/manual-adjustment", post_paths)
        self.assertNotIn("/v1/v1/inventory/manual-adjustment", post_paths)


if __name__ == "__main__":
    unittest.main()
