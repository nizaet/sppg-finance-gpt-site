import hashlib
import json
from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.db import connection, database_ready
from backend.chat_api import router as chat_router

router = APIRouter(prefix="/v1", tags=["planning"])
router.include_router(chat_router)


class PlanningItemIn(BaseModel):
    item_code: str | None = None
    item_name: str
    category_code: str | None = None
    planned_qty: float | None = None
    unit: str | None = None
    planning_price: float | None = None
    preferred_vendor_code: str | None = None
    notes: str | None = None
    source_payload: dict[str, Any] = Field(default_factory=dict)


class PlanningSnapshotIn(BaseModel):
    site: str
    distribution_date: date
    cooking_at: datetime | None = None
    source_system: str
    source_version: str | None = None
    source_updated_at: datetime | None = None
    snapshot_key: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    items: list[PlanningItemIn] = Field(default_factory=list)


def build_snapshot_key(payload: PlanningSnapshotIn) -> str:
    if payload.snapshot_key:
        return payload.snapshot_key
    base = {
        "site": payload.site.upper(),
        "distribution_date": payload.distribution_date.isoformat(),
        "source_system": payload.source_system,
        "source_version": payload.source_version,
        "source_updated_at": payload.source_updated_at.isoformat() if payload.source_updated_at else None,
        "items": [x.model_dump() for x in payload.items],
    }
    digest = hashlib.sha256(json.dumps(base, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return f"plan:{digest}"


@router.post("/planning-snapshots")
def ingest_planning_snapshot(payload: PlanningSnapshotIn) -> dict[str, Any]:
    if not database_ready():
        raise HTTPException(503, "database unavailable")

    site = payload.site.upper().strip()
    if site not in {"MAJA", "CEMPLANG"}:
        raise HTTPException(400, "site must be MAJA or CEMPLANG")

    snapshot_key = build_snapshot_key(payload)
    cycle_code = f"{site}-{payload.distribution_date.strftime('%Y%m%d')}"

    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into production_cycles(cycle_code, site, distribution_date, cooking_at, status)
                values (%s,%s,%s,%s,'PLANNING')
                on conflict (cycle_code) do update
                  set cooking_at=coalesce(excluded.cooking_at, production_cycles.cooking_at)
                returning id
                """,
                (cycle_code, site, payload.distribution_date, payload.cooking_at),
            )
            cycle_id = cur.fetchone()["id"]

            cur.execute("select id from planning_snapshots where snapshot_key=%s", (snapshot_key,))
            existing = cur.fetchone()
            if existing:
                return {"snapshotId": existing["id"], "snapshotKey": snapshot_key, "cycleCode": cycle_code, "duplicate": True}

            cur.execute(
                """
                select id from planning_snapshots
                where site=%s and distribution_date=%s and source_system=%s and status='ACTIVE'
                order by created_at desc limit 1
                """,
                (site, payload.distribution_date, payload.source_system),
            )
            previous = cur.fetchone()
            previous_id = previous["id"] if previous else None
            if previous_id:
                cur.execute("update planning_snapshots set status='SUPERSEDED' where id=%s", (previous_id,))

            cur.execute(
                """
                insert into planning_snapshots(
                  snapshot_key, site, distribution_date, cooking_at, source_system,
                  source_version, source_updated_at, production_cycle_id,
                  supersedes_snapshot_id, payload
                ) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                returning id
                """,
                (
                    snapshot_key, site, payload.distribution_date, payload.cooking_at,
                    payload.source_system, payload.source_version,
                    payload.source_updated_at or datetime.now(timezone.utc), cycle_id,
                    previous_id, json.dumps(payload.payload, ensure_ascii=False),
                ),
            )
            snapshot_id = cur.fetchone()["id"]

            for item in payload.items:
                cur.execute(
                    """
                    insert into planning_snapshot_items(
                      planning_snapshot_id, item_code, item_name, category_code,
                      planned_qty, unit, planning_price, preferred_vendor_code,
                      notes, source_payload
                    ) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                    """,
                    (
                        snapshot_id, item.item_code, item.item_name, item.category_code,
                        item.planned_qty, item.unit, item.planning_price,
                        item.preferred_vendor_code, item.notes,
                        json.dumps(item.source_payload, ensure_ascii=False),
                    ),
                )
            conn.commit()

    return {
        "snapshotId": snapshot_id,
        "snapshotKey": snapshot_key,
        "cycleCode": cycle_code,
        "supersedesSnapshotId": previous_id,
        "duplicate": False,
        "itemCount": len(payload.items),
    }


@router.get("/planning-snapshots")
def list_planning_snapshots(
    site: str = "",
    distribution_date: date | None = Query(default=None, alias="distributionDate"),
    active_only: bool = Query(default=True, alias="activeOnly"),
) -> dict[str, Any]:
    if not database_ready():
        return {"items": []}
    with connection() as conn:
        with conn.cursor() as cur:
            sql = """
                select ps.id, ps.snapshot_key, ps.site, ps.distribution_date, ps.cooking_at,
                       ps.source_system, ps.source_version, ps.source_updated_at,
                       ps.production_cycle_id, ps.supersedes_snapshot_id, ps.status,
                       ps.created_at, count(psi.id) as item_count
                from planning_snapshots ps
                left join planning_snapshot_items psi on psi.planning_snapshot_id=ps.id
                where true
            """
            params: list[Any] = []
            if site:
                sql += " and upper(ps.site)=upper(%s)"
                params.append(site)
            if distribution_date:
                sql += " and ps.distribution_date=%s"
                params.append(distribution_date)
            if active_only:
                sql += " and ps.status='ACTIVE'"
            sql += " group by ps.id order by ps.distribution_date desc, ps.created_at desc limit 250"
            cur.execute(sql, params)
            return {"items": cur.fetchall()}


@router.get("/planning-snapshots/{snapshot_id}")
def get_planning_snapshot(snapshot_id: int) -> dict[str, Any]:
    if not database_ready():
        raise HTTPException(503, "database unavailable")
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("select * from planning_snapshots where id=%s", (snapshot_id,))
            snapshot = cur.fetchone()
            if not snapshot:
                raise HTTPException(404, "planning snapshot not found")
            cur.execute(
                "select * from planning_snapshot_items where planning_snapshot_id=%s order by id",
                (snapshot_id,),
            )
            snapshot["items"] = cur.fetchall()
            return snapshot
