from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend import hermes_receiving_preview_api as preview_api


def test_receiving_preview_contract_rejects_commit_field() -> None:
    with pytest.raises(ValidationError):
        preview_api.HermesReceivingPreviewIn(
            site="MAJA",
            text="Wortel 10 kg",
            vendor_code="HOLIL",
            commit=True,
        )


def test_receiving_preview_forces_commit_false(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_resolver(payload):
        captured["payload"] = payload
        return {
            "committed": False,
            "site": payload.site,
            "vendorCode": payload.vendor_code,
            "purchaseOrderIds": [101, 102],
            "poCodes": ["PO-MAJA-20260823-HOLIL", "PO-MAJA-20260824-HOLIL"],
            "multiPo": True,
            "reportedItems": [],
            "matches": [],
            "alternatives": [],
            "resolverVersion": "multi-po-v2",
        }

    monkeypatch.setattr(preview_api, "receive_from_whatsapp_v2", fake_resolver)

    request = preview_api.HermesReceivingPreviewIn(
        site="MAJA",
        text="Wortel 10 kg",
        vendor_code="HOLIL",
    )
    result = preview_api.preview_receiving_multi_po(request, _auth=None)

    assert captured["payload"].commit is False
    assert result["committed"] is False
    assert result["readOnly"] is True
    assert result["operationalMutation"] is False
    assert result["sourceOfTruth"] == "SPPG Core PostgreSQL"
    assert result["multiPo"] is True


def test_receiving_preview_blocks_unexpected_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    def unsafe_resolver(_payload):
        return {"committed": True}

    monkeypatch.setattr(preview_api, "receive_from_whatsapp_v2", unsafe_resolver)
    request = preview_api.HermesReceivingPreviewIn(site="CEMPLANG", text="Tahu 23 papan")

    with pytest.raises(RuntimeError, match="read-only Hermes receiving preview"):
        preview_api.preview_receiving_multi_po(request, _auth=None)
