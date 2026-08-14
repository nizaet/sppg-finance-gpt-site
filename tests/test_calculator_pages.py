import importlib


def test_calculator_pages_use_existing_firestore_targets(monkeypatch):
    monkeypatch.delenv("SPPG_MAJA_CALCULATOR_APP_ID", raising=False)
    monkeypatch.delenv("SPPG_CEMPLANG_CALCULATOR_APP_ID", raising=False)
    monkeypatch.delenv("SPPG_MAJA_CALCULATOR_DATABASE_ID", raising=False)
    monkeypatch.delenv("SPPG_CEMPLANG_CALCULATOR_DATABASE_ID", raising=False)
    module = importlib.import_module("backend.calculator_pages")
    module.render_calculator_html.cache_clear()

    maja = module.calculator_html("maja", "MAJA")
    cemplang = module.calculator_html("cemplang", "CEMPLANG")

    assert "sppg-maja-gpt-site" in maja
    assert "window.__firestoreDatabaseId = \"(default)\"" in maja
    assert "sppg-cemplang2-gpt-site" in cemplang
    assert "window.__firestoreDatabaseId = \"cemplang2\"" in cemplang
    assert "#loginOverlay" in maja
    assert "sppg_session_token_v1" in cemplang


def test_auth_config_defaults_to_internal_calculator_routes(monkeypatch):
    monkeypatch.setenv("SPPG_AUTH_SECRET", "test-secret")
    monkeypatch.setenv("SPPG_OWNER_PASSWORD", "owner-password")
    monkeypatch.delenv("SPPG_MAJA_CALCULATOR_URL", raising=False)
    monkeypatch.delenv("SPPG_CEMPLANG_CALCULATOR_URL", raising=False)
    from backend.auth_api import auth_config

    config = auth_config()
    assert config["calculatorUrls"] == {
        "MAJA": "/dapur/maja",
        "CEMPLANG": "/dapur/cemplang",
    }
