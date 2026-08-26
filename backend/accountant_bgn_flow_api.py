from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from backend.db import connection, database_ready

router = APIRouter(tags=["accountant-bgn-flow"])


def require_db() -> None:
    from fastapi import HTTPException
    if not database_ready():
        raise HTTPException(503, "database unavailable")


def _table_exists(cur: Any, table_name: str) -> bool:
    cur.execute("select to_regclass(%s) is not null as exists", (table_name,))
    return bool(cur.fetchone()["exists"])


def _columns(cur: Any, table_name: str) -> set[str]:
    cur.execute("select column_name from information_schema.columns where table_schema='public' and table_name=%s", (table_name,))
    return {str(row["column_name"]) for row in cur.fetchall()}


def _col(alias: str, columns: set[str], name: str, *, as_name: str | None = None, default: str = "null") -> str:
    output = as_name or name
    return f"{alias}.{name} as {output}" if name in columns else f"{default} as {output}"


def _order(alias: str, columns: set[str]) -> str:
    if "created_at" in columns: return f"{alias}.created_at desc"
    if "id" in columns: return f"{alias}.id desc"
    return "1"


def _backfill_legacy_maker_links(cur: Any) -> int:
    """Safely link old makers created before accountant_invoice_id was populated.

    Match by same site + exact amount. A link is written only when there is one
    unique accountant invoice candidate for that maker, so repeated amounts are
    deliberately left untouched instead of guessed. Matching reference numbers
    are used only as an extra narrowing signal when available.
    """
    if not (_table_exists(cur, "bgn_makers") and _table_exists(cur, "accountant_invoices") and _table_exists(cur, "accountant_submissions")):
        return 0
    maker_cols = _columns(cur, "bgn_makers")
    invoice_cols = _columns(cur, "accountant_invoices")
    submission_cols = _columns(cur, "accountant_submissions")

    # Installations that were running before the unified Accountant/BGN flow
    # do not necessarily have every newer column.  This is a convenience
    # repair for old maker links, never a prerequisite for opening the Excel
    # queue.  Do not run a query that can take the whole Accountant page down
    # when a legacy schema is still being migrated.
    required_maker = {"id", "accountant_invoice_id", "amount", "site"}
    required_invoice = {"id", "accountant_submission_id", "invoice_amount"}
    required_submission = {"id", "site"}
    if not (
        required_maker.issubset(maker_cols)
        and required_invoice.issubset(invoice_cols)
        and required_submission.issubset(submission_cols)
    ):
        return 0

    maker_reference = (
        "lower(trim(coalesce(m.reference_number,'')))"
        if "reference_number" in maker_cols
        else "''"
    )
    invoice_reference = (
        "lower(trim(coalesce(i.invoice_number,'')))"
        if "invoice_number" in invoice_cols
        else "''"
    )
    cur.execute(
        f"""
        with raw_candidates as (
          select m.id as maker_id,i.id as invoice_id,
                 case
                   when {maker_reference}<>'' and {maker_reference}={invoice_reference} then 2
                   when {maker_reference}=lower('AKUNTAN-INV-' || i.id::text) then 2
                   else 1
                 end as ref_score
          from bgn_makers m
          join accountant_invoices i on abs(coalesce(m.amount,0)-coalesce(i.invoice_amount,0)) < 0.01
          join accountant_submissions s on s.id=i.accountant_submission_id
          where m.accountant_invoice_id is null
            and upper(coalesce(m.site,''))=upper(coalesce(s.site,''))
        ), preferred as (
          select r.*,
                 max(ref_score) over(partition by maker_id) as best_score
          from raw_candidates r
        ), candidates as (
          select maker_id,min(invoice_id) as invoice_id,count(*) as candidate_count
          from preferred
          where ref_score=best_score
          group by maker_id
        )
        update bgn_makers m
           set accountant_invoice_id=c.invoice_id
          from candidates c
         where m.id=c.maker_id and c.candidate_count=1 and m.accountant_invoice_id is null
        """
    )
    return max(int(cur.rowcount or 0), 0)


def _try_backfill_legacy_maker_links(cur: Any) -> int:
    """Run the optional legacy repair without breaking the Accountant queue.

    A failed statement leaves PostgreSQL's transaction aborted.  A savepoint is
    therefore required here: otherwise an old schema can make even the simple
    read of `accountant_submissions` fail afterwards.
    """
    cur.execute("savepoint accountant_legacy_link_repair")
    try:
        repaired = _backfill_legacy_maker_links(cur)
    except Exception:
        cur.execute("rollback to savepoint accountant_legacy_link_repair")
        repaired = 0
    finally:
        cur.execute("release savepoint accountant_legacy_link_repair")
    return repaired


