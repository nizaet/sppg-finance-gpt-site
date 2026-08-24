import pytest
from fastapi import HTTPException

import backend.firebase_auth_api as firebase_auth_api


def test_custom_token_scopes_owner_to_requested_site(monkeypatch):
    monkeypatch.setattr(firebase_auth_api, "session_role", lambda authorization: "OWNER")
    monkeypatch.setattr(
        firebase_auth_api,
        "create_firebase_custom_token",
        lambda uid, claims: f"token:{uid}:{claims['sppg_site']}",
    )

    result = firebase_auth_api.firebase_custom_token("CEMPLANG", "Bearer session")

    assert result == {
        "token": "token:sppg-owner-cemplang:CEMPLANG",
        "role": "OWNER",
        "site": "CEMPLANG",
    }


def test_kitchen_role_cannot_request_other_site_token(monkeypatch):
    monkeypatch.setattr(firebase_auth_api, "session_role", lambda authorization: "MAJA")

    with pytest.raises(HTTPException) as exc:
        firebase_auth_api.firebase_custom_token("CEMPLANG", "Bearer session")

    assert exc.value.status_code == 403
