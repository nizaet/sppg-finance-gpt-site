from workflow.workflow_service_v06 import (
    CandidateEvent,
    Decision,
    build_domain_command,
    validate_candidate,
)


def make_event(**overrides):
    base = dict(
        event_type="PO_ACKNOWLEDGED",
        source_type="whatsapp",
        source_id="drive-chat-holil",
        source_message_id="msg-001",
        site="MAJA",
        actor="HOLIL",
        vendor="HOLIL",
        confidence=0.98,
        requires_confirmation=False,
        payload={},
    )
    base.update(overrides)
    return CandidateEvent(**base)


def test_safe_high_confidence_event_can_auto_accept():
    result = validate_candidate(make_event())
    assert result.decision == Decision.AUTO_ACCEPT


def test_payment_never_auto_accepts_from_parser_alone():
    event = make_event(
        event_type="PAYMENT_EVIDENCE_CANDIDATE",
        confidence=0.99,
        requires_confirmation=False,
    )
    result = validate_candidate(event)
    assert result.decision == Decision.REQUIRE_REVIEW


def test_parser_confirmation_flag_forces_review():
    result = validate_candidate(make_event(requires_confirmation=True))
    assert result.decision == Decision.REQUIRE_REVIEW


def test_low_confidence_forces_review():
    result = validate_candidate(make_event(confidence=0.72))
    assert result.decision == Decision.REQUIRE_REVIEW


def test_invalid_confidence_is_rejected():
    result = validate_candidate(make_event(confidence=1.2))
    assert result.decision == Decision.REJECT


def test_idempotency_key_is_stable():
    a = make_event()
    b = make_event()
    assert a.idempotency_key == b.idempotency_key


def test_different_message_changes_idempotency_key():
    a = make_event(source_message_id="msg-001")
    b = make_event(source_message_id="msg-002")
    assert a.idempotency_key != b.idempotency_key


def test_stock_transfer_maps_to_stock_movement_not_expense():
    event = make_event(event_type="KOPERASI_STOCK_TRANSFER_REQUEST", vendor="KOPERASI")
    command = build_domain_command(event)
    assert command is not None
    assert command.aggregate_type == "stock_movement"
    assert command.command_type == "CREATE_STOCK_TRANSFER"


def test_po_revision_maps_to_revision_command():
    command = build_domain_command(make_event(event_type="PO_REVISION"))
    assert command is not None
    assert command.command_type == "CREATE_PO_REVISION"


def test_unknown_event_has_no_domain_command():
    assert build_domain_command(make_event(event_type="UNKNOWN_EVENT")) is None
