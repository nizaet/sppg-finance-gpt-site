from parser.parser_v04 import parse_message


def test_payment_intent_is_not_paid():
    result = parse_message("Nanti saya transfer ya")
    assert result["event_type"] == "PAYMENT_INTENT"
    assert result["requires_confirmation"] is True


def test_payment_evidence_is_candidate_only():
    result = parse_message("Pak haji udah di transfer ya")
    assert result["event_type"] == "PAYMENT_EVIDENCE_CANDIDATE"
    assert result["requires_confirmation"] is True


def test_po_revision_detected():
    result = parse_message("Tambahan wortel 2 kg untuk Maja")
    assert result["event_type"] == "PO_REVISION"
    assert result["site"] == "MAJA"


def test_koperasi_transfer_is_not_purchase():
    result = parse_message("Stok Koperasi kirim minyak 20 liter ke Maja")
    assert result["event_type"] == "KOPERASI_STOCK_TRANSFER_REQUEST"
    assert result["site"] == "MAJA"


def test_reject_detected():
    result = parse_message("Edamame reject 4 kg, tolong ditimbang")
    assert result["event_type"] == "QUALITY_REJECT_REPORTED"


def test_acknowledgement_only():
    result = parse_message("Siap")
    assert result["event_type"] == "ACKNOWLEDGEMENT_ONLY"
    assert result["requires_confirmation"] is False


def test_vendor_inference_holil():
    result = parse_message("Pak Holil tambahan jeruk 10 kg")
    assert result["vendor"] == "HOLIL"
    assert result["event_type"] == "PO_REVISION"


def test_unknown_message_requires_review():
    result = parse_message("Nanti ngobrol lagi")
    assert result["event_type"] == "UNCLASSIFIED"
    assert result["requires_confirmation"] is True
