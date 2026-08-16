from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.google_services import SITE_TARGETS, firestore_client
from backend.item_taxonomy import vendor_for_item
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
    selected_candidates = [candidate for candidate in candidates if candidate["app_id"] == app_id]
    source_plans = [
        {
            "documentId": candidate["doc"].id,
            "planName": candidate["data"].get("planName"),
            "updatedAt": _json_safe(candidate["updated_at"]),
            "data": _json_safe(candidate["data"]),
        }
        for candidate in selected_candidates
    ]
    shopping_entries: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for candidate in selected_candidates:
        shopping = ((candidate["data"].get("shoppingListJSON") or {}).get("shoppingList") or [])
        if not isinstance(shopping, list):
            continue
        for raw in shopping:
            if isinstance(raw, dict):
                shopping_entries.append((raw, candidate))
    if not shopping_entries:
        raise HTTPException(409, "rencana Kalkulator ditemukan tetapi daftar belanja masih kosong; hitung/finalkan belanja di Kalkulator terlebih dahulu")

    combined: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    skipped: list[dict[str, Any]] = []
    for idx, (raw, candidate) in enumerate(shopping_entries):
        name = str(raw.get("item") or raw.get("name") or "").strip()
        planned_qty = _as_float(raw.get("jumlah"))
        if not name or planned_qty is None:
            skipped.append({"index": idx, "item": name, "documentId": candidate["doc"].id, "reason": "missing_name_or_qty"})
            continue
        supplier_key = str(raw.get("supplierOverride") or "").strip()
        category = SUPPLIER_CATEGORY.get(supplier_key) or str(raw.get("category_code") or "").strip() or None
        unit = str(raw.get("satuan") or "").strip() or None
        item_code = str(raw.get("item_code") or "").strip() or None
        preferred_vendor = vendor_for_item(name, category, site, None)
        key = (name.lower(), str(unit or "").lower(), str(category or ""), str(item_code or ""))
        entry = combined.setdefault(key, {
            "item_code": item_code,
            "item_name": name,
            "category_code": category,
            "planned_qty": 0.0,
            "unit": unit,
            "planning_price": _as_float(raw.get("harga_satuan")),
            "preferred_vendor_code": preferred_vendor,
            "notes": [],
            "sources": [],
        })
        entry["planned_qty"] += planned_qty
        if entry["planning_price"] is None:
            entry["planning_price"] = _as_float(raw.get("harga_satuan"))
        note = str(raw.get("note") or "").strip()
        if note and note not in entry["notes"]:
            entry["notes"].append(note)
        entry["sources"].append({
            "documentId": candidate["doc"].id,
            "planName": candidate["data"].get("planName"),
            "plannedQty": planned_qty,
            "raw": _json_safe(raw),
        })

    items = [PlanningItemIn(
        item_code=entry["item_code"], item_name=entry["item_name"], category_code=entry["category_code"],
        planned_qty=round(entry["planned_qty"], 4), unit=entry["unit"], planning_price=entry["planning_price"],
        preferred_vendor_code=entry["preferred_vendor_code"], notes=" | ".join(entry["notes"]) or None,
        source_payload={"combinedPlanCount": len(entry["sources"]), "sources": entry["sources"]},
    ) for entry in combined.values()]

    updated = max((candidate["updated_at"] for candidate in selected_candidates), default=_plan_updated_at(plan))
    plan_hash = hashlib.sha256(json.dumps(source_plans, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    document_ids = sorted(candidate["doc"].id for candidate in selected_candidates)
    snapshot_key = f"calculator:{site.lower()}:{app_id}:combined:{plan_hash}"
    source_payload = {
        "firestoreDatabase": SITE_TARGETS[site]["database_id"],
        "calculatorAppId": app_id,
        "dailyPlanDocumentId": doc_snap.id,
        "dailyPlanDocumentIds": document_ids,
        "planName": plan.get("planName"),
        "planNames": [candidate["data"].get("planName") for candidate in selected_candidates],
        "porsiKecil": plan.get("porsiKecil"),
        "porsiBesar": plan.get("porsiBesar"),
        "shoppingListGrandTotal": sum(_as_float((candidate["data"].get("shoppingListJSON") or {}).get("grand_total_num")) or 0 for candidate in selected_candidates),
        "recipes": [recipe for candidate in selected_candidates for recipe in _json_safe(candidate["data"].get("recipes") or [])],
        "sourceUpdatedAt": _json_safe(updated),
        "sourceCandidateCount": len(selected_candidates),
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
        "dailyPlanDocumentIds": document_ids,
        "planName": plan.get("planName"),
        "planNames": [candidate["data"].get("planName") for candidate in selected_candidates],
        "porsiKecil": plan.get("porsiKecil"),
        "porsiBesar": plan.get("porsiBesar"),
        "itemCount": len(items),
        "skippedItems": skipped,
        "grandTotal": source_payload["shoppingListGrandTotal"],
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
