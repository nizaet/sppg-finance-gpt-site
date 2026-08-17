import unittest
from datetime import date

from backend.control_tower_api import _procurement_view


class ControlTowerPoSyncRegressionTest(unittest.TestCase):
    def test_sent_done_po_is_green_not_overdue(self):
        summary, lanes = _procurement_view(
            {
                "items": [
                    {
                        "reminder_status": "DONE",
                        "po_date": "2026-08-14",
                        "vendor_code": "WIKIAN",
                        "po_code": "PO-CEMPLANG-20260818-WIKIAN",
                        "po_status": "SENT",
                        "purchase_order_id": 10,
                        "distribution_date": "2026-08-18",
                        "cooking_date": "2026-08-17",
                        "item_names": ["Daging Ayam"],
                    }
                ]
            },
            date(2026, 8, 17),
        )
        self.assertEqual(0, summary["poOverdue"])
        self.assertEqual("SELESAI", lanes[0]["status"])
        self.assertEqual("success", lanes[0]["severity"])

    def test_completed_po_with_residual_shortage_is_amber_not_overdue(self):
        summary, lanes = _procurement_view(
            {
                "items": [
                    {
                        "reminder_status": "OVERDUE",
                        "po_date": "2026-08-16",
                        "vendor_code": "HOLIL",
                        "po_code": "PO-CEMPLANG-20260818-HOLIL",
                        "po_status": "PARTIAL_RECEIVED",
                        "purchase_order_id": 11,
                        "po_already_done": True,
                        "shortage_only": True,
                        "distribution_date": "2026-08-18",
                        "cooking_date": "2026-08-17",
                        "missing_item_names": ["Kunyit"],
                    }
                ]
            },
            date(2026, 8, 17),
        )
        self.assertEqual(0, summary["poOverdue"])
        self.assertEqual(1, summary["poShortage"])
        self.assertEqual("CEK SISA", lanes[0]["status"])
        self.assertEqual("warning", lanes[0]["severity"])

    def test_true_open_overdue_remains_overdue(self):
        summary, lanes = _procurement_view(
            {
                "items": [
                    {
                        "reminder_status": "OVERDUE",
                        "po_date": "2026-08-15",
                        "vendor_code": "KOPERASI",
                        "distribution_date": "2026-08-19",
                        "cooking_date": "2026-08-18",
                        "missing_item_names": ["Tahu Putih"],
                    }
                ]
            },
            date(2026, 8, 17),
        )
        self.assertEqual(1, summary["poOverdue"])
        self.assertEqual("TERLAMBAT", lanes[0]["status"])


if __name__ == "__main__":
    unittest.main()