@router.get("/accountant-flow")
def accountant_flow(site: str = "") -> dict[str, Any]:
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            repaired = _try_backfill_legacy_maker_links(cur)
            if repaired:
                conn.commit()
            if not _table_exists(cur, "accountant_submissions"):
                return {"items": [], "count": 0, "schemaWarning": "accountant_submissions table is not available"}
            sub_cols = _columns(cur, "accountant_submissions")
            inv_exists = _table_exists(cur, "accountant_invoices")
            inv_cols = _columns(cur, "accountant_invoices") if inv_exists else set()
            can_join_invoice = inv_exists and "accountant_submission_id" in inv_cols
            invoice_select = "null as invoice_id,null as invoice_number,null as invoice_amount,null as invoice_evidence_uri,null as received_at"
            invoice_join = ""
            if can_join_invoice:
                invoice_select = f"{_col('i',inv_cols,'id',as_name='invoice_id')},{_col('i',inv_cols,'invoice_number')},{_col('i',inv_cols,'invoice_amount')},{_col('i',inv_cols,'invoice_evidence_uri')},{_col('i',inv_cols,'received_at')}"
                invoice_join = f"left join lateral (select * from accountant_invoices x where x.accountant_submission_id=s.id order by {_order('x',inv_cols)} limit 1) i on true"

            maker_exists = _table_exists(cur, "bgn_makers")
            maker_cols = _columns(cur, "bgn_makers") if maker_exists else set()
            can_join_maker = can_join_invoice and maker_exists and "accountant_invoice_id" in maker_cols
            maker_select = "null as maker_id,null as maker_status"
            maker_join = ""
            if can_join_maker:
                maker_select = f"{_col('m',maker_cols,'id',as_name='maker_id')},{_col('m',maker_cols,'status',as_name='maker_status')}"
                maker_join = f"left join lateral (select * from bgn_makers x where x.accountant_invoice_id=i.id order by {_order('x',maker_cols)} limit 1) m on true"

            sql = f"""
                select {_col('s',sub_cols,'id',as_name='submission_id')},{_col('s',sub_cols,'production_cycle_id')},{_col('s',sub_cols,'site')},
                       {_col('s',sub_cols,'accountant_code')},{_col('s',sub_cols,'excel_evidence_uri')},{_col('s',sub_cols,'sent_at')},
                       {_col('s',sub_cols,'status',as_name='submission_status')},{_col('s',sub_cols,'source_planning_snapshot_id')},
                       {_col('s',sub_cols,'source_calculator_document_id')},{_col('s',sub_cols,'source_plan_name')},{_col('s',sub_cols,'source_distribution_date')},
                       {_col('s',sub_cols,'generated_filename')},{_col('s',sub_cols,'drive_upload_status')},{_col('s',sub_cols,'drive_upload_error')},
                       {_col('s',sub_cols,'updated_at',as_name='submission_updated_at')},{invoice_select},{maker_select}
                from accountant_submissions s {invoice_join} {maker_join} where true
            """
            params: list[Any] = []
            if site and "site" in sub_cols:
                sql += " and upper(s.site)=upper(%s)"; params.append(site)
            sql += f" order by {_order('s',sub_cols)} limit 250"
            cur.execute(sql, params); rows = cur.fetchall()
    return {"items": rows, "count": len(rows), "legacyMakerLinksRepaired": repaired}


@router.get("/accountant-flow-v2")
def accountant_flow_v2(site: str = "") -> dict[str, Any]:
    """Read the Excel queue independently from the Maker/BGN schema.

    Older production databases can have partially migrated invoice and maker
    tables.  The Excel queue must remain usable because it is the entry point
    for uploading the accountant response.  Submissions and invoices are read
    separately here, then joined in Python using only columns that exist.
    """
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            if not _table_exists(cur, "accountant_submissions"):
                return {
                    "items": [],
                    "count": 0,
                    "schemaWarning": "accountant_submissions table is not available",
                }

            sub_cols = _columns(cur, "accountant_submissions")
            submission_select = ",".join([
                _col("s", sub_cols, "id", as_name="submission_id"),
                _col("s", sub_cols, "production_cycle_id"),
                _col("s", sub_cols, "site"),
                _col("s", sub_cols, "accountant_code"),
                _col("s", sub_cols, "excel_evidence_uri"),
                _col("s", sub_cols, "sent_at"),
                _col("s", sub_cols, "status", as_name="submission_status"),
                _col("s", sub_cols, "source_planning_snapshot_id"),
                _col("s", sub_cols, "source_calculator_document_id"),
                _col("s", sub_cols, "source_plan_name"),
                _col("s", sub_cols, "source_distribution_date"),
                _col("s", sub_cols, "generated_filename"),
                _col("s", sub_cols, "drive_upload_status"),
                _col("s", sub_cols, "drive_upload_error"),
                _col("s", sub_cols, "updated_at", as_name="submission_updated_at"),
            ])
            sql = f"select {submission_select} from accountant_submissions s where true"
            params: list[Any] = []
            if site and "site" in sub_cols:
                sql += " and upper(cast(s.site as text))=upper(%s)"
                params.append(site)
            sql += f" order by {_order('s', sub_cols)} limit 250"
            cur.execute(sql, params)
            rows = [dict(row) for row in cur.fetchall()]

            invoice_by_submission: dict[Any, dict[str, Any]] = {}
            submission_ids = [row.get("submission_id") for row in rows if row.get("submission_id") is not None]
            if submission_ids and _table_exists(cur, "accountant_invoices"):
                inv_cols = _columns(cur, "accountant_invoices")
                if "accountant_submission_id" in inv_cols:
                    invoice_select = ",".join([
                        _col("i", inv_cols, "accountant_submission_id"),
                        _col("i", inv_cols, "id", as_name="invoice_id"),
                        _col("i", inv_cols, "invoice_number"),
                        _col("i", inv_cols, "invoice_amount"),
                        _col("i", inv_cols, "invoice_evidence_uri"),
                        _col("i", inv_cols, "received_at"),
                    ])
                    cur.execute(
                        f"""select {invoice_select}
                            from accountant_invoices i
                            where i.accountant_submission_id = any(%s)
                            order by {_order('i', inv_cols)}""",
                        (submission_ids,),
                    )
                    for invoice in cur.fetchall():
                        key = invoice.get("accountant_submission_id")
                        if key is not None and key not in invoice_by_submission:
                            invoice_by_submission[key] = dict(invoice)

    for row in rows:
        invoice = invoice_by_submission.get(row.get("submission_id"), {})
        row.update({
            "invoice_id": invoice.get("invoice_id"),
            "invoice_number": invoice.get("invoice_number"),
            "invoice_amount": invoice.get("invoice_amount"),
            "invoice_evidence_uri": invoice.get("invoice_evidence_uri"),
            "received_at": invoice.get("received_at"),
            "maker_id": None,
            "maker_status": None,
        })
    return {"items": rows, "count": len(rows), "mode": "SCHEMA_TOLERANT_SEPARATE_READS"}


