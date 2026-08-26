from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import date, datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from google.api_core.exceptions import AlreadyExists
from pydantic import BaseModel, Field

from backend.db import connection, database_ready
from backend.google_services import SITE_TARGETS, firestore_client
from backend.stock_opname_parser import canonical_unit, normalize_name

# This router is mounted inside ``operational_router``, whose prefix is already
# ``/v1``. Keeping another /v1 here exposes the endpoints as /v1/v1/... and
# makes the frontend's POST requests fall through to the GET-only SPA route.
router = APIRouter(tags=["calculator-data-control"])

DATA_TYPES = {"PRICES", "GRAMASI", "RECIPES", "BUMBU", "DAILY_PLANS"}


class PlanPreviewItem(BaseModel):
    client_key: str = Field(min_length=1)
    date: str
    plan_name: str = ""
    item_hash: str = Field(min_length=8)
    menu_count: int = Field(default=0, ge=0)


class PlanPreviewIn(BaseModel):
    site: Literal["MAJA", "CEMPLANG"]
    source_ref: str = Field(min_length=1)
    items: list[PlanPreviewItem]


class CalculatorImportItem(BaseModel):
    client_key: str = Field(min_length=1)
    payload: dict[str, Any]


class CalculatorImportIn(BaseModel):
    site: Literal["MAJA", "CEMPLANG"]
    data_type: Literal["PRICES", "GRAMASI", "RECIPES", "BUMBU", "DAILY_PLANS"]
    source_ref: str = Field(min_length=1)
    items: list[CalculatorImportItem]
    actor: str = "operator"
    commit: bool = False


class SharedMasterSyncIn(BaseModel):
    source_site: Literal["MAJA", "CEMPLANG"]
    data_type: Literal["PRICES", "GRAMASI", "RECIPES", "BUMBU"]
    operation: Literal["UPSERT", "REPLACE", "DELETE"]
    record_key: str | None = None
    payload: Any = None
    actor: str = "calculator"


def _require_services() -> None:
    if not database_ready():
        raise HTTPException(503, "database unavailable")


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return str(value)


def _firestore_value(value: Any) -> Any:
    """Restore Firestore timestamp exports without changing other payload fields."""
    if isinstance(value, dict):
        keys = set(value)
        if "seconds" in value and keys.issubset({"seconds", "nanoseconds"}):
            seconds = float(value.get("seconds") or 0)
            seconds += float(value.get("nanoseconds") or 0) / 1_000_000_000
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        return {str(k): _firestore_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_firestore_value(v) for v in value]
    return value


