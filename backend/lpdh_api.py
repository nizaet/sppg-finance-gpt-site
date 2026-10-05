from __future__ import annotations

import base64
import json
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from backend.db import connection, database_ready
from backend.lpdh_logic import (
    compute_preview,
    encode_bytes,
    make_master_template,
    parse_master_workbook,
    populate_workbook,
    workbook_reference_rows,
)

router = APIRouter(prefix="/v1/lpdh", tags=["lpdh"])


class MasterStateIn(BaseModel):
    site: str
    data: dict[str, Any] = Field(default_factory=dict)


class DailyStateIn(BaseModel):
    site: str
    service_date: date
    data: dict[str, Any] = Field(default_factory=dict)
    status: str = "DRAFT"


class EffectiveDaysIn(BaseModel):
    site: str
    month: str
    dates: list[date] = Field(default_factory=list)
    notes: dict[str, str] = Field(default_factory=dict)


class MasterImportIn(BaseModel):
    site: str
    filename: str = "master.xlsx"
    content_base64: str


class CalculatorFinalIn(BaseModel):
    site: str
    service_date: date
    source_plan_id: str | None = None
    plan_name: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class GenerateIn(BaseModel):
    site: str
    service_date: date


def _require_db() -> None:
    if not database_ready():
        raise HTTPException(503, "DATABASE_URL tidak tersedia")


def _role(request: Request) -> str:
    return str(getattr(request.state, "sppg_role", "") or "").upper().strip()


def _site(request: Request, requested: str) -> str:
    site = str(requested or "").upper().strip()
    if site not in {"MAJA", "CEMPLANG"}:
        raise HTTPException(400, "site harus MAJA atau CEMPLANG")
    role = _role(request)
    if role not in {"OWNER", site}:
        raise HTTPException(403, f"akun {role or '-'} tidak dapat mengakses LPDH {site}")
    return site


def _month_bounds(month: str) -> tuple[date, date]:
    try:
        year_text, month_text = month.split("-", 1)
        year = int(year_text)
        mon = int(month_text)
        start = date(year, mon, 1)
        if mon == 12:
            end = date(year + 1, 1, 1)
        else:
            end = date(year, mon + 1, 1)
        return start, end
    except Exception as exc:
        raise HTTPException(400, "month harus format YYYY-MM") from exc


def _load_master(site: str) -> dict[str, Any]:
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("select data,revision,updated_by,updated_at from lpdh_site_state where site=%s", (site,))
            row = cur.fetchone()
    if not row:
        return {"data": {}, "revision": 0, "updatedBy": None, "updatedAt": None}
    return {
        "data": row["data"] or {},
        "revision": row["revision"],
        "updatedBy": row["updated_by"],
        "updatedAt": row["updated_at"],
    }


def _load_daily(site: str, service_date: date) -> dict[str, Any]:
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select data,status,revision,updated_by,updated_at from lpdh_daily_state where site=%s and service_date=%s",
                (site, service_date),
            )
            row = cur.fetchone()
    if not row:
        return {"data": {}, "status": "DRAFT", "revision": 0, "updatedBy": None, "updatedAt": None}
    return {
        "data": row["data"] or {},
        "status": row["status"],
        "revision": row["revision"],
        "updatedBy": row["updated_by"],
        "updatedAt": row["updated_at"],
    }


def _load_final_plan(site: str, service_date: date) -> dict[str, Any] | None:
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """select source_plan_id,plan_name,payload,revision,finalized_by,finalized_at
                   from lpdh_final_plans where site=%s and service_date=%s""",
                (site, service_date),
            )
            row = cur.fetchone()
    if not row:
        return None
    return {
        "sourcePlanId": row["source_plan_id"],
        "planName": row["plan_name"],
        "payload": row["payload"] or {},
        "revision": row["revision"],
        "finalizedBy": row["finalized_by"],
        "finalizedAt": row["finalized_at"],
    }


def _effective(site: str, service_date: date) -> bool:
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select is_effective from lpdh_effective_days where site=%s and service_date=%s",
                (site, service_date),
            )
            row = cur.fetchone()
    return bool(row and row["is_effective"])


@router.get("/masters")
def get_masters(request: Request, site: str = Query()) -> dict[str, Any]:
    _require_db()
    target = _site(request, site)
    result = _load_master(target)
    return {"site": target, **result}


