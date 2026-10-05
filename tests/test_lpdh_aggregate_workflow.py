"""Synthetic regression checks for daily defaults and versioned payment packages."""
import sys
import unittest
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from lpdh_logic import master_target_by_group, normalize_daily_draft, validate_daily_financial_sources, compute_preview, raw_rows
from generated_document_logic import merge_final_documents, receipt_number
from generated_document_pdf import render_document_pdf
from generated_document_selftest import document


class AggregateWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.masters = {"schools": [{"schoolType": "SD/MI", "smallPortions": 10, "largePortions": 20, "staffLarge": 3},
            {"schoolType": "PAUD", "smallPortions": 100, "staffLarge": 7, "status": "Nonaktif"}],
            "posyandu": [{"balitaSmall": 4, "pregnantLarge": 2, "breastfeedingLarge": 1},
                         {"balitaSmall": 100, "status": "inactive"}], "groupTargets": {"PTK": 500, "KS-04": 500}}

    def test_active_detail_only_and_blank_defaults_explicit_zero(self):
        targets = master_target_by_group(self.masters)
        self.assertEqual(len(targets), 10)
        self.assertEqual(sum(targets.values()), 40)
        self.assertEqual(targets["PTK"], 3)
        self.assertEqual(targets["KS-04"], 0)
        daily = normalize_daily_draft(self.masters, {})
        self.assertEqual(daily["pm"]["production"], {"organoleptic": 3, "retainedSample": 2, "produced": 45})
        self.assertEqual(sum(row["received"] for row in daily["pm"]["rows"]), 40)
        self.assertTrue(all(row["bnba"] == "Ya" and not row.get("bastLink") for row in daily["pm"]["rows"]))
        supplied = {"pm": {"rows": [{"code": "KS-02", "distributed": 0, "received": 0, "bnba": "Tidak"}],
                           "production": {"organoleptic": 0, "retainedSample": 0, "produced": 0}}}
        normalized = normalize_daily_draft(self.masters, supplied)
        self.assertEqual(normalized["pm"]["rows"][1]["received"], 0)
        self.assertEqual(normalized["pm"]["rows"][1]["bnba"], "Tidak")
        self.assertEqual(normalized["pm"]["production"]["produced"], 0)
        self.assertEqual(supplied["pm"]["production"]["produced"], 0)

    def test_changed_master_refreshes_target_preserves_real_distribution_and_history(self):
        daily = normalize_daily_draft(self.masters, {})
        daily["pm"]["rows"][1].update(distributed=8, received=7)
        self.masters["schools"][0]["smallPortions"] = 99
        refreshed = normalize_daily_draft(self.masters, daily)
        row = refreshed["pm"]["rows"][1]
        self.assertEqual((row["targetPm"], row["distributed"], row["received"]), (99, 8, 7))
        frozen = normalize_daily_draft(self.masters, daily, "GENERATED")
        self.assertEqual(frozen["pm"], daily["pm"])
        self.assertEqual(compute_preview(self.masters, frozen, "2026-10-05", False)["pmRows"][1]["targetPm"], 10)

    def test_invoice_source_validation_and_manual_history(self):
        legacy = {"rawMaterials": [{"name": "Historis", "qty": 1, "price": 10}]}
        validate_daily_financial_sources(deepcopy(legacy), legacy)
        completed = deepcopy(legacy)
        completed["rawMaterials"][0].update(evidenceLink="https://example.test/authentic.pdf", paymentReference="BANK-123")
        validate_daily_financial_sources(completed, legacy)
        for key in ("rawMaterials", "operations", "volunteerPayments", "incentiveRecipients"):
            with self.assertRaises(ValueError):
                validate_daily_financial_sources({key: [{"name": "Injected", "qty": 1, "price": 10}]}, {})
        plan = {"payload": {"shoppingListJSON": {"shoppingList": [{"item": "Estimasi", "qty": 1, "price": 100}]}}}
        self.assertEqual(raw_rows({}, plan, "2026-10-05"), [])
        self.assertEqual(len(raw_rows({"_historicalGeneratedSnapshot": True}, plan, "2026-10-05")), 1)

    def test_aggregate_register_and_legacy_pdf(self):
        doc = document(1, "UPAH_RELAWAN", [(f"Relawan {i}", "Upah", 1, "hari", 1000 + i, {"role": "Pengolah"}) for i in range(3)])
        legacy_pdf = PdfReader(BytesIO(render_document_pdf(doc)))
        self.assertIn(receipt_number(doc, 0), legacy_pdf.pages[0].extract_text())
        doc["header"]["paymentSnapshotVersion"] = 2
        daily = merge_final_documents({}, [doc])
        preview = compute_preview({}, daily, "2026-10-05", False)
        rows = [r for r in preview["register"] if r["source"] == "C1_Relawan"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["amount"], doc["total"])
        self.assertEqual(rows[0]["proofStatus"], "UNIK")
        self.assertEqual([r["receiptNo"] for r in daily["volunteerPayments"]], [doc["documentNumber"]] * 3)
        pdf = PdfReader(BytesIO(render_document_pdf(doc)))
        self.assertEqual(len(pdf.pages), 2)
        self.assertNotIn("Relawan 0", pdf.pages[0].extract_text())
        self.assertIn("Relawan 0", pdf.pages[1].extract_text())
        self.assertIn("LAMPIRAN DAFTAR PENERIMA", pdf.pages[1].extract_text())

    def test_two_operational_invoices_cancel_only_matching_source(self):
        docs = [document(i, "OPERASIONAL", [("Gas", "Gas", 1, "tabung", 100 * i, {})]) for i in (1, 2)]
        initial = {"operations": [{"description": "Historis", "qty": 1, "price": 20, "invoiceNo": "OLD"}]}
        daily = merge_final_documents(initial, docs)
        self.assertEqual(merge_final_documents(daily, docs), daily)
        self.assertEqual([r["sourceDocumentId"] for r in daily["operations"] if r.get("sourceDocumentId")], [1, 2])
        docs[0]["status"] = "CANCELLED"
        reduced = merge_final_documents(daily, docs)
        self.assertEqual(reduced["operations"][0], initial["operations"][0])
        self.assertEqual([r["sourceDocumentId"] for r in reduced["operations"] if r.get("sourceDocumentId")], [2])
        self.assertEqual(compute_preview({}, reduced, "2026-10-05", False)["operationalTotal"], 220)


if __name__ == "__main__":
    unittest.main()
