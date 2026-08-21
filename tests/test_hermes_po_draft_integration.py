from __future__ import annotations

import os
import unittest
import uuid

from backend.db import connection
from backend.hermes_action_api import (
    HermesActionDecisionIn,
    HermesActionProposalIn,
    create_hermes_action_proposal,
    decide_hermes_action_proposal,
    execute_owner_hermes_po_draft,
)


@unittest.skipUnless(os.getenv("DATABASE_URL"), "DATABASE_URL is required")
class HermesPoDraftIntegrationTests(unittest.TestCase):
    def test_approved_create_po_is_atomic_draft_only_and_idempotent(self):
        suffix = uuid.uuid4().hex[:12].upper()
        proposal = HermesActionProposalIn(
            source_ref=f"hermes:integration:{suffix}",
            action_type="CREATE_PO",
            site="CEMPLANG",
            vendor_code="HOLIL",
            target_type="purchase_order",
            rationale="CI verifies the owner-only DRAFT executor boundary.",
            confidence=1,
            payload={
                "po_code": f"PO-CEMPLANG-20991220-HOLIL-{suffix}",
                "distribution_date": "2099-12-20",
                "cooking_at": "2099-12-19T03:00:00+07:00",
                "status": "DRAFT",
                "items": [
                    {
                        "item_name": f"CI Wortel {suffix}",
                        "planned_qty": 10,
                        "po_qty": 9.5,
                        "unit": "kg",
                    }
                ],
            },
        )
        staged = create_hermes_action_proposal(proposal)
        action_id = int(staged["actionId"])
        proposal_id = int(staged["proposalId"])
        source_id = None
        purchase_order_id = None

        try:
            decision = decide_hermes_action_proposal(
                action_id,
                HermesActionDecisionIn(
                    decision="APPROVE",
                    actor="ci-owner",
                    note="Approved only for the isolated CI database.",
                ),
            )
            self.assertEqual("VALIDATED", decision["candidateStatus"])
            self.assertEqual("READY", decision["actionStatus"])
            self.assertFalse(decision["executed"])

            result = execute_owner_hermes_po_draft(action_id)
            purchase_order_id = int(result["purchaseOrderId"])
            self.assertEqual("DRAFT", result["purchaseOrderStatus"])
            self.assertTrue(result["createdNow"])
            self.assertFalse(result["finalizedByExecutor"])
            self.assertFalse(result["markedSentByExecutor"])
            self.assertFalse(result["whatsAppSentByExecutor"])

            with connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """select status,finalized_at,sent_at,source_type,source_external_id
                           from purchase_orders where id=%s""",
                        (purchase_order_id,),
                    )
                    po = cur.fetchone()
                    self.assertEqual("DRAFT", po["status"])
                    self.assertIsNone(po["finalized_at"])
                    self.assertIsNone(po["sent_at"])
                    self.assertEqual("HERMES_APPROVED", po["source_type"])
                    self.assertEqual(f"workflow-action:{action_id}", po["source_external_id"])
                    cur.execute(
                        """select ce.status as candidate_status,wa.status as action_status,
                                  wa.target_id,wa.applied_by,ce.source_id
                           from workflow_actions wa
                           join candidate_events ce on ce.id=wa.candidate_event_id
                           where wa.id=%s""",
                        (action_id,),
                    )
                    workflow = cur.fetchone()
                    source_id = int(workflow["source_id"])
                    self.assertEqual("APPLIED", workflow["candidate_status"])
                    self.assertEqual("APPLIED", workflow["action_status"])
                    self.assertEqual(str(purchase_order_id), workflow["target_id"])
                    self.assertEqual("owner-ui", workflow["applied_by"])

            replay = execute_owner_hermes_po_draft(action_id)
            self.assertEqual(purchase_order_id, int(replay["purchaseOrderId"]))
            self.assertTrue(replay["idempotent"])
            self.assertFalse(replay["createdNow"])
        finally:
            with connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("delete from event_audit_log where workflow_action_id=%s", (action_id,))
                    if purchase_order_id is not None:
                        cur.execute(
                            """delete from purchase_order_coverage_items
                               where purchase_order_coverage_id in (
                                 select id from purchase_order_coverage where purchase_order_id=%s
                               )""",
                            (purchase_order_id,),
                        )
                        cur.execute("delete from purchase_order_coverage where purchase_order_id=%s", (purchase_order_id,))
                        cur.execute("delete from purchase_order_items where purchase_order_id=%s", (purchase_order_id,))
                        cur.execute("delete from purchase_orders where id=%s", (purchase_order_id,))
                    cur.execute("delete from workflow_actions where id=%s", (action_id,))
                    cur.execute("delete from candidate_events where id=%s", (proposal_id,))
                    if source_id is not None:
                        cur.execute("delete from ingest_sources where id=%s", (source_id,))
                conn.commit()


if __name__ == "__main__":
    unittest.main()
