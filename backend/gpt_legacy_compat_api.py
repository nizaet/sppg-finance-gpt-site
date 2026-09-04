from __future__ import annotations

import os
from copy import deepcopy
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend import action_schema_runtime_patch as action_patch
from backend import unified_action_schema_api as schema_api
from backend.db import database_ready

router = APIRouter(tags=["gpt-legacy-compat"])
SERVER = "https://sppg-finance-gpt-site-production-5b7d.up.railway.app"
NO_CACHE = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


def _build_legacy_v0186() -> dict[str, Any]:
    """Recreate the pre-runtime-patch v0.18.6 Action schema once at startup."""
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


def _status_response() -> dict[str, Any]:
    """Non-sensitive bridge health used only to separate transport from auth."""
    return {
        "databaseReady": database_ready(),
        "googleCredentialsConfigured": bool(os.getenv("SPPG_GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()),
        "rawChatFolderConfigured": bool(os.getenv("SPPG_DRIVE_RAW_CHAT_FOLDER_ID", "").strip()),
        "firestoreProject": os.getenv("SPPG_FIRESTORE_PROJECT_ID", "sppg-finance-gpt"),
    }


LEGACY_V0186 = _build_legacy_v0186()


def _build_v0191() -> dict[str, Any]:
    """Use the proven v0.18.6 Action surface, but make only bridge status public.

    This is diagnostic by design. If getSppgAccountantBridgeStatus still raises
    ClientResponseError here, Bearer authentication is not the cause because the
    operation no longer requires it. All real operational reads/writes remain on
    the original authenticated paths.
    """
    payload = deepcopy(LEGACY_V0186)
    payload.setdefault("info", {})["version"] = "0.19.1-legacy-v0186-public-status"
    old_status = deepcopy(payload.get("paths", {}).get("/v1/gpt/status") or {})
    status_get = deepcopy(old_status.get("get") or {})
    if not status_get:
        status_get = {
            "operationId": "getSppgAccountantBridgeStatus",
            "summary": "Check the SPPG Accountant database and Firestore bridge",
            "responses": {"200": {"description": "Bridge status"}},
        }
    status_get["security"] = []
    status_get["description"] = (
        "PUBLIC DIAGNOSTIC READ. No API key is required. Returns only non-sensitive "
        "bridge readiness flags so GPT Action transport can be tested independently of Bearer auth."
    )
    payload.setdefault("paths", {}).pop("/v1/gpt/status", None)
    payload["paths"]["/v1/gpt/status-public"] = {"get": status_get}
    return payload


LEGACY_V0191 = _build_v0191()


@router.get("/gpt/ping", include_in_schema=False)
def gpt_transport_ping() -> JSONResponse:
    return JSONResponse(
        {
            "ok": True,
            "service": "sppg-core",
            "probe": "gpt-action-transport",
            "authRequired": False,
        },
        headers=NO_CACHE,
    )


@router.get("/gpt/status-public", include_in_schema=False)
def gpt_public_bridge_status() -> JSONResponse:
    return JSONResponse(_status_response(), headers=NO_CACHE)


@router.get("/schema/chatgpt-sppg-v0190.json", include_in_schema=False)
def chatgpt_sppg_v0190_legacy() -> JSONResponse:
    return JSONResponse(deepcopy(LEGACY_V0186), headers=NO_CACHE)


@router.get("/schema/chatgpt-sppg-v0191.json", include_in_schema=False)
def chatgpt_sppg_v0191_legacy_public_status() -> JSONResponse:
    return JSONResponse(deepcopy(LEGACY_V0191), headers=NO_CACHE)


@router.get("/schema/chatgpt-sppg-diagnostic-v2.json", include_in_schema=False)
def chatgpt_sppg_diagnostic_v2() -> JSONResponse:
    schema = {
        "openapi": "3.1.0",
        "info": {
            "title": "SPPG GPT Connection Diagnostic",
            "version": "2.0.0",
            "description": "Separates public transport, public app readiness, and authenticated bridge access.",
        },
        "servers": [{"url": SERVER}],
        "paths": {
            "/v1/gpt/ping": {
                "get": {
                    "operationId": "pingSppgActionTransport",
                    "summary": "Test public GPT Action transport to SPPG",
                    "security": [],
                    "x-openai-isConsequential": False,
                    "responses": {
                        "200": {
                            "description": "Transport reachable",
                            "content": {"application/json": {"schema": {
                                "type": "object",
                                "properties": {
                                    "ok": {"type": "boolean"},
                                    "service": {"type": "string"},
                                    "probe": {"type": "string"},
                                    "authRequired": {"type": "boolean"},
                                },
                            }}},
                        }
                    },
                }
            },
            "/v1/gpt/status-public": {
                "get": {
                    "operationId": "getSppgPublicBridgeStatus",
                    "summary": "Read non-sensitive SPPG bridge readiness without auth",
                    "security": [],
                    "x-openai-isConsequential": False,
                    "responses": {
                        "200": {
                            "description": "Public bridge readiness",
                            "content": {"application/json": {"schema": {
                                "type": "object",
                                "properties": {
                                    "databaseReady": {"type": "boolean"},
                                    "googleCredentialsConfigured": {"type": "boolean"},
                                    "rawChatFolderConfigured": {"type": "boolean"},
                                    "firestoreProject": {"type": "string"},
                                },
                            }}},
                        }
                    },
                }
            },
            "/v1/gpt/status": {
                "get": {
                    "operationId": "getSppgAuthenticatedBridgeStatus",
                    "summary": "Test authenticated SPPG GPT bridge",
                    "security": [{"bearerAuth": []}],
                    "x-openai-isConsequential": False,
                    "responses": {
                        "200": {
                            "description": "Authenticated bridge status",
                            "content": {"application/json": {"schema": {
                                "type": "object",
                                "properties": {
                                    "databaseReady": {"type": "boolean"},
                                    "googleCredentialsConfigured": {"type": "boolean"},
                                    "rawChatFolderConfigured": {"type": "boolean"},
                                    "firestoreProject": {"type": "string"},
                                },
                            }}},
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


@router.get("/schema/chatgpt-sppg-diagnostic-v1.json", include_in_schema=False)
def chatgpt_sppg_diagnostic_v1() -> JSONResponse:
    return chatgpt_sppg_diagnostic_v2()
