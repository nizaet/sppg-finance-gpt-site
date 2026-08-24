"""Read-only weekly menu planner built from confirmed Calculator history.

The planner deliberately creates an in-memory draft only.  It never writes a
Calculator daily plan, PO, stock movement, receipt, payment, or Excel file.
Its candidates are existing historical Calculator plans, scaled from their
actual shopping-list quantities and prices.  That makes the first automation
safe: no invented recipes, portions, prices, or bumbu quantities.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from math import ceil
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.db import connection, database_ready
from backend.google_services import SITE_TARGETS, firestore_client


router = APIRouter(prefix="/v1/menu-planning-advisor", tags=["menu-planning-advisor"])
Site = Literal["MAJA", "CEMPLANG"]


class MenuDraftMaterialIn(BaseModel):
    itemName: str = Field(min_length=1, max_length=300)
    quantity: float = Field(gt=0)
    unit: str = Field(min_length=1, max_length=50)
    planningPrice: float = Field(ge=0)
    categoryCode: str | None = Field(default=None, max_length=100)
    preferredVendorCode: str | None = Field(default=None, max_length=100)


class MenuDraftTransferDayIn(BaseModel):
    date: date
    planName: str = Field(min_length=1, max_length=500)
    recipeNames: list[str] = Field(min_length=1, max_length=30)
    materials: list[MenuDraftMaterialIn] = Field(min_length=1, max_length=300)


class MenuDraftTransferIn(BaseModel):
    site: Site
    porsiKecil: int = Field(ge=0)
    porsiBesar: int = Field(ge=0)
    paguKecil: float = Field(gt=0)
    paguBesar: float = Field(gt=0)
    plans: list[MenuDraftTransferDayIn] = Field(min_length=1, max_length=7)
    confirmed: Literal[True]


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
        "sourcePayload": _payload(item.get("source_payload")),
    }


def _load_items(cur: Any, snapshot_id: int) -> list[dict[str, Any]]:
    cur.execute(
        """
        select item_code, item_name, category_code, planned_qty, unit, planning_price,
               preferred_vendor_code, notes, source_payload
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


