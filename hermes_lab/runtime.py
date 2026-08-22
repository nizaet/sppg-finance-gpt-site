from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

import httpx
from fastapi import Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from hermes_lab import app as base


# Keep the existing FastAPI app and every existing route unchanged. This module
# only adds read-only retrieval surfaces, then becomes the ASGI entrypoint.
app = base.app

base.GPT_ACTION_OPERATIONS.update(
    {
        "/v1/lab/context": {"get": "readHermesSppgContext"},
        "/v1/lab/receiving-preview": {"post": "previewHermesReceivingMultiPo"},
    }
)

base.SYSTEM_POLICY += """
For SPPG knowledge, procurement, receiving, payment, or workflow questions, retrieve the relevant LLM Wiki context before relying on memory alone.
For receiving messages, use the dedicated read-only receiving preview to reconcile the supplied text against all relevant active purchase orders and cumulative prior receipts. Use its multi-PO allocation and outstanding quantities as evidence; do not guess a single PO when the resolver reports multiple POs or ambiguity.
The receiving preview cannot commit receiving or mutate stock/PO state. Never claim that a preview was saved or committed.
"""


class LabContextResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    runtimeVersion: str | None = None
    generatedAt: str | None = None
    asOf: str | None = None
    accessMode: str | None = None
    operationalWritesExposed: bool = False
    databaseReady: bool = False
    site: str | None = None
    vendorCode: str | None = None
    topic: str | None = None
    query: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    canonicalKnowledge: dict[str, Any] = Field(default_factory=dict)
    evidenceReferences: list[dict[str, Any]] = Field(default_factory=list)
    sectionErrors: dict[str, Any] = Field(default_factory=dict)
    readOnly: bool = True
    sourceOfTruth: str = "SPPG Core PostgreSQL + confirmed LLM Wiki knowledge"


class LabReceivingPreviewRequest(BaseModel):
    """No commit field by design."""

    model_config = ConfigDict(extra="forbid")

    site: Literal["MAJA", "CEMPLANG"]
    text: str = Field(min_length=1, max_length=20000)
    vendor_code: str | None = Field(default=None, max_length=100)
    purchase_order_id: int | None = Field(default=None, ge=1)
    received_at: datetime | None = None
    source_external_id: str | None = Field(default=None, max_length=300)
    reporter: str | None = Field(default=None, max_length=200)


class LabReceivingPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    committed: bool = False
    canCommit: bool = False
    site: str
    vendorCode: str | None = None
    purchaseOrderId: int | None = None
    poCode: str | None = None
    purchaseOrderIds: list[int] = Field(default_factory=list)
    poCodes: list[str | None] = Field(default_factory=list)
    multiPo: bool = False
    poMatchConfidence: float = 0.0
    reportedItems: list[dict[str, Any]] = Field(default_factory=list)
    matches: list[dict[str, Any]] = Field(default_factory=list)
    alternatives: list[dict[str, Any]] = Field(default_factory=list)
    requiresConfirmation: bool = True
    resolverVersion: str | None = None
    readOnly: bool = True
    sourceOfTruth: str = "SPPG Core PostgreSQL"
    operationalMutation: bool = False
    resolver: str | None = None


def _require_core() -> None:
    if not base.SPPG_CORE_URL or not base.SPPG_GPT_API_KEY:
        raise HTTPException(status_code=503, detail="SPPG Core read-only API is not configured")


@app.get("/v1/lab/context", response_model=LabContextResponse)
async def read_context(
    authorization: str | None = Header(default=None),
    site: Literal["MAJA", "CEMPLANG"] | None = None,
    vendor: str = Query(default="", max_length=100),
    topic: Literal["all", "knowledge", "behavior", "procurement", "po", "receiving", "payment", "payments"] = "all",
    q: str = Query(default="", max_length=500),
    as_of: date | None = Query(default=None, alias="asOf"),
    limit: int = Query(default=20, ge=1, le=50),
) -> dict[str, Any]:
    """Read operational + confirmed LLM Wiki context from SPPG Core."""
    base._authorize(authorization)
    _require_core()

    params: dict[str, Any] = {"topic": topic, "limit": limit}
    if site:
        params["site"] = site
    if vendor.strip():
        params["vendor"] = vendor.strip()
    if q.strip():
        params["q"] = q.strip()
    if as_of:
        params["asOf"] = as_of.isoformat()

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{base.SPPG_CORE_URL}/v1/llm-wiki/context",
                params=params,
                headers=base._memory_headers(),
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"SPPG Core context connection failed: {exc.__class__.__name__}") from exc

    if response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail={"message": "SPPG Core rejected context read", "upstreamStatus": response.status_code},
        )
    try:
        data = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Unexpected SPPG Core context response") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="Unexpected SPPG Core context response")
    return {
        **data,
        "readOnly": True,
        "sourceOfTruth": "SPPG Core PostgreSQL + confirmed LLM Wiki knowledge",
    }


@app.post("/v1/lab/receiving-preview", response_model=LabReceivingPreviewResponse)
async def receiving_preview(
    payload: LabReceivingPreviewRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Proxy the Core multi-PO resolver with no operational write capability."""
    base._authorize(authorization)
    _require_core()

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{base.SPPG_CORE_URL}/v1/gpt/hermes-read/receiving-preview",
                json=payload.model_dump(mode="json", exclude_none=True),
                headers=base._memory_headers(),
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"SPPG Core receiving preview connection failed: {exc.__class__.__name__}") from exc

    if response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail={"message": "SPPG Core rejected receiving preview", "upstreamStatus": response.status_code},
        )
    try:
        data = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Unexpected SPPG Core receiving preview response") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="Unexpected SPPG Core receiving preview response")
    if bool(data.get("committed")) or bool(data.get("operationalMutation")):
        raise HTTPException(status_code=502, detail="Unsafe receiving preview response from SPPG Core")

    return {
        **data,
        "committed": False,
        "readOnly": True,
        "operationalMutation": False,
        "sourceOfTruth": "SPPG Core PostgreSQL",
    }
