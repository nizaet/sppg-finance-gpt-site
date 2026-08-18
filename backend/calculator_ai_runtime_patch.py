from __future__ import annotations

from functools import wraps

from backend import calculator_pages as _calculator_pages

_PATCH_MARKER = "__sppg_calculator_ai_backend_proxy_v1"

_AI_PROXY_SCRIPT = r"""
        // __sppg_calculator_ai_backend_proxy_v1
        window.__calculatorAIUseBackend = true;
        async function callRailwayCalculatorAI(provider, prompt, systemPrompt = null, modelName = '', abortSignal = null, timeoutMs = 70000) {
            var sessionToken = sessionStorage.getItem('sppg_session_token_v1') || localStorage.getItem('sppg_session_token_v1') || '';
            var controller = new AbortController();
            var timer = window.setTimeout(function () { controller.abort(); }, timeoutMs || 70000);
            if (abortSignal) {
                try { abortSignal.addEventListener('abort', function () { controller.abort(); }, { once: true }); } catch (_) {}
            }
            try {
                var response = await fetch('/v1/calculator-ai/generate', {
                    method: 'POST',
                    credentials: 'same-origin',
                    headers: {
                        'Content-Type': 'application/json',
                        ...(sessionToken ? { Authorization: 'Bearer ' + sessionToken } : {})
                    },
                    body: JSON.stringify({
                        provider: provider,
                        prompt: prompt,
                        system_prompt: systemPrompt || null,
                        model: modelName || null,
                        temperature: 0.1,
                        task: 'calculator'
                    }),
                    signal: controller.signal
                });
                var data = await response.json().catch(function () { return {}; });
                if (!response.ok) {
                    throw new Error(data.detail || ('SPPG Core AI ' + response.status));
                }
                return String(data.text || '');
            } finally {
                window.clearTimeout(timer);
            }
        }
"""


def _patch_legacy_ai(html: str) -> str:
    if _PATCH_MARKER in html:
        return html

    # Make the legacy provider-order filter consider the Railway backend as an
    # available provider without exposing the real key in browser/Firebase.
    html = html.replace(
        "geminiApiKey: String(appConfig.geminiApiKey || '').trim(),",
        "geminiApiKey: String(appConfig.geminiApiKey || (window.__calculatorAIUseBackend ? 'railway-backend' : '')).trim(),",
    )
    html = html.replace(
        "openAiApiKey: String(appConfig.openAiApiKey || '').trim(),",
        "openAiApiKey: String(appConfig.openAiApiKey || (window.__calculatorAIUseBackend ? 'railway-backend' : '')).trim(),",
    )

    marker = "        function getAIConfig() {"
    if marker in html:
        html = html.replace(marker, _AI_PROXY_SCRIPT + "\n" + marker, 1)

    gemini_head = (
        "        async function callGeminiDirect(prompt, systemPrompt = null, apiKey = '', modelName = 'gemini-2.5-flash', abortSignal = null, timeoutMs = 35000) {\n"
        "            const key = String(apiKey || '').trim();\n"
        "            if (!key) throw new Error(\"Gemini API Key belum diisi.\");"
    )
    gemini_repl = (
        "        async function callGeminiDirect(prompt, systemPrompt = null, apiKey = '', modelName = 'gemini-2.5-flash', abortSignal = null, timeoutMs = 35000) {\n"
        "            if (window.__calculatorAIUseBackend && typeof callRailwayCalculatorAI === 'function') {\n"
        "                return await callRailwayCalculatorAI('gemini', prompt, systemPrompt, modelName, abortSignal, timeoutMs);\n"
        "            }\n"
        "            const key = String(apiKey || '').trim();\n"
        "            if (!key) throw new Error(\"Gemini API Key belum diisi.\");"
    )
    html = html.replace(gemini_head, gemini_repl, 1)

    openai_head = (
        "        async function callOpenAIDirect(prompt, systemPrompt = null, apiKey = '', modelName = 'gpt-4o-mini', abortSignal = null, timeoutMs = 35000) {\n"
        "            const key = String(apiKey || '').trim();\n"
        "            if (!key) throw new Error(\"OpenAI API Key belum diisi.\");"
    )
    openai_repl = (
        "        async function callOpenAIDirect(prompt, systemPrompt = null, apiKey = '', modelName = 'gpt-4o-mini', abortSignal = null, timeoutMs = 35000) {\n"
        "            if (window.__calculatorAIUseBackend && typeof callRailwayCalculatorAI === 'function') {\n"
        "                return await callRailwayCalculatorAI('openai', prompt, systemPrompt, modelName, abortSignal, timeoutMs);\n"
        "            }\n"
        "            const key = String(apiKey || '').trim();\n"
        "            if (!key) throw new Error(\"OpenAI API Key belum diisi.\");"
    )
    html = html.replace(openai_head, openai_repl, 1)
    return html


_original_calculator_html = _calculator_pages.calculator_html


@wraps(_original_calculator_html)
def calculator_html(unit: str, role: str) -> str:
    return _patch_legacy_ai(_original_calculator_html(unit, role))


def install() -> None:
    _calculator_pages.calculator_html = calculator_html
