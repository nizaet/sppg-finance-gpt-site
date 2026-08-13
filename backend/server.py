"""Production ASGI entrypoint.

Serve the compiled React frontend and the SPPG API from the same Railway service.
All /v1 routes remain FastAPI endpoints; browser routes fall back to dist/index.html.
SPPG role/site enforcement remains active for protected /v1 application endpoints.
"""

from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.app import app as fastapi_app
from backend.auth_middleware import SppgAccessMiddleware

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
INDEX = DIST / "index.html"
ASSETS = DIST / "assets"

if ASSETS.is_dir():
    fastapi_app.mount("/assets", StaticFiles(directory=str(ASSETS)), name="frontend-assets")


@fastapi_app.get("/", include_in_schema=False)
def frontend_root():
    if not INDEX.is_file():
        raise HTTPException(503, "frontend build is not available")
    return FileResponse(INDEX)


@fastapi_app.get("/{full_path:path}", include_in_schema=False)
def frontend_spa(full_path: str):
    # Existing FastAPI routes are registered before this catch-all. Keep unknown
    # API/documentation paths as real 404s instead of returning HTML.
    if full_path == "openapi.json" or full_path.startswith(("v1/", "docs", "redoc")):
        raise HTTPException(404, "not found")

    candidate = DIST / full_path
    if candidate.is_file() and DIST in candidate.resolve().parents:
        return FileResponse(candidate)
    if not INDEX.is_file():
        raise HTTPException(503, "frontend build is not available")
    return FileResponse(INDEX)


app = SppgAccessMiddleware(fastapi_app)
