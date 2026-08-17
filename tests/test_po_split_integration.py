from __future__ import annotations

import unittest
from datetime import date, datetime

from backend.db import connection
from backend.operational_api import PurchaseOrderCreateIn, PurchaseOrderItemIn
from backend.po_reminder_tools_api import _insert_split_po
from backend.po_schedule import resolve_purchase_order_schedule


class SplitPoIntegrationTest(unittest.TestCase):
    def test_two_separate_koperasi_pos_can_share_date_and_keep_own_lead(self):
        distribution = date(2099, 8, 20)
        cooking = date(2099, 8, 19)
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
                # Test-specific effective rules: same vendor/date, different item lead.
                cur.execute(
                    """
                    insert into vendor_rules(vendor_code,site_code,category_code,lead_time_days_before_cooking,effective_from,notes)
                    values
                      ('KOPERASI','MAJA','TELUR',1,date '2099-01-01','integration test'),
                      ('KOPERASI','MAJA','BAHAN_KERING',0,date '2099-01-01','integration test')
                    on conflict (vendor_code,site_code,category_code,effective_from)
                    do update set lead_time_days_before_cooking=excluded.lead_time_days_before_cooking
                    """
                )
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

                telur_schedule = resolve_purchase_order_schedule(cur, {
                    "id": first_id,
                    "site": "MAJA",
                    "vendor_code": "KOPERASI",
                    "distribution_date": distribution,
                    "cooking_at": datetime(2099, 8, 19, 3, 0, 0),
                })
                dry_schedule = resolve_purchase_order_schedule(cur, {
                    "id": second_id,
                    "site": "MAJA",
                    "vendor_code": "KOPERASI",
                    "distribution_date": distribution,
                    "cooking_at": datetime(2099, 8, 19, 3, 0, 0),
                })
                self.assertEqual(cooking, telur_schedule["cooking_date"])
                self.assertEqual(1, telur_schedule["lead_time_days_before_cooking"])
                self.assertEqual(date(2099, 8, 18), telur_schedule["scheduled_order_date"])
                self.assertEqual("ITEM_SPECIFIC_VENDOR_RULES", telur_schedule["schedule_basis"])
                self.assertEqual(0, dry_schedule["lead_time_days_before_cooking"])
                self.assertEqual(date(2099, 8, 19), dry_schedule["scheduled_order_date"])
                self.assertEqual("ITEM_SPECIFIC_VENDOR_RULES", dry_schedule["schedule_basis"])
            conn.rollback()


if __name__ == "__main__":
    unittest.main()