def _restore_iso_timestamps(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    for key in ("createdAt", "updatedAt"):
        value = result.get(key)
        if not isinstance(value, str):
            continue
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            continue
        result[key] = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return result


def _stable_hash(payload: Any) -> str:
    raw = json.dumps(_json_safe(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _slug(value: str, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", normalize_name(value)).strip("_")
    return (slug or fallback)[:120]


def _data_root(site: str):
    target = SITE_TARGETS[site]
    client = firestore_client(target["database_id"])
    root = client.collection("artifacts").document(target["site_id"]).collection("public").document("data")
    return client, target, root


def _strip_compare_noise(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(k): _strip_compare_noise(v)
            for k, v in value.items()
            if k not in {"createdAt", "updatedAt", "id"}
        }
    if isinstance(value, list):
        return [_strip_compare_noise(v) for v in value]
    return _json_safe(value)


def _same_content(left: Any, right: Any) -> bool:
    return _stable_hash(_strip_compare_noise(left)) == _stable_hash(_strip_compare_noise(right))


def _record_key(data_type: str, payload: dict[str, Any], client_key: str) -> str:
    if data_type == "PRICES":
        return normalize_name(str(payload.get("name") or "")) or client_key
    if data_type == "GRAMASI":
        return str(payload.get("id") or _slug(str(payload.get("name") or ""), client_key))
    if data_type == "RECIPES":
        return str(payload.get("id") or _slug(str(payload.get("name") or ""), f"recipe_{client_key}"))
    if data_type == "BUMBU":
        return normalize_name(str(payload.get("name") or "")) or client_key
    return str(payload.get("date") or client_key)


def _price_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "price": payload.get("price") or 0,
        "unit": payload.get("unit") or "kg",
        "waste": payload.get("waste") or 0,
        "grams_per_unit": payload.get("grams_per_unit") or 0,
        "nutrition_per_100g": payload.get("nutrition_per_100g"),
    }


def _load_master_state(site: str, data_type: str) -> tuple[Any, dict[str, Any]]:
    _, _, root = _data_root(site)
    if data_type == "PRICES":
        snap = root.collection("masterData").document("priceList").get()
        return root, (snap.to_dict() or {}) if snap.exists else {}
    if data_type == "BUMBU":
        snap = root.collection("bumbuList").document("default").get()
        data = (snap.to_dict() or {}) if snap.exists else {}
        rules = data.get("rules") or {}
        names = list(dict.fromkeys([*(data.get("list") or []), *rules.keys()]))
        return root, {
            normalize_name(str(name)): {"name": str(name), **(rules.get(name) or {})}
            for name in names if str(name).strip()
        }
    collection_name = "customGramasi" if data_type == "GRAMASI" else "recipes"
    state: dict[str, Any] = {}
    for snap in root.collection(collection_name).stream():
        state[snap.id] = snap.to_dict() or {}
    return root, state


def _preview_master(site: str, data_type: str, items: list[CalculatorImportItem]) -> list[dict[str, Any]]:
    _, state = _load_master_state(site, data_type)
    seen: Counter[str] = Counter(_record_key(data_type, item.payload, item.client_key) for item in items)
    rows: list[dict[str, Any]] = []
    for item in items:
        payload = item.payload
        key = _record_key(data_type, payload, item.client_key)
        name = str(payload.get("name") or key).strip()
        invalid = not name or (data_type == "RECIPES" and not isinstance(payload.get("ingredients"), list))
        previous = state.get(key)
        compare_payload = _price_payload(payload) if data_type == "PRICES" else payload
        if invalid:
            status = "INVALID"
        elif seen[key] > 1:
            status = "DUPLICATE_KEY_IN_FILE"
        elif previous is None:
            status = "NEW"
        elif _same_content(previous, compare_payload):
            status = "UNCHANGED"
        else:
            status = "CHANGED"
        rows.append({
            "clientKey": item.client_key,
            "recordKey": key,
            "name": name,
            "status": status,
            "selectable": status in {"NEW", "CHANGED"},
            "defaultSelected": status == "NEW",
            "sourceHash": _stable_hash(payload),
        })
    return rows


def _existing_plan_dates(site: str) -> dict[str, list[dict[str, Any]]]:
    _, _, root = _data_root(site)
    dates: dict[str, list[dict[str, Any]]] = {}
    for snap in root.collection("dailyPlans").stream():
        data = snap.to_dict() or {}
        plan_date = str(data.get("date") or "").strip()
        if not plan_date:
            continue
        dates.setdefault(plan_date, []).append({
            "documentId": snap.id,
            "planName": data.get("planName"),
            "itemHash": _stable_hash(_strip_compare_noise(data)),
        })
    return dates


def _plan_preview_rows(site: str, items: list[PlanPreviewItem]) -> list[dict[str, Any]]:
    existing = _existing_plan_dates(site)
    seen_in_file: set[tuple[str, str]] = set()
    rows: list[dict[str, Any]] = []
    for item in items:
        plan_date = item.date.strip()
        item_key = (plan_date, item.item_hash)
        existing_hashes = {str(plan.get("itemHash") or "") for plan in existing.get(plan_date, [])}
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", plan_date):
            status = "INVALID_DATE"
        elif item.item_hash in existing_hashes:
            status = "ALREADY_EXISTS"
        elif item_key in seen_in_file:
            status = "DUPLICATE_CONTENT_IN_FILE"
        elif plan_date in existing:
            status = "ADDITIONAL_PLAN_SAME_DATE"
        else:
            status = "NEW"
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", plan_date):
            seen_in_file.add(item_key)
        rows.append({
            "clientKey": item.client_key,
            "date": plan_date,
            "planName": item.plan_name,
            "menuCount": item.menu_count,
            "itemHash": item.item_hash,
            "status": status,
            "selectable": status in {"NEW", "ADDITIONAL_PLAN_SAME_DATE"},
            "defaultSelected": status in {"NEW", "ADDITIONAL_PLAN_SAME_DATE"},
            "existingPlans": existing.get(plan_date, []),
        })
    return rows


def _audit_begin(
    *, site: str, data_type: str, record_key: str, record_date: str | None,
    source_ref: str, source_hash: str, target_path: str, previous: Any,
    imported: Any, actor: str,
) -> int:
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into calculator_import_events(
                  site,data_type,record_key,record_date,source_ref,source_hash,target_path,
                  outcome,previous_payload,imported_payload,created_by
                ) values (%s,%s,%s,%s,%s,%s,%s,'PENDING',%s::jsonb,%s::jsonb,%s) returning id
                """,
                (
                    site, data_type, record_key, record_date or None, source_ref, source_hash, target_path,
                    json.dumps(_json_safe(previous), ensure_ascii=False) if previous is not None else None,
                    json.dumps(_json_safe(imported), ensure_ascii=False), actor,
                ),
            )
            event_id = cur.fetchone()["id"]
        conn.commit()
    return int(event_id)


def _audit_finish(event_id: int, outcome: str, error: str | None = None) -> None:
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update calculator_import_events set outcome=%s,error_message=%s,completed_at=now() where id=%s",
                (outcome, error, event_id),
            )
        conn.commit()


def _catalog_replace(site: str, source_type: str, document_key: str, rows: list[dict[str, Any]]) -> None:
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update calculator_master_catalog set active=false,updated_at=now() where site=%s and source_type=%s and source_document_key=%s",
                (site, source_type, document_key),
            )
            for row in rows:
                name = str(row.get("name") or "").strip()
                if not name:
                    continue
                record_key = str(row.get("recordKey") or _stable_hash(row)[:24])
                payload = row.get("payload") or {}
                cur.execute(
                    """
                    insert into calculator_master_catalog(
                      site,source_type,source_document_key,record_key,canonical_name,normalized_name,
                      category_code,unit,source_hash,source_payload,active
                    ) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,true)
                    on conflict (site,source_type,record_key) do update set
                      source_document_key=excluded.source_document_key,canonical_name=excluded.canonical_name,
                      normalized_name=excluded.normalized_name,category_code=excluded.category_code,
                      unit=excluded.unit,source_hash=excluded.source_hash,source_payload=excluded.source_payload,
                      active=true,updated_at=now()
                    """,
                    (
                        site, source_type, document_key, record_key, name, normalize_name(name),
                        row.get("categoryCode"), canonical_unit(row.get("unit")) or None,
                        _stable_hash(payload), json.dumps(_json_safe(payload), ensure_ascii=False),
                    ),
                )
        conn.commit()


def _catalog_for_master(site: str, data_type: str, key: str, payload: dict[str, Any]) -> None:
    name = str(payload.get("name") or key).strip()
    if data_type == "PRICES":
        _catalog_replace(site, "PRICE", key, [{
            "recordKey": key, "name": name, "unit": payload.get("unit"), "payload": payload,
        }])
    elif data_type == "GRAMASI":
        _catalog_replace(site, "GRAMASI", key, [{
            "recordKey": key, "name": name, "payload": payload,
        }])
    elif data_type == "RECIPES":
        _catalog_replace(site, "RECIPE", key, [{
            "recordKey": key, "name": name, "payload": payload,
        }])
        ingredients = []
        for idx, ingredient in enumerate(payload.get("ingredients") or []):
            if not isinstance(ingredient, dict) or not str(ingredient.get("name") or "").strip():
                continue
            ingredients.append({
                "recordKey": f"{key}:{idx}",
                "name": ingredient.get("name"),
                "unit": "gr" if ingredient.get("quantity_gr") is not None else None,
                "payload": ingredient,
            })
        _catalog_replace(site, "RECIPE_INGREDIENT", key, ingredients)
    elif data_type == "BUMBU":
        _catalog_replace(site, "BUMBU", key, [{
            "recordKey": key, "name": name, "unit": "gr", "payload": payload,
        }])


def _deactivate_catalog(site: str, source_type: str, record_key: str | None = None) -> None:
    with connection() as conn:
        with conn.cursor() as cur:
            sql = "update calculator_master_catalog set active=false,updated_at=now() where site=%s and source_type=%s"
            params: list[Any] = [site, source_type]
            if record_key:
                sql += " and record_key=%s"
                params.append(record_key)
            cur.execute(sql, params)
        conn.commit()


def _shared_master_target(root: Any, data_type: str, record_key: str | None):
    if data_type == "PRICES":
        return root.collection("masterData").document("priceList")
    if data_type == "GRAMASI":
        return root.collection("customGramasi").document(str(record_key or ""))
    if data_type == "RECIPES":
        return root.collection("recipes").document(str(record_key or ""))
    return root.collection("bumbuList").document("default")


@router.post("/calculator-data/shared-master-sync")
def sync_shared_calculator_master(payload: SharedMasterSyncIn, request: Request) -> dict[str, Any]:
    """Mirror calculator master writes to Maja and Cemplang; never touch daily plans.

    Calculator master data lives in Firestore.  The Postgres catalog and audit
    trail are useful indexes, but they must not turn a successful price save in
    the calculator into a visible failure when the database is briefly
    unavailable.  In particular, the small save icon in the planning table
    must keep working independently of the operational/audit database.
    """
    role = str(getattr(request.state, "sppg_role", "") or "").upper()
    if role and role not in {"OWNER", payload.source_site}:
        raise HTTPException(403, "akun hanya boleh menyinkronkan master dari kalkulator sendiri")
    if payload.data_type in {"GRAMASI", "RECIPES"} and not str(payload.record_key or "").strip():
        raise HTTPException(400, "record_key wajib untuk gramasi/resep")
    if payload.data_type == "PRICES" and payload.operation == "UPSERT" and not str(payload.record_key or "").strip():
        raise HTTPException(400, "record_key wajib untuk update satu harga")
    if payload.data_type == "BUMBU" and payload.operation != "REPLACE":
        raise HTTPException(400, "bumbu wajib memakai REPLACE agar daftar kedua kalkulator identik")
    if payload.operation == "DELETE" and payload.data_type in {"PRICES", "BUMBU"}:
        raise HTTPException(400, "harga/bumbu memakai REPLACE agar daftar kedua kalkulator tetap identik")
    if payload.operation != "DELETE" and not isinstance(payload.payload, dict):
        raise HTTPException(400, "payload master wajib berupa object")

    source_ref = f"calculator-live:{payload.source_site}:{payload.data_type.lower()}"
    writes: list[dict[str, Any]] = []
    audit_warnings: list[dict[str, str]] = []
    source_type = {"PRICES": "PRICE", "GRAMASI": "GRAMASI", "RECIPES": "RECIPE", "BUMBU": "BUMBU"}[payload.data_type]
    for target_site in ("MAJA", "CEMPLANG"):
        record_key = str(payload.record_key or "all")
        imported = payload.payload if payload.operation != "DELETE" else {"deleted": True, "recordKey": record_key}
        event_id: int | None = None
        try:
            # Firestore is the source of truth for calculator masters.  Do this
            # first and do not require PostgreSQL to be healthy just to save one
            # planned-item price.
            _, _, root = _data_root(target_site)
            target = _shared_master_target(root, payload.data_type, payload.record_key)
            snap = target.get()
            previous = snap.to_dict() if snap.exists else None

            if database_ready():
                try:
                    event_id = _audit_begin(
                        site=target_site, data_type=payload.data_type, record_key=record_key, record_date=None,
                        source_ref=source_ref, source_hash=_stable_hash(imported), target_path=target.path,
                        previous=previous, imported=imported, actor=payload.actor,
                    )
                except Exception as exc:  # Audit must never block calculator masters.
                    audit_warnings.append({"site": target_site, "stage": "audit_begin", "message": str(exc)[:300]})
            else:
                audit_warnings.append({"site": target_site, "stage": "audit_begin", "message": "database audit sedang tidak tersedia"})

            if payload.operation == "DELETE":
                target.delete()
            elif payload.data_type == "PRICES":
                incoming = _firestore_value(payload.payload)
                if payload.operation == "UPSERT":
                    target.set({record_key: incoming}, merge=True)
                else:
                    target.set(incoming)
            elif payload.data_type == "BUMBU":
                target.set(_firestore_value(payload.payload))
            else:
                incoming = _restore_iso_timestamps(payload.payload)
                if payload.data_type == "GRAMASI":
                    incoming["id"] = record_key
                elif payload.data_type == "RECIPES":
                    incoming.pop("id", None)
                target.set(_firestore_value(incoming), merge=True)

            # Keep the searchable Postgres catalog in sync when it is available,
            # but a catalog/audit outage must not roll back or misreport the
            # Firestore save above.
            if database_ready():
                try:
                    if payload.operation == "DELETE":
                        _deactivate_catalog(target_site, source_type, record_key)
                        if payload.data_type == "RECIPES":
                            with connection() as conn:
                                with conn.cursor() as cur:
                                    cur.execute(
                                        "update calculator_master_catalog set active=false,updated_at=now() where site=%s and source_type='RECIPE_INGREDIENT' and source_document_key=%s",
                                        (target_site, record_key),
                                    )
                                conn.commit()
                    elif payload.data_type == "PRICES":
                        if payload.operation == "UPSERT":
                            _catalog_for_master(target_site, "PRICES", record_key, {"name": record_key, **payload.payload})
                        else:
                            _deactivate_catalog(target_site, "PRICE")
                            for name, value in payload.payload.items():
                                if isinstance(value, dict):
                                    _catalog_for_master(target_site, "PRICES", normalize_name(str(name)), {"name": str(name), **value})
                    elif payload.data_type == "BUMBU":
                        _deactivate_catalog(target_site, "BUMBU")
                        rules = payload.payload.get("rules") or {}
                        for name in payload.payload.get("list") or []:
                            normalized = normalize_name(str(name))
                            if normalized:
                                _catalog_for_master(target_site, "BUMBU", normalized, {"name": str(name), **(rules.get(name) or {})})
                    else:
                        _catalog_for_master(target_site, payload.data_type, record_key, {**payload.payload, "id": record_key})
                except Exception as exc:
                    audit_warnings.append({"site": target_site, "stage": "catalog", "message": str(exc)[:300]})

            if event_id is not None:
                try:
                    _audit_finish(event_id, "COMMITTED")
                except Exception as exc:
                    audit_warnings.append({"site": target_site, "stage": "audit_finish", "message": str(exc)[:300]})
            writes.append({"site": target_site, "path": target.path, "eventId": event_id})
        except Exception as exc:
            if event_id is not None:
                try:
                    _audit_finish(event_id, "FAILED", str(exc)[:1000])
                except Exception:
                    pass
            raise HTTPException(502, f"sinkronisasi master {target_site} gagal: {exc}") from exc
    return {
        "committed": True,
        "sourceSite": payload.source_site,
        "dataType": payload.data_type,
        "operation": payload.operation,
        "targetSites": ["MAJA", "CEMPLANG"],
        "writes": writes,
        "dailyPlansChanged": False,
        "auditWarnings": audit_warnings,
    }


def _catalog_for_plan(site: str, document_id: str, payload: dict[str, Any]) -> None:
    rows = []
    shopping = ((payload.get("shoppingListJSON") or {}).get("shoppingList") or [])
    supplier_categories = {
        "supplier_ayam": "AYAM", "supplier_ikan": "IKAN", "supplier_tempe_tahu": "TEMPE_TAHU",
        "supplier_telur": "TELUR", "supplier_beras": "BERAS", "supplier_kering": "BAHAN_KERING",
        "supplier_sayur": "SAYUR_BUAH_BUMBU",
    }
    for idx, item in enumerate(shopping):
        if not isinstance(item, dict):
            continue
        name = str(item.get("item") or item.get("source_ingredient") or item.get("name") or "").strip()
        if not name:
            continue
        rows.append({
            "recordKey": f"{document_id}:{idx}",
            "name": name,
            "categoryCode": supplier_categories.get(str(item.get("supplierOverride") or "")),
            "unit": item.get("satuan"),
            "payload": item,
        })
    _catalog_replace(site, "PLAN_ITEM", document_id, rows)


@router.post("/calculator-data/plan-preview")
def preview_daily_plan_import(payload: PlanPreviewIn) -> dict[str, Any]:
    _require_services()
    if len(payload.items) > 500:
        raise HTTPException(413, "maximum 500 plan summaries per preview")
    rows = _plan_preview_rows(payload.site, payload.items)
    counts = Counter(row["status"] for row in rows)
    return {
        "committed": False,
        "site": payload.site,
        "sourceRef": payload.source_ref,
        "items": rows,
        "counts": dict(counts),
        "rule": "Existing plan documents are never overwritten. Distinct plans may share one date; identical content is skipped.",
    }


def _commit_master(payload: CalculatorImportIn) -> dict[str, Any]:
    root, current = _load_master_state(payload.site, payload.data_type)
    preview_rows = _preview_master(payload.site, payload.data_type, payload.items)
    committed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for item, preview in zip(payload.items, preview_rows):
        if preview["status"] not in {"NEW", "CHANGED"}:
            skipped.append(preview)
            continue
        key = preview["recordKey"]
        incoming = dict(item.payload)
        if payload.data_type == "PRICES":
            previous = current.get(key)
            target = root.collection("masterData").document("priceList")
            firestore_payload = {key: _firestore_value(_price_payload(incoming))}
        elif payload.data_type == "GRAMASI":
            previous = current.get(key)
            target = root.collection("customGramasi").document(key)
            incoming["id"] = key
            firestore_payload = _firestore_value(incoming)
        elif payload.data_type == "BUMBU":
            previous = current.get(key)
            target = root.collection("bumbuList").document("default")
            incoming["name"] = str(incoming.get("name") or key).strip().lower()
            current[key] = incoming
            names = sorted({str(value.get("name") or state_key).strip().lower() for state_key, value in current.items()})
            rules = {
                str(value.get("name") or state_key).strip().lower(): {
                    "kecil": value.get("kecil") or 0,
                    "besar": value.get("besar") or 0,
                }
                for state_key, value in current.items()
                if value.get("kecil") is not None or value.get("besar") is not None
            }
            firestore_payload = _firestore_value({"list": names, "rules": rules})
        else:
            previous = current.get(key)
            target = root.collection("recipes").document(key)
            incoming.pop("id", None)
            firestore_payload = _firestore_value(incoming)
        event_id = _audit_begin(
            site=payload.site, data_type=payload.data_type, record_key=key, record_date=None,
            source_ref=payload.source_ref, source_hash=preview["sourceHash"], target_path=target.path,
            previous=previous, imported=item.payload, actor=payload.actor,
        )
        try:
            target.set(firestore_payload, merge=True)
            _catalog_for_master(payload.site, payload.data_type, key, item.payload)
            _audit_finish(event_id, "COMMITTED")
            committed.append({**preview, "eventId": event_id, "targetPath": target.path})
        except Exception as exc:
            _audit_finish(event_id, "FAILED", str(exc)[:1000])
            raise HTTPException(502, f"Firestore write failed for {key}: {exc}") from exc
    return {
        "committed": True,
        "site": payload.site,
        "dataType": payload.data_type,
        "committedCount": len(committed),
        "skippedCount": len(skipped),
        "items": committed,
        "skipped": skipped,
    }


def _commit_plans(payload: CalculatorImportIn) -> dict[str, Any]:
    _, _, root = _data_root(payload.site)
    plans = root.collection("dailyPlans")
    committed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for item in payload.items:
        incoming = dict(item.payload)
        plan_date = str(incoming.get("date") or "").strip()
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", plan_date):
            skipped.append({"clientKey": item.client_key, "date": plan_date, "status": "INVALID_DATE"})
            continue
        existing = list(plans.where("date", "==", plan_date).limit(50).stream())
        source_hash = _stable_hash(_strip_compare_noise(incoming))
        identical = next(
            (
                snap for snap in existing
                if _same_content(snap.to_dict() or {}, incoming)
            ),
            None,
        )
        if identical is not None:
            skipped.append({
                "clientKey": item.client_key,
                "date": plan_date,
                "status": "ALREADY_EXISTS",
                "existingPlans": [{
                    "documentId": identical.id,
                    "planName": (identical.to_dict() or {}).get("planName"),
                }],
            })
            continue
        doc_id = f"imported_plan_{plan_date}_{source_hash[:12]}"
        target = plans.document(doc_id)
        incoming.pop("id", None)
        event_id = _audit_begin(
            site=payload.site, data_type="DAILY_PLANS", record_key=doc_id, record_date=plan_date,
            source_ref=payload.source_ref, source_hash=source_hash, target_path=target.path,
            previous=None, imported=item.payload, actor=payload.actor,
        )
        try:
            target.create(_firestore_value(incoming))
            _catalog_for_plan(payload.site, doc_id, item.payload)
            _audit_finish(event_id, "COMMITTED")
            committed.append({
                "clientKey": item.client_key, "date": plan_date, "planName": incoming.get("planName"),
                "status": "COMMITTED_ADDITIONAL" if existing else "COMMITTED_NEW",
                "documentId": doc_id,
                "eventId": event_id,
            })
        except AlreadyExists:
            _audit_finish(event_id, "SKIPPED_EXISTING")
            skipped.append({"clientKey": item.client_key, "date": plan_date, "status": "ALREADY_EXISTS"})
        except Exception as exc:
            _audit_finish(event_id, "FAILED", str(exc)[:1000])
            raise HTTPException(502, f"Firestore write failed for plan {plan_date}: {exc}") from exc
    return {
        "committed": True,
        "site": payload.site,
        "dataType": "DAILY_PLANS",
        "committedCount": len(committed),
        "skippedCount": len(skipped),
        "items": committed,
        "skipped": skipped,
        "rule": "No existing plan document was overwritten. Distinct plans on the same date were stored separately.",
    }


@router.post("/calculator-data/import")
def preview_or_commit_calculator_data(payload: CalculatorImportIn) -> dict[str, Any]:
    _require_services()
    if not payload.items:
        raise HTTPException(400, "items must not be empty")
    if len(payload.items) > 500:
        raise HTTPException(413, "maximum 500 items per request; split larger files into batches")
    if payload.data_type not in DATA_TYPES:
        raise HTTPException(400, "unsupported data_type")

    if not payload.commit:
        if payload.data_type == "DAILY_PLANS":
            summaries = [PlanPreviewItem(
                client_key=item.client_key,
                date=str(item.payload.get("date") or ""),
                plan_name=str(item.payload.get("planName") or item.payload.get("name") or ""),
                item_hash=_stable_hash(item.payload),
                menu_count=len(item.payload.get("recipes") or []),
            ) for item in payload.items]
            rows = _plan_preview_rows(payload.site, summaries)
        else:
            previews = {
                target_site: _preview_master(target_site, payload.data_type, payload.items)
                for target_site in ("MAJA", "CEMPLANG")
            }
            by_site = {
                target_site: {row["clientKey"]: row for row in target_rows}
                for target_site, target_rows in previews.items()
            }
            rows = []
            for item in payload.items:
                site_rows = [by_site[target_site][item.client_key] for target_site in ("MAJA", "CEMPLANG")]
                statuses = [row["status"] for row in site_rows]
                if "INVALID" in statuses:
                    status = "INVALID"
                elif "DUPLICATE_KEY_IN_FILE" in statuses:
                    status = "DUPLICATE_KEY_IN_FILE"
                elif "CHANGED" in statuses:
                    status = "CHANGED"
                elif all(value == "UNCHANGED" for value in statuses):
                    status = "UNCHANGED"
                else:
                    status = "NEW"
                rows.append({
                    **site_rows[0],
                    "status": status,
                    "siteStatuses": {"MAJA": statuses[0], "CEMPLANG": statuses[1]},
                    "selectable": status in {"NEW", "CHANGED"},
                    "defaultSelected": status == "NEW",
                })
        return {
            "committed": False,
            "site": payload.site if payload.data_type == "DAILY_PLANS" else "SHARED",
            "sourceSite": payload.site,
            "targetSites": [payload.site] if payload.data_type == "DAILY_PLANS" else ["MAJA", "CEMPLANG"],
            "dataType": payload.data_type,
            "sourceRef": payload.source_ref,
            "counts": dict(Counter(row["status"] for row in rows)),
            "items": rows,
        }

    if payload.data_type == "DAILY_PLANS":
        return _commit_plans(payload)
    target_results = [
        _commit_master(payload.model_copy(update={"site": target_site}))
        for target_site in ("MAJA", "CEMPLANG")
    ]
    return {
        "committed": True,
        "site": "SHARED",
        "sourceSite": payload.site,
        "targetSites": ["MAJA", "CEMPLANG"],
        "dataType": payload.data_type,
        "committedCount": sum(result["committedCount"] for result in target_results),
        "skippedCount": sum(result["skippedCount"] for result in target_results),
        "items": [
            {**item, "site": result["site"]}
            for result in target_results for item in result["items"]
        ],
        "skipped": [
            {**item, "site": result["site"]}
            for result in target_results for item in result["skipped"]
        ],
        "dailyPlansChanged": False,
    }
