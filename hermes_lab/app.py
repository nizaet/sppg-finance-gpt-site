import hashlib
import hmac
import json
import os
from collections import defaultdict
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Literal
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, Header, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

app = FastAPI(
    title="SPPG Hermes Lab Gateway",
    version="0.5.2",
    description="Isolated SPPG gateway that lets Hermes read context, share durable memory, and stage approval-required action proposals. The gateway cannot execute operations.",
)

HERMES_API_URL = os.getenv("HERMES_API_URL", "").rstrip("/")
HERMES_API_KEY = os.getenv("HERMES_API_KEY", "")
LAB_GATEWAY_KEY = os.getenv("LAB_GATEWAY_KEY", "")
HERMES_MODEL = os.getenv("HERMES_MODEL", "hermes-agent")
SPPG_CORE_URL = os.getenv("SPPG_CORE_URL", "").rstrip("/")
SPPG_GPT_API_KEY = os.getenv("SPPG_GPT_API_KEY", "")
HERMES_PUBLIC_URL = os.getenv("HERMES_PUBLIC_URL", "").strip().rstrip("/")

GPT_ACTION_OPERATIONS = {
    "/health": {"get": "hermesLabHealth"},
    "/v1/lab/chat": {"post": "askHermesLab"},
    "/v1/lab/purchase-orders": {"get": "searchHermesSppgPurchaseOrders"},
    "/v1/lab/proposals": {"post": "createHermesActionProposal"},
}

SYSTEM_POLICY = """You are SPPG Hermes Lab, an experimental operations agent in migration mode.
You may inspect and reason over approved SPPG/LLM Wiki context, including confirmed knowledge and conversation behavior learned from the legacy GPTS.
You may write to the shared LLM memory/knowledge layer and prepare an explicit action proposal in the isolated staging queue. A proposal is not approval and is never execution.
You must not approve, execute, create, update, delete, send, pay, commit, or otherwise mutate operational production data such as PO, receiving, stock, finance, payment, Firestore, Drive, GitHub, or SPPG Core ledger records.
Use the supplied behavior memory to preserve the user's established corrections, classification choices, workflow habits, terminology, and formatting preferences. More recent explicit corrections override older behavior.
Treat assistant inference as weaker than explicit user statements or confirmed actions. Never turn an inferred pattern directly into an operational mutation.
If the user asks for a production mutation, explain or propose the action only unless a separately approved production tool is explicitly provided later.
Prefer explicit site/date/vendor identifiers and report genuine uncertainty rather than guessing.
For live PO questions, use the dedicated read-only purchase-order search result supplied by the Custom GPT action. Never claim database access succeeded when that action returned an authentication or connection error.
For CREATE_PO proposals, provide only a complete canonical DRAFT payload using snake_case fields: po_code, distribution_date, optional cooking_at/source_planning_snapshot_id, status DRAFT, items, and optional per-day coverage. Every item requires item_name and po_qty greater than zero. Never invent a quantity, price, planning identifier, vendor, site, or date.
"""


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class LabChatRequest(BaseModel):
    messages: List[Message] = Field(min_length=1, max_length=40)
    conversation_ref: str | None = Field(default=None, max_length=200)
    turn_ref: str | None = Field(default=None, max_length=200)


class LabChatResponse(BaseModel):
    answer: str
    mode: str = "read_operational_write_memory_propose_actions"
    model: str
    memory_loaded: bool = False
    memory_stored: bool = False


class LabHealthResponse(BaseModel):
    ok: bool
    service: str
    mode: str
    hermes_configured: bool
    shared_memory_configured: bool
    operational_read_configured: bool
    action_proposals_configured: bool
    action_execution_exposed: bool
    gpt_action_schema: str


class LabPurchaseOrderItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    purchase_order_item_id: int | None = None
    item_code: str | None = None
    item_name: str | None = None
    planned_qty: float | None = None
    po_qty: float | None = None
    unit: str | None = None
    planning_price: float | None = None
    po_price: float | None = None


class LabPurchaseOrderRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    purchase_order_id: int
    po_code: str
    revision_no: int | None = None
    site: str | None = None
    vendor_code: str | None = None
    status: str | None = None
    distribution_date: date | None = None
    item_count: int = 0
    items: list[LabPurchaseOrderItem] = Field(default_factory=list)


class LabPurchaseOrderSearchResponse(BaseModel):
    items: list[LabPurchaseOrderRecord]
    count: int
    readOnly: bool
    sourceOfTruth: str


ActionType = Literal[
    "CREATE_PO",
    "RECORD_RECEIVING",
    "RECORD_VENDOR_PAYABLE",
    "RECORD_VENDOR_PAYMENT",
    "RECORD_FINANCE_TRANSACTION",
    "SEND_WHATSAPP",
]


class LabPoDraftItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_code: str | None = Field(default=None, max_length=160)
    item_name: str = Field(min_length=1, max_length=300)
    planning_snapshot_item_id: int | None = Field(default=None, ge=1)
    planned_qty: float | None = Field(default=None, ge=0)
    po_qty: float = Field(gt=0)
    unit: str | None = Field(default=None, max_length=40)
    planning_price: float | None = Field(default=None, ge=0)
    po_price: float | None = Field(default=None, ge=0)
    aliases: list[str] = Field(default_factory=list, max_length=30)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("item_name")
    @classmethod
    def normalize_item_name(cls, value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("item_name cannot be blank")
        return name


class LabPoDraftCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    distribution_date: date
    cooking_date: date | None = None
    source_planning_snapshot_id: int | None = Field(default=None, ge=1)
    items: list[LabPoDraftItem] = Field(min_length=1, max_length=300)


class LabPoDraftPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    po_code: str = Field(min_length=3, max_length=220)
    distribution_date: date
    cooking_at: datetime | None = None
    source_planning_snapshot_id: int | None = Field(default=None, ge=1)
    status: Literal["DRAFT"] = "DRAFT"
    items: list[LabPoDraftItem] = Field(min_length=1, max_length=300)
    coverage: list[LabPoDraftCoverage] = Field(default_factory=list, max_length=31)

    @field_validator("po_code")
    @classmethod
    def normalize_po_code(cls, value: str) -> str:
        return value.strip().upper()

    @model_validator(mode="after")
    def validate_coverage_totals(self) -> "LabPoDraftPayload":
        if not self.coverage:
            return self
        dates = [row.distribution_date for row in self.coverage]
        if len(set(dates)) != len(dates) or min(dates) != self.distribution_date:
            raise ValueError("coverage dates must be unique and start at distribution_date")

        def key(item: LabPoDraftItem) -> tuple[str, str]:
            return (
                str(item.item_code or item.item_name).strip().upper(),
                str(item.unit or "").strip().lower(),
            )

        order_totals: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
        coverage_totals: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
        for item in self.items:
            order_totals[key(item)] += Decimal(str(item.po_qty))
        for coverage in self.coverage:
            for item in coverage.items:
                coverage_totals[key(item)] += Decimal(str(item.po_qty))
        if order_totals != coverage_totals:
            raise ValueError("aggregate items must exactly match coverage item quantities")
        return self


class LabActionProposalRequest(BaseModel):
    source_ref: str = Field(min_length=1, max_length=300)
    action_type: ActionType
    site: Literal["MAJA", "CEMPLANG"]
    vendor_code: str | None = Field(default=None, max_length=100)
    entity_code: str | None = Field(default=None, max_length=160)
    target_type: str = Field(min_length=1, max_length=100)
    target_id: str | None = Field(default=None, max_length=200)
    rationale: str = Field(min_length=1, max_length=2000)
    confidence: float = Field(default=0.5, ge=0, le=1)
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_create_po_contract(self) -> "LabActionProposalRequest":
        if self.action_type != "CREATE_PO":
            return self
        if self.target_type != "purchase_order" or self.target_id is not None:
            raise ValueError("CREATE_PO must target a new purchase_order")
        if not str(self.vendor_code or "").strip():
            raise ValueError("CREATE_PO requires vendor_code")
        draft = LabPoDraftPayload.model_validate(self.payload)
        site = self.site.upper()
        expected_prefix = f"PO-{site}-{draft.distribution_date.strftime('%Y%m%d')}"
        if not draft.po_code.upper().startswith(expected_prefix):
            raise ValueError(f"CREATE_PO po_code must start with {expected_prefix}")
        self.vendor_code = str(self.vendor_code).strip().upper()
        self.payload = draft.model_dump(mode="json")
        return self


class LabActionProposalResponse(BaseModel):
    proposalId: int
    actionId: int
    candidateStatus: str
    actionStatus: str
    inserted: bool
    approvalRequired: bool
    executed: bool
    executionLocked: bool


def _authorize(authorization: str | None) -> None:
    if not LAB_GATEWAY_KEY:
        raise HTTPException(status_code=503, detail="LAB_GATEWAY_KEY is not configured")
    scheme, separator, credential = (authorization or "").partition(" ")
    if not separator or scheme.lower() != "bearer" or not hmac.compare_digest(credential, LAB_GATEWAY_KEY):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _memory_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {SPPG_GPT_API_KEY}",
        "Content-Type": "application/json",
    }


