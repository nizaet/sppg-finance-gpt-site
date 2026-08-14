"""Production ASGI entrypoint.

Serve React frontend + SPPG API from one Railway service.
- / and /accountant/maja use the MAJA accountant build.
- /accountant/cemplang uses the CEMPLANG accountant build.
- /operations and /calculator use the shared SPA shell.
All /v1 routes remain API endpoints and are protected by SPPG role middleware.
"""

from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.app import app as fastapi_app
from backend.auth_middleware import SppgAccessMiddleware

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
INDEX_MAJA = DIST / "index.html"
INDEX_CEMPLANG = DIST / "index-cemplang.html"
ASSETS = DIST / "assets"

if ASSETS.is_dir():
    fastapi_app.mount("/assets", StaticFiles(directory=str(ASSETS)), name="frontend-assets")


def _index_for_path(full_path: str) -> Path:
    normalized = full_path.strip("/").lower()
    if normalized == "accountant/cemplang" or normalized.startswith("accountant/cemplang/"):
        return INDEX_CEMPLANG
    return INDEX_MAJA


@fastapi_app.get("/", include_in_schema=False)
def frontend_root():
    if not INDEX_MAJA.is_file():
        raise HTTPException(503, "frontend build is not available")
    return FileResponse(INDEX_MAJA)


@fastapi_app.get("/{full_path:path}", include_in_schema=False)
def frontend_spa(full_path: str):
    if full_path == "openapi.json" or full_path.startswith(("v1/", "docs", "redoc")):
        raise HTTPException(404, "not found")

    candidate = DIST / full_path
    if candidate.is_file() and DIST in candidate.resolve().parents:
        return FileResponse(candidate)

    index = _index_for_path(full_path)
    if not index.is_file():
        raise HTTPException(503, "frontend build is not available")
    return FileResponse(index)


app = SppgAccessMiddleware(fastapi_app)