@router.put("/masters")
def save_masters(payload: MasterStateIn, request: Request) -> dict[str, Any]:
    _require_db()
    site = _site(request, payload.site)
    actor = _role(request)
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """insert into lpdh_site_state(site,data,revision,updated_by,updated_at)
                   values (%s,%s::jsonb,1,%s,now())
                   on conflict (site) do update
                   set data=excluded.data,
                       revision=lpdh_site_state.revision+1,
                       updated_by=excluded.updated_by,
                       updated_at=now()
                   returning revision,updated_at""",
                (site, json.dumps(payload.data, ensure_ascii=False), actor),
            )
            row = cur.fetchone()
        conn.commit()
    return {"site": site, "saved": True, "revision": row["revision"], "updatedAt": row["updated_at"]}


@router.get("/daily")
def get_daily(request: Request, site: str = Query(), service_date: date = Query(alias="date")) -> dict[str, Any]:
    _require_db()
    target = _site(request, site)
    daily = _load_daily(target, service_date)
    return {
        "site": target,
        "serviceDate": service_date,
        **daily,
        "effective": _effective(target, service_date),
        "finalPlan": _load_final_plan(target, service_date),
    }


@router.put("/daily")
def save_daily(payload: DailyStateIn, request: Request) -> dict[str, Any]:
    _require_db()
    site = _site(request, payload.site)
    status = str(payload.status or "DRAFT").upper()
    if status not in {"DRAFT", "READY", "GENERATED"}:
        raise HTTPException(400, "status daily tidak valid")
    actor = _role(request)
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """insert into lpdh_daily_state(site,service_date,data,status,revision,updated_by,updated_at)
                   values (%s,%s,%s::jsonb,%s,1,%s,now())
                   on conflict (site,service_date) do update
                   set data=excluded.data,status=excluded.status,
                       revision=lpdh_daily_state.revision+1,
                       updated_by=excluded.updated_by,updated_at=now()
                   returning revision,updated_at""",
                (site, payload.service_date, json.dumps(payload.data, ensure_ascii=False), status, actor),
            )
            row = cur.fetchone()
        conn.commit()
    return {"site": site, "serviceDate": payload.service_date, "saved": True, "status": status, "revision": row["revision"], "updatedAt": row["updated_at"]}


@router.delete("/daily")
def delete_daily(request: Request, site: str = Query(), service_date: date = Query(alias="date")) -> dict[str, Any]:
    _require_db()
    target = _site(request, site)
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("delete from lpdh_daily_state where site=%s and service_date=%s", (target, service_date))
            deleted = cur.rowcount
        conn.commit()
    return {"site": target, "serviceDate": service_date, "deleted": bool(deleted)}


@router.get("/effective-days")
def get_effective_days(request: Request, site: str = Query(), month: str = Query()) -> dict[str, Any]:
    _require_db()
    target = _site(request, site)
    start, end = _month_bounds(month)
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """select service_date,is_effective,note,updated_by,updated_at
                   from lpdh_effective_days
                   where site=%s and service_date >= %s and service_date < %s
                   order by service_date""",
                (target, start, end),
            )
            rows = cur.fetchall()
    return {
        "site": target,
        "month": month,
        "dates": [row["service_date"] for row in rows if row["is_effective"]],
        "items": rows,
    }


@router.put("/effective-days")
def save_effective_days(payload: EffectiveDaysIn, request: Request) -> dict[str, Any]:
    _require_db()
    site = _site(request, payload.site)
    actor = _role(request)
    start, end = _month_bounds(payload.month)
    chosen = sorted({item for item in payload.dates if start <= item < end})
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "delete from lpdh_effective_days where site=%s and service_date >= %s and service_date < %s",
                (site, start, end),
            )
            for item in chosen:
                cur.execute(
                    """insert into lpdh_effective_days(site,service_date,is_effective,note,updated_by,updated_at)
                       values (%s,%s,true,%s,%s,now())""",
                    (site, item, payload.notes.get(item.isoformat(), ""), actor),
                )
        conn.commit()
    return {"site": site, "month": payload.month, "saved": True, "count": len(chosen), "dates": chosen}