def _validated_origin(value: str) -> str | None:
    candidate = value.strip().rstrip("/")
    parsed = urlsplit(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def _request_public_origin(request: Request) -> str:
    if HERMES_PUBLIC_URL:
        configured = _validated_origin(HERMES_PUBLIC_URL)
        if not configured:
            raise HTTPException(status_code=503, detail="HERMES_PUBLIC_URL is invalid")
        return configured

    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip()
    forwarded_host = request.headers.get("x-forwarded-host", "").split(",", 1)[0].strip()
    scheme = forwarded_proto or request.url.scheme
    host = forwarded_host or request.headers.get("host", "").strip()
    inferred = _validated_origin(f"{scheme}://{host}")
    if not inferred:
        raise HTTPException(status_code=503, detail="Unable to determine the public Hermes origin")
    return inferred


def _build_chatgpt_action_schema(public_origin: str) -> dict[str, Any]:
    """Return the small, stable GPT Action contract with a real runtime origin."""
    schema = deepcopy(app.openapi())
    schema["info"] = {
        **schema.get("info", {}),
        "title": "SPPG Hermes Lab",
        "version": app.version,
        "description": (
            "Authenticated SPPG Hermes gateway with shared behavior memory, "
            "read-only operational access, and approval-required staging proposals."
        ),
    }
    schema["servers"] = [{"url": public_origin}]
    schema["paths"] = {
        path: deepcopy(schema["paths"][path])
        for path in GPT_ACTION_OPERATIONS
        if path in schema.get("paths", {})
    }

    for path, methods in GPT_ACTION_OPERATIONS.items():
        for method, operation_id in methods.items():
            operation = schema["paths"][path][method]
            operation["operationId"] = operation_id
            if path != "/health":
                operation["security"] = [{"bearerAuth": []}]
                operation["parameters"] = [
                    parameter
                    for parameter in operation.get("parameters", [])
                    if str(parameter.get("name", "")).lower() != "authorization"
                ]

    components = schema.setdefault("components", {})
    if not isinstance(components.get("schemas"), dict):
        components["schemas"] = {}
    components.setdefault("securitySchemes", {})["bearerAuth"] = {
        "type": "http",
        "scheme": "bearer",
    }
    _ensure_object_schema_properties(schema)
    return schema


def _ensure_object_schema_properties(node: Any) -> None:
    """Make every object schema explicit for the strict GPT Action importer."""
    if isinstance(node, dict):
        if node.get("type") == "object" and not isinstance(node.get("properties"), dict):
            node["properties"] = {}
        for value in node.values():
            _ensure_object_schema_properties(value)
    elif isinstance(node, list):
        for value in node:
            _ensure_object_schema_properties(value)


def _last_user_message(messages: List[Message]) -> str:
    for message in reversed(messages):
        if message.role == "user":
            return message.content
    return messages[-1].content


def _refs(payload: LabChatRequest) -> tuple[str, str]:
    if payload.conversation_ref:
        conversation_ref = payload.conversation_ref
    else:
        first_user = next((m.content for m in payload.messages if m.role == "user"), payload.messages[0].content)
        digest = hashlib.sha256(first_user.encode("utf-8")).hexdigest()[:20]
        conversation_ref = f"hermes-lab:{digest}"
    if payload.turn_ref:
        turn_ref = payload.turn_ref
    else:
        canonical = json.dumps([m.model_dump() for m in payload.messages], sort_keys=True, ensure_ascii=False)
        turn_ref = "turn:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
    return conversation_ref, turn_ref


async def _load_shared_behavior(client: httpx.AsyncClient) -> dict[str, Any] | None:
    if not SPPG_CORE_URL or not SPPG_GPT_API_KEY:
        return None
    try:
        response = await client.get(
            f"{SPPG_CORE_URL}/v1/llm-wiki/context",
            params={"topic": "behavior", "limit": 20},
            headers=_memory_headers(),
        )
        if response.status_code >= 400:
            return None
        data = response.json()
        return data if isinstance(data, dict) else None
    except (httpx.HTTPError, ValueError):
        return None


async def _store_shared_turn(
    client: httpx.AsyncClient,
    payload: LabChatRequest,
    answer: str,
) -> bool:
    if not SPPG_CORE_URL or not SPPG_GPT_API_KEY:
        return False
    conversation_ref, turn_ref = _refs(payload)
    body = {
        "conversation_ref": conversation_ref,
        "turn_ref": turn_ref,
        "user_message": _last_user_message(payload.messages),
        "assistant_summary": answer[:6000],
        "action_context": {
            "source": "hermes_lab_gateway",
            "mode": "read_operational_write_memory_propose_actions",
            "operationalMutation": False,
        },
        "facts": [],
        "actor": "hermes",
    }
    try:
        response = await client.post(
            f"{SPPG_CORE_URL}/v1/llm-wiki/learn-conversation",
            json=body,
            headers=_memory_headers(),
        )
        return response.status_code < 400
    except httpx.HTTPError:
        return False


@app.get("/health", response_model=LabHealthResponse)
def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "service": "sppg-hermes-lab",
        "mode": "read_operational_write_memory_propose_actions",
        "hermes_configured": bool(HERMES_API_URL and HERMES_API_KEY),
        "shared_memory_configured": bool(SPPG_CORE_URL and SPPG_GPT_API_KEY),
        "operational_read_configured": bool(SPPG_CORE_URL and SPPG_GPT_API_KEY),
        "action_proposals_configured": bool(SPPG_CORE_URL and SPPG_GPT_API_KEY),
        "action_execution_exposed": False,
        "gpt_action_schema": "/v1/schema/chatgpt-hermes.json",
    }


