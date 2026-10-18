"""Tests of the OWNER change-ticket guard with no operational DB writes."""
import unittest
from unittest.mock import AsyncMock, patch

from plugin_mcp.approval_workflow import (
    ChangeRequest, _preview, confirm_change, CONTROL_ACTIONS,
)
from plugin_mcp.v0186_tools import createSppgAccountantTransactions


class TicketCursor:
    def __init__(self, state):
        self.state = state
        self.next_row = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        sql = " ".join(sql.lower().split())
        self.next_row = None
        if "select * from sppg_mcp_approvals" in sql:
            self.next_row = dict(self.state)
        elif "set status='executing'" in sql and self.state["status"] == "PENDING":
            self.state["status"] = "EXECUTING"
            self.next_row = {"id": self.state["id"]}
        elif "set status=%s" in sql and self.state["status"] == "EXECUTING":
            self.state["status"] = params[0]
            self.state["result_data"] = __import__("json").loads(params[1])
        elif "set status='declined'" in sql:
            self.state["status"] = "DECLINED"

    def fetchone(self):
        return self.next_row


class TicketConnection:
    def __init__(self, state):
        self.state = state

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return TicketCursor(self.state)

    def commit(self):
        return None


class ApprovalTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_unlisted_action_can_be_prepared(self):
        self.assertNotIn("ARBITRARY_SQL", CONTROL_ACTIONS)
        change = ChangeRequest(
            action="ARBITRARY_SQL", payload={"sql": "DROP TABLE finance_transactions"},
            site="MAJA", reason="must be blocked",
        )
        with self.assertRaisesRegex(ValueError, "allowlist"):
            await _preview(change)

    async def test_cross_site_payload_fails_before_network(self):
        change = ChangeRequest(
            action="CREATE_PO", payload={"site": "CEMPLANG"},
            site="MAJA", reason="must be blocked",
        )
        with self.assertRaisesRegex(ValueError, "Cross-site"):
            await _preview(change)

    async def test_private_whatsapp_reconstruction_needs_original_evidence(self):
        change = ChangeRequest(
            action="IMPORT_WHATSAPP_PO",
            payload={"site": "MAJA", "vendor_code": "HOLIL", "distribution_date": "2026-10-18",
                     "source_type": "WHATSAPP_PRIVATE", "po_lines": []},
            site="MAJA", reason="missing actual forwarded message",
        )
        with self.assertRaisesRegex(ValueError, "Original WhatsApp"):
            await _preview(change)

    async def test_payment_preview_warns_about_auto_accountant_write(self):
        change = ChangeRequest(
            action="RECORD_VENDOR_PAYMENT", payload={
                "site": "MAJA", "vendor_code": "HOLIL", "amount": 50000,
                "reference_number": "test-reference",
            },
            site="MAJA", reason="verification",
        )
        with patch("plugin_mcp.approval_workflow.core_request",
                   new_callable=AsyncMock, return_value={"canCommit": True, "amount": 50000}) as request:
            preview, before, impact = await _preview(change)
        self.assertIn("AUTO CREATES", impact["finance"])
        self.assertFalse(request.call_args.kwargs["json_body"]["commit"])

    async def test_confirm_gate_closed_does_not_execute(self):
        state = {
            "id": "46ca5d44-c746-437a-aef6-5fcecb384006",
            "status": "PENDING", "operator_sub": "SPPG_OWNER",
            "site": "CEMPLANG", "action": "CREATE_NO_PO_PAYABLE",
            "reason": "test", "proposed_payload": {}, "preview_data": {},
            "before_hash": None, "expires_at": __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ) + __import__("datetime").timedelta(minutes=9),
            "result_data": None,
        }
        with patch("plugin_mcp.approval_workflow._db_ready"), \
             patch("plugin_mcp.approval_workflow._ensure_table"), \
             patch("plugin_mcp.approval_workflow.connection", return_value=TicketConnection(state)), \
             patch("plugin_mcp.approval_workflow.operational_writes_enabled", return_value=False), \
             patch("plugin_mcp.approval_workflow._execute", new_callable=AsyncMock) as execute:
            response = await confirm_change(state["id"], "CONFIRM")
        self.assertEqual(response["status"], "WRITE_GATE_CLOSED")
        self.assertEqual(state["status"], "PENDING")
        execute.assert_not_called()

    async def test_approved_change_claimed_once_then_replay_blocked(self):
        from datetime import datetime, timedelta, timezone
        state = {
            "id": "8e9270f0-67a1-4992-8ff9-0b7fa786e73c",
            "status": "PENDING", "operator_sub": "SPPG_OWNER",
            "site": "MAJA", "action": "CREATE_PO", "reason": "test",
            "proposed_payload": {"site": "MAJA", "po_code": "TEST-NOT-COMMITTED"},
            "preview_data": {"canCommit": True, "committed": False},
            "before_hash": None, "expires_at": datetime.now(timezone.utc)+timedelta(minutes=9),
            "result_data": None,
        }
        with patch("plugin_mcp.approval_workflow._db_ready"), \
             patch("plugin_mcp.approval_workflow._ensure_table"), \
             patch("plugin_mcp.approval_workflow.connection", return_value=TicketConnection(state)), \
             patch("plugin_mcp.approval_workflow.operational_writes_enabled", return_value=True), \
             patch("plugin_mcp.approval_workflow._preview",
                   new_callable=AsyncMock, return_value=({"canCommit":True,"committed":False},None,{})), \
             patch("plugin_mcp.approval_workflow._execute",
                   new_callable=AsyncMock, return_value={"committed":True,"purchaseOrderId":12345}) as execute:
            first = await confirm_change(state["id"], "CONFIRM")
            second = await confirm_change(state["id"], "CONFIRM")
        self.assertEqual(first["status"], "APPLIED")
        self.assertTrue(first["committed"])
        self.assertEqual(second["status"], "APPLIED")
        self.assertEqual(execute.await_count, 1)

    async def test_legacy_direct_finance_write_always_blocked(self):
        with patch("plugin_mcp.core_proxy.operational_writes_enabled", return_value=True):
            result = await createSppgAccountantTransactions({
                "site":"MAJA","items":[{"description":"test","amount":1}]
            })
        self.assertEqual(result["status"], "WRITE_GATE_CLOSED")
        self.assertFalse(result["committed"])


if __name__ == "__main__":
    unittest.main()
