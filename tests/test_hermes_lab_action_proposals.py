from hermes_lab.app import LabActionProposalRequest, app


def test_gateway_exposes_explicit_proposal_route_but_no_approval_or_execution():
    paths = {route.path for route in app.routes}
    assert "/v1/lab/proposals" in paths
    assert all("approve" not in path.lower() for path in paths)
    assert all("execute" not in path.lower() for path in paths)


def test_gateway_proposal_model_uses_strict_action_allowlist():
    proposal = LabActionProposalRequest(
        source_ref="hermes:test:gateway",
        action_type="RECORD_RECEIVING",
        site="MAJA",
        target_type="goods_receipt",
        rationale="Prepare a receiving proposal for operator review.",
    )
    assert proposal.action_type == "RECORD_RECEIVING"
    assert proposal.payload == {}
