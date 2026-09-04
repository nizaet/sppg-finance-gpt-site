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


def _operation_ids(payload: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for methods in (payload.get("paths") or {}).values():
        if not isinstance(methods, dict):
            continue
        for operation in methods.values():
            if isinstance(operation, dict) and operation.get("operationId"):
                ids.append(str(operation["operationId"]))
    return ids


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
    """Legacy full schema with a public status replacement for diagnostics."""
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


def _build_v0192_full() -> dict[str, Any]:
    """Full operational GPT schema using the proven legacy transport/auth contract.

    Unlike the diagnostic schema, this intentionally exposes the complete
    v0.18.6 operation set, including readSppgOperationalApplication, PO/receipt,
    inventory, payable, Accountant/BGN, and conversation-memory actions. The
    authenticated /v1/gpt/status route is preserved because Bearer auth has now
    been proven from GPT Builder to Railway.
    """
    payload = deepcopy(LEGACY_V0186)
    operation_ids = _operation_ids(payload)
    payload.setdefault("info", {})["version"] = "0.19.2-full-legacy-v0186"
    payload["info"]["title"] = "SPPG FULL OPERATIONS - Legacy Compatible"
    payload["info"]["description"] = (
        f"Full SPPG operational Action surface restored from the last known-good v0.18.6 contract. "
        f"Server and Bearer authentication are unchanged. Exported operation count: {len(operation_ids)}."
    )
    # Helpful metadata for human inspection. GPT Builder ignores x-* fields.
    payload["x-sppg-operation-count"] = len(operation_ids)
    payload["x-sppg-operation-ids"] = operation_ids
    return payload


FULL_V0192 = _build_v0192_full()


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


@router.get("/gpt/schema-v0192-summary", include_in_schema=False)
def gpt_v0192_schema_summary() -> JSONResponse:
    ids = _operation_ids(FULL_V0192)
    return JSONResponse(
        {
            "schema": "v0192",
            "operationCount": len(ids),
            "operationIds": ids,
            "hasOperationalGateway": "readSppgOperationalApplication" in ids,
            "hasOperationalExecute": "previewOrExecuteSppgOperationalApplication" in ids,
            "hasOperationalContext": any("Operational" in value or "operational" in value for value in ids),
        },
        headers=NO_CACHE,
    )


@router.get("/schema/chatgpt-sppg-v0190.json", include_in_schema=False)
def chatgpt_sppg_v0190_legacy() -> JSONResponse:
    return JSONResponse(deepcopy(LEGACY_V0186), headers=NO_CACHE)


@router.get("/schema/chatgpt-sppg-v0191.json", include_in_schema=False)
def chatgpt_sppg_v0191_legacy_public_status() -> JSONResponse:
    return JSONResponse(deepcopy(LEGACY_V0191), headers=NO_CACHE)


@router.get("/schema/chatgpt-sppg-v0192.json", include_in_schema=False)
def chatgpt_sppg_v0192_full() -> JSONResponse:
    return JSONResponse(deepcopy(FULL_V0192), headers=NO_CACHE)


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