@app.get("/v1/schema/chatgpt-hermes.json", include_in_schema=False)
def chatgpt_action_schema(request: Request) -> dict[str, Any]:
    """Serve an import-ready GPT Action schema for the gateway's current origin."""
    return _build_chatgpt_action_schema(_request_public_origin(request))


@app.get("/v1/lab/purchase-orders", response_model=LabPurchaseOrderSearchResponse)
async def search_purchase_orders_read_only(
    authorization: str | None = Header(default=None),
    site: Literal["MAJA", "CEMPLANG"] | None = None,
    vendor: str = Query(default="", max_length=100),
    distribution_date: date | None = Query(default=None, alias="distributionDate"),
    date_from: date | None = Query(default=None, alias="dateFrom"),
    date_to: date | None = Query(default=None, alias="dateTo"),
    status: str = Query(default="", max_length=60),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """Proxy an authenticated, read-only PO search to SPPG Core."""
    _authorize(authorization)
    if not SPPG_CORE_URL or not SPPG_GPT_API_KEY:
        raise HTTPException(status_code=503, detail="SPPG Core operational read API is not configured")
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=422, detail="dateFrom must be on or before dateTo")

    params: dict[str, Any] = {"limit": limit}
    if site:
        params["site"] = site
    if vendor.strip():
        params["vendor"] = vendor.strip()
    if distribution_date:
        params["distributionDate"] = distribution_date.isoformat()
    if date_from:
        params["dateFrom"] = date_from.isoformat()
    if date_to:
        params["dateTo"] = date_to.isoformat()
    if status.strip():
        params["status"] = status.strip()

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{SPPG_CORE_URL}/v1/purchase-orders/search",
                params=params,
                headers=_memory_headers(),
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"SPPG Core PO search connection failed: {exc.__class__.__name__}",
        ) from exc

    if response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "SPPG Core rejected the read-only PO search",
                "upstreamStatus": response.status_code,
            },
        )
    try:
        data = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Unexpected SPPG Core PO search response") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="Unexpected SPPG Core PO search response")
    return {**data, "readOnly": True, "sourceOfTruth": "SPPG Core PostgreSQL"}


