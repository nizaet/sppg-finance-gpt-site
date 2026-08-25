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

