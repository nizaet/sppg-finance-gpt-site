"""HTTP-level tests for OAuth discovery and the MCP bearer gate."""
import os
import unittest
from unittest.mock import patch

from starlette.testclient import TestClient

from plugin_mcp.oauth_server import (
    CHATGPT_STABLE_REDIRECT,
    DCR_CLIENT_ID,
    issue_access_token,
)
from plugin_mcp.server import app, LEGACY_V0186_TOOL_NAMES


ISSUER = "https://mcp.example.test"
RESOURCE = ISSUER + "/mcp"
CONFIG = {
    "SPPG_OAUTH_ISSUER": ISSUER,
    "SPPG_OAUTH_AUDIENCE": RESOURCE,
    "SPPG_OAUTH_JWKS_URL": ISSUER + "/jwks.json",
    "SPPG_OAUTH_RESOURCE_URL": RESOURCE,
    "SPPG_OAUTH_ALLOWED_SUBJECTS": "SPPG_OWNER",
    "SPPG_OAUTH_SCOPE": "sppg:read",
    "SPPG_OAUTH_PRIVATE_KEY_B64": "gateway-test-secret-" + ("z" * 64),
}


class GatewayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = patch.dict(os.environ, CONFIG, clear=False)
        cls.env.start()
        cls.client_context = TestClient(app)
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)
        cls.env.stop()

    def test_health_proves_token_round_trip(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["oauthReady"])
        self.assertEqual(body["mode"], "v0186-parity-operational-preview")
        self.assertTrue(body["legacyV0186Parity"])
        self.assertEqual(body["legacyV0186ToolCount"], 30)
        self.assertTrue(body["knowledgeLearningEnabled"])
        self.assertFalse(body["operationalWritesEnabled"])

    def test_protected_resource_metadata(self):
        response = self.client.get("/.well-known/oauth-protected-resource")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["resource"], RESOURCE)
        self.assertEqual(body["authorization_servers"], [ISSUER])
        self.assertEqual(body["scopes_supported"], ["sppg:read"])

    def test_authorization_server_metadata(self):
        response = self.client.get("/.well-known/oauth-authorization-server")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["issuer"], ISSUER)
        self.assertEqual(body["authorization_endpoint"], ISSUER + "/authorize")
        self.assertEqual(body["token_endpoint"], ISSUER + "/token")
        self.assertTrue(body["authorization_response_iss_parameter_supported"])
        self.assertTrue(body["client_id_metadata_document_supported"])
        self.assertIn("S256", body["code_challenge_methods_supported"])

    def test_oidc_discovery_is_disabled(self):
        response = self.client.get("/.well-known/openid-configuration")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "OpenID Connect is not enabled")

    def test_mcp_without_token_challenges_oauth(self):
        response = self.client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        self.assertEqual(response.status_code, 401)
        challenge = response.headers.get("www-authenticate", "")
        self.assertIn("/.well-known/oauth-protected-resource", challenge)
        self.assertIn('scope="sppg:read"', challenge)

    def test_authenticated_mcp_initialize_and_tools_list(self):
        token = issue_access_token(ISSUER, RESOURCE, ttl_seconds=60)
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-06-18",
        }
        initialized = self.client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "sppg-test", "version": "1.0"},
                },
            },
        )
        self.assertEqual(initialized.status_code, 200, initialized.text)

        listed = self.client.post(
            "/mcp",
            headers=headers,
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        self.assertEqual(listed.status_code, 200, listed.text)
        payload = listed.json()
        tools = payload["result"]["tools"]
        names = {tool["name"] for tool in tools}
        focused = {
            "po_action_queue",
            "receiving_preview",
            "stock_opname_preview",
            "vendor_invoice_parse_preview",
            "vendor_payable_preview",
            "vendor_payables_list",
        }
        self.assertTrue(focused.issubset(names))
        self.assertTrue(set(LEGACY_V0186_TOOL_NAMES).issubset(names))
        self.assertEqual(len(LEGACY_V0186_TOOL_NAMES), 30)
        self.assertEqual(len(names), len(focused) + 30)

        by_name = {tool["name"]: tool for tool in tools}
        for tool in tools:
            schemes = tool.get("securitySchemes", [])
            self.assertIn({"type": "oauth2", "scopes": ["sppg:read"]}, schemes)

        for name in focused:
            self.assertTrue(by_name[name].get("annotations", {}).get("readOnlyHint"))
        self.assertFalse(by_name["learnSppgConversationTurn"].get("annotations", {}).get("readOnlyHint"))
        self.assertFalse(by_name["recordExplicitSppgKnowledge"].get("annotations", {}).get("readOnlyHint"))
        self.assertFalse(by_name["createSppgAccountantTransactions"].get("annotations", {}).get("readOnlyHint"))

    def test_authorization_error_redirect_includes_issuer(self):
        params = {
            "response_type": "code",
            "client_id": "https://chatgpt.com/oauth/client.json",
            "redirect_uri": CHATGPT_STABLE_REDIRECT,
            "state": "state-123",
            "code_challenge": "A" * 43,
            "code_challenge_method": "S256",
            "scope": "wrong:scope",
            "resource": RESOURCE,
        }
        response = self.client.get("/authorize", params=params, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        location = response.headers["location"]
        self.assertTrue(location.startswith(CHATGPT_STABLE_REDIRECT + "?"))
        self.assertIn("error=invalid_scope", location)
        self.assertIn("state=state-123", location)
        self.assertIn("iss=https%3A%2F%2Fmcp.example.test", location)

    def test_dcr_accepts_only_stable_chatgpt_callback(self):
        response = self.client.post(
            "/register",
            json={
                "redirect_uris": [CHATGPT_STABLE_REDIRECT],
                "token_endpoint_auth_method": "none",
            },
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["client_id"], DCR_CLIENT_ID)

        rejected = self.client.post(
            "/register",
            json={"redirect_uris": ["https://attacker.example/callback"]},
        )
        self.assertEqual(rejected.status_code, 400)


if __name__ == "__main__":
    unittest.main()
