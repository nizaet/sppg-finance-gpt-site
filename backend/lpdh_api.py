from __future__ import annotations

import base64
import json
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from backend.db import connection, database_ready
from backend.lpdh_logic import (
    compute_preview,
    encode_bytes,
    make_master_template,
    parse_master_workbook,
    workbook_reference_rows,
    merge_master_import,
    validate_master_portions,
    master_target_by_group,
    normalize_daily_draft,
    validate_daily_financial_sources,
)
from backend.document_numbering import claim_number, daily_number, suggest_number
from backend.lpdh_approval import incentive_defaults, approval_hash, attach_approval, cancel_approval, render_approval, ASSETS
from backend.lpdh_template import prepare_template, fill_template, source_hash, VERSION as TEMPLATE_VERSION

TEMPLATE_KEYS = ('_officialTemplateBase64', '_officialTemplateFilename',
                 '_preparedTemplateBase64', '_preparedTemplateVersion',
                 '_preparedTemplateSourceHash', '_officialTemplateHistory')

router = APIRouter(prefix="/v1/lpdh", tags=["lpdh"])


class MasterStateIn(BaseModel):
    site: str
    data: dict[str, Any] = Field(default_factory=dict)


class DailyStateIn(BaseModel):
    site: str
    service_date: date
    data: dict[str, Any] = Field(default_factory=dict)
    status: str = "DRAFT"
    require_editable: bool = False
    expected_revision: int | None = Field(default=None, ge=0)


class EffectiveDaysIn(BaseModel):
    site: str
    month: str
    dates: list[date] = Field(default_factory=list)
    notes: dict[str, str] = Field(default_factory=dict)


class MasterImportIn(BaseModel):
    site: str
    filename: str = "master.xlsx"
    content_base64: str


class OfficialTemplateIn(BaseModel):
    site: str
    filename: str = Field(min_length=1, max_length=200)
    content_base64: str = Field(min_length=1, max_length=20000000)


class CalculatorFinalIn(BaseModel):
    site: str
    service_date: date
    source_plan_id: str | None = None
    plan_name: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class GenerateIn(BaseModel):
    site: str
    service_date: date
    draft_only: bool = False


class TopupEvidenceIn(BaseModel):
    site: str
    service_date: date
    content_base64: str = Field(min_length=1,max_length=6990508)


class ApprovalIn(BaseModel):
    site: str
    service_date: date
    expected_hash: str | None = Field(default=None, max_length=64)


class ApprovalCancelIn(ApprovalIn):
    reason: str = Field(min_length=1, max_length=500)


def _with_incentive_defaults(cur, site, service_date, masters, daily, context, reserve=False):
    if daily.get('_historicalGeneratedSnapshot'):
        return daily
    preview = compute_preview(masters, daily, service_date.isoformat(), context['effective'], _load_final_plan(site, service_date))
    inc = daily.get('incentive') or {}
    owner = 'DAY:' + service_date.isoformat()
    cur.execute("select full_number from document_number_serials where site=%s and namespace='D_INS_RECEIPT' and owner_key=%s order by created_at desc limit 1", (site, owner))
    own = cur.fetchone()
    roman = ['I','II','III','IV','V','VI','VII','VIII','IX','X','XI','XII'][service_date.month - 1]
    receipt = inc.get('receiptNo') or (own or {}).get('full_number') or suggest_number(cur, site, 'D_INS_RECEIPT', f'001/KW-INS/SPPG-{site}/{roman}/{service_date.year}')
    result = incentive_defaults(daily, preview['incentiveCalculated'], service_date.isoformat(), site, receipt)
    if reserve:
        claim_number(cur, site, 'D_INS_RECEIPT', result['incentive']['receiptNo'], owner)
        claim_number(cur, site, 'D_INS_PROOF', result['incentive']['proofNo'], owner)
    return result


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


def _effective_context(site: str, service_date: date) -> dict[str, Any]:
    week_start = service_date - timedelta(days=service_date.weekday())
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select is_effective from lpdh_effective_days where site=%s and service_date=%s",
                (site, service_date),
            )
            row = cur.fetchone()
            effective = bool(row and row["is_effective"])
            if effective:
                cur.execute(
                    """select count(*) as n
                       from lpdh_effective_days
                       where site=%s
                         and is_effective=true
                         and service_date >= %s
                         and service_date <= %s""",
                    (site, week_start, service_date),
                )
                count_row = cur.fetchone()
                hpe_number = int((count_row or {}).get("n") or 0)
            else:
                hpe_number = 0
    return {"effective": effective, "hpeNumber": hpe_number}


