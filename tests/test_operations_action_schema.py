from backend.operations_action_schema_v017_api import schema_v017


def test_v017_schema_exposes_safe_current_receiving_and_payments():
    schema = schema_v017()
    paths = schema["paths"]

    assert schema["info"]["version"] == "0.17.1"

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
