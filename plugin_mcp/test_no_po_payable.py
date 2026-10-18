import unittest
from decimal import Decimal

from pydantic import ValidationError

from backend.vendor_payables_manual_api import ManualPayableIn, preview_manual_payable


def example(**overrides):
    data = {
        "site": "CEMPLANG",
        "vendor_code": "HOLIL",
        "invoice_number": "HLL/2026/10/18",
        "invoice_date": "2026-10-18",
        "exception_reason": "Vendor sudah mengirim barang melalui japri WA, tetapi PO formal belum pernah dibuat.",
        "source_type": "WHATSAPP_PRIVATE",
        "lines": [
            {"item_name": "Jeruk Medan", "invoiced_qty": "185", "rejected_qty": "3",
             "vendor_cost_price": "18000", "unit": "kg"},
        ],
        "commit": False,
    }
    data.update(overrides)
    return ManualPayableIn.model_validate(data)


class ManualPayableTests(unittest.TestCase):
    def test_no_po_invoice_preview_and_net(self):
        result = preview_manual_payable(example())
        self.assertFalse(result["committed"])
        self.assertTrue(result["canCommit"])
        self.assertTrue(result["noPoException"])
        self.assertIsNone(result["purchaseOrderId"])
        self.assertIsNone(result["goodsReceiptId"])
        self.assertEqual(result["grossAmount"], "3330000.00")
        self.assertEqual(result["rejectDeduction"], "54000.00")
        self.assertEqual(result["netAmount"], "3276000.00")
        self.assertEqual(result["lines"][0]["payableQty"], "182.0000")
        self.assertFalse(result["stockMovementCreated"])
        self.assertFalse(result["financeTransactionCreated"])

    def test_identity_is_deterministic(self):
        p = example()
        self.assertEqual(preview_manual_payable(p)["sourceKey"], preview_manual_payable(p)["sourceKey"])
        self.assertNotEqual(
            preview_manual_payable(p)["sourceKey"],
            preview_manual_payable(example(lines=[{
                "item_name": "Jeruk Medan", "invoiced_qty": "185",
                "rejected_qty": "2", "vendor_cost_price": "18000",
            }]))["sourceKey"],
        )

    def test_missing_identification_rejected(self):
        with self.assertRaises(ValidationError):
            example(invoice_number=None, source_ref=None)

    def test_reject_cannot_exceed_invoice(self):
        with self.assertRaises(ValidationError):
            example(lines=[{"item_name": "Jeruk Medan", "invoiced_qty": 2,
                            "rejected_qty": 3, "vendor_cost_price": 18000}])

    def test_conflicting_declared_total_blocks_commit(self):
        result = preview_manual_payable(example(declared_total=Decimal("3200000")))
        self.assertFalse(result["canCommit"])
        self.assertTrue(any("TOTAL BERBEDA" in x for x in result["warnings"]))

    def test_full_reject_blocks_zero_value_payable(self):
        result = preview_manual_payable(example(lines=[{
            "item_name": "Jeruk Medan", "invoiced_qty": 185,
            "rejected_qty": 185, "vendor_cost_price": 18000,
        }]))
        self.assertFalse(result["canCommit"])
        self.assertEqual(result["netAmount"], "0.00")


if __name__ == "__main__":
    unittest.main()