def _effective(site: str, service_date: date) -> bool:
    return bool(_effective_context(site, service_date)["effective"])


def _daily_with_hpe(site: str, service_date: date, daily: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    context = _effective_context(site, service_date)
    normalized = dict(daily or {})
    normalized["dayStatus"] = "HPE" if context["effective"] else normalized.get("dayStatus") or "Tidak HPE"
    normalized["hpeNumber"] = context["hpeNumber"]
    return normalized, context


@router.get("/masters")
def get_masters(request: Request, site: str = Query()) -> dict[str, Any]:
    _require_db()
    target = _site(request, site)
    result = _load_master(target)
    public_data = dict(result.get("data") or {})
    for key in TEMPLATE_KEYS:
        public_data.pop(key, None)
    public_data["groupTargetAggregate"] = master_target_by_group(public_data)
    result = {**result, "data": public_data}
    return {"site": target, **result}


@router.put("/masters")
def save_masters(payload: MasterStateIn, request: Request) -> dict[str, Any]:
    _require_db()
    site = _site(request, payload.site)
    actor = _role(request)
    current = _load_master(site)["data"] or {}
    incoming = dict(payload.data or {})
    try:
        validate_master_portions(incoming)
        from backend.generated_document_settings import validate_artwork
        for key in ASSETS:
            if (incoming.get('assets') or {}).get(key):
                validate_artwork(str(incoming['assets'][key]).split(',', 1)[-1])
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    for protected_key in TEMPLATE_KEYS:
        if protected_key in current:
            incoming[protected_key] = current[protected_key]
        else:
            incoming.pop(protected_key, None)
    # The original workbook totals are read-only import history.
    incoming["groupTargets"] = current.get("groupTargets") or {}
    incoming.pop("groupTargetAggregate", None)
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """insert into lpdh_site_state(site,data,revision,updated_by,updated_at)
                   values (%s,%s::jsonb,1,%s,now())
                   on conflict (site) do update
                   set data=excluded.data || coalesce((select jsonb_object_agg(key,value)
                       from jsonb_each(lpdh_site_state.data) where key in (
                           '_officialTemplateBase64','_officialTemplateFilename',
                           '_preparedTemplateBase64','_preparedTemplateVersion',
                           '_preparedTemplateSourceHash','_officialTemplateHistory')),'{}'::jsonb),
                       revision=lpdh_site_state.revision+1,
                       updated_by=excluded.updated_by,
                       updated_at=now()
                   returning revision,updated_at""",
                (site, json.dumps(incoming, ensure_ascii=False), actor),
            )
            row = cur.fetchone()
        conn.commit()
    return {"site": site, "saved": True, "revision": row["revision"], "updatedAt": row["updated_at"]}


@router.get("/daily")
def get_daily(request: Request, site: str = Query(), service_date: date = Query(alias="date")) -> dict[str, Any]:
    _require_db()
    target = _site(request, site)
    daily = _load_daily(target, service_date)
    masters = _load_master(target)["data"]
    normalized = normalize_daily_draft(masters, daily.get("data") or {}, daily["status"])
    if daily["status"] != "GENERATED":
        from backend.accountant_generated_document_api import load_documents
        from backend.generated_document_logic import merge_final_documents
        with connection() as conn, conn.cursor() as cur:
            normalized = merge_final_documents(normalized, load_documents(cur, target, service_date, True))
    normalized, context = _daily_with_hpe(target, service_date, normalized)
    with connection() as conn, conn.cursor() as cur:
        normalized["lpdhNumber"] = daily_number(cur, target, service_date, _load_master(target)["data"], normalized.get("lpdhNumber"))
        if daily['status'] != 'GENERATED':
            normalized = _with_incentive_defaults(cur, target, service_date, masters, normalized, context)
    return {
        "site": target,
        "serviceDate": service_date,
        **daily,
        "data": normalized,
        **context,
        "finalPlan": _load_final_plan(target, service_date),
    }


