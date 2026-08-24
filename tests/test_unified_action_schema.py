from pathlib import Path

from backend.operations_action_schema_v017_api import schema_v0172
from backend.unified_action_schema_api import schema_v0180, schema_v0181, schema_v0182, schema_v0183, schema_v0184, schema_v0185, schema_v0186


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


def test_v0182_preserves_v0181_and_adds_safe_calculator_imports():
    previous = schema_v0181()
    unified = schema_v0182()
    assert unified["info"]["version"] == "0.18.2"
    for path, methods in previous["paths"].items():
        assert unified["paths"][path] == methods

    plan_preview = unified["paths"]["/v1/calculator-data/plan-preview"]["post"]
    assert plan_preview["x-openai-isConsequential"] is False
    assert plan_preview["operationId"] == "previewSppgCalculatorDailyPlanImport"

    data_import = unified["paths"]["/v1/calculator-data/import"]["post"]
    assert data_import["x-openai-isConsequential"] is True
    body = data_import["requestBody"]["content"]["application/json"]["schema"]
    assert set(body["required"]) == {"site", "data_type", "source_ref", "items", "commit"}
    assert "DAILY_PLANS" in body["properties"]["data_type"]["enum"]
    assert "BUMBU" in body["properties"]["data_type"]["enum"]
    opname = unified["paths"]["/v1/inventory/stock-opname/whatsapp"]["post"]
    opname_body = opname["requestBody"]["content"]["application/json"]["schema"]
    assert "reviewed_items" in opname_body["properties"]


def test_v0182_has_unique_operation_ids_and_fits_gpt_action_limits():
    operation_ids = []
    for methods in schema_v0182()["paths"].values():
        for operation in methods.values():
            if not isinstance(operation, dict) or "operationId" not in operation:
                continue
            operation_ids.append(operation["operationId"])
            assert len(operation.get("summary", "")) <= 300
            assert len(operation.get("description", "")) <= 300
            for parameter in operation.get("parameters", []):
                assert len(parameter.get("description", "")) <= 700
    assert len(operation_ids) == len(set(operation_ids))


def test_v0182_new_action_response_objects_have_explicit_properties():
    unified = schema_v0182()
    contexts = [
        ("/v1/inventory/balances", "get"),
        ("/v1/inventory/items", "get"),
        ("/v1/inventory/items", "post"),
        ("/v1/calculator-data/plan-preview", "post"),
        ("/v1/calculator-data/import", "post"),
    ]

    def assert_object_properties(schema):
        schema_type = schema.get("type")
        if schema_type == "object" or (isinstance(schema_type, list) and "object" in schema_type):
            assert "properties" in schema
            for child in schema["properties"].values():
                assert_object_properties(child)
        if schema_type == "array":
            assert_object_properties(schema["items"])

    for path, method in contexts:
        response = unified["paths"][path][method]["responses"]["200"]["content"]["application/json"]["schema"]
        assert_object_properties(response)


def test_v0182_gpts_instructions_keep_canonical_accountant_rules_and_fit_limit():
    instructions = Path("api/gpts_instructions_v0182.md").read_text(encoding="utf-8")
    assert len(instructions.encode("utf-8")) <= 8_000
    for category in (
        "Pemasukan: Insentif Sewa",
        "Pemasukan: Dana Operasional",
        "Pemasukan: Dana Bahan Baku",
        "Bahan Baku (Lauk)",
        "Bahan Baku (Sayur/Buah)",
        "Bahan Baku (Sembako/Bumbu)",
        "Operasional (Kebersihan/APD)",
        "Operasional (Utilitas)",
        "Operasional (Transport)",
        "Operasional (Gaji/Admin)",
        "Belanja Modal (Capex)",
        "Beban Profit (Non-Reimburse)",
        "Pembagian Dividen",
    ):
        assert f"`{category}`" in instructions
    assert "SPPG_DRIVE_RAW_CHAT_FOLDER_ID" in instructions
    assert "Jika `SYNCED`, transaksi berhasil" in instructions
    assert "satu pesan = satu preview dan satu commit/`stockOpnameId`" in instructions


def test_v0183_preserves_v0182_and_forbids_split_stock_opname_commits():
    previous = schema_v0182()
    unified = schema_v0183()
    assert unified["info"]["version"] == "0.18.3"
    assert unified["paths"] == previous["paths"]
    description = unified["paths"]["/v1/inventory/stock-opname/whatsapp"]["post"]["description"]
    assert "one baseline" in description
    assert "Never split" in description
    assert len(description) <= 300


def test_v0184_exposes_multi_day_po_coverage_and_runtime_extensions_within_builder_limit():
    unified = schema_v0184()
    assert unified["info"]["version"] == "0.18.10"
    assert "/v1/inventory/stock-opname/whatsapp" in unified["paths"]
    opname_description = unified["paths"]["/v1/inventory/stock-opname/whatsapp"]["post"]["description"]
    assert "replaces the prior physical count" in opname_description
    assert "qty 0" in opname_description
    assert len(opname_description) <= 300
    response = unified["paths"]["/v1/po-whatsapp-preview"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert response["properties"]["coverageDates"]["type"] == "array"
    assert response["properties"]["coverageDayCount"]["type"] == "integer"
    operations = [
        (method, path)
        for path, path_item in unified["paths"].items()
        for method in path_item
        if method.lower() in {"get", "post", "put", "patch", "delete"}
    ]
    assert len(operations) == 30


def test_v0185_adds_allowlisted_application_bridge_without_losing_existing_actions():
    previous = schema_v0184()
    unified = schema_v0185()
    assert unified["info"]["version"] == "0.18.5"
    for path, methods in previous["paths"].items():
        assert unified["paths"][path] == methods

    read = unified["paths"]["/v1/gpt/operations/read"]["post"]
    write = unified["paths"]["/v1/gpt/operations/execute"]["post"]
    assert read["operationId"] == "readSppgOperationalApplication"
    assert read["x-openai-isConsequential"] is False
    assert write["operationId"] == "previewOrExecuteSppgOperationalApplication"
    assert write["x-openai-isConsequential"] is True
    assert write["requestBody"]["content"]["application/json"]["schema"]["required"] == ["operation", "payload", "commit"]
    assert "VOID_STOCK_OPNAME" in write["requestBody"]["content"]["application/json"]["schema"]["properties"]["operation"]["enum"]
    assert "PURCHASE_ORDERS" in read["requestBody"]["content"]["application/json"]["schema"]["properties"]["resource"]["enum"]

    ids = [
        operation["operationId"]
        for methods in unified["paths"].values()
        for operation in methods.values()
        if isinstance(operation, dict) and "operationId" in operation
    ]
    assert len(ids) == len(set(ids))



def test_v0186_fits_gpt_operation_limit_without_losing_item_master_capability():
    unified = schema_v0186()
    assert unified["info"]["version"] == "0.18.6"
    assert "/v1/inventory/items" not in unified["paths"]

    read = unified["paths"]["/v1/gpt/operations/read"]["post"]
    write = unified["paths"]["/v1/gpt/operations/execute"]["post"]
    assert "INVENTORY_ITEM_MASTER" in read["requestBody"]["content"]["application/json"]["schema"]["properties"]["resource"]["enum"]
    assert "UPSERT_INVENTORY_ITEM_MASTER" in write["requestBody"]["content"]["application/json"]["schema"]["properties"]["operation"]["enum"]

    ids = [
        operation["operationId"]
        for methods in unified["paths"].values()
        for operation in methods.values()
        if isinstance(operation, dict) and "operationId" in operation
    ]
    assert len(ids) == 30
    assert len(ids) == len(set(ids))
