from unittest.mock import patch

from backend import accountant_document_api as api


def test_invoice_fallback_reads_indonesian_number_and_category() -> None:
    parsed = api._fallback_invoice(
        """Nomor Invoice : 167/IM/DMM/VIII/2026
        Tanggal : 27 Agustus 2026
        Insentif Mitra 1 hari 6.000.000
        TOTAL Rp 6.000.000"""
    )
    assert parsed["invoice_number"] == "167/IM/DMM/VIII/2026"
    assert parsed["invoice_amount"] == 6_000_000
    assert parsed["category"] == "SEWA_MITRA"


def test_approval_matches_reference_before_amount() -> None:
    makers = [
        {"maker_id": 7, "site": "MAJA", "reference_number": "167/IM/DMM/VIII/2026", "amount": 6_000_000, "approval_status": "PENDING"},
        {"maker_id": 8, "site": "MAJA", "reference_number": "168/IM/DMM/VIII/2026", "amount": 6_000_000, "approval_status": "PENDING"},
    ]
    parsed = {"transactions": [{"reference_number": "167/IM/DMM/VIII/2026", "amount": 6_000_000, "status": "Success"}]}
    with patch.object(api, "_maker_candidates", return_value=makers):
        result = api._match_transactions(parsed, "MAJA")
    assert result[0]["matchedMakerId"] == 7
    assert result[0]["matchMethod"] == "REFERENCE_EXACT"
    assert result[0]["willApprove"] is True


def test_approval_does_not_approve_pending_bank_transaction() -> None:
    makers = [{"maker_id": 9, "site": "CEMPLANG", "reference_number": "94/OP/DMM/VIII/2026", "amount": 1_003_000, "approval_status": "PENDING"}]
    parsed = {"transactions": [{"reference_number": "94/OP/DMM/VIII/2026", "amount": 1_003_000, "status": "PENDING"}]}
    with patch.object(api, "_maker_candidates", return_value=makers):
        result = api._match_transactions(parsed, "CEMPLANG")
    assert result[0]["matchedMakerId"] == 9
    assert result[0]["willApprove"] is False


def test_mandiri_status_pdf_without_time_reads_every_wrapped_row() -> None:
    # Actual Jasper/BNI exports put Reference No. directly after the date, not
    # after a clock value.  The beneficiary reference year can be wrapped into
    # a different visual column too.
    text = """TRANSACTION STATUS
Reference No.
11-Sep-2026 20260911145646842629 BB7SEPT26 IDR 19,776,000.00 KOPERASI 205/BB/MMD/IX/ Immediate 11-Sep-2026 Berhasil
2026 15:30:38 Dijalankan
11-Sep-2026 20260911145919843671 UPAHDLL IDR 8,948,000.00 DERMAWAN 43/OP/DMM/IX/2 Immediate 11-Sep-2026 Berhasil
026 15:30:38 Dijalankan
11-Sep-2026 20260911145755843101 BPJS IDR 789,599.00 DERMAWAN 9/BPJS/DMM/IX/ 2026 11-Sep-2026 Berhasil
"""
    rows = api._mandiri_status_transactions(text)
    assert [(row["transaction_id"], row["reference_number"], row["amount"], row["status"]) for row in rows] == [
        ("20260911145646842629", "205/BB/MMD/IX/2026", 19_776_000.0, "SUCCESS"),
        ("20260911145919843671", "43/OP/DMM/IX/2026", 8_948_000.0, "SUCCESS"),
        ("20260911145755843101", "9/BPJS/DMM/IX/2026", 789_599.0, "SUCCESS"),
    ]


def test_date_range_uses_period_end_as_invoice_date_without_false_fallback_warning() -> None:
    fallback = api._fallback_invoice("")
    parsed = {
        "invoice_number": "93/OP/DMM/VIII/2026",
        "period_start": "2026-08-17",
        "period_end": "2026-08-21",
        "invoice_amount": 10_990_700,
        "lines": [],
        "confidence": 0.98,
    }
    result = api._normalize_invoice(parsed, fallback, "CEMPLANG", "OPERASIONAL_LAIN")
    assert result["invoiceDate"] == "2026-08-21"
    assert result["dateDerivedFromPeriod"] is True
    assert result["warnings"] == []


def test_direct_invoice_never_creates_maker_by_default() -> None:
    payload = api.DirectInvoiceIn(
        file_name="invoice.jpg",
        mime_type="image/jpeg",
        content_base64="YQ==",
        site="MAJA",
        category="SEWA_MITRA",
        invoice_number="168/IM/DMM/VIII/2026",
        invoice_date="2026-08-28",
        invoice_amount=6_000_000,
        commit=True,
    )
    assert payload.create_maker is False