@router.put("/daily")
def save_daily(payload: DailyStateIn, request: Request) -> dict[str, Any]:
    _require_db()
    site = _site(request, payload.site)
    requested_status = str(payload.status or "DRAFT").upper()
    if requested_status not in {"DRAFT", "READY", "GENERATED"}:
        raise HTTPException(400, "status daily tidak valid")
    if requested_status == "GENERATED":
        raise HTTPException(422, "Gunakan Generate LPDH untuk menyimpan snapshot final")
    from backend.accountant_generated_document_api import daily_lock, load_documents
    from backend.generated_document_logic import merge_final_documents
    with connection() as conn, conn.cursor() as cur:
        daily_lock(cur, site, payload.service_date)
        try:
            existing = _load_daily(site, payload.service_date)
            if payload.require_editable and (existing['status'] == 'GENERATED' or existing['data'].get('_historicalGeneratedSnapshot')):
                raise HTTPException(409, "LPDH sudah digenerate. Tarikan rutin tidak boleh mengganti snapshot tersebut.")
            if payload.expected_revision is not None and existing['revision'] != payload.expected_revision:
                raise HTTPException(409, "Data harian berubah saat penarikan. Refresh dan periksa kembali sebelum menarik.")
            validate_daily_financial_sources(payload.data, existing["data"])
            from backend.topup_receipt import protect_final_rows
            protect_final_rows(cur, site, payload.service_date, payload.data)
            for protected in ('_approval', '_approvalHistory'):
                payload.data.pop(protected, None)
                if protected in existing['data']:
                    payload.data[protected] = existing['data'][protected]
            prior_approval = existing['data'].get('_approval') or {}
            if prior_approval.get('pdfLink'):
                inc = payload.data.setdefault('incentive', {})
                inc['approvalEvidenceLink'] = prior_approval['pdfLink']
                if not inc.get('evidenceLink'):
                    inc['evidenceLink'] = prior_approval['pdfLink']
            # Replacement audit history is server-owned, not editable form data.
            payload.data.pop('_replacedLegacyPayments', None)
            if '_replacedLegacyPayments' in existing['data']:
                payload.data['_replacedLegacyPayments'] = existing['data']['_replacedLegacyPayments']
            if existing["status"] == "GENERATED" or existing["data"].get("_historicalGeneratedSnapshot"):
                payload.data["_historicalGeneratedSnapshot"] = True
            else:
                payload.data.pop("_historicalGeneratedSnapshot", None)
            payload.data = normalize_daily_draft(_load_master(site)["data"], payload.data, "DRAFT")
            payload.data = merge_final_documents(payload.data, load_documents(cur, site, payload.service_date, True))
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        result = _save_daily_locked(payload, request, site, cur)
        conn.commit()
    return result


@router.post("/topup/evidence")
def upload_topup_evidence(payload: TopupEvidenceIn, request: Request):
    _require_db()
    site=_site(request,payload.site)
    from backend.topup_evidence import decode_evidence
    from backend.accountant_drive import upload_accountant_artifact
    import hashlib
    try:
        content,mime,extension=decode_evidence(payload.content_base64)
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from exc
    digest=hashlib.sha256(content).hexdigest()
    filename=f'Bukti_TopUp_{site}_{payload.service_date}_{digest[:12]}.{extension}'
    try:
        archive=upload_accountant_artifact(kind='invoice',filename=filename,data=content,mime_type=mime,
            site=site,service_date=payload.service_date.isoformat(),artifact_key=f'topup-{site}-{payload.service_date}-{digest}')
    except Exception as exc:
        raise HTTPException(502,'Upload Drive gagal. Link lama tidak diubah; silakan coba lagi.') from exc
    link=archive.get('driveUri') or ''
    if not link.startswith('https://'):
        raise HTTPException(502,'Drive belum mengembalikan link bukti. Silakan coba lagi.')
    return {'evidenceLink':link,'filename':filename}


@router.post("/daily/validation/cancel")
def cancel_daily_validation(payload: GenerateIn, request: Request) -> dict[str, Any]:
    _require_db()
    site = _site(request, payload.site)
    from backend.accountant_generated_document_api import daily_lock
    with connection() as conn, conn.cursor() as cur:
        daily_lock(cur, site, payload.service_date)
        state = _load_daily(site, payload.service_date)
        if state['status'] == 'GENERATED' or state['data'].get('_historicalGeneratedSnapshot'):
            raise HTTPException(409, 'Snapshot Excel final tidak diubah. Buka kembali sebagai draft terlebih dahulu.')
        # Change only the validation marker; never overwrite user data or FINAL documents.
        cur.execute("""update lpdh_daily_state set data=jsonb_set(data,'{_reviewValidated}','false'::jsonb),
                    status='DRAFT',revision=revision+1,updated_by=%s,updated_at=now()
                    where site=%s and service_date=%s""", (_role(request), site, payload.service_date))
        conn.commit()
    return {'site':site, 'serviceDate':payload.service_date, 'cancelled':True}


