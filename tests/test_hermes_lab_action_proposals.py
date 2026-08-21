import unittest

from pydantic import ValidationError

from hermes_lab.app import LabActionProposalRequest, app


class HermesLabActionProposalTests(unittest.TestCase):
    def test_gateway_exposes_proposal_but_no_approval_or_execution(self):
        paths = {route.path for route in app.routes}
        self.assertIn("/v1/lab/proposals", paths)
        self.assertTrue(all("approve" not in path.lower() for path in paths))
        self.assertTrue(all("execute" not in path.lower() for path in paths))

    def test_gateway_proposal_model_uses_strict_action_allowlist(self):
        proposal = LabActionProposalRequest(
            source_ref="hermes:test:gateway",
            action_type="RECORD_RECEIVING",
            site="MAJA",
            target_type="goods_receipt",
            rationale="Prepare a receiving proposal for operator review.",
        )
        self.assertEqual(proposal.action_type, "RECORD_RECEIVING")
        self.assertEqual(proposal.payload, {})

    def test_gateway_requires_canonical_create_po_draft(self):
        proposal = LabActionProposalRequest(
            source_ref="hermes:test:po-draft",
            action_type="CREATE_PO",
            site="MAJA",
            vendor_code="holil",
            target_type="purchase_order",
            rationale="Prepare an exact draft PO for owner review.",
            payload={
                "po_code": "PO-MAJA-20260822-HOLIL",
                "distribution_date": "2026-08-22",
                "status": "DRAFT",
                "items": [{"item_name": "Wortel", "po_qty": 10, "unit": "kg"}],
            },
        )
        self.assertEqual(proposal.vendor_code, "HOLIL")
        self.assertEqual(proposal.payload["status"], "DRAFT")

        with self.assertRaises(ValidationError):
            LabActionProposalRequest(
                source_ref="hermes:test:invalid-po",
                action_type="CREATE_PO",
                site="MAJA",
                vendor_code="HOLIL",
                target_type="purchase_order",
                rationale="Incomplete payload must be rejected.",
                payload={"distribution_date": "2026-08-22"},
            )


if __name__ == "__main__":
    unittest.main()
