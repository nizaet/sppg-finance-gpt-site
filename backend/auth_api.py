from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from backend.google_services import GoogleServicesNotConfigured, create_firebase_custom_token

router = APIRouter(prefix="/auth", tags=["auth"])

ROLES = ("OWNER", "MAJA", "CEMPLANG")
SESSION_TTL_SECONDS = 12 * 60 * 60
REMEMBER_TTL_SECONDS = 30 * 24 * 60 * 60


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)
    remember: bool = False


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def auth_config() -> dict[str, Any]:
    configured_roles = [role for role in ROLES if _env(f"SPPG_{role}_PASSWORD")]
    secret_ready = bool(_env("SPPG_AUTH_SECRET"))
    return {
        "enabled": secret_ready and len(configured_roles) == len(ROLES),
        "configuredRoles": configured_roles,
        "requiredRoles": list(ROLES),
        "secretReady": secret_ready,
    }


def _secret() -> bytes:
    value = _env("SPPG_AUTH_SECRET")
    if not value:
        raise HTTPException(503, "SPPG authentication secret is not configured")
    return value.encode("utf-8")


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def issue_session(role: str, remember: bool = False) -> tuple[str, int]:
    role = role.upper().strip()
    if role not in ROLES:
        raise ValueError("invalid role")
    now = int(time.time())
    ttl = REMEMBER_TTL_SECONDS if remember else SESSION_TTL_SECONDS
    payload = {
        "v": 1,
        "role": role,
        "iat": now,
        "exp": now + ttl,
    }
    body = _b64encode(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    signature = _b64encode(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{signature}", payload["exp"]


def verify_session(token: str) -> dict[str, Any]:
    try:
        body, supplied_signature = token.split(".", 1)
    except ValueError as exc:
        raise HTTPException(401, "invalid SPPG session") from exc

    expected_signature = _b64encode(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(supplied_signature, expected_signature):
        raise HTTPException(401, "invalid SPPG session")

    try:
        payload = json.loads(_b64decode(body).decode("utf-8"))
    except Exception as exc:
        raise HTTPException(401, "invalid SPPG session") from exc

    role = str(payload.get("role") or "").upper()
    if role not in ROLES:
        raise HTTPException(401, "invalid SPPG session role")
    if int(payload.get("exp") or 0) <= int(time.time()):
        raise HTTPException(401, "SPPG session expired")
    return payload


def bearer_token(authorization: str | None) -> str:
    value = (authorization or "").strip()
    if not value.lower().startswith("bearer "):
        raise HTTPException(401, "SPPG login required")
    token = value[7:].strip()
    if not token:
        raise HTTPException(401, "SPPG login required")
    return token


def session_role(authorization: str | None) -> Literal["OWNER", "MAJA", "CEMPLANG"]:
    payload = verify_session(bearer_token(authorization))
    return payload["role"]


@router.get("/config")
def get_auth_config() -> dict[str, Any]:
    return auth_config()


@router.post("/login")
def login(payload: LoginIn) -> dict[str, Any]:
    config = auth_config()
    if not config["enabled"]:
        raise HTTPException(503, "SPPG login is not fully configured")

    role = payload.username.upper().strip()
    if role not in ROLES:
        # Keep the response deliberately generic so role/user probing gives no extra signal.
        raise HTTPException(401, "username atau password salah")

    expected = _env(f"SPPG_{role}_PASSWORD")
    if not expected or not hmac.compare_digest(payload.password, expected):
        raise HTTPException(401, "username atau password salah")

    token, expires_at = issue_session(role, payload.remember)
    return {
        "token": token,
        "role": role,
        "expiresAt": expires_at,
        "remember": payload.remember,
    }


@router.get("/me")
def me(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    payload = verify_session(bearer_token(authorization))
    return {
        "role": payload["role"],
        "expiresAt": payload["exp"],
    }


@router.get("/firebase-token/cemplang")
def cemplang_accountant_firebase_token(
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    """Bridge an authenticated OWNER session to Firebase Auth for Cemplang only."""
    role = session_role(authorization)
    if role != "OWNER":
        raise HTTPException(403, "OWNER access required for Cemplang accountant Firebase")

    try:
        custom_token = create_firebase_custom_token(
            uid="sppg-owner-cemplang-accountant",
            claims={
                "sppg_site": "CEMPLANG",
                "sppg_role": "OWNER",
            },
        )
    except GoogleServicesNotConfigured as exc:
        raise HTTPException(503, str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(503, f"Firebase custom token configuration error: {exc}") from exc

    return {
        "customToken": custom_token,
        "site": "CEMPLANG",
        "role": "OWNER",
    }


@router.post("/logout")
def logout() -> dict[str, bool]:
    # Sessions are stateless signed tokens; logout is completed by deleting the token in the browser.
    return {"ok": True}
