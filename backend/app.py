import os
from datetime import date
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="SPPG Core API", version="0.1.0")

origins = [x.strip() for x in os.getenv("SPPG_ALLOWED_ORIGINS", "").split(",") if x.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SITE_DEFS = [
    {"siteId": "sppg-maja-gpt-site", "siteLabel": "SPPG MAJA BARU"},
    {"siteId": "sppg-cemplang2-gpt-site", "siteLabel": "SPPG CEMPLANG 2"},
]


def empty_site(site: dict[str, str]) -> dict[str, Any]:
    return {
        **site,
        "summary": {
            "poDueToday": 0,
            "poOverdue": 0,
            "deliveriesExpected": 0,
            "unresolvedRejects": 0,
            "paymentsDue": 0,
            "reviewQueue": 0,
        },
        "lanes": {
            "procurement": [],
            "receiving": [],
            "payments": [],
            "costing": [],
            "accountant": [],
            "bgn": [],
        },
    }


class ReviewDecision(BaseModel):
    decision: str
    note: str = ""


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "sppg-core"}


@app.get("/v1/control-tower")
def control_tower(target_date: date = Query(alias="date")) -> dict[str, Any]:
    # Database-backed implementation will replace the empty projection once
    # DATABASE_URL is provisioned and migrations are applied.
    return {"date": target_date.isoformat(), "sites": [empty_site(x) for x in SITE_DEFS]}


@app.get("/v1/po-calendar")
def po_calendar(from_: date = Query(alias="from"), to: date = Query(), site: str | None = None) -> dict[str, Any]:
    return {"from": from_.isoformat(), "to": to.isoformat(), "site": site, "items": []}


@app.get("/v1/vendor-payments")
def vendor_payments(status: str = "", site: str = "") -> dict[str, Any]:
    return {"status": status, "site": site, "items": []}


@app.get("/v1/review-queue")
def review_queue() -> dict[str, Any]:
    return {"items": []}


@app.post("/v1/review-queue/{event_id}")
def review_decision(event_id: str, payload: ReviewDecision) -> dict[str, Any]:
    decision = payload.decision.upper().strip()
    if decision not in {"APPROVE", "REJECT"}:
        raise HTTPException(400, "decision must be APPROVE or REJECT")
    return {"eventId": event_id, "decision": decision, "note": payload.note, "status": "accepted"}
