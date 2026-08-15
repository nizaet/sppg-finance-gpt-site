from backend.operations_action_schema_v017_api import schema_v0172
from backend.unified_action_schema_api import schema_v0180, schema_v0181


def test_v0180_preserves_v0172_and_adds_accountant_and_final_po_actions():
    previous = schema_v0172()
    unified = schema_v0180()

    assert unified["info"]["version"] == "0.18.0"
    for path, methods in previous["paths"].items():
        assert unified["paths"][path] == methods

    finance = unified["paths"]["/v1/gpt/finance-transactions"]
    assert finance["get"]["operationId"] == "searchSppgAccountantTransactions"
    assert finance["post"]["operationId"] == "createSppgAccountantTransactions"
    assert finance["post"]["x-openai-isConsequential"] is True

    patch = unified["paths"]["/v1/gpt/finance-transactions/{transaction_id}"]["patch"]
    assert patch["operationId"] == "updateSppgAccountantTransaction"
    assert patch["x-openai-isConsequential"] is True

    backfill = unified["paths"]["/v1/gpt/backfill-firestore"]["post"]
    assert backfill["operationId"] == "previewOrBackfillSppgAccountantFirestoreHistory"
    assert backfill["x-openai-isConsequential"] is True
    backfill_body = backfill["requestBody"]["content"]["application/json"]["schema"]
    assert backfill_body["properties"]["dry_run"]["default"] is True

    po = unified["paths"]["/v1/po-whatsapp-preview"]["get"]
    assert po["operationId"] == "getFinalSppgPurchaseOrderWhatsAppMessage"
    assert po["x-openai-isConsequential"] is False


def test_v0180_has_unique_operation_ids_and_fits_gpt_action_limits():
    unified = schema_v0180()
    operation_ids = []
    for methods in unified["paths"].values():
        for operation in methods.values():
            if not isinstance(operation, dict) or "operationId" not in operation:
                continue
            operation_ids.append(operation["operationId"])
            assert len(operation.get("summary", "")) <= 300
            assert len(operation.get("description", "")) <= 300
            for parameter in operation.get("parameters", []):
                assert len(parameter.get("description", "")) <= 700

    assert len(operation_ids) == len(set(operation_ids))


def test_finance_create_requires_exact_source_and_transaction_fields():
    operation = schema_v0180()["paths"]["/v1/gpt/finance-transactions"]["post"]
    batch = operation["requestBody"]["content"]["application/json"]["schema"]
    assert set(batch["required"]) == {"site", "source_ref", "items"}
    item = batch["properties"]["items"]["items"]
    assert set(item["required"]) == {"date", "description", "type", "category", "amount"}


def test_v0181_preserves_v0180_and_adds_warehouse_actions():
    previous = schema_v0180()
    unified = schema_v0181()
    assert unified["info"]["version"] == "0.18.1"
    for path, methods in previous["paths"].items():
        assert unified["paths"][path] == methods

    opname = unified["paths"]["/v1/inventory/stock-opname/whatsapp"]["post"]
    body = opname["requestBody"]["content"]["application/json"]["schema"]
    assert opname["x-openai-isConsequential"] is True
    assert body["properties"]["commit"]["default"] is False
    assert set(body["required"]) == {"location", "text", "commit"}

    balance = unified["paths"]["/v1/inventory/balances"]["get"]
    assert balance["x-openai-isConsequential"] is False
    master = unified["paths"]["/v1/inventory/items"]["post"]
    assert master["x-openai-isConsequential"] is True


def test_v0181_has_unique_operation_ids_and_fits_gpt_action_limits():
    operation_ids = []
    for methods in schema_v0181()["paths"].values():
        for operation in methods.values():
            if not isinstance(operation, dict) or "operationId" not in operation:
                continue
            operation_ids.append(operation["operationId"])
            assert len(operation.get("summary", "")) <= 300
            assert len(operation.get("description", "")) <= 300
    assert len(operation_ids) == len(set(operation_ids))