def _save_daily_locked(payload, request, site, cur):
    masters = _load_master(site)["data"] or {}
    if not str(payload.data.get("lpdhNumber") or "").strip():
        cur.execute("select data from lpdh_daily_state where site=%s and service_date=%s", (site, payload.service_date))
        old = (cur.fetchone() or {}).get("data") or {}
        payload.data["lpdhNumber"] = daily_number(cur, site, payload.service_date, masters, old.get("lpdhNumber"))
    claim_number(cur, site, "LPDH", payload.data["lpdhNumber"], "DAY:" + payload.service_date.isoformat())
    requested_status = str(payload.status or "DRAFT").upper()
    status = requested_status
    if requested_status != "GENERATED":
        normalized, context = _daily_with_hpe(site, payload.service_date, payload.data or {})
        payload.data = _with_incentive_defaults(cur, site, payload.service_date, masters, normalized, context, reserve=True)
        normalized = payload.data
        final_plan = _load_final_plan(site, payload.service_date)
        if final_plan and context["effective"]:
            validation = compute_preview(
                masters,
                normalized,
                payload.service_date.isoformat(),
                context["effective"],
                final_plan,
            )
            status = "READY" if validation["ready"] else "DRAFT"
        else:
            status = "DRAFT"
    actor = _role(request)
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


@router.get("/calendar")
def calendar_month(request: Request, site: str = Query(), month: str = Query()) -> dict[str, Any]:
    _require_db()
    target = _site(request, site)
    start, end = _month_bounds(month)
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """select service_date,is_effective,note
                   from lpdh_effective_days
                   where site=%s and service_date >= %s and service_date < %s
                   order by service_date""",
                (target, start, end),
            )
            effective_rows = cur.fetchall()
            cur.execute(
                """select service_date,status,revision,updated_at
                   from lpdh_daily_state
                   where site=%s and service_date >= %s and service_date < %s
                   order by service_date""",
                (target, start, end),
            )
            daily_rows = cur.fetchall()
            cur.execute(
                """select service_date,revision,finalized_at
                   from lpdh_final_plans
                   where site=%s and service_date >= %s and service_date < %s
                   order by service_date""",
                (target, start, end),
            )
            plan_rows = cur.fetchall()

    effective_map = {row["service_date"].isoformat(): row for row in effective_rows}
    daily_map = {row["service_date"].isoformat(): row for row in daily_rows}
    plan_map = {row["service_date"].isoformat(): row for row in plan_rows}
    all_dates = sorted(set(effective_map) | set(daily_map) | set(plan_map))
    items = []
    for day in all_dates:
        e = effective_map.get(day)
        d = daily_map.get(day)
        p = plan_map.get(day)
        items.append({
            "serviceDate": day,
            "effective": bool(e and e["is_effective"]),
            "note": (e or {}).get("note") if e else "",
            "status": (d or {}).get("status") if d else "EMPTY",
            "dailyRevision": (d or {}).get("revision") if d else 0,
            "updatedAt": (d or {}).get("updated_at") if d else None,
            "finalized": bool(p),
            "finalPlanRevision": (p or {}).get("revision") if p else 0,
        })
    return {"site": target, "month": month, "items": items}


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

    source_name = str((parsed.get("identity") or {}).get("sppgName") or "").upper()
    if parsed.get("source") == "OFFICIAL_LPDH" and site not in source_name:
        raise HTTPException(422, "Nama dapur workbook tidak cocok dengan dapur tujuan. Pilih dapur yang benar.")
    try:
        validate_master_portions(parsed)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    actor = _role(request)
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("select pg_advisory_xact_lock(hashtextextended(%s,0))", ("lpdh-master:" + site,))
            cur.execute("select data from lpdh_site_state where site=%s for update", (site,))
            existing = (cur.fetchone() or {}).get("data") or {}
            merged, added, warnings = merge_master_import(existing, parsed, payload.filename)
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
        "imported": added,
        "groupTargets": len(parsed.get("groupTargets") or {}),
        "warnings": warnings,
        "revision": revision,
    }


