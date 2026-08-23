"""Read-only context pack for the future menu-planning advisor.

This module intentionally does not generate, save, revise, or approve a menu.
It only presents existing planning and confirmed knowledge in a stable shape so a
separate GPT draft can reason from evidence.  It has no dependency on the
calculator workflow and it never calls any PO, payment, stock, or Excel route.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query

from backend.db import connection, database_ready


router = APIRouter(prefix="/v1/menu-planning-advisor", tags=["menu-planning-advisor"])

Site = Literal["MAJA", "CEMPLANG"]


def _as_dict(row: Any) -> dict[str, Any] | None:
    return dict(row) if row else None


def _item_view(item: dict[str, Any]) -> dict[str, Any]:
    """Keep planning facts distinct from an advisor recommendation."""
    return {
        "itemCode": item.get("item_code"),
        "itemName": item.get("item_name"),
        "categoryCode": item.get("category_code"),
        "plannedQty": item.get("planned_qty"),
        "unit": item.get("unit"),
        "planningPrice": item.get("planning_price"),
        "preferredVendorCode": item.get("preferred_vendor_code"),
        "notes": item.get("notes"),
        "sourcePayload": item.get("source_payload") or {},
    }


def _snapshot_view(snapshot: dict[str, Any] | None, items: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not snapshot:
        return None
    return {
        "snapshotId": snapshot.get("id"),
        "snapshotKey": snapshot.get("snapshot_key"),
        "site": snapshot.get("site"),
        "distributionDate": snapshot.get("distribution_date"),
        "cookingAt": snapshot.get("cooking_at"),
        "sourceSystem": snapshot.get("source_system"),
        "sourceVersion": snapshot.get("source_version"),
        "sourceUpdatedAt": snapshot.get("source_updated_at"),
        "status": snapshot.get("status"),
        "payload": snapshot.get("payload") or {},
        "items": [_item_view(item) for item in items],
    }


def _data_gaps(
    requested_date: date | None,
    target: dict[str, Any] | None,
    target_items: list[dict[str, Any]],
    confirmed_knowledge: list[dict[str, Any]],
) -> list[dict[str, str]]:
    gaps: list[dict[str, str]] = []
    if requested_date and not target:
        gaps.append({
            "code": "PLANNING_NOT_FOUND",
            "message": "Belum ada snapshot planning aktif untuk tanggal distribusi yang diminta.",
        })
    elif not target:
        gaps.append({
            "code": "PLANNING_NOT_FOUND",
            "message": "Belum ada snapshot planning aktif untuk site ini.",
        })
    elif not target_items:
        gaps.append({
            "code": "PLANNING_ITEMS_EMPTY",
            "message": "Snapshot planning ditemukan, tetapi belum memiliki rincian bahan.",
        })

    if target_items and any(item.get("planned_qty") is None for item in target_items):
        gaps.append({
            "code": "PLANNED_QTY_MISSING",
            "message": "Sebagian bahan belum memiliki jumlah rencana.",
        })
    if target_items and any(item.get("planning_price") is None for item in target_items):
        gaps.append({
            "code": "PLANNING_PRICE_MISSING",
            "message": "Sebagian bahan belum memiliki harga perencanaan; pagu belum boleh disimpulkan.",
        })
    if not confirmed_knowledge:
        gaps.append({
            "code": "CONFIRMED_MENU_KNOWLEDGE_EMPTY",
            "message": "Belum ada knowledge terkonfirmasi untuk dijadikan pola menu; jangan membuat asumsi pola.",
        })
    return gaps


def _preview_response(
    *,
    site: str,
    requested_date: date | None,
    target_snapshot: dict[str, Any] | None,
    target_items: list[dict[str, Any]],
    history: list[dict[str, Any]],
    confirmed_knowledge: list[dict[str, Any]],
    database_ready: bool,
) -> dict[str, Any]:
    target = _snapshot_view(target_snapshot, target_items)
    return {
        "engine": "menu-planning-advisor-v1",
        "readOnly": True,
        "draftOnly": True,
        "databaseReady": database_ready,
        "site": site,
        "requestedDistributionDate": requested_date,
        "sourceOfTruth": {
            "planning": "PostgreSQL planning snapshots",
            "knowledge": "Confirmed LLM Wiki knowledge only",
            "rule": "This endpoint does not infer or write operational data.",
        },
        "targetPlanning": target,
        "planningHistory": history,
        "confirmedKnowledge": confirmed_knowledge,
        "dataGaps": _data_gaps(requested_date, target_snapshot, target_items, confirmed_knowledge),
        "automationBoundary": {
            "canCreateOrEditCalculator": False,
            "canCreateOrEditPurchaseOrder": False,
            "canRecordReceiving": False,
            "canRecordPayment": False,
            "canGenerateOrSendExcel": False,
            "requiresHumanConfirmationForEveryOperationalChange": True,
        },
        "recommendedUse": (
            "Gunakan paket ini hanya untuk membuat DRAFT menu dan daftar data yang perlu dicek. "
            "Jangan menyatakan menu hemat pagu sebelum jumlah porsi, gramasi, dan harga tersedia."
        ),
    }


def _load_items(cur: Any, snapshot_id: int) -> list[dict[str, Any]]:
    cur.execute(
        """
        select item_code, item_name, category_code, planned_qty, unit, planning_price,
               preferred_vendor_code, notes, source_payload
        from planning_snapshot_items
        where planning_snapshot_id=%s
        order by id
        """,
        (snapshot_id,),
    )
    return [dict(row) for row in cur.fetchall()]


def _load_target(cur: Any, site: str, distribution_date: date | None) -> dict[str, Any] | None:
    sql = """
        select id, snapshot_key, site, distribution_date, cooking_at, source_system,
               source_version, source_updated_at, status, payload
        from planning_snapshots
        where upper(site)=upper(%s) and status='ACTIVE'
    """
    params: list[Any] = [site]
    if distribution_date:
        sql += " and distribution_date=%s"
        params.append(distribution_date)
    sql += " order by distribution_date desc, created_at desc limit 1"
    cur.execute(sql, params)
    return _as_dict(cur.fetchone())


def _load_history(cur: Any, site: str, target_id: int | None) -> list[dict[str, Any]]:
    sql = """
        select id, snapshot_key, site, distribution_date, cooking_at, source_system,
               source_version, source_updated_at, status, payload
        from planning_snapshots
        where upper(site)=upper(%s) and status='ACTIVE'
    """
    params: list[Any] = [site]
    if target_id is not None:
        sql += " and id<>%s"
        params.append(target_id)
    sql += " order by distribution_date desc, created_at desc limit 6"
    cur.execute(sql, params)
    snapshots = [dict(row) for row in cur.fetchall()]
    return [_snapshot_view(snapshot, _load_items(cur, int(snapshot["id"]))) for snapshot in snapshots]


def _load_confirmed_knowledge(cur: Any, site: str) -> list[dict[str, Any]]:
    cur.execute(
        """
        select scope_type, site, vendor_code, topic, statement, knowledge_kind,
               confidence, evidence_count, metadata, last_seen_at
        from llm_learned_knowledge
        where status='CONFIRMED'
          and (site is null or upper(site)=upper(%s))
        order by confidence desc, evidence_count desc, last_seen_at desc
        limit 20
        """,
        (site,),
    )
    return [
        {
            "scopeType": row.get("scope_type"),
            "site": row.get("site"),
            "vendorCode": row.get("vendor_code"),
            "topic": row.get("topic"),
            "statement": row.get("statement"),
            "knowledgeKind": row.get("knowledge_kind"),
            "confidence": row.get("confidence"),
            "evidenceCount": row.get("evidence_count"),
            "metadata": row.get("metadata") or {},
            "lastSeenAt": row.get("last_seen_at"),
        }
        for row in cur.fetchall()
    ]


@router.get("/preview")
def menu_planning_preview(
    site: Site,
    distribution_date: date | None = Query(default=None, alias="distributionDate"),
) -> dict[str, Any]:
    """Return evidence for a menu draft. This route is permanently read-only."""
    if not database_ready():
        return _preview_response(
            site=site,
            requested_date=distribution_date,
            target_snapshot=None,
            target_items=[],
            history=[],
            confirmed_knowledge=[],
            database_ready=False,
        )

    try:
        with connection() as conn:
            with conn.cursor() as cur:
                target_snapshot = _load_target(cur, site, distribution_date)
                target_items = _load_items(cur, int(target_snapshot["id"])) if target_snapshot else []
                history = _load_history(cur, site, int(target_snapshot["id"])) if target_snapshot else _load_history(cur, site, None)
                confirmed_knowledge = _load_confirmed_knowledge(cur, site)
    except Exception as exc:
        raise HTTPException(503, "menu planning context is temporarily unavailable") from exc

    return _preview_response(
        site=site,
        requested_date=distribution_date,
        target_snapshot=target_snapshot,
        target_items=target_items,
        history=history,
        confirmed_knowledge=confirmed_knowledge,
        database_ready=True,
    )