def _plan_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    for candidate in (text[:10], text):
        try:
            return date.fromisoformat(candidate)
        except ValueError:
            pass
    for pattern in ("%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            pass
    return None


def _load_calculator_history(site: str, end: date, limit: int = 365) -> tuple[list[dict[str, Any]], str | None]:
    """Read historical daily plans directly from Calculator Firestore.

    PostgreSQL snapshots are only created when a day has been synced. They are
    not a complete menu archive, so the planner must read the Calculator's
    full historical daily-plan collection before it declares that variation is
    unavailable. This is read-only and affects only Asisten Menu.
    """
    try:
        target = SITE_TARGETS[site]
        root = (
            firestore_client(target["database_id"])
            .collection("artifacts").document(target["site_id"])
            .collection("public").document("data").collection("dailyPlans")
        )
        result: list[dict[str, Any]] = []
        for document in root.stream():
            payload = document.to_dict() or {}
            distribution_date = _plan_date(payload.get("date") or payload.get("distributionDate") or payload.get("planDate"))
            if not distribution_date or distribution_date > end:
                continue
            shopping = ((payload.get("shoppingListJSON") or {}).get("shoppingList") or [])
            if not isinstance(shopping, list) or not shopping:
                continue
            items: list[dict[str, Any]] = []
            for raw in shopping:
                if not isinstance(raw, dict):
                    continue
                name = str(raw.get("item") or raw.get("name") or "").strip()
                quantity = _number(raw.get("jumlah"))
                if not name or quantity is None:
                    continue
                items.append({
                    "item_code": raw.get("item_code"), "item_name": name,
                    "category_code": raw.get("category_code"), "planned_qty": quantity,
                    "unit": raw.get("satuan") or "kg", "planning_price": _number(raw.get("harga_satuan")),
                    "preferred_vendor_code": raw.get("supplierOverride"), "notes": raw.get("note"),
                    "source_payload": raw,
                })
            if items:
                result.append({
                    "id": f"firestore:{document.id}", "snapshot_key": f"calculator-history:{document.id}",
                    "site": site, "distribution_date": distribution_date, "status": "ACTIVE",
                    "source_system": "CALCULATOR_FIRESTORE_HISTORY", "payload": payload, "items": items,
                })
        result.sort(key=lambda snapshot: snapshot["distribution_date"], reverse=True)
        return result[:limit], None
    except Exception as exc:
        # A database snapshot remains a safe fallback when Firestore is
        # temporarily unreachable; never make the advisor invent a menu.
        return [], type(exc).__name__


def _first_number(payload: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        number = _number(payload.get(key))
        if number is not None and number > 0:
            return number
    return None


def _total_pm(payload: dict[str, Any]) -> int | None:
    small = _number(payload.get("porsiKecil")) or 0
    large = _number(payload.get("porsiBesar")) or 0
    total = small + large
    if total > 0:
        return int(round(total))
    explicit = _first_number(payload, ("targetPm", "targetPM", "totalPm", "totalPM", "totalPorsi", "totalPortion"))
    return int(round(explicit)) if explicit else None


def _pm_breakdown(payload: dict[str, Any]) -> dict[str, int | None]:
    small = _number(payload.get("porsiKecil"))
    large = _number(payload.get("porsiBesar"))
    if small is not None or large is not None:
        return {"small": int(round(small or 0)), "large": int(round(large or 0)), "total": int(round((small or 0) + (large or 0)))}
    explicit = _first_number(payload, ("targetPm", "targetPM", "totalPm", "totalPM", "totalPorsi", "totalPortion"))
    return {"small": None, "large": None, "total": int(round(explicit)) if explicit else None}


def _pagu_per_pm(payload: dict[str, Any]) -> float | None:
    return _first_number(payload, ("paguPerPm", "paguPerPM", "paguPerPorsi", "budgetPerPortion", "budgetPerPm"))


def _pagu_total(
    porsi_kecil: int | None,
    porsi_besar: int | None,
    pagu_kecil: float | None,
    pagu_besar: float | None,
) -> float | None:
    """Return the exact daily ceiling, without averaging small and large PM."""
    if porsi_kecil is None or porsi_besar is None or not pagu_kecil or not pagu_besar:
        return None
    total_pm = porsi_kecil + porsi_besar
    if total_pm <= 0:
        return None
    return round((porsi_kecil * pagu_kecil) + (porsi_besar * pagu_besar), 2)


def _is_b3_milk_name(value: str) -> bool:
    normalized = value.casefold()
    return "susu" in normalized or "milk" in normalized


def _recipe_names(payload: dict[str, Any]) -> list[str]:
    recipes = payload.get("recipes") or []
    names: list[str] = []
    if not isinstance(recipes, list):
        recipes = []
    for recipe in recipes:
        if not isinstance(recipe, dict):
            continue
        name = str(recipe.get("name") or recipe.get("recipeName") or recipe.get("title") or "").strip()
        if name and not _is_b3_milk_name(name) and name.lower() not in {value.lower() for value in names}:
            names.append(name)
    return names


def _menu_title(payload: dict[str, Any], recipe_names: list[str]) -> str:
    title = str(payload.get("planName") or payload.get("menuName") or "").strip()
    return " + ".join(recipe_names[:4]) or title or "Menu historis tanpa nama"


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


def _menu_profile(template: dict[str, Any]) -> dict[str, Any]:
    """Describe a complete historical menu package for safe weekly selection.

    Calculator snapshots store one combined shopping list, not a reliable
    ingredient-to-recipe map.  We therefore score complete historical menu
    packages, preserving their real bumbu and quantities, rather than mixing
    disconnected ingredients into a made-up recipe.
    """
    items = template.get("sourceItems") or []
    categories = {str(item.get("category_code") or "").upper() for item in items}
    names = " ".join(str(item.get("item_name") or "").casefold() for item in items)
    recipes = " ".join(str(value).casefold() for value in template.get("recipeNames") or [])
    haystack = f"{names} {recipes}"
    if "telur" in haystack or "TELUR" in categories:
        protein = "TELUR"
    elif "AYAM" in categories or "ayam" in haystack:
        protein = "AYAM"
    elif "IKAN" in categories or any(token in haystack for token in ("ikan", "dori", "lele", "bandeng")):
        protein = "IKAN"
    elif "TEMPE_TAHU" in categories or any(token in haystack for token in ("tempe", "tahu")):
        protein = "TEMPE_TAHU"
    else:
        protein = "LAINNYA"
    return {
        "proteinType": protein,
        "isEggMenu": protein == "TELUR",
        "hasFruit": bool(template.get("fruitNames")),
        "recipeCount": len(template.get("recipeNames") or []),
    }


def _material_catalog(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Offer only known Calculator material names for draft editing."""
    by_name: dict[str, dict[str, Any]] = {}
    for snapshot in snapshots:
        for item in snapshot.get("items") or []:
            name = str(item.get("item_name") or "").strip()
            if not name:
                continue
            key = name.casefold()
            candidate = {
                "itemName": name,
                "unit": item.get("unit") or "kg",
                "planningPrice": item.get("planning_price"),
                "categoryCode": item.get("category_code"),
                "preferredVendorCode": item.get("preferred_vendor_code"),
            }
            previous = by_name.get(key)
            if previous is None or (candidate.get("planningPrice") is not None and previous.get("planningPrice") is None):
                by_name[key] = candidate
    return sorted(by_name.values(), key=lambda item: str(item["itemName"]).casefold())[:500]


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


def _wet_menu_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Exclude B3 milk from the wet-menu draft; retain rice and cooking bumbu."""
    return [item for item in items if not _is_b3_milk_name(str(item.get("item_name") or ""))]


def _round_up_quantity(value: float, unit: Any) -> float:
    normalized = str(unit or "").casefold().strip()
    whole_units = {"pcs", "pc", "buah", "butir", "papan", "ikat", "dus", "box", "kotak", "karung", "pack", "pak"}
    # The displayed buying quantity must be visibly usable: count units are
    # whole, weights are rounded up to the next 0.1 kg (not hidden at 0.01).
    precision = 1 if normalized in whole_units or normalized in {"gr", "gram"} else 10
    return ceil((value * precision) - 1e-9) / precision


def _template(snapshot: dict[str, Any]) -> dict[str, Any]:
    payload = _payload(snapshot.get("payload"))
    recipes = _recipe_names(payload)
    pm_breakdown = _pm_breakdown(payload)
    pm = pm_breakdown["total"]
    wet_items = _wet_menu_items(snapshot.get("items") or [])
    cost, cost_gaps = _material_cost(wet_items)
    last_date = snapshot.get("distribution_date")
    template = {
        "snapshotId": snapshot.get("id"), "distributionDate": last_date,
        "menuTitle": _menu_title(payload, recipes), "recipeNames": recipes,
        "menuKey": "|".join(value.casefold() for value in recipes) or str(payload.get("planName") or "").casefold(),
        "fruitNames": _fruit_names(wet_items),
        "sourcePm": pm, "sourcePaguPerPm": _pagu_per_pm(payload),
        "sourcePmBreakdown": pm_breakdown, "sourceCost": cost, "sourceItems": wet_items, "dataGaps": cost_gaps,
    }
    template["profile"] = _menu_profile(template)
    return template


def _scale_materials(items: list[dict[str, Any]], factor: float) -> tuple[list[dict[str, Any]], float | None, list[str]]:
    materials: list[dict[str, Any]] = []
    total = 0.0
    gaps: list[str] = []
    for item in items:
        quantity = _number(item.get("planned_qty"))
        price = _number(item.get("planning_price"))
        name = str(item.get("item_name") or "bahan tanpa nama")
        raw_quantity = quantity * factor if quantity is not None else None
        # Keep operational quantities safe: weights go up to the next 0.1 kg,
        # while whole units (pcs/buah/butir/etc.) go to the next full unit.
        scaled_quantity = _round_up_quantity(raw_quantity, item.get("unit")) if raw_quantity is not None else None
        line_total = round(scaled_quantity * price, 2) if scaled_quantity is not None and price is not None else None
        if line_total is None:
            gaps.append(f"Jumlah atau harga {name} belum lengkap.")
        else:
            total += line_total
        materials.append({
            "itemName": item.get("item_name"), "categoryCode": item.get("category_code"),
            "quantity": scaled_quantity, "rawQuantity": raw_quantity, "roundingApplied": raw_quantity != scaled_quantity,
            "unit": item.get("unit"), "planningPrice": price,
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
        "recipeNames": template["recipeNames"], "fruitNames": template["fruitNames"], "targetPm": pm,
        "targetPmBreakdown": template["sourcePmBreakdown"], "estimatedTotal": cost,
        "estimatedPerPm": per_pm, "paguPerPm": pagu or template["sourcePaguPerPm"],
        "withinPagu": None if per_pm is None or not (pagu or template["sourcePaguPerPm"]) else per_pm <= (pagu or template["sourcePaguPerPm"]),
        "materials": [_item_view(item) for item in template["sourceItems"]], "dataGaps": gaps,
        "sourceTemplate": {"snapshotId": template["snapshotId"], "distributionDate": template["distributionDate"]},
    }


def _day_from_template(
    day: date,
    template: dict[str, Any],
    target_pm: int | None,
    target_pm_breakdown: dict[str, int | None],
    pagu: float | None,
    pagu_total: float | None,
    selection_reasons: list[str] | None = None,
) -> dict[str, Any]:
    if not target_pm or not template["sourcePm"]:
        return {
            "date": day, "state": "NEEDS_DATA", "draft": True, "menuTitle": template["menuTitle"],
            "recipeNames": template["recipeNames"], "fruitNames": template["fruitNames"], "targetPm": target_pm,
            "targetPmBreakdown": target_pm_breakdown, "estimatedTotal": None,
            "estimatedPerPm": None, "paguPerPm": pagu, "paguTotal": pagu_total, "withinPagu": None, "materials": [],
            "dataGaps": ["Target PM belum tersedia sehingga jumlah bahan tidak boleh dihitung."],
            "selectionReasons": selection_reasons or [], "menuProfile": template["profile"],
            "sourceTemplate": {"snapshotId": template["snapshotId"], "distributionDate": template["distributionDate"], "daysSinceLastPlanned": template.get("daysSinceLastPlanned")},
        }
    materials, total, gaps = _scale_materials(template["sourceItems"], target_pm / template["sourcePm"])
    per_pm = round(total / target_pm, 2) if total is not None else None
    effective_pagu = pagu or template["sourcePaguPerPm"]
    if not effective_pagu:
        gaps.append("Pagu per PM belum tersedia sehingga status hemat pagu belum dapat diputuskan.")
    return {
        "date": day, "state": "PROPOSED_DRAFT" if total is not None else "NEEDS_DATA", "draft": True,
        "menuTitle": template["menuTitle"], "recipeNames": template["recipeNames"], "fruitNames": template["fruitNames"], "targetPm": target_pm,
        "targetPmBreakdown": target_pm_breakdown,
        "estimatedTotal": total, "estimatedPerPm": per_pm, "paguPerPm": effective_pagu, "paguTotal": pagu_total,
        "withinPagu": None if total is None or not (pagu_total or effective_pagu) else total <= pagu_total if pagu_total is not None else per_pm <= effective_pagu,
        "materials": materials, "dataGaps": gaps, "selectionReasons": selection_reasons or [], "menuProfile": template["profile"],
        "sourceTemplate": {"snapshotId": template["snapshotId"], "distributionDate": template["distributionDate"], "sourcePm": template["sourcePm"], "daysSinceLastPlanned": template.get("daysSinceLastPlanned")},
    }


def _snapshot_completeness(snapshot: dict[str, Any]) -> tuple[int, int, int, int]:
    """Prefer a full Calculator daily plan over a one-item fragment.

    A date can contain an old/imported fragment beside the actual daily plan.
    The Firestore stream order is not a business rule, so selecting its first
    document can make a fruit such as Jeruk Medan appear to be the whole menu.
    """
    payload = _payload(snapshot.get("payload"))
    items = _wet_menu_items(snapshot.get("items") or [])
    recipes = _recipe_names(payload)
    priced_items = sum(
        _number(item.get("planned_qty")) is not None
        and _number(item.get("planning_price")) is not None
        for item in items
    )
    return (len(items), len(recipes), priced_items, int(_total_pm(payload) or 0))


def _build_week_draft(
    *, site: str, week_start: date, days: int, snapshots: list[dict[str, Any]],
    target_pm: int | None, pagu_per_pm: float | None, knowledge: list[dict[str, Any]],
    target_pm_breakdown: dict[str, int | None] | None = None,
    pagu_kecil: float | None = None,
    pagu_besar: float | None = None,
) -> dict[str, Any]:
    week_end = week_start + timedelta(days=days - 1)
    # Multiple documents for one distribution date can exist in Firestore.
    # Collapse them first, always retaining the complete daily plan rather
    # than whichever fragment happens to arrive first from the stream.
    best_by_date: dict[date, dict[str, Any]] = {}
    for snapshot in snapshots:
        distribution_date = snapshot.get("distribution_date")
        if not isinstance(distribution_date, date):
            continue
        current = best_by_date.get(distribution_date)
        if current is None or _snapshot_completeness(snapshot) > _snapshot_completeness(current):
            best_by_date[distribution_date] = snapshot

    existing_by_date = {
        distribution_date: snapshot
        for distribution_date, snapshot in best_by_date.items()
        if week_start <= distribution_date <= week_end
    }
    historical = [
        snapshot
        for distribution_date, snapshot in best_by_date.items()
        if distribution_date < week_start
    ]

    template_occurrences = [_template(snapshot) for snapshot in historical]
    # Keep only the latest occurrence for each menu.  The date used for
    # priority is therefore its real last use, not its oldest record.
    latest_by_menu: dict[str, dict[str, Any]] = {}
    for template in template_occurrences:
        if not template["sourcePm"] or not template["sourceItems"] or not template["menuKey"]:
            continue
        previous = latest_by_menu.get(template["menuKey"])
        if previous is None or template["distributionDate"] > previous["distributionDate"]:
            latest_by_menu[template["menuKey"]] = template
    templates = list(latest_by_menu.values())
    for template in templates:
        template["daysSinceLastPlanned"] = max(0, (week_start - template["distributionDate"]).days)
    # The menu least recently used gets priority; a menu absent for a month
    # naturally rises ahead of a menu served yesterday.
    templates.sort(key=lambda template: template["distributionDate"], reverse=False)
    suggested_template = next((template for template in reversed(templates) if template["sourcePm"]), None)
    requested_breakdown = target_pm_breakdown or {}
    requested_small = requested_breakdown.get("small")
    requested_large = requested_breakdown.get("large")
    requested_total = (requested_small or 0) + (requested_large or 0) if requested_small is not None and requested_large is not None else None
    suggested_pm = requested_total or target_pm or (suggested_template["sourcePm"] if suggested_template else None)
    suggested_pm_breakdown = (
        {"small": requested_small, "large": requested_large, "total": requested_total}
        if requested_total else suggested_template["sourcePmBreakdown"] if suggested_template else {"small": None, "large": None, "total": suggested_pm}
    )
    suggested_pagu_total = _pagu_total(requested_small, requested_large, pagu_kecil, pagu_besar)
    suggested_pagu = (
        round(suggested_pagu_total / suggested_pm, 2) if suggested_pagu_total is not None and suggested_pm
        else pagu_per_pm or next((template["sourcePaguPerPm"] for template in reversed(templates) if template["sourcePaguPerPm"]), None)
    )

    result_days: list[dict[str, Any]] = []
    last_key = ""
    last_fruit = ""
    last_protein = ""
    egg_days = 0
    used_menu_keys: set[str] = set()
    candidate_totals: dict[str, float | None] = {}
    # The weekly ceiling applies to the days this assistant is actually
    # proposing. Existing Calculator days are immutable and therefore are not
    # silently counted as editable budget for a new draft.
    draft_slots = sum(
        (week_start + timedelta(days=offset)) not in existing_by_date
        for offset in range(days)
    )
    weekly_spend = 0.0
    weekly_budget = round((suggested_pagu_total or 0) * draft_slots, 2) if suggested_pagu_total is not None else None

    def expected_total(template: dict[str, Any]) -> float | None:
        key = str(template["snapshotId"])
        if key not in candidate_totals:
            if not template["sourcePm"] or not suggested_pm:
                candidate_totals[key] = None
            else:
                _, total, _ = _scale_materials(template["sourceItems"], suggested_pm / template["sourcePm"])
                candidate_totals[key] = total
        return candidate_totals[key]

    def candidate_rank(template: dict[str, Any]) -> tuple[Any, ...]:
        profile = template["profile"]
        total = expected_total(template)
        over_pagu = bool(suggested_pagu_total is not None and total is not None and total > suggested_pagu_total)
        same_fruit = bool(last_fruit and "|".join(value.casefold() for value in template["fruitNames"]) == last_fruit)
        same_protein = bool(last_protein and profile["proteinType"] == last_protein)
        return (
            1 if over_pagu else 0,
            1 if profile["recipeCount"] < 2 else 0,
            1 if not profile["hasFruit"] else 0,
            1 if same_fruit else 0,
            1 if same_protein else 0,
            -int(template.get("daysSinceLastPlanned") or 0),
            total if total is not None else float("inf"),
        )

    for offset in range(days):
        target_date = week_start + timedelta(days=offset)
        existing = existing_by_date.get(target_date)
        if existing:
            record = _day_from_existing(target_date, existing, pagu_per_pm)
            last_key = "|".join(value.casefold() for value in record["recipeNames"])
            last_fruit = "|".join(value.casefold() for value in record.get("fruitNames") or [])
            existing_profile = _template(existing)["profile"]
            last_protein = existing_profile["proteinType"]
            egg_days += int(existing_profile["isEggMenu"])
            used_menu_keys.add(last_key)
            result_days.append(record)
            continue
        candidates = [template for template in templates if template["menuKey"] and template["menuKey"] not in used_menu_keys]
        if egg_days >= 1:
            candidates = [template for template in candidates if not template["profile"]["isEggMenu"]]
        if suggested_pagu_total is not None:
            candidates = [
                template for template in candidates
                if expected_total(template) is not None
                and (weekly_budget is None or weekly_spend + float(expected_total(template) or 0) <= weekly_budget)
            ]
        if not candidates:
            result_days.append({
                "date": target_date, "state": "NEEDS_DATA", "draft": True, "menuTitle": None,
                "recipeNames": [], "targetPm": suggested_pm, "targetPmBreakdown": suggested_pm_breakdown, "estimatedTotal": None, "estimatedPerPm": None,
                "paguPerPm": suggested_pagu, "paguTotal": suggested_pagu_total, "withinPagu": None, "fruitNames": [], "materials": [],
                "dataGaps": ["Tidak ada variasi menu historis unik yang masih bisa masuk total pagu DRAFT minggu. Hari ini tidak dibuat agar menu tidak diulang atau melebihi pagu minggu."], "sourceTemplate": None,
            })
            continue
        candidate = min(candidates, key=candidate_rank)
        candidate_total = expected_total(candidate)
        if candidate_total is not None:
            weekly_spend += candidate_total
        profile = candidate["profile"]
        reasons = [
            "Paket resep historis lengkap dipilih agar bumbu dan kebutuhan bahan tetap nyambung.",
            f"Protein {profile['proteinType'].lower()} dibandingkan dengan variasi hari lain.",
            f"Terakhir digunakan {candidate.get('daysSinceLastPlanned') or 0} hari lalu.",
        ]
        if profile["hasFruit"] and (not last_fruit or "|".join(value.casefold() for value in candidate["fruitNames"]) != last_fruit):
            reasons.append("Buah berbeda dari hari sebelumnya.")
        if suggested_pagu_total is not None:
            if candidate_total is not None and candidate_total > suggested_pagu_total:
                reasons.append("Biaya hari ini di atas batas harian, tetapi masih ditutup penghematan hari lain dalam pagu DRAFT minggu.")
            else:
                reasons.append("Estimasi menjaga sisa pagu DRAFT minggu.")
        record = _day_from_template(
            target_date, candidate, suggested_pm, suggested_pm_breakdown,
            suggested_pagu, suggested_pagu_total, reasons,
        )
        last_key = candidate["menuKey"]
        last_fruit = "|".join(value.casefold() for value in candidate["fruitNames"])
        last_protein = profile["proteinType"]
        egg_days += int(profile["isEggMenu"])
        used_menu_keys.add(candidate["menuKey"])
        result_days.append(record)

    proposed = [day for day in result_days if day["state"] == "PROPOSED_DRAFT"]
    known_totals = [day["estimatedTotal"] for day in proposed if day["estimatedTotal"] is not None]
    all_within = [day["withinPagu"] for day in proposed if day["withinPagu"] is not None]
    weekly_estimated = round(sum(known_totals), 2) if len(known_totals) == len(proposed) else None
    weekly_within = None if weekly_estimated is None or weekly_budget is None else weekly_estimated <= weekly_budget
    for record in proposed:
        record["withinWeeklyPagu"] = weekly_within
    return {
        "engine": "menu-planning-weekly-v4", "readOnly": True, "draftOnly": True, "site": site,
        "weekStart": week_start, "weekEnd": week_end, "requestedDays": days,
        "targetPm": suggested_pm, "targetPmBreakdown": suggested_pm_breakdown,
        "paguPerPm": suggested_pagu, "paguKecil": pagu_kecil, "paguBesar": pagu_besar,
        "paguTotal": suggested_pagu_total, "weeklyPaguTotal": weekly_budget, "days": result_days,
        "materialCatalog": _material_catalog(snapshots),
        "summary": {
            "existingDays": sum(day["state"] == "EXISTING" for day in result_days),
            "proposedDays": len(proposed), "needsDataDays": sum(day["state"] == "NEEDS_DATA" for day in result_days),
            "totalEstimatedSpend": weekly_estimated,
            "weeklyPaguTotal": weekly_budget,
            "weeklyVariance": None if weekly_estimated is None or weekly_budget is None else round(weekly_budget - weekly_estimated, 2),
            "withinWeeklyPagu": weekly_within,
            "allProposedWithinPagu": weekly_within if len(all_within) == len(proposed) and proposed and not any(day["state"] == "NEEDS_DATA" for day in result_days) and weekly_within is not None else None,
        },
        "confirmedKnowledge": knowledge,
        "rulesApplied": [
            "Hari yang sudah memiliki planning ditampilkan sebagai EXISTING dan tidak ditimpa.",
            "Hari kosong hanya memakai menu historis Calculator dengan bahan, jumlah, dan harga yang tersedia.",
            "Menu dan bahan susu/B3 kering tidak dijadikan acuan; pemilihan memakai menu masak basah.",
            "Paket resep lengkap dinilai sebagai satu kombinasi; satu menu tidak diulang dalam minggu sebelum semua variasi unik yang aman tersedia.",
            "Menu telur dibatasi maksimal satu hari dalam satu minggu; bila alternatif non-telur tidak ada, hari tersebut ditandai perlu data.",
            "Buah dari histori tidak diulang pada hari berikutnya bila alternatif buah tersedia.",
            "Jumlah tiap bahan, termasuk bumbu, diskalakan dari histori menu sumber menurut target PM.",
            "Pagu dihitung tepat dari PM kecil × pagu kecil ditambah PM besar × pagu besar; tidak dirata-ratakan untuk validasi.",
            "Total biaya semua DRAFT wajib tidak melebihi total pagu DRAFT minggu. Satu hari boleh di atas batas harian hanya bila ditutup penghematan hari lain; bila dipindahkan sendiri, batas hariannya tetap berlaku.",
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
    porsi_kecil: int | None = Query(default=None, alias="porsiKecil", ge=0),
    porsi_besar: int | None = Query(default=None, alias="porsiBesar", ge=0),
    pagu_kecil: float | None = Query(default=None, alias="paguKecil", gt=0),
    pagu_besar: float | None = Query(default=None, alias="paguBesar", gt=0),
) -> dict[str, Any]:
    """Build a read-only weekly draft from Calculator history and snapshots."""
    breakdown = {"small": porsi_kecil, "large": porsi_besar} if porsi_kecil is not None and porsi_besar is not None else None
    history_end = week_start + timedelta(days=days - 1)
    # Firestore is the Calculator's complete daily-plan archive. PostgreSQL is
    # retained as a safe fallback and also supplies confirmed knowledge.
    firestore_snapshots, firestore_error = _load_calculator_history(site, history_end)
    database_snapshots: list[dict[str, Any]] = []
    knowledge: list[dict[str, Any]] = []
    if database_ready():
        try:
            with connection() as conn:
                with conn.cursor() as cur:
                    database_snapshots = _load_snapshots(cur, site, None, history_end, limit=180)
                    knowledge = _load_confirmed_knowledge(cur, site)
        except Exception:
            # A useful Calculator-history draft must not become unavailable
            # merely because the optional snapshot cache is momentarily down.
            database_snapshots = []
            knowledge = []
    snapshots = firestore_snapshots + database_snapshots
    result = _build_week_draft(site=site, week_start=week_start, days=days, snapshots=snapshots, target_pm=target_pm, pagu_per_pm=pagu_per_pm, knowledge=knowledge, target_pm_breakdown=breakdown, pagu_kecil=pagu_kecil, pagu_besar=pagu_besar)
    result["historySource"] = "Calculator Firestore + snapshot planning" if firestore_snapshots else "Snapshot planning"
    result["historyFallback"] = bool(firestore_error)
    return result


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


def _supplier_override(category: str | None) -> str | None:
    return {
        "AYAM": "supplier_ayam", "IKAN": "supplier_ikan", "TEMPE_TAHU": "supplier_tempe_tahu",
        "TELUR": "supplier_telur", "BERAS": "supplier_beras", "BAHAN_KERING": "supplier_kering",
        "SAYUR_BUAH_BUMBU": "supplier_sayur",
    }.get(str(category or "").upper())


def _calculator_payload_from_draft(day: MenuDraftTransferDayIn, porsi_kecil: int, porsi_besar: int) -> dict[str, Any]:
    shopping_list: list[dict[str, Any]] = []
    total = 0.0
    for material in day.materials:
        quantity = _round_up_quantity(float(material.quantity), material.unit)
        line_total = quantity * float(material.planningPrice)
        total += line_total
        shopping_list.append({
            "item": material.itemName.strip(), "jumlah": quantity, "satuan": material.unit.strip(),
            "harga_satuan": float(material.planningPrice), "category_code": material.categoryCode,
            "supplierOverride": _supplier_override(material.categoryCode), "source": "menu_advisor_draft",
        })
    return {
        "date": day.date.isoformat(), "planName": day.planName.strip(),
        "porsiKecil": porsi_kecil, "porsiBesar": porsi_besar,
        "recipes": [{"name": value.strip(), "source": "menu_advisor_wet_history"} for value in day.recipeNames if value.strip()],
        "shoppingListJSON": {"shoppingList": shopping_list, "grand_total_num": round(total, 2)},
        "menuAdvisorDraft": True,
    }


@router.post("/transfer-to-calculator")
def transfer_weekly_draft_to_calculator(payload: MenuDraftTransferIn) -> dict[str, Any]:
    """Commit explicitly confirmed, within-pagu menu drafts as new Calculator plans.

    Existing plans are never overwritten.  This is intentionally the only
    write endpoint in the advisor, and it is guarded by an explicit UI
    confirmation plus server-side completeness and pagu checks.
    """
    if payload.porsiKecil + payload.porsiBesar <= 0:
        raise HTTPException(422, "PM kecil dan PM besar tidak boleh sama-sama nol")
    if len({item.date for item in payload.plans}) != len(payload.plans):
        raise HTTPException(422, "tanggal draft tidak boleh ganda")
    pagu_total = _pagu_total(payload.porsiKecil, payload.porsiBesar, payload.paguKecil, payload.paguBesar)
    assert pagu_total is not None
    calculator_plans = [_calculator_payload_from_draft(day, payload.porsiKecil, payload.porsiBesar) for day in payload.plans]
    combined_total = 0.0
    for plan in calculator_plans:
        total = float((plan.get("shoppingListJSON") or {}).get("grand_total_num") or 0)
        combined_total += total
    weekly_ceiling = pagu_total * len(calculator_plans)
    if combined_total > weekly_ceiling:
        raise HTTPException(422, "total draft terpilih masih melebihi pagu gabungan untuk jumlah hari yang dipindahkan")

    if not database_ready():
        raise HTTPException(503, "database unavailable")
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select distribution_date from planning_snapshots
                    where upper(site)=upper(%s) and status='ACTIVE' and distribution_date = any(%s)
                    """,
                    (payload.site, [day.date for day in payload.plans]),
                )
                occupied = [row["distribution_date"].isoformat() for row in cur.fetchall()]
    except Exception as exc:
        raise HTTPException(503, "gagal memeriksa planning yang sudah ada") from exc
    if occupied:
        raise HTTPException(409, {"message": "hari ini sudah memiliki planning; transfer dihentikan agar tidak menimpa", "dates": occupied})

    # Reuse the Calculator's audited import path. Preview first so an
    # independently-created Firestore plan can never be silently added beside
    # this draft after the weekly preview was shown.
    from backend.calculator_data_api import CalculatorImportIn, CalculatorImportItem, preview_or_commit_calculator_data

    import_request = CalculatorImportIn(
        site=payload.site, data_type="DAILY_PLANS", source_ref="menu-advisor-weekly-draft",
        actor="menu_advisor", items=[CalculatorImportItem(client_key=plan["date"], payload=plan) for plan in calculator_plans], commit=False,
    )
    preview = preview_or_commit_calculator_data(import_request)
    blocked = [item for item in preview.get("items", []) if item.get("status") != "NEW"]
    if blocked:
        raise HTTPException(409, {"message": "Kalkulator sudah memiliki planning pada salah satu tanggal; transfer dihentikan", "items": blocked})
    return preview_or_commit_calculator_data(import_request.model_copy(update={"commit": True}))
