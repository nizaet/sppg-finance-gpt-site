from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.google_services import SITE_TARGETS, firestore_client
from backend.planning_api import PlanningItemIn, PlanningSnapshotIn, ingest_planning_snapshot, get_planning_snapshot

router = APIRouter(tags=["calculator-planning-bridge"])

SUPPLIER_CATEGORY = {
    "supplier_ayam": "AYAM",
    "supplier_ikan": "IKAN",
    "supplier_tempe_tahu": "TEMPE_TAHU",
    "supplier_telur": "TELUR",
    "supplier_beras": "BERAS",
    "supplier_kering": "BAHAN_KERING",
    "supplier_sayur": "SAYUR_BUAH_BUMBU",
}


class CalculatorPlanningSyncIn(BaseModel):
    site: Literal["MAJA", "CEMPLANG"]
    distribution_date: date


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return str(value)


def _as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _configured_app_id(site: str) -> str:
    return os.getenv(f"SPPG_{site}_CALCULATOR_APP_ID", "").strip()


def _plan_updated_at(data: dict[str, Any]) -> datetime:
    value = data.get("updatedAt") or data.get("createdAt")
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.min.replace(tzinfo=timezone.utc)


def _daily_plan_matches(site: str, distribution_date: date) -> tuple[str, Any, dict[str, Any], list[dict[str, Any]]]:
    target = SITE_TARGETS[site]
    client = firestore_client(target["database_id"])
    target_date = distribution_date.isoformat()
    configured = _configured_app_id(site)

    app_refs = []
    if configured:
        app_refs = [client.collection("artifacts").document(configured)]
    else:
        try:
            app_refs = list(client.collection("artifacts").list_documents(page_size=100))
        except TypeError:
            app_refs = list(client.collection("artifacts").list_documents())[:100]

    candidates: list[dict[str, Any]] = []
    for app_ref in app_refs:
        try:
            query = (
                app_ref.collection("public").document("data").collection("dailyPlans")
                .where("date", "==", target_date)
                .limit(20)
            )
            docs = list(query.stream())
        except Exception:
            continue
        for snap in docs:
            data = snap.to_dict() or {}
            shopping = ((data.get("shoppingListJSON") or {}).get("shoppingList") or [])
            candidates.append({
                "app_id": app_ref.id,
                "doc": snap,
                "data": data,
                "updated_at": _plan_updated_at(data),
                "item_count": len(shopping) if isinstance(shopping, list) else 0,
            })

    if not candidates:
        suffix = f" untuk appId {configured}" if configured else ""
        raise HTTPException(404, f"rencana Kalkulator {site} tanggal {target_date} tidak ditemukan{suffix}")

    app_ids = sorted({x["app_id"] for x in candidates})
    if not configured and len(app_ids) > 1:
        raise HTTPException(
            409,
            detail={
                "message": "lebih dari satu appId Kalkulator memiliki rencana pada tanggal yang sama; konfigurasi appId diperlukan agar tidak salah menarik data",
                "site": site,
                "distributionDate": target_date,
                "candidateAppIds": app_ids,
                "candidates": [
                    {
                        "appId": x["app_id"],
                        "documentId": x["doc"].id,
                        "planName": x["data"].get("planName"),
                        "itemCount": x["item_count"],
                        "updatedAt": _json_safe(x["updated_at"]),
                    }
                    for x in sorted(candidates, key=lambda y: y["updated_at"], reverse=True)
                ],
            },
        )

    candidates.sort(key=lambda x: (x["updated_at"], x["item_count"]), reverse=True)
    chosen = candidates[0]
    return chosen["app_id"], chosen["doc"], chosen["data"], candidates


