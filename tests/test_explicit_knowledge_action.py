from backend import knowledge_runtime_api as runtime
from backend.action_schema_runtime_patch import schema_v0184_core_repair


def test_explicit_knowledge_action_is_distinct_from_operational_review():
    schema = schema_v0184_core_repair()
    operation = schema["paths"]["/v1/gpt/knowledge"]["post"]

    assert schema["info"]["version"] == "0.18.9"
    assert operation["operationId"] == "recordExplicitSppgKnowledge"
    assert operation["x-openai-isConsequential"] is False
    assert "never send them to operational review" in operation["description"]


def test_primary_custom_gpt_schema_stays_within_operation_limit():
    schema = schema_v0184_core_repair()
    operations = [
        (method, path)
        for path, path_item in schema["paths"].items()
        for method in path_item
        if method.lower() in {"get", "post", "put", "patch", "delete"}
    ]

    assert len(operations) == 30
    assert "/v1/gpt/operational-context" in schema["paths"]
    assert "/v1/gpt/learn-conversation" in schema["paths"]
    assert "/v1/gpt/knowledge" in schema["paths"]
    assert "/v1/operations/history/import" not in schema["paths"]
    assert "/v1/gpt/backfill-firestore" not in schema["paths"]
    assert "/v1/calculator-data/plan-preview" not in schema["paths"]
    assert "/v1/calculator-data/import" not in schema["paths"]
    assert "/v1/accountant-excel/from-planning" not in schema["paths"]


def test_explicit_knowledge_is_promoted_as_confirmed_user_fact(monkeypatch):
    captured = {}

    def fake_learn(payload):
        captured["payload"] = payload
        return {"stored": True, "promoted": [{"status": "CONFIRMED"}], "candidates": []}

    monkeypatch.setattr(runtime, "learn_conversation", fake_learn)
    result = runtime.record_explicit_knowledge(runtime.ExplicitKnowledgeIn(
        source_ref="unit-conversion-oil-20260821",
        user_message="Catat di LLM Wiki: minyak 1 pcs = 2 liter.",
        facts=[runtime.ExplicitKnowledgeFactIn(
            statement="Minyak goreng 1 pcs = 2 liter.",
            scope_type="ITEM",
            topic="unit conversion",
        )],
    ))

    fact = captured["payload"].facts[0]
    assert fact.kind == "USER_EXPLICIT"
    assert fact.confidence == 1.0
    assert fact.metadata["explicitlyRequested"] is True
    assert result["knowledgeStatus"] == "CONFIRMED"
    assert result["operationalMutation"] is False
