"""Production ASGI entrypoint.

Serve React frontend + SPPG API from one Railway service.
- / and /accountant/maja use the MAJA accountant build.
- /accountant/cemplang uses the CEMPLANG accountant build.
- /operations and /calculator use the shared SPA shell.
All /v1 routes remain API endpoints and are protected by SPPG role middleware.
"""

from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from backend.app import app as fastapi_app
from backend.auth_api import SESSION_COOKIE, verify_session
from backend.auth_middleware import SppgAccessMiddleware
from backend.calculator_ai_api import router as calculator_ai_router
from backend.calculator_ai_runtime_patch import install as install_calculator_ai_patch
from backend.finance_runtime_patch import install as install_finance_runtime_patch

install_calculator_ai_patch()
install_finance_runtime_patch()
from backend.calculator_pages import calculator_html  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
INDEX_MAJA = DIST / "index.html"
INDEX_CEMPLANG = DIST / "index-cemplang.html"
ASSETS = DIST / "assets"

# The SPA shell must never be reused across Railway deploys. Vite assets are
# content-hashed, so they may be cached normally; stale index.html is dangerous
# because it can keep pointing at an old lazy-loaded PO chunk while the backend
# has already moved to a newer commit.
SPA_HTML_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
    "X-Content-Type-Options": "nosniff",
}

# Calculator AI must be served by Railway so provider keys stay in env vars and
# never leak into the legacy browser/Firebase appConfig path.
fastapi_app.include_router(calculator_ai_router)

if ASSETS.is_dir():
    fastapi_app.mount("/assets", StaticFiles(directory=str(ASSETS)), name="frontend-assets")


def _index_for_path(full_path: str) -> Path:
    normalized = full_path.strip("/").lower()
    if normalized == "accountant/cemplang" or normalized.startswith("accountant/cemplang/"):
        return INDEX_CEMPLANG
    return INDEX_MAJA


def _html_file_response(path: Path) -> FileResponse:
    return FileResponse(path, headers=SPA_HTML_HEADERS)


def _calculator_role(request: Request) -> str | None:
    token = request.cookies.get(SESSION_COOKIE, "").strip()
    if not token:
        return None
    try:
        return str(verify_session(token).get("role") or "").upper() or None
    except Exception:
        return None


@fastapi_app.get("/dapur/{unit}", include_in_schema=False)
def frontend_calculator(unit: str, request: Request):
    normalized = unit.lower().strip()
    if normalized not in {"maja", "cemplang"}:
        raise HTTPException(404, "calculator not found")
    role = _calculator_role(request)
    if role is None:
        return RedirectResponse("/", status_code=302)
    required_role = normalized.upper()
    if role not in {"OWNER", required_role}:
        return RedirectResponse(f"/dapur/{role.lower()}", status_code=302)
    return HTMLResponse(
        calculator_html(normalized, role),
        headers={
            **SPA_HTML_HEADERS,
            "Referrer-Policy": "same-origin",
        },
    )


@fastapi_app.get("/", include_in_schema=False)
def frontend_root():
    if not INDEX_MAJA.is_file():
        raise HTTPException(503, "frontend build is not available")
    return _html_file_response(INDEX_MAJA)


@fastapi_app.get("/{full_path:path}", include_in_schema=False)
def frontend_spa(full_path: str):
    if full_path == "openapi.json" or full_path.startswith(("v1/", "docs", "redoc")):
        raise HTTPException(404, "not found")

    candidate = DIST / full_path
    if candidate.is_file() and DIST in candidate.resolve().parents:
        if candidate.suffix.lower() == ".html":
            return _html_file_response(candidate)
        return FileResponse(candidate)

    index = _index_for_path(full_path)
    if not index.is_file():
        raise HTTPException(503, "frontend build is not available")
    return _html_file_response(index)


app = SppgAccessMiddleware(fastapi_app)
