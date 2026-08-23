"""Read-only weekly menu planner built from confirmed Calculator history.

The planner deliberately creates an in-memory draft only.  It never writes a
Calculator daily plan, PO, stock movement, receipt, payment, or Excel file.
Its candidates are existing historical Calculator plans, scaled from their
actual shopping-list quantities and prices.  That makes the first automation
safe: no invented recipes, portions, prices, or bumbu quantities.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query

from backend.db import connection, database_ready


router = APIRouter(prefix="/v1/menu-planning-advisor", tags=["menu-planning-advisor"])
Site = Literal["MAJA", "CEMPLANG"]


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result >= 0 else None


def _payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except ValueError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _as_dict(row: Any) -> dict[str, Any] | None:
    return dict(row) if row else None


def _item_view(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "itemCode": item.get("item_code"), "itemName": item.get("item_name"),
        "categoryCode": item.get("category_code"), "plannedQty": item.get("planned_qty"),
        "unit": item.get("unit"), "planningPrice": item.get("planning_price"),
        "preferredVendorCode": item.get("preferred_vendor_code"), "notes": item.get("notes"),
    }


def _load_items(cur: Any, snapshot_id: int) -> list[dict[str, Any]]:
    cur.execute(
        """
        select item_code, item_name, category_code, planned_qty, unit, planning_price,
               preferred_vendor_code, notes
        from planning_snapshot_items where planning_snapshot_id=%s order by id
        """,
        (snapshot_id,),
    )
    return [dict(row) for row in cur.fetchall()]


def _snapshot_view(snapshot: dict[str, Any] | None, items: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not snapshot:
        return None
    return {
        "snapshotId": snapshot.get("id"), "snapshotKey": snapshot.get("snapshot_key"),
        "site": snapshot.get("site"), "distributionDate": snapshot.get("distribution_date"),
        "cookingAt": snapshot.get("cooking_at"), "sourceSystem": snapshot.get("source_system"),
        "sourceVersion": snapshot.get("source_version"), "sourceUpdatedAt": snapshot.get("source_updated_at"),
        "status": snapshot.get("status"), "payload": _payload(snapshot.get("payload")),
        "items": [_item_view(item) for item in items],
    }


def _load_confirmed_knowledge(cur: Any, site: str) -> list[dict[str, Any]]:
    cur.execute(
        """
        select scope_type, site, topic, statement, knowledge_kind, confidence,
               evidence_count, metadata, last_seen_at
        from llm_learned_knowledge
        where status='CONFIRMED' and (site is null or upper(site)=upper(%s))
        order by confidence desc, evidence_count desc, last_seen_at desc limit 30
        """,
        (site,),
    )
    return [{
        "scopeType": row.get("scope_type"), "site": row.get("site"), "topic": row.get("topic"),
        "statement": row.get("statement"), "knowledgeKind": row.get("knowledge_kind"),
        "confidence": row.get("confidence"), "evidenceCount": row.get("evidence_count"),
        "metadata": _payload(row.get("metadata")), "lastSeenAt": row.get("last_seen_at"),
    } for row in cur.fetchall()]


def _load_snapshots(cur: Any, site: str, start: date | None, end: date | None, limit: int = 120) -> list[dict[str, Any]]:
    sql = """
        select id, snapshot_key, site, distribution_date, cooking_at, source_system,
               source_version, source_updated_at, status, payload
        from planning_snapshots where upper(site)=upper(%s) and status='ACTIVE'
    """
    params: list[Any] = [site]
    if start:
        sql += " and distribution_date >= %s"; params.append(start)
    if end:
        sql += " and distribution_date <= %s"; params.append(end)
    sql += " order by distribution_date desc, source_updated_at desc, created_at desc limit %s"
    params.append(limit)
    cur.execute(sql, params)
    result: list[dict[str, Any]] = []
    for row in cur.fetchall():
        snapshot = dict(row)
        snapshot["items"] = _load_items(cur, int(snapshot["id"]))
        result.append(snapshot)
    return result


def _first_number(payload: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        number = _number(payload.get(key))
        if number is not None and number > 0:
            return number
    return None


def _total_pm(payload: dict[str, Any]) -> int | None:
    explicit = _first_number(payload, ("targetPm", "targetPM", "totalPm", "totalPM", "totalPorsi", "totalPortion"))
    if explicit:
        return int(round(explicit))
    small = _number(payload.get("porsiKecil")) or 0
    large = _number(payload.get("porsiBesar")) or 0
    total = small + large
    return int(round(total)) if total > 0 else None


def _pagu_per_pm(payload: dict[str, Any]) -> float | None:
    return _first_number(payload, ("paguPerPm", "paguPerPM", "paguPerPorsi", "budgetPerPortion", "budgetPerPm"))


def _recipe_names(payload: dict[str, Any]) -> list[str]:
    recipes = payload.get("recipes") or []
    names: list[str] = []
    if not isinstance(recipes, list):
        recipes = []
    for recipe in recipes:
        if not isinstance(recipe, dict):
            continue
        name = str(recipe.get("name") or recipe.get("recipeName") or recipe.get("title") or "").strip()
        if name and name.lower() not in {value.lower() for value in names}:
            names.append(name)
    return names


def _menu_title(payload: dict[str, Any], recipe_names: list[str]) -> str:
    title = str(payload.get("planName") or payload.get("menuName") or "").strip()
    return title or " + ".join(recipe_names[:4]) or "Menu historis tanpa nama"


def _fruit_names(items: list[dict[str, Any]]) -> list[str]:
    """Return only explicitly named fruit already present in the source plan."""
    tokens = (
        "apel", "anggur", "alpukat", "belimbing", "duren", "jambu", "jeruk", "kiwi",
        "mangga", "melon", "nanas", "nangka", "pear", "pepaya", "pisang", "salak",
        "semangka", "sirsak", "stroberi", "sukun",
    )
    found: list[str] = []
    for item in items:
        name = str(item.get("item_name") or "").strip()
        if name and any(token in name.casefold() for token in tokens) and name not in found:
            found.append(name)
    return found


def _material_cost(items: list[dict[str, Any]]) -> tuple[float | None, list[str]]:
    total = 0.0
    gaps: list[str] = []
    for item in items:
        name = str(item.get("item_name") or "bahan tanpa nama")
        quantity = _number(item.get("planned_qty"))
        price = _number(item.get("planning_price"))
        if quantity is None:
            gaps.append(f"Jumlah rencana {name} belum tersedia.")
        elif price is None:
            gaps.append(f"Harga rencana {name} belum tersedia.")
        else:
            total += quantity * price
    return (round(total, 2) if not gaps else None), gaps


def _template(snapshot: dict[str, Any]) -> dict[str, Any]:
    payload = _payload(snapshot.get("payload"))
    recipes = _recipe_names(payload)
    pm = _total_pm(payload)
    cost, cost_gaps = _material_cost(snapshot.get("items") or [])
    last_date = snapshot.get("distribution_date")
    return {
        "snapshotId": snapshot.get("id"), "distributionDate": last_date,
        "menuTitle": _menu_title(payload, recipes), "recipeNames": recipes,
        "menuKey": "|".join(value.casefold() for value in recipes) or str(payload.get("planName") or "").casefold(),
        "fruitNames": _fruit_names(snapshot.get("items") or []),
        "sourcePm": pm, "sourcePaguPerPm": _pagu_per_pm(payload),
        "sourceCost": cost, "sourceItems": snapshot.get("items") or [], "dataGaps": cost_gaps,
    }


def _scale_materials(items: list[dict[str, Any]], factor: float) -> tuple[list[dict[str, Any]], float | None, list[str]]:
    materials: list[dict[str, Any]] = []
    total = 0.0
    gaps: list[str] = []
    for item in items:
        quantity = _number(item.get("planned_qty"))
        price = _number(item.get("planning_price"))
        name = str(item.get("item_name") or "bahan tanpa nama")
        scaled_quantity = round(quantity * factor, 4) if quantity is not None else None
        line_total = round(scaled_quantity * price, 2) if scaled_quantity is not None and price is not None else None
        if line_total is None:
            gaps.append(f"Jumlah atau harga {name} belum lengkap.")
        else:
            total += line_total
        materials.append({
            "itemName": item.get("item_name"), "categoryCode": item.get("category_code"),
            "quantity": scaled_quantity, "unit": item.get("unit"), "planningPrice": price,
            "estimatedLineTotal": line_total, "preferredVendorCode": item.get("preferred_vendor_code"),
            "notes": item.get("notes"),
        })
    return materials, (round(total, 2) if not gaps else None), gaps


def _day_from_existing(day: date, snapshot: dict[str, Any], pagu: float | None) -> dict[str, Any]:
    template = _template(snapshot)
    pm = template["sourcePm"]
    cost = template["sourceCost"]
    per_pm = round(cost / pm, 2) if cost is not None and pm else None
    gaps = list(template["dataGaps"])
    if not pm:
        gaps.append("Target PM dari planning yang sudah ada belum tercatat.")
    return {
        "date": day, "state": "EXISTING", "draft": False, "menuTitle": template["menuTitle"],
        "recipeNames": template["recipeNames"], "fruitNames": template["fruitNames"], "targetPm": pm, "estimatedTotal": cost,
        "estimatedPerPm": per_pm, "paguPerPm": pagu or template["sourcePaguPerPm"],
        "withinPagu": None if per_pm is None or not (pagu or template["sourcePaguPerPm"]) else per_pm <= (pagu or template["sourcePaguPerPm"]),
        "materials": [_item_view(item) for item in template["sourceItems"]], "dataGaps": gaps,
        "sourceTemplate": {"snapshotId": template["snapshotId"], "distributionDate": template["distributionDate"]},
    }


def _day_from_template(day: date, template: dict[str, Any], target_pm: int | None, pagu: float | None) -> dict[str, Any]:
    if not target_pm or not template["sourcePm"]:
        return {
            "date": day, "state": "NEEDS_DATA", "draft": True, "menuTitle": template["menuTitle"],
            "recipeNames": template["recipeNames"], "fruitNames": template["fruitNames"], "targetPm": target_pm, "estimatedTotal": None,
            "estimatedPerPm": None, "paguPerPm": pagu, "withinPagu": None, "materials": [],
            "dataGaps": ["Target PM belum tersedia sehingga jumlah bahan tidak boleh dihitung."],
            "sourceTemplate": {"snapshotId": template["snapshotId"], "distributionDate": template["distributionDate"]},
        }
    materials, total, gaps = _scale_materials(template["sourceItems"], target_pm / template["sourcePm"])
    per_pm = round(total / target_pm, 2) if total is not None else None
    effective_pagu = pagu or template["sourcePaguPerPm"]
    if not effective_pagu:
        gaps.append("Pagu per PM belum tersedia sehingga status hemat pagu belum dapat diputuskan.")
    return {
        "date": day, "state": "PROPOSED_DRAFT" if total is not None else "NEEDS_DATA", "draft": True,
        "menuTitle": template["menuTitle"], "recipeNames": template["recipeNames"], "fruitNames": template["fruitNames"], "targetPm": target_pm,
        "estimatedTotal": total, "estimatedPerPm": per_pm, "paguPerPm": effective_pagu,
        "withinPagu": None if per_pm is None or not effective_pagu else per_pm <= effective_pagu,
        "materials": materials, "dataGaps": gaps,
        "sourceTemplate": {"snapshotId": template["snapshotId"], "distributionDate": template["distributionDate"], "sourcePm": template["sourcePm"]},
    }


def _build_week_draft(
    *, site: str, week_start: date, days: int, snapshots: list[dict[str, Any]],
    target_pm: int | None, pagu_per_pm: float | None, knowledge: list[dict[str, Any]],
) -> dict[str, Any]:
    week_end = week_start + timedelta(days=days - 1)
    existing_by_date: dict[date, dict[str, Any]] = {}
    historical: list[dict[str, Any]] = []
    for snapshot in snapshots:
        distribution_date = snapshot.get("distribution_date")
        if not isinstance(distribution_date, date):
            continue
        if week_start <= distribution_date <= week_end:
            existing_by_date.setdefault(distribution_date, snapshot)
        elif distribution_date < week_start:
            historical.append(snapshot)

    templates = [_template(snapshot) for snapshot in historical]
    templates = [template for template in templates if template["sourcePm"] and template["sourceItems"]]
    templates.sort(key=lambda template: template["distributionDate"], reverse=False)
    suggested_pm = target_pm or next((template["sourcePm"] for template in reversed(templates) if template["sourcePm"]), None)
    suggested_pagu = pagu_per_pm or next((template["sourcePaguPerPm"] for template in reversed(templates) if template["sourcePaguPerPm"]), None)

    result_days: list[dict[str, Any]] = []
    last_key = ""
    last_fruit = ""
    use_counts: dict[int, int] = {}
    for offset in range(days):
        target_date = week_start + timedelta(days=offset)
        existing = existing_by_date.get(target_date)
        if existing:
            record = _day_from_existing(target_date, existing, pagu_per_pm)
            last_key = "|".join(value.casefold() for value in record["recipeNames"])
            last_fruit = "|".join(value.casefold() for value in record.get("fruitNames") or [])
            result_days.append(record)
            continue
        candidates = [template for template in templates if template["menuKey"] and template["menuKey"] != last_key]
        fruit_varied = [template for template in candidates if not last_fruit or "|".join(value.casefold() for value in template["fruitNames"]) != last_fruit]
        if fruit_varied:
            candidates = fruit_varied
        if not candidates:
            candidates = templates
        if not candidates:
            result_days.append({
                "date": target_date, "state": "NEEDS_DATA", "draft": True, "menuTitle": None,
                "recipeNames": [], "targetPm": suggested_pm, "estimatedTotal": None, "estimatedPerPm": None,
                "paguPerPm": suggested_pagu, "withinPagu": None, "fruitNames": [], "materials": [],
                "dataGaps": ["Belum ada menu historis lengkap untuk dijadikan draft yang aman."], "sourceTemplate": None,
            })
            continue
        candidate = min(candidates, key=lambda template: (use_counts.get(int(template["snapshotId"]), 0), template["distributionDate"]))
        use_counts[int(candidate["snapshotId"])] = use_counts.get(int(candidate["snapshotId"]), 0) + 1
        record = _day_from_template(target_date, candidate, suggested_pm, pagu_per_pm)
        last_key = candidate["menuKey"]
        last_fruit = "|".join(value.casefold() for value in candidate["fruitNames"])
        result_days.append(record)

    proposed = [day for day in result_days if day["state"] == "PROPOSED_DRAFT"]
    known_totals = [day["estimatedTotal"] for day in proposed if day["estimatedTotal"] is not None]
    all_within = [day["withinPagu"] for day in proposed if day["withinPagu"] is not None]
    return {
        "engine": "menu-planning-weekly-v2", "readOnly": True, "draftOnly": True, "site": site,
        "weekStart": week_start, "weekEnd": week_end, "requestedDays": days,
        "targetPm": suggested_pm, "paguPerPm": suggested_pagu, "days": result_days,
        "summary": {
            "existingDays": sum(day["state"] == "EXISTING" for day in result_days),
            "proposedDays": len(proposed), "needsDataDays": sum(day["state"] == "NEEDS_DATA" for day in result_days),
            "totalEstimatedSpend": round(sum(known_totals), 2) if len(known_totals) == len(proposed) else None,
            "allProposedWithinPagu": all(all_within) if len(all_within) == len(proposed) and proposed else None,
        },
        "confirmedKnowledge": knowledge,
        "rulesApplied": [
            "Hari yang sudah memiliki planning ditampilkan sebagai EXISTING dan tidak ditimpa.",
            "Hari kosong hanya memakai menu historis Calculator dengan bahan, jumlah, dan harga yang tersedia.",
            "Menu yang sama tidak dipilih untuk dua hari berturut-turut bila alternatif tersedia.",
            "Buah dari histori tidak diulang pada hari berikutnya bila alternatif buah tersedia.",
            "Jumlah tiap bahan, termasuk bumbu, diskalakan dari histori menu sumber menurut target PM.",
            "Status hemat pagu hanya diberikan jika harga bahan, target PM, dan pagu per PM tersedia.",
        ],
        "automationBoundary": {
            "canCreateOrEditCalculator": False, "canCreateOrEditPurchaseOrder": False,
            "canRecordReceiving": False, "canRecordPayment": False, "canGenerateOrSendExcel": False,
        },
    }


@router.get("/week-preview")
def weekly_menu_preview(
    site: Site,
    week_start: date = Query(alias="weekStart"),
    days: int = Query(default=7, ge=1, le=7),
    target_pm: int | None = Query(default=None, alias="targetPm", ge=1),
    pagu_per_pm: float | None = Query(default=None, alias="paguPerPm", gt=0),
) -> dict[str, Any]:
    """Build a read-only weekly draft from historical Calculator snapshots."""
    if not database_ready():
        return _build_week_draft(site=site, week_start=week_start, days=days, snapshots=[], target_pm=target_pm, pagu_per_pm=pagu_per_pm, knowledge=[])
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                snapshots = _load_snapshots(cur, site, None, week_start + timedelta(days=days - 1), limit=180)
                knowledge = _load_confirmed_knowledge(cur, site)
    except Exception as exc:
        raise HTTPException(503, "menu planning data is temporarily unavailable") from exc
    return _build_week_draft(site=site, week_start=week_start, days=days, snapshots=snapshots, target_pm=target_pm, pagu_per_pm=pagu_per_pm, knowledge=knowledge)


@router.get("/preview")
def menu_planning_preview(site: Site, distribution_date: date | None = Query(default=None, alias="distributionDate")) -> dict[str, Any]:
    """Compatibility read-only context route for the first advisor screen."""
    if not database_ready():
        return {"readOnly": True, "draftOnly": True, "databaseReady": False, "site": site, "requestedDistributionDate": distribution_date, "targetPlanning": None, "planningHistory": [], "confirmedKnowledge": [], "dataGaps": [{"code": "DATABASE_UNAVAILABLE", "message": "Database belum tersedia."}]}
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                snapshots = _load_snapshots(cur, site, None, distribution_date, limit=8)
                target = next((snapshot for snapshot in snapshots if snapshot.get("distribution_date") == distribution_date), None) if distribution_date else (snapshots[0] if snapshots else None)
                history = [snapshot for snapshot in snapshots if snapshot is not target]
                knowledge = _load_confirmed_knowledge(cur, site)
    except Exception as exc:
        raise HTTPException(503, "menu planning context is temporarily unavailable") from exc
    target_items = target.get("items") if target else []
    return {
        "readOnly": True, "draftOnly": True, "databaseReady": True, "site": site,
        "requestedDistributionDate": distribution_date, "targetPlanning": _snapshot_view(target, target_items),
        "planningHistory": [_snapshot_view(snapshot, snapshot.get("items") or []) for snapshot in history],
        "confirmedKnowledge": knowledge, "dataGaps": [],
    }