@router.get("/master-template")
def master_template(request: Request, site: str = Query()) -> dict[str, Any]:
    _site(request, site)
    content = make_master_template()
    return {
        "filename": "Template_Import_Master_LPDH_Sekolah_Posyandu_v2.xlsx",
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
        "fillOnly": masters.get('_preparedTemplateVersion') == TEMPLATE_VERSION,
        "templateVersion": masters.get('_preparedTemplateVersion'),
    }


@router.put("/official-template")
def save_official_template(payload: OfficialTemplateIn, request: Request) -> dict[str, Any]:
    _require_db()
    site = _site(request, payload.site)
    try:
        raw = base64.b64decode(payload.content_base64, validate=True)
        prepared = prepare_template(raw)
    except Exception as exc:
        raise HTTPException(400, f"Template LPDH tidak valid: {exc}") from exc
    # Patch only template metadata; a concurrent master edit must survive.
    current = {"_officialTemplateBase64": payload.content_base64,
               "_officialTemplateFilename": payload.filename,
               "_preparedTemplateBase64": encode_bytes(prepared),
               "_preparedTemplateVersion": TEMPLATE_VERSION,
               "_preparedTemplateSourceHash": source_hash(raw)}
    actor = _role(request)
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """insert into lpdh_site_state(site,data,revision,updated_by,updated_at)
                   values (%s,%s::jsonb,1,%s,now())
                   on conflict (site) do update
                   set data=lpdh_site_state.data || excluded.data || jsonb_build_object(
                       '_officialTemplateHistory',
                       coalesce(lpdh_site_state.data->'_officialTemplateHistory','[]'::jsonb) ||
                       case when lpdh_site_state.data ? '_officialTemplateBase64' then
                         jsonb_build_array(jsonb_build_object(
                           'filename',lpdh_site_state.data->'_officialTemplateFilename',
                           'sourceBase64',lpdh_site_state.data->'_officialTemplateBase64',
                           'preparedBase64',lpdh_site_state.data->'_preparedTemplateBase64',
                           'sourceHash',lpdh_site_state.data->'_preparedTemplateSourceHash',
                           'replacedAt',now())) else '[]'::jsonb end),
                       revision=lpdh_site_state.revision+1,
                       updated_by=excluded.updated_by,updated_at=now()
                   returning revision""",
                (site, json.dumps(current, ensure_ascii=False), actor),
            )
            revision = cur.fetchone()["revision"]
        conn.commit()
    return {"site": site, "installed": True, "filename": payload.filename, "revision": revision,
            "fillOnly": True, "templateVersion": TEMPLATE_VERSION}


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
    daily_state = _load_daily(target, service_date)
    raw_daily = normalize_daily_draft(masters, daily_state["data"] or {}, daily_state["status"])
    if daily_state["status"] != "GENERATED":
        from backend.accountant_generated_document_api import load_documents
        from backend.generated_document_logic import merge_final_documents
        with connection() as conn, conn.cursor() as cur:
            raw_daily = merge_final_documents(raw_daily, load_documents(cur, target, service_date, True))
    daily, context = _daily_with_hpe(target, service_date, raw_daily)
    final_plan = _load_final_plan(target, service_date)
    if daily_state['status'] != 'GENERATED':
        initial = compute_preview(masters, daily, service_date.isoformat(), context['effective'], final_plan)
        daily = incentive_defaults(daily, initial['incentiveCalculated'], service_date.isoformat(), target)
    return compute_preview(masters, daily, service_date.isoformat(), context["effective"], final_plan)


@router.post("/preview")
def preview_draft(payload: DailyStateIn, request: Request) -> dict[str, Any]:
    """Calculate the current form without saving, claiming numbers or finalizing."""
    _require_db()
    target = _site(request, payload.site)
    masters = _load_master(target)["data"] or {}
    existing = _load_daily(target, payload.service_date)
    incoming = dict(payload.data)
    # Historical provenance is trusted only from the stored daily state.
    incoming.pop("_historicalGeneratedSnapshot", None)
    if existing["status"] == "GENERATED" or existing["data"].get("_historicalGeneratedSnapshot"):
        incoming["_historicalGeneratedSnapshot"] = True
    try:
        validate_daily_financial_sources(incoming, existing["data"])
        daily = normalize_daily_draft(masters, incoming)
        if existing["status"] != "GENERATED":
            from backend.accountant_generated_document_api import load_documents
            from backend.generated_document_logic import merge_final_documents
            with connection() as conn, conn.cursor() as cur:
                daily = merge_final_documents(daily, load_documents(cur, target, payload.service_date, True))
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    daily, context = _daily_with_hpe(target, payload.service_date, daily)
    if existing['status'] != 'GENERATED':
        initial = compute_preview(masters, daily, payload.service_date.isoformat(), context['effective'], _load_final_plan(target, payload.service_date))
        daily = incentive_defaults(daily, initial['incentiveCalculated'], payload.service_date.isoformat(), target)
    result = compute_preview(masters, daily, payload.service_date.isoformat(), context["effective"], _load_final_plan(target, payload.service_date))
    return {**result, "previewSource": "CURRENT_FORM"}


