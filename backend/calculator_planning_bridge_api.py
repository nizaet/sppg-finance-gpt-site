from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.db import connection, database_ready
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

PLAN_DATE_FIELDS = ("date", "tanggal", "planDate", "distributionDate")
CANONICAL_SCAN_LIMIT = 500
DISCOVERY_LIMIT = 50


class CalculatorPlanningSyncIn(BaseModel):
    site: Literal["MAJA", "CEMPLANG"]
    distribution_date: date
    deactivate_missing: bool = False


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
    # The calculator pages write to the canonical per-site artifact root from
    # SITE_TARGETS. Reading a deployment override here can silently point the
    # PO bridge at a different artifact, while leaving the calculator itself
    # on the canonical root. Pin both sides to the same source of truth.
    return str(SITE_TARGETS[site]["site_id"])


def _plan_updated_at(data: dict[str, Any]) -> datetime:
    value = data.get("updatedAt") or data.get("createdAt")
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.min.replace(tzinfo=timezone.utc)


def _normalized_plan_date(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip()
    if not text:
        return None
    for pattern, date_format in (
        (r"^\d{4}-\d{2}-\d{2}", "%Y-%m-%d"),
        (r"^\d{1,2}/\d{1,2}/\d{4}$", "%d/%m/%Y"),
        (r"^\d{1,2}-\d{1,2}-\d{4}$", "%d-%m-%Y"),
    ):
        matched = re.match(pattern, text)
        if not matched:
            continue
        try:
            return datetime.strptime(matched.group(0), date_format).date().isoformat()
        except ValueError:
            return None
    return None


def _plan_date(data: dict[str, Any]) -> tuple[str | None, Any, str | None]:
    for field in PLAN_DATE_FIELDS:
        if field not in data:
            continue
        raw = data.get(field)
        normalized = _normalized_plan_date(raw)
        if normalized:
            return field, raw, normalized
    return None, None, None


def _artifact_app_id(snapshot: Any) -> str | None:
    path = str(getattr(getattr(snapshot, "reference", None), "path", "") or "")
    parts = [part for part in path.split("/") if part]
    if len(parts) == 6 and parts[0] == "artifacts" and parts[2:5] == ["public", "data", "dailyPlans"]:
        return parts[1]
    return None


def _candidate(app_id: str, snapshot: Any, data: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = data if data is not None else (snapshot.to_dict() or {})
    shopping = ((payload.get("shoppingListJSON") or {}).get("shoppingList") or [])
    date_field, raw_date, normalized_date = _plan_date(payload)
    return {
        "app_id": app_id,
        "doc": snapshot,
        "data": payload,
        "updated_at": _plan_updated_at(payload),
        "item_count": len(shopping) if isinstance(shopping, list) else 0,
        "date_field": date_field,
        "raw_date": raw_date,
        "normalized_date": normalized_date,
    }


def _source_detail(client: Any, site: str, target_date: str, configured: str) -> dict[str, Any]:
    target = SITE_TARGETS[site]
    return {
        "site": site,
        "distributionDate": target_date,
        "projectId": str(getattr(client, "project", "") or "unknown"),
        "databaseId": target["database_id"],
        "appId": configured,
        "canonicalAppId": configured,
        "canonicalPath": f"artifacts/{configured}/public/data/dailyPlans",
    }


def _visible_plan_dates(documents: list[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for snapshot in documents:
        data = snapshot.to_dict() or {}
        field, raw, normalized = _plan_date(data)
        rows.append({
            "documentId": snapshot.id,
            "planName": data.get("planName"),
            "dateField": field,
            "rawDate": _json_safe(raw),
            "normalizedDate": normalized,
        })
    rows.sort(key=lambda row: str(row.get("normalizedDate") or ""), reverse=True)
    return rows[:12]


def _daily_plan_matches(site: str, distribution_date: date) -> tuple[str, Any, dict[str, Any], list[dict[str, Any]]]:
    target = SITE_TARGETS[site]
    client = firestore_client(target["database_id"])
    target_date = distribution_date.isoformat()
    configured = _configured_app_id(site)
    app_ref = client.collection("artifacts").document(configured)
    daily_plans = app_ref.collection("public").document("data").collection("dailyPlans")
    source_detail = _source_detail(client, site, target_date, configured)

    candidates: list[dict[str, Any]] = []
    try:
        query = daily_plans.where("date", "==", target_date).limit(20)
        docs = list(query.stream())
    except Exception as exc:
        # Never translate Firestore permission, network, or configuration
        # failures into a misleading "plan not found" response.
        raise HTTPException(
            502,
            detail={
                "message": "gagal membaca rencana Kalkulator dari Firestore",
                **source_detail,
                "errorType": type(exc).__name__,
            },
        ) from exc

    for snap in docs:
        candidates.append(_candidate(configured, snap))

    if not candidates:
        try:
            canonical_docs = list(daily_plans.limit(CANONICAL_SCAN_LIMIT).stream())
        except Exception as exc:
            raise HTTPException(
                502,
                detail={
                    "message": "gagal memeriksa format tanggal lama pada rencana Kalkulator",
                    **source_detail,
                    "errorType": type(exc).__name__,
                },
            ) from exc

        for snap in canonical_docs:
            candidate = _candidate(configured, snap)
            if candidate["normalized_date"] == target_date:
                candidates.append(candidate)

    if not candidates:
        discovered: dict[str, dict[str, Any]] = {}
        try:
            for field in PLAN_DATE_FIELDS:
                query = client.collection_group("dailyPlans").where(field, "==", target_date).limit(DISCOVERY_LIMIT)
                for snap in query.stream():
                    app_id = _artifact_app_id(snap)
                    if not app_id:
                        continue
                    key = str(getattr(getattr(snap, "reference", None), "path", "") or f"{app_id}/{snap.id}")
                    discovered[key] = _candidate(app_id, snap)
        except Exception as exc:
            raise HTTPException(
                502,
                detail={
                    "message": "gagal mencari sumber rencana Kalkulator di Firestore",
                    **source_detail,
                    "canonicalDocumentsInspected": len(canonical_docs),
                    "visibleCanonicalPlans": _visible_plan_dates(canonical_docs),
                    "errorType": type(exc).__name__,
                },
            ) from exc

        other_site = "CEMPLANG" if site == "MAJA" else "MAJA"
        forbidden_app_id = _configured_app_id(other_site)
        discovered_candidates = [
            candidate for candidate in discovered.values()
            if candidate["app_id"] != forbidden_app_id
        ]
        app_ids = sorted({candidate["app_id"] for candidate in discovered_candidates})

        if len(app_ids) == 1:
            candidates = discovered_candidates
            configured = app_ids[0]
        elif len(app_ids) > 1:
            raise HTTPException(
                409,
                detail={
                    "message": "rencana ditemukan pada beberapa appId; sinkronisasi dihentikan agar MAJA dan CEMPLANG tidak tertukar",
                    **source_detail,
                    "candidateAppIds": app_ids,
                    "candidates": [
                        {
                            "appId": candidate["app_id"],
                            "documentId": candidate["doc"].id,
                            "planName": candidate["data"].get("planName"),
                            "dateField": candidate["date_field"],
                            "itemCount": candidate["item_count"],
                        }
                        for candidate in discovered_candidates
                    ],
                },
            )

    if not candidates:
        raise HTTPException(
            404,
            detail={
                "message": f"rencana Kalkulator {site} tanggal {target_date} tidak ditemukan pada sumber Firestore yang terlihat backend",
                **source_detail,
                "canonicalDocumentsInspected": len(canonical_docs),
                "visibleCanonicalPlans": _visible_plan_dates(canonical_docs),
                "nextCheck": "pastikan Kalkulator tidak memakai Firebase Data Connection override lokal",
            },
        )

    candidates.sort(key=lambda x: (x["updated_at"], x["item_count"]), reverse=True)
    chosen = candidates[0]
    return chosen["app_id"], chosen["doc"], chosen["data"], candidates


def _planning_payload(site: str, distribution_date: date) -> tuple[PlanningSnapshotIn, dict[str, Any]]:
    app_id, doc_snap, plan, candidates = _daily_plan_matches(site, distribution_date)
    canonical_app_id = _configured_app_id(site)
    source_resolution = "CANONICAL" if app_id == canonical_app_id else "DISCOVERED_UNIQUE_APP_ID"
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
        "canonicalCalculatorAppId": canonical_app_id,
        "sourceResolution": source_resolution,
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
        "canonicalAppId": canonical_app_id,
        "sourceResolution": source_resolution,
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
    try:
        planning, preview = _planning_payload(payload.site, payload.distribution_date)
    except HTTPException as exc:
        if exc.status_code != 404 or not payload.deactivate_missing:
            raise
        if not database_ready():
            raise HTTPException(503, "database unavailable") from exc
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    update planning_snapshots
                    set status='SUPERSEDED'
                    where upper(site)=%s
                      and distribution_date=%s
                      and source_system='CALCULATOR_FIRESTORE'
                      and status='ACTIVE'
                    returning id
                    """,
                    (payload.site, payload.distribution_date),
                )
                superseded_ids = [int(row["id"]) for row in cur.fetchall()]
            conn.commit()
        return {
            "committed": True,
            "sourceMissing": True,
            "site": payload.site,
            "distributionDate": payload.distribution_date.isoformat(),
            "supersededSnapshotIds": superseded_ids,
            "itemCount": 0,
        }
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
