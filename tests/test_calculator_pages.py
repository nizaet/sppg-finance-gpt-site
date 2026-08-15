import importlib


def test_calculator_pages_use_existing_firestore_targets(monkeypatch):
    monkeypatch.setenv("SPPG_MAJA_CALCULATOR_APP_ID", "wrong-maja-target")
    monkeypatch.setenv("SPPG_CEMPLANG_CALCULATOR_APP_ID", "sppg-maja-gpt-site")
    monkeypatch.setenv("SPPG_MAJA_CALCULATOR_DATABASE_ID", "wrong-maja-database")
    monkeypatch.setenv("SPPG_CEMPLANG_CALCULATOR_DATABASE_ID", "(default)")
    module = importlib.import_module("backend.calculator_pages")
    module.render_calculator_html.cache_clear()

    maja = module.calculator_html("maja", "MAJA")
    cemplang = module.calculator_html("cemplang", "CEMPLANG")

    assert "sppg-maja-gpt-site" in maja
    assert "window.__firestoreDatabaseId = \"(default)\"" in maja
    assert "sppg-cemplang2-gpt-site" in cemplang
    assert "window.__firestoreDatabaseId = \"cemplang2\"" in cemplang
    assert "wrong-maja-target" not in maja
    assert "wrong-maja-database" not in maja
    assert "var __initial_auth_token = 'railway-session'" not in maja
    assert "spbg_firebase_connection_v1-maja" in maja
    assert "spbg_firebase_connection_v1-cemplang" in cemplang
    assert "#legacyMainContent.legacy-main-expanded .desktop-wide-tabs" in maja
    assert "#loginOverlay" in maja
    assert "sppg_session_token_v1" in cemplang
    assert "/v1/firebase/custom-token?site=MAJA" in maja
    assert "/v1/firebase/custom-token?site=CEMPLANG" in cemplang
    assert "await signInWithCustomToken(auth, firebaseToken)" in cemplang
    cemplang_auth = cemplang.split("async function authWithFirebase() {", 1)[1].split("function enableUI() {", 1)[0]
    assert "onAuthStateChanged" not in cemplang_auth
    assert "await signInWithCustomToken(auth, firebaseToken)" in cemplang_auth
    assert "await user.getIdTokenResult(true)" in cemplang_auth
    assert "claims.sppg_site" in cemplang_auth
    assert "actualSite !== expectedSite" in cemplang_auth


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
