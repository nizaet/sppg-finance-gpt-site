"""Unit tests for the fail-closed MCP OAuth resource gate."""
import os
import unittest
from unittest.mock import patch

import jwt

from plugin_mcp.oauth_resource import (
    protected_resource_metadata,
    protected_resource_metadata_url,
    settings,
    validate_access_token,
)
from plugin_mcp.oauth_server import issue_access_token


CONFIG = {
    "SPPG_OAUTH_ISSUER": "https://auth.example.test",
    "SPPG_OAUTH_AUDIENCE": "https://mcp.example.test/mcp",
    "SPPG_OAUTH_JWKS_URL": "https://auth.example.test/jwks.json",
    "SPPG_OAUTH_RESOURCE_URL": "https://mcp.example.test/mcp",
    "SPPG_OAUTH_ALLOWED_SUBJECTS": "SPPG_OWNER",
    "SPPG_OAUTH_SCOPE": "sppg:read",
    "SPPG_OAUTH_PRIVATE_KEY_B64": "test-secret-material-" + ("x" * 64),
}


class OAuthResourceTests(unittest.TestCase):
    def test_missing_config_fails_closed(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                settings()

    def test_reject_http_jwks(self):
        with patch.dict(
            os.environ,
            {**CONFIG, "SPPG_OAUTH_JWKS_URL": "http://bad.test/jwks"},
            clear=True,
        ):
            with self.assertRaises(RuntimeError):
                settings()

    def test_reject_empty_allowlist(self):
        with patch.dict(
            os.environ,
            {**CONFIG, "SPPG_OAUTH_ALLOWED_SUBJECTS": ""},
            clear=True,
        ):
            with self.assertRaises(RuntimeError):
                settings()

    def test_metadata(self):
        result = protected_resource_metadata(
            CONFIG["SPPG_OAUTH_RESOURCE_URL"],
            CONFIG["SPPG_OAUTH_ISSUER"],
            "sppg:read",
        )
        self.assertEqual(
            result["authorization_servers"],
            [CONFIG["SPPG_OAUTH_ISSUER"]],
        )
        self.assertEqual(
            protected_resource_metadata_url(CONFIG["SPPG_OAUTH_RESOURCE_URL"]),
            "https://mcp.example.test/.well-known/oauth-protected-resource",
        )

    def test_round_trip(self):
        with patch.dict(os.environ, CONFIG, clear=True):
            token = issue_access_token(
                CONFIG["SPPG_OAUTH_ISSUER"],
                CONFIG["SPPG_OAUTH_AUDIENCE"],
                ttl_seconds=60,
            )
            claims = validate_access_token(token)
            self.assertEqual(claims["sub"], "SPPG_OWNER")
            self.assertEqual(claims["scope"], "sppg:read")

    def test_reject_wrong_subject(self):
        with patch.dict(os.environ, CONFIG, clear=True):
            token = issue_access_token(
                CONFIG["SPPG_OAUTH_ISSUER"],
                CONFIG["SPPG_OAUTH_AUDIENCE"],
                subject="ATTACKER",
                ttl_seconds=60,
            )
            with self.assertRaises(jwt.InvalidTokenError):
                validate_access_token(token)

    def test_reject_wrong_scope(self):
        with patch.dict(os.environ, CONFIG, clear=True):
            token = issue_access_token(
                CONFIG["SPPG_OAUTH_ISSUER"],
                CONFIG["SPPG_OAUTH_AUDIENCE"],
                scope="other:read",
                ttl_seconds=60,
            )
            with self.assertRaises(jwt.InvalidTokenError):
                validate_access_token(token)


if __name__ == "__main__":
    unittest.main()
