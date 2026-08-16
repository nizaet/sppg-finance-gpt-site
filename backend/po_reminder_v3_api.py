from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Query

from backend.po_reminder_v4_api import po_reminders_v4

router = APIRouter(tags=["po-reminder-v3"])


@router.get("/po-reminders-v3")
def po_reminders_v3(
    site: str = "",
    as_of: date | None = Query(default=None, alias="date"),
    horizon_days: int = Query(default=2, ge=1, le=31, alias="horizonDays"),
) -> dict[str, Any]:
    """Compatibility endpoint backed by the strict v4 reminder engine.

    The frontend keeps the stable v3 URL so existing deployment/build guards and
    clients do not drift, while all coverage decisions use the corrected engine.
    """
    return po_reminders_v4(site=site, as_of=as_of, horizon_days=horizon_days)
