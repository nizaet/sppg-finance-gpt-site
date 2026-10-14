"""OAuth 2.0 protected resource validation for the SPPG MCP gateway.

This module verifies JWT access tokens issued by a trusted OAuth provider.
It does not issue tokens or implement an authorization server.
"""
from __future__ import annotations

import os
from urllib.parse import urlparse

import jwt
from jwt import PyJWKClient
from starlette.responses import JSONResponse


def settings():
    issuer = os.getenv("SPPG_OAUTH_ISSUER", "").strip().rstrip("/")
    audience = os.getenv("SPPG_OAUTH_AUDIENCE", "").strip()
    jwks_url = os.getenv("SPPG_OAUTH_JWKS_URL", "").strip()
    resource = os.getenv("SPPG_OAUTH_RESOURCE_URL", "").strip().rstrip("/")
    required_scope = os.getenv("SPPG_OAUTH_SCOPE", "sppg:read").strip()
    allowed_subjects = {s.strip() for s in os.getenv("SPPG_OAUTH_ALLOWED_SUBJECTS", "").split(",") if s.strip()}
    if not all((issuer, audience, jwks_url, resource, allowed_subjects)):
        raise RuntimeError("OAuth issuer, audience, JWKS, resource and allowed subjects must be configured")
    for url in (issuer, jwks_url, resource):
        p = urlparse(url)
        if p.scheme != "https" or not p.netloc or p.username or p.password:
            raise RuntimeError("OAuth URLs must be HTTPS")
    return issuer, audience, jwks_url, resource, required_scope, allowed_subjects


def validate_access_token(token: str) -> dict:
    issuer, audience, jwks_url, _, required_scope, allowed_subjects = settings()
    key = PyJWKClient(jwks_url, cache_jwk_set=True, lifespan=300).get_signing_key_from_jwt(token)
    claims = jwt.decode(
        token, key.key, algorithms=["RS256"], audience=audience,
        issuer=issuer, options={"require": ["exp", "iat", "iss", "sub", "aud"]},
        leeway=30,
    )
    if claims.get("sub") not in allowed_subjects:
        raise jwt.InvalidTokenError("Subject not authorized for SPPG")
    scopes = set(str(claims.get("scope") or "").split())
    if required_scope and required_scope not in scopes:
        raise jwt.InvalidTokenError("Missing required SPPG scope")
    return claims


def unauthorized(resource: str, detail: str = "OAuth access token required"):
    return JSONResponse(
        {"detail": detail}, status_code=401,
        headers={"WWW-Authenticate": f'Bearer resource_metadata="{resource}/.well-known/oauth-protected-resource"'},
    )


def protected_resource_metadata(resource: str, issuer: str, scope: str) -> dict:
    return {
        "resource": resource,
        "authorization_servers": [issuer],
        "bearer_methods_supported": ["header"],
        "scopes_supported": [scope] if scope else [],
    }