@router.post("/generate")
def generate(payload: GenerateIn, request: Request) -> dict[str, Any]:
    _require_db()
    site = _site(request, payload.site)
    from backend.accountant_generated_document_api import daily_lock
    with connection() as conn, conn.cursor() as cur:
        daily_lock(cur, site, payload.service_date)
        result = _generate_locked(payload, request, site, cur)
        conn.commit()
    return result


def _generate_locked(payload, request, site, cur):
    actor = _role(request)
    masters = _load_master(site)["data"] or {}
    daily_state = _load_daily(site, payload.service_date)
    from backend.accountant_generated_document_api import load_documents
    from backend.generated_document_logic import merge_final_documents
    raw_daily = normalize_daily_draft(masters, daily_state["data"] or {}, daily_state["status"])
    if daily_state["status"] != "GENERATED":
        raw_daily = merge_final_documents(raw_daily, load_documents(cur, site, payload.service_date, True))
    daily, context = _daily_with_hpe(site, payload.service_date, raw_daily)
    if daily_state['status'] != 'GENERATED':
        daily = _with_incentive_defaults(cur, site, payload.service_date, masters, daily, context)
    if not payload.draft_only:
        daily["lpdhNumber"] = daily_number(cur, site, payload.service_date, masters, daily.get("lpdhNumber"))
    final_plan = _load_final_plan(site, payload.service_date)
    if not final_plan and not payload.draft_only:
        raise HTTPException(409, {"message": "Data Kalkulator belum berstatus FINAL untuk tanggal ini"})
    if not context["effective"] and not payload.draft_only:
        raise HTTPException(409, {"message": "Tanggal ini bukan Hari Pelayanan Efektif"})
    preview_data = compute_preview(masters, daily, payload.service_date.isoformat(), context["effective"], final_plan)
    if not preview_data["ready"] and not payload.draft_only:
        issues = [row for row in preview_data["checks"] if not row["ok"]]
        raise HTTPException(
            409,
            {
                "message": "LPDH belum dapat digenerate karena validasi belum bersih",
                "errorCount": len(issues),
                "issues": issues,
            },
        )

    if not payload.draft_only:
        claim_number(cur, site, "LPDH", daily["lpdhNumber"], "DAY:" + payload.service_date.isoformat())

    stored_template = masters.get("_officialTemplateBase64")
    if not stored_template:
        raise HTTPException(409, 'Unggah Template LPDH Resmi terlebih dahulu. Unduhan hanya mengisi salinan template server, bukan membuat workbook cadangan.')
    try:
        raw_template = base64.b64decode(stored_template, validate=True)
        digest = source_hash(raw_template)
        if (masters.get('_preparedTemplateVersion') != TEMPLATE_VERSION or
                masters.get('_preparedTemplateSourceHash') != digest or not masters.get('_preparedTemplateBase64')):
            # One-time upgrade of an already installed private template, inside
            # the existing transaction. Never overwrite its original bytes.
            template_bytes = prepare_template(raw_template)
            metadata = {'_preparedTemplateBase64':encode_bytes(template_bytes),
                        '_preparedTemplateVersion':TEMPLATE_VERSION,'_preparedTemplateSourceHash':digest}
            cur.execute('update lpdh_site_state set data=data || %s::jsonb where site=%s and data->>\'_officialTemplateBase64\'=%s',
                        (json.dumps(metadata),site,stored_template))
            if getattr(cur,'rowcount',1) == 0:
                raise ValueError('Template baru dipasang saat unduhan disiapkan. Ulangi unduhan agar memakai template terbaru.')
        else:
            template_bytes = base64.b64decode(masters['_preparedTemplateBase64'],validate=True)
        content = fill_template(template_bytes, masters, daily, preview_data, payload.service_date.isoformat())
    except Exception as exc:
        raise HTTPException(409, f'Template LPDH belum dapat diisi: {exc}. Template asli dan data harian tidak diubah.') from exc
    if payload.draft_only:
        return {'filename':f'LPDH_DRAFT_{site}_{payload.service_date.isoformat()}.xlsx',
                'mimeType':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                'contentBase64':encode_bytes(content), 'draft':True,
                'validation':{'ready':preview_data['ready'],'errorCount':preview_data['errorCount']}}
    daily["_historicalGeneratedSnapshot"] = True
    filename = f"LPDH_{site}_{payload.service_date.isoformat()}.xlsx"
    cur.execute(
        """insert into lpdh_generation_log(
             site,service_date,filename,validation_status,validation_error_count,generated_by,payload
           ) values (%s,%s,%s,'OK',0,%s,%s::jsonb)""",
        (site, payload.service_date, filename, actor, json.dumps({"preview": {"errorCount": 0},
            "template": {"sourceHash":digest,"version":TEMPLATE_VERSION,
                         "filename":masters.get('_officialTemplateFilename')}}, ensure_ascii=False)),
    )
    cur.execute(
        """insert into lpdh_daily_state(site,service_date,data,status,revision,updated_by,updated_at)
           values (%s,%s,%s::jsonb,'GENERATED',1,%s,now())
           on conflict (site,service_date) do update
           set data=excluded.data,status='GENERATED',revision=lpdh_daily_state.revision+1,
               updated_by=excluded.updated_by,updated_at=now()""",
        (site, payload.service_date, json.dumps(daily, ensure_ascii=False), actor),
    )
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


