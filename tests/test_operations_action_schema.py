from backend.operations_action_schema_v017_api import schema_v017, schema_v0170


def test_v017_schema_exposes_safe_current_receiving_and_payments():
    schema = schema_v017()
    paths = schema["paths"]

    assert schema["info"]["version"] == "0.17.2"

    receiving = paths["/v1/receiving/whatsapp"]["post"]
    receiving_body = receiving["requestBody"]["content"]["application/json"]["schema"]
    assert receiving["operationId"] == "previewOrRecordSppgGoodsReceiptFromMessage"
    assert receiving["x-openai-isConsequential"] is True
    assert receiving_body["properties"]["commit"]["default"] is False
    assert set(receiving_body["required"]) == {"site", "text", "commit"}

    payment = paths["/v1/vendor-payments/confirm"]["post"]
    payment_body = payment["requestBody"]["content"]["application/json"]["schema"]
    assert payment["operationId"] == "confirmSppgVendorPayment"
    assert payment_body["properties"]["commit"]["default"] is False


def test_v0172_preserves_every_v0170_action_and_adds_staging_and_review():
    original = schema_v0170()
    enhanced = schema_v017()

    assert original["info"]["version"] == "0.17.0"
    assert len(original["paths"]) == 11
    for path, operation in original["paths"].items():
        assert enhanced["paths"][path] == operation

    staging = enhanced["paths"]["/v1/parse-message"]["post"]
    staging_body = staging["requestBody"]["content"]["application/json"]["schema"]
    assert staging["operationId"] == "stageSuppliedSppgWhatsAppActivityForReview"
    assert staging["x-openai-isConsequential"] is False
    assert staging_body["properties"]["stage"]["enum"] == [True]
    assert set(staging_body["required"]) == {"text", "stage"}

    review = enhanced["paths"]["/v1/review-queue"]["get"]
    assert review["operationId"] == "listSppgPendingOperationalReviews"
