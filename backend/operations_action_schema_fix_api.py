from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.operations_action_schema_api import schema as operations_schema_v0163

router = APIRouter(tags=["chatgpt-schema"])


@router.get("/schema/chatgpt-operations-v0164.json", include_in_schema=False)
def chatgpt_operations_schema_v0164() -> JSONResponse:
    payload = operations_schema_v0163()
    payload["info"]["version"] = "0.16.4"
    components = payload.setdefault("components", {})
    components["schemas"] = {}
    return JSONResponse(payload)
