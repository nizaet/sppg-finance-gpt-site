from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

import httpx
from fastapi import Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from hermes_lab import app as base


# Keep the existing FastAPI app and every existing route unchanged. This module
# only adds isolated retrieval/memory/action surfaces, then becomes the ASGI entrypoint.
app = base.app

base.GPT_ACTION_OPERATIONS.update(
    {
        "/v1/lab/context": {"get": "readHermesSppgContext"},
        "/v1/lab/knowledge": {"post": "storeHermesKnowledge"},
        "/v1/lab/receiving-preview": {"post": "previewHermesReceivingMultiPo"},
        "/v1/lab/receiving-commit": {"post": "commitHermesReceiving"},
    }
)

base.SYSTEM_POLICY += """
For SPPG knowledge, procurement, receiving, payment, or workflow questions, retrieve the relevant LLM Wiki context before relying on memory alone.
When the user explicitly says catat, ingat, simpan ke knowledge, masukkan ke knowledge, jadikan pengetahuan, atau an equivalent explicit instruction, call storeHermesKnowledge with only the facts the user explicitly confirmed. This writes durable LLM Wiki memory only and must never be described as an operational database mutation.
Do not promote assistant inference into confirmed knowledge. If a fact is inferred rather than explicitly supplied or corrected by the user, do not store it through storeHermesKnowledge.
For receiving messages, always call previewHermesReceivingMultiPo first. Use its multi-PO allocation, cumulative receipts, and outstanding quantities as evidence; do not guess a single PO when the resolver reports multiple POs or ambiguity.
The receiving preview never commits. A receiving commit is allowed only when the preview returns commitEligible=true and a confirmationToken, and the user then explicitly says COMMIT TRUE. Only then call commitHermesReceiving with the exact same receiving payload and token. Never call receiving commit proactively, never synthesize COMMIT TRUE yourself, and never claim receiving was saved unless the commit action returns committed=true.
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


class LabKnowledgeFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statement: str = Field(min_length=3, max_length=1500)
    scope_type: Literal["GLOBAL", "SITE", "VENDOR", "ITEM", "WORKFLOW"] = "GLOBAL"
    topic: str | None = Field(default=None, max_length=160)
    metadata: dict[str, Any] = Field(default_factory=dict)


class LabKnowledgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_ref: str = Field(min_length=1, max_length=200)
    site: Literal["MAJA", "CEMPLANG"] | None = None
    vendor: str | None = Field(default=None, max_length=100)
    user_message: str = Field(min_length=1, max_length=20000)
    facts: list[LabKnowledgeFact] = Field(min_length=1, max_length=30)


class LabKnowledgeResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    stored: bool
    databaseReady: bool | None = None
    eventId: int | None = None
    sourceKey: str | None = None
    promoted: list[dict[str, Any]] = Field(default_factory=list)
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    knowledgeWrite: bool = True
    knowledgeStatus: str | None = None
    operationalMutation: bool = False


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
    commitEligible: bool = False
    confirmationToken: str | None = None
    confirmationExpiresInSeconds: int | None = None
    commitBlockReason: str | None = None


class LabReceivingCommitRequest(LabReceivingPreviewRequest):
    confirmation_token: str = Field(min_length=20, max_length=500)
    confirmation: Literal["COMMIT TRUE"]


class LabReceivingCommitResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    committed: bool
    operationalMutation: bool = True
    mutationType: str = "RECEIVING"
    humanConfirmation: bool = True
    confirmation: str = "COMMIT TRUE"
    receiptId: int | None = None
    receiptIds: list[int] = Field(default_factory=list)
    receipts: list[dict[str, Any]] = Field(default_factory=list)
    purchaseOrderId: int | None = None
    purchaseOrderIds: list[int] = Field(default_factory=list)
    poCode: str | None = None
    poCodes: list[str | None] = Field(default_factory=list)
    stockCommitted: bool | None = None
    stockInserted: int | None = None
    stockDuplicates: int | None = None


def _require_core() -> None:
    if not base.SPPG_CORE_URL or not base.SPPG_GPT_API_KEY:
        raise HTTPException(status_code=503, detail="SPPG Core API is not configured")


async def _post_core(path: str, body: dict[str, Any], label: str) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{base.SPPG_CORE_URL}{path}",
                json=body,
                headers=base._memory_headers(),
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"SPPG Core {label} connection failed: {exc.__class__.__name__}") from exc

    if response.status_code >= 400:
        detail: Any = None
        try:
            detail = response.json()
        except ValueError:
            detail = None
        raise HTTPException(
            status_code=502,
            detail={"message": f"SPPG Core rejected {label}", "upstreamStatus": response.status_code, "upstreamDetail": detail},
        )
    try:
        data = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=f"Unexpected SPPG Core {label} response") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail=f"Unexpected SPPG Core {label} response")
    return data


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
        raise HTTPException(status_code=502, detail={"message": "SPPG Core rejected context read", "upstreamStatus": response.status_code})
    try:
        data = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Unexpected SPPG Core context response") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="Unexpected SPPG Core context response")
    return {**data, "readOnly": True, "sourceOfTruth": "SPPG Core PostgreSQL + confirmed LLM Wiki knowledge"}


@app.post("/v1/lab/knowledge", response_model=LabKnowledgeResponse)
async def store_knowledge(payload: LabKnowledgeRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """Store explicit user-confirmed facts in durable LLM Wiki memory only."""
    base._authorize(authorization)
    _require_core()
    body = {**payload.model_dump(mode="json", exclude_none=True), "actor": "hermes"}
    data = await _post_core("/v1/gpt/knowledge", body, "knowledge write")
    if bool(data.get("operationalMutation")):
        raise HTTPException(status_code=502, detail="Unsafe knowledge response from SPPG Core")
    return {**data, "knowledgeWrite": True, "operationalMutation": False}


@app.post("/v1/lab/receiving-preview", response_model=LabReceivingPreviewResponse)
async def receiving_preview(payload: LabReceivingPreviewRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """Proxy the Core multi-PO resolver without operational mutation."""
    base._authorize(authorization)
    _require_core()
    data = await _post_core(
        "/v1/gpt/hermes-read/receiving-preview",
        payload.model_dump(mode="json", exclude_none=True),
        "receiving preview",
    )
    if bool(data.get("committed")) or bool(data.get("operationalMutation")):
        raise HTTPException(status_code=502, detail="Unsafe receiving preview response from SPPG Core")
    return {**data, "committed": False, "readOnly": True, "operationalMutation": False, "sourceOfTruth": "SPPG Core PostgreSQL"}


@app.post("/v1/lab/receiving-commit", response_model=LabReceivingCommitResponse)
async def receiving_commit(payload: LabReceivingCommitRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """Commit receiving only with a valid preview token and explicit COMMIT TRUE."""
    base._authorize(authorization)
    _require_core()
    data = await _post_core(
        "/v1/gpt/hermes-actions/receiving-commit",
        payload.model_dump(mode="json", exclude_none=True),
        "receiving commit",
    )
    if not bool(data.get("committed")) or not bool(data.get("operationalMutation")):
        raise HTTPException(status_code=502, detail="SPPG Core did not confirm receiving mutation")
    return data
