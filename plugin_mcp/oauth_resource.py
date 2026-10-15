"""OAuth 2.1 protected-resource validation for the SPPG MCP gateway."""
from __future__ import annotations

import base64
import os
from urllib.parse import urlparse

import jwt
from cryptography.hazmat.primitives import serialization
from jwt import PyJWKClient
from starlette.responses import JSONResponse


def settings():
    issuer = os.getenv("SPPG_OAUTH_ISSUER", "").strip().rstrip("/")
    audience = os.getenv("SPPG_OAUTH_AUDIENCE", "").strip()
    jwks_url = os.getenv("SPPG_OAUTH_JWKS_URL", "").strip()
    resource = os.getenv("SPPG_OAUTH_RESOURCE_URL", "").strip().rstrip("/")
    required_scope = os.getenv("SPPG_OAUTH_SCOPE", "sppg:read").strip()
    allowed_subjects = {
        s.strip()
        for s in os.getenv("SPPG_OAUTH_ALLOWED_SUBJECTS", "").split(",")
        if s.strip()
    }
    if not all((issuer, audience, jwks_url, resource, allowed_subjects)):
        raise RuntimeError(
            "OAuth issuer, audience, JWKS, resource and allowed subjects must be configured"
        )
    for url in (issuer, jwks_url, resource):
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.fragment
        ):
            raise RuntimeError("OAuth URLs must be canonical HTTPS URLs")
    return issuer, audience, jwks_url, resource, required_scope, allowed_subjects


def _verification_key(issuer: str, jwks_url: str):
    local_b64 = os.getenv("SPPG_OAUTH_PRIVATE_KEY_B64", "").strip()
    if local_b64 and jwks_url == issuer + "/jwks.json":
        try:
            private_key = serialization.load_pem_private_key(
                base64.b64decode(local_b64, validate=True),
                password=None,
            )
            return private_key.public_key()
        except Exception as exc:
            raise jwt.InvalidTokenError("Local OAuth verification key is invalid") from exc
    return PyJWKClient(
        jwks_url,
        cache_jwk_set=True,
        lifespan=300,
    ).get_signing_key_from_jwt(token).key


def validate_access_token(token: str) -> dict:
    issuer, audience, jwks_url, _, required_scope, allowed_subjects = settings()
    key = _verification_key(issuer, jwks_url)
    claims = jwt.decode(
        token,
        key,
        algorithms=["RS256"],
        audience=audience,
        issuer=issuer,
        options={"require": ["exp", "iat", "iss", "sub", "aud"]},
        leeway=30,
    )
    if claims.get("sub") not in allowed_subjects:
        raise jwt.InvalidTokenError("Subject not authorized for SPPG")
    scopes = set(str(claims.get("scope") or "").split())
    if required_scope and required_scope not in scopes:
        raise jwt.InvalidTokenError("Missing required SPPG scope")
    return claims


def protected_resource_metadata_url(resource: str) -> str:
    parsed = urlparse(resource)
    return f"{parsed.scheme}://{parsed.netloc}/.well-known/oauth-protected-resource"


def unauthorized(
    resource: str,
    scope: str = "",
    detail: str = "OAuth access token required",
) -> JSONResponse:
    challenge = f'Bearer resource_metadata="{protected_resource_metadata_url(resource)}"'
    if scope:
        challenge += f', scope="{scope}"'
    return JSONResponse(
        {"detail": detail},
        status_code=401,
        headers={"WWW-Authenticate": challenge},
    )


def protected_resource_metadata(resource: str, issuer: str, scope: str) -> dict:
    return {
        "resource": resource,
        "authorization_servers": [issuer],
        "bearer_methods_supported": ["header"],
        "scopes_supported": [scope] if scope else [],
    }
