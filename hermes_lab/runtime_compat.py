from __future__ import annotations

from copy import deepcopy
from typing import Any

from hermes_lab import app as base
from hermes_lab import runtime as runtime


app = runtime.app
_original_builder = base._build_chatgpt_action_schema


def _compat_response_schema(operation: dict[str, Any]) -> None:
    responses = operation.setdefault("responses", {})
    for code, response in list(responses.items()):
        if not str(code).startswith("2") or not isinstance(response, dict):
            continue
        content = response.setdefault("content", {})
        app_json = content.setdefault("application/json", {})
        app_json["schema"] = {
            "type": "object",
            "properties": {},
            "additionalProperties": True,
        }


def build_chatgpt_action_schema_compat(public_origin: str) -> dict[str, Any]:
    """Keep request schemas strict but make success response schemas permissive.

    OpenAI Custom GPT Actions only needs a reliable JSON object contract for
    these gateway operations. The runtime payload itself remains unchanged.
    This avoids client-side response validation failures caused by rich nested
    Pydantic response models containing nullable/Any-heavy structures.
    """

    schema = deepcopy(_original_builder(public_origin))
    for path, methods in schema.get("paths", {}).items():
        if path == "/health" or not isinstance(methods, dict):
            continue
        for method, operation in methods.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                continue
            if isinstance(operation, dict):
                _compat_response_schema(operation)
    return schema


# The already-registered schema route resolves this module attribute at request
# time, so replacing it here changes only the generated Custom GPT schema.
base._build_chatgpt_action_schema = build_chatgpt_action_schema_compat
