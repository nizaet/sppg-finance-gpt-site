from __future__ import annotations

import unittest
from datetime import date, datetime

from backend.db import connection
from backend.operational_api import PurchaseOrderCreateIn, PurchaseOrderItemIn
from backend.po_reminder_tools_api import _insert_split_po


class SplitPoIntegrationTest(unittest.TestCase):
    def test_two_separate_koperasi_pos_can_share_distribution_date(self):
        distribution = date(2099, 8, 20)
        first = PurchaseOrderCreateIn(
            po_code="TEST-SPLIT-KOPERASI-TELUR-20990820",
            site="MAJA",
            vendor_code="KOPERASI",
            distribution_date=distribution,
            cooking_at=datetime(2099, 8, 19, 3, 0, 0),
            status="DRAFT",
            items=[PurchaseOrderItemIn(item_name="Telur Ayam", planned_qty=100, po_qty=100, unit="pcs")],
        )
        second = PurchaseOrderCreateIn(
            po_code="TEST-SPLIT-KOPERASI-KERING-20990820",
            site="MAJA",
            vendor_code="KOPERASI",
            distribution_date=distribution,
            cooking_at=datetime(2099, 8, 19, 3, 0, 0),
            status="DRAFT",
            items=[PurchaseOrderItemIn(item_name="Tepung Beras", planned_qty=10, po_qty=10, unit="kg")],
        )

        with connection() as conn:
            with conn.cursor() as cur:
                first_id, _, _ = _insert_split_po(cur, first, "MAJA", "KOPERASI")
                second_id, _, _ = _insert_split_po(cur, second, "MAJA", "KOPERASI")
                self.assertNotEqual(first_id, second_id)
                cur.execute(
                    """
                    select count(*) as total
                    from purchase_orders po
                    join production_cycles pc on pc.id=po.production_cycle_id
                    where po.id=any(%s) and pc.distribution_date=%s and po.vendor_code='KOPERASI'
                    """,
                    ([first_id, second_id], distribution),
                )
                self.assertEqual(2, int(cur.fetchone()["total"]))
            conn.rollback()


if __name__ == "__main__":
    unittest.main()