@router.get("/bgn-flow")
def bgn_flow(site: str = "") -> dict[str, Any]:
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            repaired = _try_backfill_legacy_maker_links(cur)
            if repaired:
                conn.commit()
            if not _table_exists(cur, "bgn_makers"):
                return {"items": [], "count": 0, "schemaWarning": "bgn_makers table is not available"}
            maker_cols = _columns(cur, "bgn_makers")
            appr_exists = _table_exists(cur, "bgn_approvals")
            appr_cols = _columns(cur, "bgn_approvals") if appr_exists else set()
            receipt_exists = _table_exists(cur, "bgn_receipts")
            receipt_cols = _columns(cur, "bgn_receipts") if receipt_exists else set()

            approval_select = "null as approval_id,null as approver_code,null as approval_status,null as requested_at,null as approved_at,null as rejected_at,null as approval_evidence_uri,null as approval_method"
            approval_join = ""
            if appr_exists and "bgn_maker_id" in appr_cols:
                approval_select = f"{_col('a',appr_cols,'id',as_name='approval_id')},{_col('a',appr_cols,'approver_code')},{_col('a',appr_cols,'status',as_name='approval_status')},{_col('a',appr_cols,'requested_at')},{_col('a',appr_cols,'approved_at')},{_col('a',appr_cols,'rejected_at')},{_col('a',appr_cols,'evidence_uri',as_name='approval_evidence_uri')},{_col('a',appr_cols,'approval_method')}"
                approval_join = f"left join lateral (select * from bgn_approvals x where x.bgn_maker_id=m.id order by {_order('x',appr_cols)} limit 1) a on true"

            receipt_select = "null as receipt_id,null as receipt_amount,null as payment_received_at,null as payment_evidence_uri"
            receipt_join = ""
            if receipt_exists and "bgn_maker_id" in receipt_cols:
                receipt_select = f"{_col('r',receipt_cols,'id',as_name='receipt_id')},{_col('r',receipt_cols,'amount',as_name='receipt_amount')},{_col('r',receipt_cols,'received_at',as_name='payment_received_at')},{_col('r',receipt_cols,'evidence_uri',as_name='payment_evidence_uri')}"
                receipt_join = f"left join lateral (select * from bgn_receipts x where x.bgn_maker_id=m.id order by {_order('x',receipt_cols)} limit 1) r on true"

            sql = f"""
                select {_col('m',maker_cols,'id',as_name='maker_id')},{_col('m',maker_cols,'production_cycle_id')},{_col('m',maker_cols,'accountant_invoice_id')},
                       {_col('m',maker_cols,'site')},{_col('m',maker_cols,'reference_number')},{_col('m',maker_cols,'amount',as_name='maker_amount')},
                       {_col('m',maker_cols,'status',as_name='maker_status')},{_col('m',maker_cols,'created_at',as_name='maker_created_at')},
                       {approval_select},{receipt_select}
                from bgn_makers m {approval_join} {receipt_join} where true
            """
            params: list[Any] = []
            if site and "site" in maker_cols:
                sql += " and upper(m.site)=upper(%s)"; params.append(site)
            sql += f" order by {_order('m',maker_cols)} limit 250"
            cur.execute(sql, params); rows = cur.fetchall()
    return {"items": rows, "count": len(rows), "legacyMakerLinksRepaired": repaired}
