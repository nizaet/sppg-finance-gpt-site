"""Production ASGI entrypoint.

Serve React frontend + SPPG API from one Railway service.
- / and /accountant/maja use the MAJA accountant build.
- /accountant/cemplang uses the CEMPLANG accountant build.
- /operations and /calculator use the shared SPA shell.
All /v1 routes remain API endpoints and are protected by SPPG role middleware.
"""

from datetime import timedelta
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from backend.app import app as fastapi_app
from backend.auth_api import SESSION_COOKIE, verify_session
from backend.auth_middleware import SppgAccessMiddleware
from backend.calculator_ai_api import router as calculator_ai_router
from backend.calculator_ai_runtime_patch import install as install_calculator_ai_patch
from backend.finance_runtime_patch import install as install_finance_runtime_patch
from backend.koperasi_transfer_export_api import router as koperasi_transfer_export_router
from backend.unified_action_schema_api import schema_v0188
from backend.vendor_payment_runtime_fail_safe_patch import install as install_vendor_payment_fail_safe
from backend import po_operational_policy_patch as po_policy

install_calculator_ai_patch()
install_finance_runtime_patch()
install_vendor_payment_fail_safe()
po_policy.install()


def _po_inventory_balances_v2(*args, **kwargs):
    """Return one physical stock row per classified ingredient type.

    raw_item_names are aliases for the same warehouse row, not separate stock
    lots. The PO frontend uses aliases for exact-name matching and previously
    also iterated them as stock entries, so a 1 kg Knorr row with four aliases
    was counted as 4 kg. Classified rows already have a canonical stock type,
    therefore aliases are not needed for quantity aggregation.
    """
    payload = po_policy._ORIGINAL_INVENTORY_BALANCES_V2(*args, **kwargs)
    for item in payload.get("items") or []:
        if str(item.get("stock_type_method") or "").upper() == "ITEM_TYPE_RULE":
            item["raw_item_names"] = []
    return payload


# Gudang MAJA, CEMPLANG, and KOPERASI are separate physical locations. The PO
# planner subtracts only the selected dapur stock from planning. Gudang Koperasi
# is fetched separately and is informational for fulfillment/shortfall only.
po_policy.inventory_projection.inventory_balances_v2 = _po_inventory_balances_v2
po_policy._patch_route(
    po_policy.inventory_projection.router,
    "/inventory/balances-v2",
    _po_inventory_balances_v2,
)


def _site_only_po_projection(site, distribution_date):
    """Stock available immediately before the cooking day for a distribution.

    Inventory consumption happens on the cooking day. The reminder therefore
    projects to D-1 (the normal cooking date), rather than subtracting the plan
    for the prior distribution a second time from a same-day physical SO.
    """
    stock_before_date = distribution_date - timedelta(days=1)
    try:
        payload = po_policy._ORIGINAL_INVENTORY_BALANCES_V2(
            site=site,
            search="",
            limit=1000,
            for_date=stock_before_date,
        )
    except Exception:
        return {}, "PROJECTION_UNAVAILABLE"

    lookup = {}
    for item in payload.get("items") or []:
        key = po_policy.reminder._stock_key(item.get("item_name"), item.get("unit"))
        available = item.get("available_for_po")
        if available is None:
            available = item.get("balance")
        lookup[key] = max(lookup.get(key, 0.0), max(0.0, float(available or 0)))
    return lookup, str(payload.get("projectionModel") or "INVENTORY_PROJECTION_V2_COOKING_DAY")


# Reminder reads only the selected dapur stock. Gudang Koperasi remains a
# separate source and is shown/handled separately by the PO planner.
po_policy.reminder._projection_lookup = _site_only_po_projection

# backend.app has already copied nested APIRouter routes onto the live FastAPI
# application before runtime patches are installed. Replace only the planning
# snapshot callable so vendor/lead-time policy is refreshed. Inventory stays on
# the site-scoped endpoint above, with alias quantities de-duplicated.
for _route in fastapi_app.routes:
    _path = str(getattr(_route, "path", ""))
    _endpoint = None
    if _path.endswith("/inventory/balances-v2"):
        _endpoint = _po_inventory_balances_v2
    elif _path.endswith("/planning-snapshots/{snapshot_id}"):
        _endpoint = po_policy.get_planning_snapshot_with_vendor_policy
    if _endpoint is not None:
        _route.endpoint = _endpoint
        if getattr(_route, "dependant", None) is not None:
            _route.dependant.call = _endpoint

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
fastapi_app.include_router(koperasi_transfer_export_router)


# GPT Builder was instructed to import the /v1/schema URL, but backend.app only
# exposed the compatibility /schema alias. Keep the canonical public URL live so
# the custom GPT can re-import v0.18.8 without falling through to the SPA/404.
@fastapi_app.get("/v1/schema/chatgpt-sppg-v0188.json", include_in_schema=False)
def chatgpt_sppg_schema_v0188_canonical() -> JSONResponse:
    return JSONResponse(schema_v0188())


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