def _planning_payload(site: str, distribution_date: date) -> tuple[PlanningSnapshotIn, dict[str, Any]]:
    app_id, doc_snap, plan, candidates = _daily_plan_matches(site, distribution_date)
    shopping_json = plan.get("shoppingListJSON") or {}
    shopping = shopping_json.get("shoppingList") or []
    if not isinstance(shopping, list) or not shopping:
        raise HTTPException(409, "rencana Kalkulator ditemukan tetapi daftar belanja masih kosong; hitung/finalkan belanja di Kalkulator terlebih dahulu")

    items: list[PlanningItemIn] = []
    skipped: list[dict[str, Any]] = []
    for idx, raw in enumerate(shopping):
        if not isinstance(raw, dict):
            skipped.append({"index": idx, "reason": "not_object"})
            continue
        name = str(raw.get("item") or raw.get("name") or "").strip()
        planned_qty = _as_float(raw.get("jumlah"))
        if not name or planned_qty is None:
            skipped.append({"index": idx, "item": name, "reason": "missing_name_or_qty"})
            continue
        supplier_key = str(raw.get("supplierOverride") or "").strip()
        category = SUPPLIER_CATEGORY.get(supplier_key) or str(raw.get("category_code") or "").strip() or None
        items.append(PlanningItemIn(
            item_code=str(raw.get("item_code") or "").strip() or None,
            item_name=name,
            category_code=category,
            planned_qty=planned_qty,
            unit=str(raw.get("satuan") or "").strip() or None,
            planning_price=_as_float(raw.get("harga_satuan")),
            preferred_vendor_code=None,
            notes=str(raw.get("note") or "").strip() or None,
            source_payload=_json_safe(raw),
        ))

    updated = _plan_updated_at(plan)
    plan_hash = hashlib.sha256(json.dumps(_json_safe(plan), sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    snapshot_key = f"calculator:{site.lower()}:{app_id}:{doc_snap.id}:{plan_hash}"
    source_payload = {
        "firestoreDatabase": SITE_TARGETS[site]["database_id"],
        "calculatorAppId": app_id,
        "dailyPlanDocumentId": doc_snap.id,
        "planName": plan.get("planName"),
        "porsiKecil": plan.get("porsiKecil"),
        "porsiBesar": plan.get("porsiBesar"),
        "shoppingListGrandTotal": shopping_json.get("grand_total_num"),
        "recipes": _json_safe(plan.get("recipes") or []),
        "sourceUpdatedAt": _json_safe(updated),
        "sourceCandidateCount": len(candidates),
        "skippedItems": skipped,
    }
    payload = PlanningSnapshotIn(
        site=site,
        distribution_date=distribution_date,
        cooking_at=None,
        source_system="CALCULATOR_FIRESTORE",
        source_version="dailyPlans-v1",
        source_updated_at=updated if updated.year > 1900 else datetime.now(timezone.utc),
        snapshot_key=snapshot_key,
        payload=source_payload,
        items=items,
    )
    return payload, {
        "site": site,
        "distributionDate": distribution_date.isoformat(),
        "appId": app_id,
        "dailyPlanDocumentId": doc_snap.id,
        "planName": plan.get("planName"),
        "porsiKecil": plan.get("porsiKecil"),
        "porsiBesar": plan.get("porsiBesar"),
        "itemCount": len(items),
        "skippedItems": skipped,
        "grandTotal": shopping_json.get("grand_total_num"),
        "sourceUpdatedAt": _json_safe(updated),
        "snapshotKey": snapshot_key,
        "items": [x.model_dump() for x in items],
    }


@router.get("/calculator-planning/preview")
def preview_calculator_planning(
    site: Literal["MAJA", "CEMPLANG"],
    distribution_date: date = Query(alias="distributionDate"),
) -> dict[str, Any]:
    _, preview = _planning_payload(site, distribution_date)
    return {"committed": False, **preview}


@router.post("/calculator-planning/sync")
def sync_calculator_planning(payload: CalculatorPlanningSyncIn) -> dict[str, Any]:
    planning, preview = _planning_payload(payload.site, payload.distribution_date)
    result = ingest_planning_snapshot(planning)
    detail = get_planning_snapshot(result["snapshotId"])
    return {
        "committed": True,
        "duplicate": bool(result.get("duplicate")),
        "snapshotId": result["snapshotId"],
        "snapshotKey": result["snapshotKey"],
        "cycleCode": result["cycleCode"],
        "source": preview,
        "snapshot": detail,
    }
