"""Unit tests for the fail-closed MCP OAuth resource gate."""
import os
import unittest
from unittest.mock import patch

import jwt

from plugin_mcp.oauth_resource import settings, validate_access_token, protected_resource_metadata


CONFIG = {
    "SPPG_OAUTH_ISSUER": "https://auth.example.test",
    "SPPG_OAUTH_AUDIENCE": "https://mcp.example.test/mcp",
    "SPPG_OAUTH_JWKS_URL": "https://auth.example.test/jwks.json",
    "SPPG_OAUTH_RESOURCE_URL": "https://mcp.example.test/mcp",
    "SPPG_OAUTH_ALLOWED_SUBJECTS": "firebase-owner-uid",
    "SPPG_OAUTH_SCOPE": "sppg:read",
}


class OAuthResourceTests(unittest.TestCase):
    def test_missing_config_fails_closed(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                settings()

    def test_reject_http_jwks(self):
        with patch.dict(os.environ, {**CONFIG, "SPPG_OAUTH_JWKS_URL": "http://bad.test/jwks"}):
            with self.assertRaises(RuntimeError):
                settings()

    def test_reject_empty_allowlist(self):
        with patch.dict(os.environ, {**CONFIG, "SPPG_OAUTH_ALLOWED_SUBJECTS": ""}):
            with self.assertRaises(RuntimeError):
                settings()

    def test_metadata(self):
        result = protected_resource_metadata(
            CONFIG["SPPG_OAUTH_RESOURCE_URL"], CONFIG["SPPG_OAUTH_ISSUER"], "sppg:read"
        )
        self.assertEqual(result["authorization_servers"], [CONFIG["SPPG_OAUTH_ISSUER"]])

    def test_reject_wrong_subject(self):
        with patch.dict(os.environ, CONFIG):
            with patch("plugin_mcp.oauth_resource.PyJWKClient") as client:
                client.return_value.get_signing_key_from_jwt.return_value.key = "fake-key"
                with patch("plugin_mcp.oauth_resource.jwt.decode", return_value={"sub": "attacker", "scope": "sppg:read"}):
                    with self.assertRaises(jwt.InvalidTokenError):
                        validate_access_token("dummy")

    def test_reject_wrong_scope(self):
        with patch.dict(os.environ, CONFIG):
            with patch("plugin_mcp.oauth_resource.PyJWKClient") as client:
                client.return_value.get_signing_key_from_jwt.return_value.key = "fake-key"
                with patch("plugin_mcp.oauth_resource.jwt.decode", return_value={"sub": "firebase-owner-uid", "scope": "other:read"}):
                    with self.assertRaises(jwt.InvalidTokenError):
                        validate_access_token("dummy")


if __name__ == "__main__":
    unittest.main()