@router.post("/import-master")
def import_master(payload: MasterImportIn, request: Request) -> dict[str, Any]:
    _require_db()
    site = _site(request, payload.site)
    try:
        content = base64.b64decode(payload.content_base64, validate=True)
        parsed = parse_master_workbook(content)
    except Exception as exc:
        raise HTTPException(400, f"File master tidak dapat dibaca: {exc}") from exc

    existing = _load_master(site)["data"] or {}
    merged = dict(existing)
    for key in ("beneficiaries", "volunteers", "operations"):
        if parsed.get(key):
            merged[key] = parsed[key]

    actor = _role(request)
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """insert into lpdh_site_state(site,data,revision,updated_by,updated_at)
                   values (%s,%s::jsonb,1,%s,now())
                   on conflict (site) do update
                   set data=excluded.data,revision=lpdh_site_state.revision+1,
                       updated_by=excluded.updated_by,updated_at=now()
                   returning revision""",
                (site, json.dumps(merged, ensure_ascii=False), actor),
            )
            revision = cur.fetchone()["revision"]
        conn.commit()

    return {
        "site": site,
        "filename": payload.filename,
        "imported": {key: len(parsed.get(key) or []) for key in ("beneficiaries", "volunteers", "operations")},
        "revision": revision,
    }


@router.get("/master-template")
def master_template(request: Request, site: str = Query()) -> dict[str, Any]:
    _site(request, site)
    content = make_master_template()
    return {
        "filename": "Template_Import_Master_LPDH.xlsx",
        "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "contentBase64": encode_bytes(content),
    }


@router.get("/reference")
def reference(request: Request, site: str = Query()) -> dict[str, Any]:
    _site(request, site)
    return {"sheet": "Ref", "rows": workbook_reference_rows()}




@router.get("/official-template")
def official_template_status(request: Request, site: str = Query()) -> dict[str, Any]:
    _require_db()
    target = _site(request, site)
    masters = _load_master(target)["data"] or {}
    return {
        "site": target,
        "installed": bool(masters.get("_officialTemplateBase64")),
        "filename": masters.get("_officialTemplateFilename") or None,
    }


@router.put("/official-template")
def save_official_template(payload: OfficialTemplateIn, request: Request) -> dict[str, Any]:
    _require_db()
    site = _site(request, payload.site)
    try:
        raw = base64.b64decode(payload.content_base64, validate=True)
        from openpyxl import load_workbook
        import io
        workbook = load_workbook(io.BytesIO(raw), read_only=True, data_only=False)
        required = {"Identitas","A_PM","B_BahanBaku","C_Operasional","C1_Relawan","D_Insentif","E_Saldo","F_TopUp","G_CekPPK","H_RekapPPK","I_RegisterBukti","J_Pengesahan","Ref"}
        missing = sorted(required.difference(workbook.sheetnames))
        if missing:
            raise ValueError("sheet wajib tidak ada: " + ", ".join(missing))
    except Exception as exc:
        raise HTTPException(400, f"Template LPDH tidak valid: {exc}") from exc
    current = _load_master(site)["data"] or {}
    current["_officialTemplateBase64"] = payload.content_base64
    current["_officialTemplateFilename"] = payload.filename
    actor = _role(request)
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """insert into lpdh_site_state(site,data,revision,updated_by,updated_at)
                   values (%s,%s::jsonb,1,%s,now())
                   on conflict (site) do update
                   set data=excluded.data,revision=lpdh_site_state.revision+1,
                       updated_by=excluded.updated_by,updated_at=now()
                   returning revision""",
                (site, json.dumps(current, ensure_ascii=False), actor),
            )
            revision = cur.fetchone()["revision"]
        conn.commit()
    return {"site": site, "installed": True, "filename": payload.filename, "revision": revision}


@router.get("/calculator-final")
def get_calculator_final(request: Request, site: str = Query(), service_date: date = Query(alias="date")) -> dict[str, Any]:
    _require_db()
    target = _site(request, site)
    plan = _load_final_plan(target, service_date)
    return {"site": target, "serviceDate": service_date, "finalized": bool(plan), "plan": plan}


