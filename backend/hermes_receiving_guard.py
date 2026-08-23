from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from typing import Any

from fastapi import HTTPException

_TOKEN_TTL_SECONDS = 600
_MAX_FUTURE_SKEW_SECONDS = 60


def _approval_key() -> bytes:
    value = os.getenv("SPPG_HERMES_APPROVAL_KEY", "").strip()
    if not value:
        raise HTTPException(status_code=503, detail="Hermes receiving approval key is not configured")
    return value.encode("utf-8")


def _canonical_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _signature(payload: dict[str, Any], issued_at: int) -> str:
    message = f"{issued_at}.{_canonical_payload(payload)}".encode("utf-8")
    return hmac.new(_approval_key(), message, hashlib.sha256).hexdigest()


def issue_receiving_confirmation_token(payload: dict[str, Any]) -> str:
    issued_at = int(time.time())
    return f"{issued_at}.{_signature(payload, issued_at)}"


def validate_receiving_confirmation_token(payload: dict[str, Any], token: str) -> None:
    try:
        timestamp_raw, supplied = token.split(".", 1)
        issued_at = int(timestamp_raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="invalid receiving confirmation token")

    now = int(time.time())
    age = now - issued_at
    if age < -_MAX_FUTURE_SKEW_SECONDS or age > _TOKEN_TTL_SECONDS:
        raise HTTPException(status_code=409, detail="receiving confirmation token expired")

    expected = _signature(payload, issued_at)
    if not hmac.compare_digest(expected, supplied):
        raise HTTPException(status_code=409, detail="receiving confirmation token does not match payload")


def receiving_has_over_receipt(result: dict[str, Any]) -> bool:
    for match in result.get("matches") or []:
        for allocation in match.get("allocations") or []:
            if bool(allocation.get("over_receipt")):
                return True
    return False


def receiving_commit_eligible(result: dict[str, Any]) -> bool:
    return bool(result.get("canCommit")) and not receiving_has_over_receipt(result)


def token_ttl_seconds() -> int:
    return _TOKEN_TTL_SECONDS
