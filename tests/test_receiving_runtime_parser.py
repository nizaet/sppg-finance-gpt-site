from __future__ import annotations

import unittest

from backend.receiving_runtime_patch import extract_receipt_items, match_items


HOLIL_TEXT = """DATANG BARANG TGL 19 AGUSTUS 2026
Rincian Berat Jeruk
66,06 + 58,60 + 37,18 + 36,10
Total Berak kotor jeruk (197,94 kg)
Total Berat Bersih jeruk (190 kg)
1. Wortel=60,28 kg
2. Kembang kol=29,74 kg
3. Kembang kol=39,54 kg
4. Daun bawang=4,12 kg
5. Kemiri=2,02 kg
6. Bawang merah=5,10 kg
7. Gula merah=4,90 kg
8. Lengkuas=2,02 kg
9. Jahe=2,08 kg
10. Daun salam=1,70 kg/1ikat
11. Bawang putih=6,04 kg
"""


class ReceivingRuntimeParserTests(unittest.TestCase):
    def test_holil_message_uses_net_orange_and_aggregates_duplicate_lines(self):
        items = extract_receipt_items(HOLIL_TEXT)
        by_name = {row["reported_item_name"].lower(): row for row in items}

        self.assertAlmostEqual(by_name["jeruk"]["received_qty"], 190.0)
        self.assertAlmostEqual(by_name["jeruk"]["gross_received_qty"], 197.94)
        self.assertEqual(by_name["jeruk"]["quantity_basis"], "NET_WEIGHT")
        self.assertAlmostEqual(by_name["wortel"]["received_qty"], 60.28)
        self.assertAlmostEqual(by_name["kembang kol"]["received_qty"], 69.28)
        self.assertAlmostEqual(by_name["daun bawang"]["received_qty"], 4.12)
        self.assertAlmostEqual(by_name["daun salam"]["received_qty"], 1.70)
        self.assertEqual(by_name["daun salam"]["unit"], "kg")
        self.assertFalse(any(row["unit"] == "ikat" for row in items))

    def test_dede_compact_message_extracts_rice(self):
        items = extract_receipt_items("beras dari dede 200kg")
        rice = [row for row in items if row["reported_item_name"].lower() == "beras"]
        self.assertEqual(len(rice), 1)
        self.assertAlmostEqual(rice[0]["received_qty"], 200.0)
        self.assertEqual(rice[0]["unit"], "kg")

    def test_short_name_matches_more_specific_po_name(self):
        reported = [{"reported_item_name": "Jeruk", "received_qty": 190.0, "unit": "kg"}]
        po_items = [
            {"id": 1, "item_name": "Jeruk Medan", "po_qty": 190.0, "unit": "kg", "item_aliases": []},
            {"id": 2, "item_name": "Wortel", "po_qty": 60.0, "unit": "kg", "item_aliases": []},
        ]
        matched = match_items(reported, po_items)
        self.assertTrue(matched[0]["matched"])
        self.assertEqual(matched[0]["purchase_order_item_id"], 1)
        self.assertIn(matched[0]["match_method"], {"item_name", "unique_po_token_containment"})


if __name__ == "__main__":
    unittest.main()
