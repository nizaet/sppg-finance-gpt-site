from backend import calculator_ai_api as ai


def test_gemini_legacy_model_is_upgraded(monkeypatch):
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.delenv("AI_MENU_MODEL", raising=False)

    assert ai._gemini_model("gemini-2.5-flash") == "gemini-3.6-flash"
    assert ai._gemini_model("models/gemini-2.5-flash-preview-09-2025") == "gemini-3.6-flash"


def test_gemini_current_model_is_preserved(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.6-flash")

    assert ai._gemini_model(None) == "gemini-3.6-flash"