def _approval_inputs(cur, site, service_date):
    from backend.accountant_generated_document_api import load_documents
    from backend.generated_document_logic import merge_final_documents
    masters = _load_master(site)['data'] or {}
    state = _load_daily(site, service_date)
    if state['status'] == 'GENERATED' or state['data'].get('_historicalGeneratedSnapshot'):
        raise HTTPException(409, 'Snapshot LPDH sudah terkunci. Pengesahan tidak boleh mengubah arsip lama.')
    data = normalize_daily_draft(masters, state['data'])
    data = merge_final_documents(data, load_documents(cur, site, service_date, True))
    data, context = _daily_with_hpe(site, service_date, data)
    data = _with_incentive_defaults(cur, site, service_date, masters, data, context)
    preview_data = compute_preview(masters, data, service_date.isoformat(), context['effective'], _load_final_plan(site, service_date))
    source = masters.get('_officialTemplateBase64')
    if not source:
        raise HTTPException(422, 'Unggah template LPDH resmi sebelum mencetak J_Pengesahan.')
    try:
        prepared = prepare_template(base64.b64decode(source, validate=True))
        content = fill_template(prepared, masters, data, preview_data, service_date.isoformat())
    except Exception as exc:
        raise HTTPException(422, 'Template belum dapat dicetak. Periksa pemetaan template resmi.') from exc
    digest = approval_hash(masters, data, service_date.isoformat(), preview_data)
    return masters, data, preview_data, content, digest, context


@router.post('/approval/preview')
def approval_preview(payload: ApprovalIn, request: Request):
    _require_db()
    site = _site(request, payload.site)
    with connection() as conn, conn.cursor() as cur:
        masters, data, preview_data, content, digest, context = _approval_inputs(cur, site, payload.service_date)
    try:
        pdf = render_approval(content, masters.get('assets') or {})
    except Exception as exc:
        import logging
        logging.getLogger(__name__).exception('LPDH approval print failed (%s)', type(exc).__name__)
        raise HTTPException(422, 'Pratinjau pengesahan belum berhasil dicetak. Data tidak difinalkan.') from exc
    return {'filename': f'J_Pengesahan_{site}_{payload.service_date}.pdf',
            'mimeType': 'application/pdf', 'contentBase64': encode_bytes(pdf),
            'hash': digest, 'validation': {'ready': preview_data['ready'], 'errorCount': preview_data['errorCount']}}


