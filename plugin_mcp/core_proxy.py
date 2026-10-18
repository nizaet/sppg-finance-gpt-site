from __future__ import annotations

import os
from typing import Any

import httpx


CORE_API_URL = os.getenv(
    "SPPG_CORE_API_URL",
    "https://sppg-finance-gpt-site-production-5b7d.up.railway.app",
).rstrip("/")


def operational_writes_enabled() -> bool:
    return os.getenv("SPPG_MCP_OPERATIONAL_WRITES_ENABLED", "").strip().lower() in {
        "1", "true", "yes", "on"
    }


def _headers() -> dict[str, str]:
    key = os.getenv("SPPG_GPT_API_KEY", "").strip()
    if not key:
        raise RuntimeError("SPPG_GPT_API_KEY is not configured for the MCP-to-Core bridge")
    return {
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
    }


async def core_request(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    clean_params = {
        key: value for key, value in (params or {}).items()
        if value is not None and value != ""
    }
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        response = await client.request(
            method.upper(),
            CORE_API_URL + path,
            params=clean_params or None,
            json=json_body,
            headers=_headers(),
        )
    try:
        body: Any = response.json()
    except Exception:
        body = {"detail": response.text[:1500]}
    if response.status_code >= 400:
        detail = body.get("detail") if isinstance(body, dict) else body
        raise RuntimeError(
            f"SPPG Core {response.status_code} for {method.upper()} {path}: {str(detail)[:1200]}"
        )
    if isinstance(body, dict):
        return body
    return {"result": body}


def preview_only(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    value = dict(payload or {})
    value["commit"] = False
    return value


def blocked_write(operation: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "operation": operation,
        "committed": False,
        "canCommit": False,
        "writeEnabled": operational_writes_enabled(),
        "confirmationGateRequired": True,
        "status": "WRITE_GATE_CLOSED",
        "message": (
            "Tool parity is installed, but production mutation is still disabled. "
            "Use the available preview/read flow. Operational writes will be enabled "
            "gradually behind an explicit confirmation gate."
        ),
        "requestedPayload": payload or {},
    }
