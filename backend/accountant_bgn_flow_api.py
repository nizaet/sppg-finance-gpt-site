from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from backend.db import connection, database_ready

router = APIRouter(prefix="/v1", tags=["accountant-bgn-flow"])


def require_db() -> None:
    from fastapi import HTTPException

    if not database_ready():
        raise HTTPException(503, "database unavailable")


def _table_exists(cur: Any, table_name: str) -> bool:
    cur.execute("select to_regclass(%s) is not null as exists", (table_name,))
    return bool(cur.fetchone()["exists"])


def _columns(cur: Any, table_name: str) -> set[str]:
    cur.execute(
        """select column_name
           from information_schema.columns
           where table_schema='public' and table_name=%s""",
        (table_name,),
    )
    return {str(row["column_name"]) for row in cur.fetchall()}


def _col(alias: str, columns: set[str], name: str, *, as_name: str | None = None, default: str = "null") -> str:
    output = as_name or name
    if name in columns:
        return f"{alias}.{name} as {output}"
    return f"{default} as {output}"


def _order(alias: str, columns: set[str]) -> str:
    if "created_at" in columns:
        return f"{alias}.created_at desc"
    if "id" in columns:
        return f"{alias}.id desc"
    return "1"


@router.get("/accountant-flow")
def accountant_flow(site: str = "") -> dict[str, Any]:
    """Read accountant submissions without assuming every Railway DB has all new columns."""
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            if not _table_exists(cur, "accountant_submissions"):
                return {"items": [], "count": 0, "schemaWarning": "accountant_submissions table is not available"}
            sub_cols = _columns(cur, "accountant_submissions")
            inv_exists = _table_exists(cur, "accountant_invoices")
            inv_cols = _columns(cur, "accountant_invoices") if inv_exists else set()
            can_join_invoice = inv_exists and "accountant_submission_id" in inv_cols

            invoice_select = """
                       null as invoice_id, null as invoice_number, null as invoice_amount,
                       null as invoice_evidence_uri, null as received_at
            """
            invoice_join = ""
            if can_join_invoice:
                invoice_select = f"""
                       {_col('i', inv_cols, 'id', as_name='invoice_id')},
                       {_col('i', inv_cols, 'invoice_number')},
                       {_col('i', inv_cols, 'invoice_amount')},
                       {_col('i', inv_cols, 'invoice_evidence_uri')},
                       {_col('i', inv_cols, 'received_at')}
                """
                invoice_join = "left join accountant_invoices i on i.accountant_submission_id=s.id"

            sql = f"""
                select {_col('s', sub_cols, 'id', as_name='submission_id')},
                       {_col('s', sub_cols, 'production_cycle_id')},
                       {_col('s', sub_cols, 'site')},
                       {_col('s', sub_cols, 'accountant_code')},
                       {_col('s', sub_cols, 'excel_evidence_uri')},
                       {_col('s', sub_cols, 'sent_at')},
                       {_col('s', sub_cols, 'status', as_name='submission_status')},
                       {_col('s', sub_cols, 'source_planning_snapshot_id')},
                       {_col('s', sub_cols, 'generated_filename')},
                       {invoice_select}
                from accountant_submissions s
                {invoice_join}
                where true
            """
            params: list[Any] = []
            if site and "site" in sub_cols:
                sql += " and upper(s.site)=upper(%s)"
                params.append(site)
            sql += f" order by {_order('s', sub_cols)} limit 250"
            cur.execute(sql, params)
            rows = cur.fetchall()
    return {"items": rows, "count": len(rows)}


@router.get("/bgn-flow")
def bgn_flow(site: str = "") -> dict[str, Any]:
    """Read BGN maker/approval state while tolerating partial legacy schemas."""
    require_db()
    with connection() as conn:
        with conn.cursor() as cur:
            if not _table_exists(cur, "bgn_makers"):
                return {"items": [], "count": 0, "schemaWarning": "bgn_makers table is not available"}
            maker_cols = _columns(cur, "bgn_makers")
            appr_exists = _table_exists(cur, "bgn_approvals")
            appr_cols = _columns(cur, "bgn_approvals") if appr_exists else set()
            can_join_approval = appr_exists and "bgn_maker_id" in appr_cols

            approval_select = """
                       null as approval_id, null as approver_code, null as approval_status,
                       null as requested_at, null as approved_at, null as rejected_at
            """
            approval_join = ""
            if can_join_approval:
                approval_order = _order("x", appr_cols)
                approval_select = f"""
                       {_col('a', appr_cols, 'id', as_name='approval_id')},
                       {_col('a', appr_cols, 'approver_code')},
                       {_col('a', appr_cols, 'status', as_name='approval_status')},
                       {_col('a', appr_cols, 'requested_at')},
                       {_col('a', appr_cols, 'approved_at')},
                       {_col('a', appr_cols, 'rejected_at')}
                """
                approval_join = f"""
                left join lateral (
                  select * from bgn_approvals x where x.bgn_maker_id=m.id order by {approval_order} limit 1
                ) a on true
                """

            sql = f"""
                select {_col('m', maker_cols, 'id', as_name='maker_id')},
                       {_col('m', maker_cols, 'production_cycle_id')},
                       {_col('m', maker_cols, 'site')},
                       {_col('m', maker_cols, 'reference_number')},
                       {_col('m', maker_cols, 'amount', as_name='maker_amount')},
                       {_col('m', maker_cols, 'status', as_name='maker_status')},
                       {_col('m', maker_cols, 'created_at', as_name='maker_created_at')},
                       {approval_select}
                from bgn_makers m
                {approval_join}
                where true
            """
            params: list[Any] = []
            if site and "site" in maker_cols:
                sql += " and upper(m.site)=upper(%s)"
                params.append(site)
            sql += f" order by {_order('m', maker_cols)} limit 250"
            cur.execute(sql, params)
            rows = cur.fetchall()
    return {"items": rows, "count": len(rows)}
