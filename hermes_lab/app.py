import hashlib
import json
import os
from typing import Any, Dict, List, Literal

import httpx
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(
    title="SPPG Hermes Lab Gateway",
    version="0.2.0",
    description="Isolated SPPG gateway that lets Hermes read production context and share durable memory with the legacy GPTS without operational write access.",
)

HERMES_API_URL = os.getenv("HERMES_API_URL", "").rstrip("/")
HERMES_API_KEY = os.getenv("HERMES_API_KEY", "")
LAB_GATEWAY_KEY = os.getenv("LAB_GATEWAY_KEY", "")
HERMES_MODEL = os.getenv("HERMES_MODEL", "hermes-agent")
SPPG_CORE_URL = os.getenv("SPPG_CORE_URL", "").rstrip("/")
SPPG_GPT_API_KEY = os.getenv("SPPG_GPT_API_KEY", "")

SYSTEM_POLICY = """You are SPPG Hermes Lab, an experimental operations agent in migration mode.
You may inspect and reason over approved SPPG/LLM Wiki context, including confirmed knowledge and conversation behavior learned from the legacy GPTS.
You may write only to the shared LLM memory/knowledge layer. You must not create, update, delete, send, approve, pay, commit, or otherwise mutate operational production data such as PO, receiving, stock, finance, payment, Firestore, Drive, GitHub, or SPPG Core records.
Use the supplied behavior memory to preserve the user's established corrections, classification choices, workflow habits, terminology, and formatting preferences. More recent explicit corrections override older behavior.
Treat assistant inference as weaker than explicit user statements or confirmed actions. Never turn an inferred pattern directly into an operational mutation.
If the user asks for a production mutation, explain or propose the action only unless a separately approved production tool is explicitly provided later.
Prefer explicit site/date/vendor identifiers and report genuine uncertainty rather than guessing.
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
    mode: str = "read_operational_write_memory"
    model: str
    memory_loaded: bool = False
    memory_stored: bool = False


def _authorize(authorization: str | None) -> None:
    if not LAB_GATEWAY_KEY:
        raise HTTPException(status_code=503, detail="LAB_GATEWAY_KEY is not configured")
    if authorization != f"Bearer {LAB_GATEWAY_KEY}":
        raise HTTPException(status_code=401, detail="Unauthorized")


def _memory_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {SPPG_GPT_API_KEY}",
        "Content-Type": "application/json",
    }


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
            "mode": "read_operational_write_memory",
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


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "service": "sppg-hermes-lab",
        "mode": "read_operational_write_memory",
        "hermes_configured": bool(HERMES_API_URL and HERMES_API_KEY),
        "shared_memory_configured": bool(SPPG_CORE_URL and SPPG_GPT_API_KEY),
    }


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
