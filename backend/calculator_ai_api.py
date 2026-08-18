from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1", tags=["calculator-ai"])


class CalculatorAIRequest(BaseModel):
    provider: Literal["gemini", "openai"] = "gemini"
    prompt: str = Field(min_length=1)
    system_prompt: str | None = None
    model: str | None = None
    temperature: float = 0.1
    task: str | None = None


def _env_first(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def _read_error(exc: urllib.error.HTTPError) -> str:
    try:
        raw = exc.read().decode("utf-8", errors="replace")
        if raw:
            return raw[:1200]
    except Exception:
        pass
    return str(exc)


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: int = 70) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = _read_error(exc)
        raise HTTPException(exc.code, f"AI provider error: {detail}") from exc
    except urllib.error.URLError as exc:
        raise HTTPException(502, f"AI provider tidak bisa dihubungi: {exc.reason}") from exc
    except TimeoutError as exc:
        raise HTTPException(504, "AI provider timeout") from exc


def _gemini_key() -> str:
    return _env_first("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GEMINI_API_KEY", "AI_GEMINI_API_KEY")


def _openai_key() -> str:
    return _env_first("OPENAI_API_KEY", "AI_OPENAI_API_KEY")


def _gemini_model(requested: str | None) -> str:
    return (requested or os.getenv("GEMINI_MODEL") or os.getenv("AI_MENU_MODEL") or "gemini-2.5-flash").strip()


def _openai_model(requested: str | None) -> str:
    return (requested or os.getenv("OPENAI_MODEL") or os.getenv("AI_MENU_MODEL") or "gpt-4o-mini").strip()


def _call_gemini(payload: CalculatorAIRequest) -> str:
    key = _gemini_key()
    if not key:
        raise HTTPException(503, "GEMINI_API_KEY belum ada di Railway Variables")
    model = _gemini_model(payload.model)
    body: dict[str, Any] = {
        "contents": [{"parts": [{"text": payload.prompt}]}],
        "generationConfig": {"temperature": payload.temperature},
    }
    if payload.system_prompt:
        body["systemInstruction"] = {"parts": [{"text": payload.system_prompt}]}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{urllib.parse.quote(model)}:generateContent?key={urllib.parse.quote(key)}"
    data = _post_json(url, body, {"Content-Type": "application/json"}, timeout=75)
    text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text")
    if not text:
        raise HTTPException(502, "Gemini tidak mengembalikan konten")
    return str(text)


def _call_openai(payload: CalculatorAIRequest) -> str:
    key = _openai_key()
    if not key:
        raise HTTPException(503, "OPENAI_API_KEY belum ada di Railway Variables")
    messages: list[dict[str, str]] = []
    if payload.system_prompt:
        messages.append({"role": "system", "content": payload.system_prompt})
    messages.append({"role": "user", "content": payload.prompt})
    body = {
        "model": _openai_model(payload.model),
        "messages": messages,
        "temperature": payload.temperature,
    }
    data = _post_json(
        "https://api.openai.com/v1/chat/completions",
        body,
        {"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        timeout=60,
    )
    text = data.get("choices", [{}])[0].get("message", {}).get("content")
    if not text:
        raise HTTPException(502, "OpenAI tidak mengembalikan konten")
    return str(text)


@router.get("/calculator-ai/status")
def calculator_ai_status() -> dict[str, Any]:
    return {
        "enabled": bool(_gemini_key() or _openai_key()),
        "geminiConfigured": bool(_gemini_key()),
        "openaiConfigured": bool(_openai_key()),
        "defaultProvider": os.getenv("AI_MENU_PROVIDER", "gemini").strip() or "gemini",
        "geminiModel": _gemini_model(None),
        "openaiModel": _openai_model(None),
    }


@router.post("/calculator-ai/generate")
def calculator_ai_generate(payload: CalculatorAIRequest) -> dict[str, Any]:
    provider = payload.provider
    if provider == "openai":
        text = _call_openai(payload)
        model = _openai_model(payload.model)
    else:
        text = _call_gemini(payload)
        model = _gemini_model(payload.model)
    return {"provider": provider, "model": model, "text": text}