@router.post('/approval/finalize')
def approval_finalize(payload: ApprovalIn, request: Request):
    _require_db()
    site = _site(request, payload.site)
    if not payload.expected_hash:
        raise HTTPException(422, 'Buka pratinjau cetak sebelum finalisasi pengesahan.')
    from backend.accountant_generated_document_api import daily_lock
    from backend.accountant_drive import upload_accountant_artifact
    with connection() as conn, conn.cursor() as cur:
        daily_lock(cur, site, payload.service_date)
        masters, data, preview_data, content, digest, context = _approval_inputs(cur, site, payload.service_date)
        if digest != payload.expected_hash:
            raise HTTPException(409, 'Data atau template berubah. Buka dan cetak pratinjau terbaru sebelum Finalkan.')
        if not context['effective']:
            raise HTTPException(409, 'Pengesahan final harus menggunakan tanggal HPE.')
        current = data.get('_approval') or {}
        if current.get('status') == 'FINAL' and current.get('hash') == digest and current.get('pdfLink'):
            return {'saved': True, 'approval': current, 'alreadyFinal': True}
        if len(masters.get('signers') or []) < 3 or any(not str(s.get('name') or '').strip() for s in masters['signers'][:3]):
            raise HTTPException(422, 'Lengkapi nama tiga pengesah pada Master → Pengesah.')
        owner = 'DAY:' + payload.service_date.isoformat()
        claim_number(cur, site, 'D_INS_RECEIPT', data['incentive']['receiptNo'], owner)
        claim_number(cur, site, 'D_INS_PROOF', data['incentive']['proofNo'], owner)
        try:
            pdf = render_approval(content, masters.get('assets') or {})
            archive = upload_accountant_artifact(kind='invoice', filename=f'J_Pengesahan_{site}_{payload.service_date}_{digest[:12]}.pdf',
                data=pdf, mime_type='application/pdf', site=site, service_date=payload.service_date.isoformat(),
                artifact_key=f'lpdh-approval-{site}-{payload.service_date}-{digest}')
            data = attach_approval(data, archive, digest, _role(request), datetime.now(timezone.utc).isoformat())
        except Exception as exc:
            raise HTTPException(502, 'PDF pengesahan belum tersimpan di Drive. Status FINAL dan link D_Insentif tidak diubah; silakan ulangi.') from exc
        cur.execute("""insert into lpdh_daily_state(site,service_date,data,status,revision,updated_by,updated_at)
            values (%s,%s,%s::jsonb,'DRAFT',1,%s,now()) on conflict (site,service_date) do update
            set data=excluded.data,revision=lpdh_daily_state.revision+1,updated_by=excluded.updated_by,updated_at=now()""",
            (site, payload.service_date, json.dumps(data, ensure_ascii=False), _role(request)))
        conn.commit()
    return {'saved': True, 'approval': data['_approval'], 'evidenceLink': data['incentive'].get('evidenceLink')}


@router.post('/approval/cancel')
def approval_cancel(payload: ApprovalCancelIn, request: Request):
    _require_db()
    site = _site(request, payload.site)
    from backend.accountant_generated_document_api import daily_lock
    reason = payload.reason.strip()
    if not reason:
        raise HTTPException(422, 'Isi alasan pembatalan pengesahan.')
    with connection() as conn, conn.cursor() as cur:
        daily_lock(cur, site, payload.service_date)
        state = _load_daily(site, payload.service_date)
        if state['status'] == 'GENERATED' or state['data'].get('_historicalGeneratedSnapshot'):
            raise HTTPException(409, 'Snapshot LPDH terkunci; arsip lama tidak boleh diubah.')
        current = state['data'].get('_approval') or {}
        if not payload.expected_hash or current.get('hash') != payload.expected_hash:
            raise HTTPException(409, 'Pengesahan berubah. Muat ulang sebelum membatalkan.')
        if current.get('status') == 'CANCELLED':
            return {'saved': True, 'approval': current, 'alreadyCancelled': True}
        if current.get('status') != 'FINAL':
            raise HTTPException(409, 'Hanya pengesahan FINAL yang dapat dibatalkan.')
        data = cancel_approval(state['data'], _role(request), datetime.now(timezone.utc).isoformat(), reason)
        cur.execute("""update lpdh_daily_state set data=%s::jsonb,
            revision=revision+1,updated_by=%s,updated_at=now() where site=%s and service_date=%s""",
            (json.dumps(data, ensure_ascii=False), _role(request), site, payload.service_date))
        conn.commit()
    return {'saved': True, 'approval': data['_approval']}


from backend.topup_receipt_api import router as topup_receipt_router
router.include_router(topup_receipt_router)

