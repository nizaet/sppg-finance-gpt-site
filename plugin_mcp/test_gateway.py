"""HTTP-level tests for OAuth discovery and the MCP bearer gate."""
import os
import unittest
from unittest.mock import patch

from starlette.testclient import TestClient

from plugin_mcp.oauth_server import (
    CHATGPT_STABLE_REDIRECT,
    DCR_CLIENT_ID,
)
from plugin_mcp.server import app


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
    def setUp(self):
        self.env = patch.dict(os.environ, CONFIG, clear=False)
        self.env.start()
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.env.stop()

    def test_health_proves_token_round_trip(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["oauthReady"])
        self.assertEqual(body["mode"], "read-only")

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

    def test_mcp_without_token_challenges_oauth(self):
        response = self.client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        self.assertEqual(response.status_code, 401)
        challenge = response.headers.get("www-authenticate", "")
        self.assertIn("/.well-known/oauth-protected-resource", challenge)
        self.assertIn('scope="sppg:read"', challenge)

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
