import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

import hermes_lab.app as hermes_gateway
from hermes_lab.app import LabActionProposalRequest, app


class HermesLabActionProposalTests(unittest.TestCase):
    def test_gateway_exposes_proposal_but_no_approval_or_execution(self):
        paths = {route.path for route in app.routes}
        self.assertIn("/v1/lab/proposals", paths)
        self.assertIn("/v1/lab/purchase-orders", paths)
        self.assertTrue(all("approve" not in path.lower() for path in paths))
        self.assertTrue(all("execute" not in path.lower() for path in paths))

    def test_gateway_openapi_exposes_authenticated_read_only_po_search(self):
        schema = app.openapi()
        operation = schema["paths"]["/v1/lab/purchase-orders"]["get"]
        parameters = {parameter["name"] for parameter in operation["parameters"]}

        self.assertEqual("search_purchase_orders_read_only_v1_lab_purchase_orders_get", operation["operationId"])
        self.assertTrue({"site", "vendor", "distributionDate", "dateFrom", "dateTo", "status", "limit"}.issubset(parameters))

        custom_schema = Path("hermes_lab/openapi.yaml").read_text(encoding="utf-8")
        self.assertIn("operationId: searchHermesSppgPurchaseOrders", custom_schema)
        self.assertIn("READ-ONLY", custom_schema)

    def test_gateway_bearer_auth_accepts_active_lab_key_only(self):
        original = hermes_gateway.LAB_GATEWAY_KEY
        hermes_gateway.LAB_GATEWAY_KEY = "unit-test-lab-key"
        try:
            hermes_gateway._authorize("Bearer unit-test-lab-key")
            hermes_gateway._authorize("bearer unit-test-lab-key")
            with self.assertRaises(HTTPException) as raised:
                hermes_gateway._authorize("Bearer wrong-key")
            self.assertEqual(401, raised.exception.status_code)
        finally:
            hermes_gateway.LAB_GATEWAY_KEY = original

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


class HermesLabReadOnlySearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_po_search_proxies_site_vendor_and_inclusive_date_range(self):
        captured = {}

        class FakeResponse:
            status_code = 200

            @staticmethod
            def json():
                return {"items": [{"purchase_order_id": 123}], "count": 1}

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, url, *, params, headers):
                captured.update({"url": url, "params": params, "headers": headers})
                return FakeResponse()

        original_values = (
            hermes_gateway.LAB_GATEWAY_KEY,
            hermes_gateway.SPPG_CORE_URL,
            hermes_gateway.SPPG_GPT_API_KEY,
        )
        hermes_gateway.LAB_GATEWAY_KEY = "lab-key"
        hermes_gateway.SPPG_CORE_URL = "https://sppg-core.example"
        hermes_gateway.SPPG_GPT_API_KEY = "core-key"
        try:
            with patch.object(hermes_gateway.httpx, "AsyncClient", return_value=FakeClient()):
                result = await hermes_gateway.search_purchase_orders_read_only(
                    authorization="Bearer lab-key",
                    site="MAJA",
                    vendor="WIKIAN",
                    distribution_date=None,
                    date_from=date(2026, 8, 23),
                    date_to=date(2026, 8, 26),
                    status="",
                    limit=50,
                )
        finally:
            (
                hermes_gateway.LAB_GATEWAY_KEY,
                hermes_gateway.SPPG_CORE_URL,
                hermes_gateway.SPPG_GPT_API_KEY,
            ) = original_values

        self.assertEqual("https://sppg-core.example/v1/purchase-orders/search", captured["url"])
        self.assertEqual("MAJA", captured["params"]["site"])
        self.assertEqual("WIKIAN", captured["params"]["vendor"])
        self.assertEqual("2026-08-23", captured["params"]["dateFrom"])
        self.assertEqual("2026-08-26", captured["params"]["dateTo"])
        self.assertEqual("Bearer core-key", captured["headers"]["Authorization"])
        self.assertTrue(result["readOnly"])
        self.assertEqual("SPPG Core PostgreSQL", result["sourceOfTruth"])


if __name__ == "__main__":
    unittest.main()
