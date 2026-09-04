from __future__ import annotations

from copy import deepcopy
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend import action_schema_runtime_patch as action_patch
from backend import unified_action_schema_api as schema_api

router = APIRouter(tags=["gpt-legacy-compat"])
SERVER = "https://sppg-finance-gpt-site-production-5b7d.up.railway.app"
NO_CACHE = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


def _build_legacy_v0186() -> dict[str, Any]:
    """Recreate the pre-runtime-patch v0.18.6 Action schema once at startup.

    v0.18.6 is the user's last known-good Custom GPT schema. Later runtime
    patches intentionally renamed a few operationIds while keeping the same
    endpoints. For diagnosis and rollback, build the original v0.18.6 surface
    before serving requests, then restore the current patched generator.
    """
    active_v0184 = schema_api.schema_v0184
    try:
        schema_api.schema_v0184 = action_patch._ORIGINAL_V0184
        payload = deepcopy(schema_api.schema_v0186())
    finally:
        schema_api.schema_v0184 = active_v0184

    payload["servers"] = [{"url": SERVER}]
    payload.setdefault("components", {})["securitySchemes"] = {
        "bearerAuth": {"type": "http", "scheme": "bearer"}
    }
    payload["security"] = [{"bearerAuth": []}]
    payload.setdefault("info", {})["version"] = "0.19.0-legacy-v0186"
    payload["info"]["title"] = "SPPG Full Operations Application Bridge"
    payload["info"]["description"] = (
        "Legacy-compatible v0.18.6 operation surface on the current SPPG backend. "
        "Transport and bearer authentication intentionally match the last known-good GPT Action schema."
    )
    return payload


LEGACY_V0186 = _build_legacy_v0186()


@router.get("/gpt/ping", include_in_schema=False)
def gpt_transport_ping() -> JSONResponse:
    """Public transport probe. No application data and no auth required."""
    return JSONResponse(
        {
            "ok": True,
            "service": "sppg-core",
            "probe": "gpt-action-transport",
            "authRequired": False,
        },
        headers=NO_CACHE,
    )


@router.get("/schema/chatgpt-sppg-v0190.json", include_in_schema=False)
def chatgpt_sppg_v0190_legacy() -> JSONResponse:
    """Fresh URL carrying the old proven v0.18.6 Action contract."""
    return JSONResponse(deepcopy(LEGACY_V0186), headers=NO_CACHE)


@router.get("/schema/chatgpt-sppg-diagnostic-v1.json", include_in_schema=False)
def chatgpt_sppg_diagnostic_v1() -> JSONResponse:
    """Two-call schema that separates network/transport failure from bearer auth."""
    schema = {
        "openapi": "3.1.0",
        "info": {
            "title": "SPPG GPT Connection Diagnostic",
            "version": "1.0.0",
            "description": "First call pingSppgActionTransport. Then call getSppgAccountantBridgeStatus with Bearer auth.",
        },
        "servers": [{"url": SERVER}],
        "paths": {
            "/v1/gpt/ping": {
                "get": {
                    "operationId": "pingSppgActionTransport",
                    "summary": "Test public GPT Action transport to SPPG",
                    "description": "No auth and no operational data. A successful response proves DNS/TLS/HTTP transport from GPT Actions to Railway.",
                    "security": [],
                    "x-openai-isConsequential": False,
                    "responses": {
                        "200": {
                            "description": "Transport reachable",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "ok": {"type": "boolean"},
                                            "service": {"type": "string"},
                                            "probe": {"type": "string"},
                                            "authRequired": {"type": "boolean"},
                                        },
                                        "required": ["ok", "service", "probe", "authRequired"],
                                    }
                                }
                            },
                        }
                    },
                }
            },
            "/v1/gpt/status": {
                "get": {
                    "operationId": "getSppgAccountantBridgeStatus",
                    "summary": "Test authenticated SPPG GPT bridge",
                    "description": "If ping works but this fails, the remaining issue is Bearer/API-key configuration rather than Railway transport.",
                    "security": [{"bearerAuth": []}],
                    "x-openai-isConsequential": False,
                    "responses": {
                        "200": {
                            "description": "Authenticated bridge status",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "databaseReady": {"type": "boolean"},
                                            "googleCredentialsConfigured": {"type": "boolean"},
                                            "rawChatFolderConfigured": {"type": "boolean"},
                                            "firestoreProject": {"type": "string"},
                                        },
                                    }
                                }
                            },
                        }
                    },
                }
            },
        },
        "components": {
            "securitySchemes": {
                "bearerAuth": {"type": "http", "scheme": "bearer"}
            },
            "schemas": {},
        },
    }
    return JSONResponse(schema, headers=NO_CACHE)
