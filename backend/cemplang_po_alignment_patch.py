from __future__ import annotations

import json
from datetime import date
from typing import Any

from fastapi import HTTPException

from backend import calculator_pages
from backend import calculator_planning_bridge_api as planning_bridge

_INSTALLED = False
_ORIGINAL_CALCULATOR_HTML = calculator_pages.calculator_html
_ORIGINAL_DAILY_PLAN_MATCHES = planning_bridge._daily_plan_matches


def _canonical_calculator_html(unit: str, role: str) -> str:
    """Force both calculators to use their server-pinned canonical Firestore root.

    The legacy calculator still contains an admin-only localStorage Firebase
    connection override. That was useful while migrating old standalone HTML,
    but on Railway it can make one browser write CEMPLANG planning to a different
    app/data root while the PO backend reads the canonical cemplang2 root. MAJA
    may then look correct while CEMPLANG appears stale or inconsistent.

    Remove both the old shared key and the per-site key before any legacy script
    can read them. The canonical app id/database id injected by calculator_pages
    remains the only active source.
    """
    html = _ORIGINAL_CALCULATOR_HTML(unit, role)
    per_site_key = f"spbg_firebase_connection_v1-{unit}"
    guard = f"""
    <script>
      try {{
        localStorage.removeItem('spbg_firebase_connection_v1');
        localStorage.removeItem({json.dumps(per_site_key)});
      }} catch (e) {{}}
      window.__sppgCanonicalFirebaseOnly = true;
    </script>
    """
    return html.replace("<head>", f"<head>{guard}", 1)


def _canonical_daily_plan_matches(
    site: str,
    distribution_date: date,
) -> tuple[str, Any, dict[str, Any], list[dict[str, Any]]]:
    """Never let PO sync silently switch to a browser-specific alternate appId.

    MAJA and CEMPLANG intentionally live in different Firestore databases, but
    they now follow the exact same rule: read only the canonical app/data root
    declared in SITE_TARGETS. Discovery remains useful inside the original
    reader for diagnostics, but an alternate appId is rejected instead of being
    treated as the live PO source.
    """
    app_id, doc, data, candidates = _ORIGINAL_DAILY_PLAN_MATCHES(site, distribution_date)
    canonical = planning_bridge._configured_app_id(site)
    if app_id != canonical:
        raise HTTPException(
            409,
            detail={
                "message": (
                    f"rencana Kalkulator {site} ditemukan pada appId non-kanonik; "
                    "PO dihentikan agar sumber MAJA/CEMPLANG tidak berbeda antar browser"
                ),
                "site": site,
                "distributionDate": distribution_date.isoformat(),
                "candidateAppId": app_id,
                "canonicalAppId": canonical,
                "canonicalDatabaseId": planning_bridge.SITE_TARGETS[site]["database_id"],
                "nextAction": "buka ulang Kalkulator site lalu simpan/finalkan planning pada sumber canonical",
            },
        )
    return app_id, doc, data, candidates


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    calculator_pages.calculator_html = _canonical_calculator_html
    planning_bridge._daily_plan_matches = _canonical_daily_plan_matches
    _INSTALLED = True