@app.post("/v1/lab/proposals", response_model=LabActionProposalResponse)
async def create_action_proposal(
    payload: LabActionProposalRequest,
    authorization: str | None = Header(default=None),
) -> LabActionProposalResponse:
    _authorize(authorization)
    if not SPPG_CORE_URL or not SPPG_GPT_API_KEY:
        raise HTTPException(status_code=503, detail="SPPG Core proposal API is not configured")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{SPPG_CORE_URL}/v1/gpt/hermes-actions/proposals",
                json=payload.model_dump(mode="json", exclude_none=True),
                headers=_memory_headers(),
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"SPPG Core proposal connection failed: {exc.__class__.__name__}",
        ) from exc

    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail="SPPG Core rejected the action proposal")
    try:
        data = response.json()
        result = LabActionProposalResponse.model_validate(data)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=502, detail="Unexpected SPPG Core proposal response") from exc
    if result.executed or not result.executionLocked or not result.approvalRequired:
        raise HTTPException(status_code=502, detail="Unsafe proposal response from SPPG Core")
    return result


@app.post("/v1/lab/chat", response_model=LabChatResponse)
async def lab_chat(payload: LabChatRequest, authorization: str | None = Header(default=None)) -> LabChatResponse:
    _authorize(authorization)
    if not HERMES_API_URL or not HERMES_API_KEY:
        raise HTTPException(status_code=503, detail="Hermes backend is not configured")

    headers = {
        "Authorization": f"Bearer {HERMES_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            shared_memory = await _load_shared_behavior(client)

            messages = [{"role": "system", "content": SYSTEM_POLICY}]
            if shared_memory:
                compact_memory = json.dumps(shared_memory, ensure_ascii=False, default=str)
                messages.append({
                    "role": "system",
                    "content": "SHARED SPPG MEMORY FROM LEGACY GPTS AND HERMES:\n" + compact_memory[:24000],
                })
            messages.extend(m.model_dump() for m in payload.messages)

            body = {
                "model": HERMES_MODEL,
                "messages": messages,
                "stream": False,
                "temperature": 0.1,
            }

            response = await client.post(
                f"{HERMES_API_URL}/v1/chat/completions",
                json=body,
                headers=headers,
            )
            if response.status_code >= 400:
                raise HTTPException(status_code=502, detail="Hermes backend returned an error")

            data = response.json()
            try:
                answer = data["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError) as exc:
                raise HTTPException(status_code=502, detail="Unexpected Hermes response format") from exc

            memory_stored = await _store_shared_turn(client, payload, answer)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Hermes connection failed: {exc.__class__.__name__}") from exc

    return LabChatResponse(
        answer=answer,
        model=HERMES_MODEL,
        memory_loaded=bool(shared_memory),
        memory_stored=memory_stored,
    )