@router.post("/calculator-final")
def save_calculator_final(payload: CalculatorFinalIn, request: Request) -> dict[str, Any]:
    _require_db()
    site = _site(request, payload.site)
    actor = _role(request)
    if not payload.payload:
        raise HTTPException(400, "payload final kalkulator kosong")
    if not str(payload.payload.get("date") or payload.service_date.isoformat()).startswith(payload.service_date.isoformat()):
        raise HTTPException(400, "tanggal payload kalkulator tidak sesuai tanggal final")
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """insert into lpdh_final_plans(site,service_date,source_plan_id,plan_name,payload,revision,finalized_by,finalized_at)
                   values (%s,%s,%s,%s,%s::jsonb,1,%s,now())
                   on conflict (site,service_date) do update
                   set source_plan_id=excluded.source_plan_id,
                       plan_name=excluded.plan_name,
                       payload=excluded.payload,
                       revision=lpdh_final_plans.revision+1,
                       finalized_by=excluded.finalized_by,
                       finalized_at=now()
                   returning revision,finalized_at""",
                (
                    site, payload.service_date, payload.source_plan_id, payload.plan_name,
                    json.dumps(payload.payload, ensure_ascii=False), actor,
                ),
            )
            row = cur.fetchone()
        conn.commit()
    return {
        "site": site,
        "serviceDate": payload.service_date,
        "finalized": True,
        "revision": row["revision"],
        "finalizedAt": row["finalized_at"],
    }


@router.get("/preview")
def preview(request: Request, site: str = Query(), service_date: date = Query(alias="date")) -> dict[str, Any]:
    _require_db()
    target = _site(request, site)
    masters = _load_master(target)["data"] or {}
    daily = _load_daily(target, service_date)["data"] or {}
    final_plan = _load_final_plan(target, service_date)
    return compute_preview(masters, daily, service_date.isoformat(), _effective(target, service_date), final_plan)


@router.post("/generate")
def generate(payload: GenerateIn, request: Request) -> dict[str, Any]:
    _require_db()
    site = _site(request, payload.site)
    actor = _role(request)
    masters = _load_master(site)["data"] or {}
    daily_state = _load_daily(site, payload.service_date)
    daily = daily_state["data"] or {}
    final_plan = _load_final_plan(site, payload.service_date)
    preview_data = compute_preview(masters, daily, payload.service_date.isoformat(), _effective(site, payload.service_date), final_plan)
    if not preview_data["ready"]:
        issues = [row for row in preview_data["checks"] if not row["ok"]]
        raise HTTPException(
            409,
            {
                "message": "LPDH belum dapat digenerate karena validasi belum bersih",
                "errorCount": len(issues),
                "issues": issues,
            },
        )

    template_bytes = None
    stored_template = masters.get("_officialTemplateBase64")
    if stored_template:
        try:
            template_bytes = base64.b64decode(stored_template, validate=True)
        except Exception:
            template_bytes = None
    content = populate_workbook(masters, daily, preview_data, payload.service_date.isoformat(), template_bytes=template_bytes)
    filename = f"LPDH_{site}_{payload.service_date.isoformat()}.xlsx"
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """insert into lpdh_generation_log(
                     site,service_date,filename,validation_status,validation_error_count,generated_by,payload
                   ) values (%s,%s,%s,'OK',0,%s,%s::jsonb)""",
                (site, payload.service_date, filename, actor, json.dumps({"preview": {"errorCount": 0}}, ensure_ascii=False)),
            )
            cur.execute(
                """insert into lpdh_daily_state(site,service_date,data,status,revision,updated_by,updated_at)
                   values (%s,%s,%s::jsonb,'GENERATED',1,%s,now())
                   on conflict (site,service_date) do update
                   set status='GENERATED',revision=lpdh_daily_state.revision+1,
                       updated_by=excluded.updated_by,updated_at=now()""",
                (site, payload.service_date, json.dumps(daily, ensure_ascii=False), actor),
            )
        conn.commit()
    return {
        "filename": filename,
        "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "contentBase64": encode_bytes(content),
        "validation": {"ready": True, "errorCount": 0},
    }


@router.get("/history")
def history(request: Request, site: str = Query(), limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
    _require_db()
    target = _site(request, site)
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """select id,site,service_date,filename,validation_status,validation_error_count,generated_by,generated_at
                   from lpdh_generation_log where site=%s order by generated_at desc limit %s""",
                (target, limit),
            )
            rows = cur.fetchall()
    return {"site": target, "items": rows}
