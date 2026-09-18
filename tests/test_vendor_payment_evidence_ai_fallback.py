from fastapi import HTTPException

from backend import vendor_payment_evidence_api as evidence


def test_openai_is_primary_for_payment_proof(monkeypatch):
    monkeypatch.setattr(evidence, "_openai_key", lambda: "configured")
    monkeypatch.setattr(evidence, "_gemini_key", lambda: "configured")
    monkeypatch.setattr(evidence, "_inspect_with_openai", lambda *args: {"provider": "openai", "amount": 100})
    monkeypatch.setattr(evidence, "_inspect_with_gemini", lambda *args: (_ for _ in ()).throw(AssertionError("Gemini must not run")))

    assert evidence._inspect_with_ai(b"image", "image/jpeg", {})["provider"] == "openai"


def test_gemini_is_fallback_when_openai_fails(monkeypatch):
    monkeypatch.setattr(evidence, "_openai_key", lambda: "configured")
    monkeypatch.setattr(evidence, "_gemini_key", lambda: "configured")
    monkeypatch.setattr(evidence, "_inspect_with_openai", lambda *args: (_ for _ in ()).throw(HTTPException(503, "busy")))
    monkeypatch.setattr(evidence, "_inspect_with_gemini", lambda *args: {"provider": "gemini", "amount": 100})

    result = evidence._inspect_with_ai(b"image", "image/jpeg", {})
    assert result["provider"] == "gemini"
    assert "dialihkan" in result["warning"]
