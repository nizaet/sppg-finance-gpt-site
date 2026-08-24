import inspect
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import ValidationError
from starlette.requests import Request

import backend.hermes_action_api as hermes_action_api
from backend.auth_api import issue_session
from backend.auth_middleware import _auth_context


def _po_payload(**overrides):
    values = {
        "po_code": "PO-CEMPLANG-20260822-HOLIL",
        "distribution_date": "2026-08-22",
        "cooking_at": "2026-08-21T03:00:00+07:00",
        "status": "DRAFT",
        "items": [
            {
                "item_name": "Wortel",
                "planned_qty": 10,
                "po_qty": 10,
                "unit": "kg",
            }
        ],
    }
    values.update(overrides)
    return values


def _proposal(**overrides):
    values = {
        "source_ref": "hermes:test:001",
        "action_type": "CREATE_PO",
        "site": "CEMPLANG",
        "vendor_code": "HOLIL",
        "target_type": "purchase_order",
        "rationale": "Operator asked Hermes to prepare a PO proposal.",
        "confidence": 0.9,
        "payload": _po_payload(),
    }
    values.update(overrides)
    return hermes_action_api.HermesActionProposalIn(**values)


class HermesActionApiTests(unittest.TestCase):
    def test_proposal_keys_are_stable_and_payload_sensitive(self):
        first = hermes_action_api.proposal_keys(_proposal())
        replay = hermes_action_api.proposal_keys(_proposal())
        changed = hermes_action_api.proposal_keys(
            _proposal(payload=_po_payload(
                po_code="PO-CEMPLANG-20260823-HOLIL",
                distribution_date="2026-08-23",
            ))
        )

        self.assertEqual(first, replay)
        self.assertNotEqual(first, changed)
        self.assertTrue(first[0].startswith("hermes-proposal:"))
        self.assertTrue(first[1].startswith("hermes-action:"))

    def test_action_type_is_strictly_allowlisted(self):
        with self.assertRaises(ValidationError):
            _proposal(action_type="DELETE_DATABASE")

    def test_approval_requires_separate_key(self):
        with patch.dict(os.environ, {"SPPG_HERMES_APPROVAL_KEY": "approval-secret"}):
            with self.assertRaises(HTTPException) as exc:
                hermes_action_api.require_hermes_approval_auth(
                    HTTPAuthorizationCredentials(
                        scheme="Bearer",
                        credentials="gpt-or-hermes-key",
                    )
                )
            self.assertEqual(exc.exception.status_code, 403)

            hermes_action_api.require_hermes_approval_auth(
                HTTPAuthorizationCredentials(
                    scheme="Bearer",
                    credentials="approval-secret",
                )
            )

    def test_hermes_cannot_be_named_as_approver(self):
        with self.assertRaises(ValidationError):
            hermes_action_api.HermesActionDecisionIn(
                decision="APPROVE",
                actor="hermes-agent",
            )

    def test_create_po_requires_complete_strict_draft_payload(self):
        proposal = _proposal()
        self.assertEqual(proposal.vendor_code, "HOLIL")
        self.assertEqual(proposal.payload["status"], "DRAFT")
        self.assertEqual(proposal.payload["items"][0]["po_qty"], 10.0)

        with self.assertRaises(ValidationError):
            _proposal(payload=_po_payload(items=[]))
        with self.assertRaises(ValidationError):
            _proposal(payload=_po_payload(items=[{"item_name": "Wortel", "po_qty": 0, "unit": "kg"}]))
        with self.assertRaises(ValidationError):
            _proposal(payload={**_po_payload(), "execute_immediately": True})
        with self.assertRaises(ValidationError):
            _proposal(target_type="finance_transaction")
        with self.assertRaises(ValidationError):
            _proposal(target_id="99")

    def test_multi_day_coverage_must_match_aggregate_items(self):
        coverage = [
            {
                "distribution_date": "2026-08-22",
                "cooking_date": "2026-08-21",
                "items": [{"item_name": "Wortel", "po_qty": 4, "unit": "kg"}],
            },
            {
                "distribution_date": "2026-08-23",
                "cooking_date": "2026-08-22",
                "items": [{"item_name": "Wortel", "po_qty": 6, "unit": "kg"}],
            },
        ]
        proposal = _proposal(payload=_po_payload(coverage=coverage))
        self.assertEqual(len(proposal.payload["coverage"]), 2)

        broken = [*coverage]
        broken[1] = {**broken[1], "items": [{"item_name": "Wortel", "po_qty": 5, "unit": "kg"}]}
        with self.assertRaises(ValidationError):
            _proposal(payload=_po_payload(coverage=broken))

    def test_only_owner_route_can_create_po_draft(self):
        gpt_paths = {route.path for route in hermes_action_api.router.routes}
        owner_paths = {route.path for route in hermes_action_api.owner_router.routes}
        self.assertIn("/gpt/hermes-actions/proposals", gpt_paths)
        self.assertIn("/gpt/hermes-actions/proposals/{action_id}/decision", gpt_paths)
        self.assertTrue(all("create-po-draft" not in path for path in gpt_paths))
        self.assertIn("/hermes-actions/proposals", owner_paths)
        self.assertIn("/hermes-actions/proposals/{action_id}/decision", owner_paths)
        self.assertIn("/hermes-actions/proposals/{action_id}/po-draft-preview", owner_paths)
        self.assertIn("/hermes-actions/proposals/{action_id}/create-po-draft", owner_paths)

        source = inspect.getsource(hermes_action_api).lower()
        forbidden_writes = (
            "insert into purchase_orders",
            "insert into goods_receipts",
            "insert into vendor_payments",
            "insert into finance_transactions",
            "insert into inventory_ledger",
        )
        self.assertTrue(all(statement not in source for statement in forbidden_writes))
        executor_source = inspect.getsource(hermes_action_api.execute_owner_hermes_po_draft)
        self.assertIn("create_purchase_order_record", executor_source)
        self.assertIn("candidate_status\"] != \"VALIDATED\"", executor_source)
        self.assertIn("action_status\"] != \"READY\"", executor_source)
        self.assertIn("purchaseOrderStatus\": \"DRAFT\"", executor_source)
        self.assertNotIn("finalize_purchase_order", executor_source)
        self.assertNotIn("mark_purchase_order_sent", executor_source)

    def test_owner_route_requires_owner_state(self):
        owner_request = Request({
            "type": "http",
            "state": {"sppg_role": "OWNER", "sppg_auth_kind": "SESSION"},
        })
        hermes_action_api.require_owner_request(owner_request)

        kitchen_request = Request({
            "type": "http",
            "state": {"sppg_role": "MAJA", "sppg_auth_kind": "SESSION"},
        })
        with self.assertRaises(HTTPException) as exc:
            hermes_action_api.require_owner_request(kitchen_request)
        self.assertEqual(exc.exception.status_code, 403)

        gpt_owner_request = Request({
            "type": "http",
            "state": {"sppg_role": "OWNER", "sppg_auth_kind": "GPT_KEY"},
        })
        with self.assertRaises(HTTPException) as exc:
            hermes_action_api.require_owner_request(gpt_owner_request)
        self.assertEqual(exc.exception.status_code, 403)

    def test_gpt_key_cannot_become_owner_browser_session(self):
        with patch.dict(
            os.environ,
            {
                "SPPG_GPT_API_KEY": "ci-gpt-key",
                "SPPG_AUTH_SECRET": "ci-session-secret",
                "SPPG_OWNER_PASSWORD": "ci-owner-password",
            },
        ):
            self.assertEqual(("OWNER", "GPT_KEY"), _auth_context("Bearer ci-gpt-key"))
            token, _ = issue_session("OWNER")
            self.assertEqual(("OWNER", "SESSION"), _auth_context(f"Bearer {token}"))

    def test_owner_decision_payload_cannot_override_actor(self):
        with self.assertRaises(ValidationError):
            hermes_action_api.OwnerHermesActionDecisionIn(
                decision="APPROVE",
                note="reviewed",
                actor="hermes",
            )

    def test_generic_review_queue_excludes_hermes_proposals(self):
        source = Path("backend/app.py").read_text(encoding="utf-8")
        self.assertIn("event_type not like 'HERMES_PROPOSAL_%'", source)
        self.assertIn("event_type not like 'HERMES_PROPOSAL_%%'", source)


if __name__ == "__main__":
    unittest.main()
