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
