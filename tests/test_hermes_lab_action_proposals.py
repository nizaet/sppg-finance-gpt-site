import unittest

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


if __name__ == "__main__":
    unittest.main()
