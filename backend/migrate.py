import hashlib
from pathlib import Path

from backend.db import connection

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = [
    ROOT / "schema" / "reference_master_v09.sql",
    ROOT / "schema" / "reference_seed_v09.sql",
    ROOT / "schema" / "staging_v05.sql",
    ROOT / "schema" / "core_domain_v05.sql",
    ROOT / "schema" / "planning_bridge_v010.sql",
    ROOT / "schema" / "operational_receiving_v012.sql",
    ROOT / "schema" / "vendor_payables_v013.sql",
    ROOT / "schema" / "operational_rules_v014.sql",
    ROOT / "schema" / "inventory_ledger_v014.sql",
    ROOT / "schema" / "vendor_invoice_reconciliation_v015.sql",
    ROOT / "schema" / "vendor_payment_workflow_v016.sql",
    ROOT / "schema" / "operational_history_provenance_v017.sql",
    ROOT / "schema" / "whatsapp_ingress_v018.sql",
    ROOT / "schema" / "operational_rules_v019.sql",
    ROOT / "schema" / "accountant_excel_v020.sql",
    ROOT / "schema" / "inventory_stock_opname_v021.sql",
    ROOT / "schema" / "calculator_data_control_v022.sql",
    ROOT / "schema" / "calculator_shared_master_v023.sql",
    ROOT / "schema" / "purchase_order_coverage_v024.sql",
    ROOT / "schema" / "inventory_stock_opname_lifecycle_v025.sql",
    ROOT / "schema" / "po_reminder_rules_v026.sql",
    ROOT / "schema" / "po_reminder_overrides_v027.sql",
    ROOT / "schema" / "po_reminder_review_resolution_v028.sql",
    ROOT / "schema" / "vendor_payment_unreconciled_v029.sql",
    ROOT / "schema" / "accountant_plan_selection_v030.sql",
    ROOT / "schema" / "llm_conversation_memory_v031.sql",
    ROOT / "schema" / "accountant_source_freshness_v032.sql",
    ROOT / "schema" / "manual_receipt_match_backfill_v033.sql",
    ROOT / "schema" / "finance_ledger_v011.sql",
]


def checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run() -> None:
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                create table if not exists schema_migrations (
                  migration_name text primary key,
                  checksum text not null,
                  applied_at timestamptz not null default now()
                )
                """
            )
            for path in MIGRATIONS:
                sql = path.read_text(encoding="utf-8")
                name = str(path.relative_to(ROOT))
                digest = checksum(sql)
                cur.execute("select checksum from schema_migrations where migration_name=%s", (name,))
                row = cur.fetchone()
                if row and row["checksum"] == digest:
                    print(f"skip unchanged: {name}")
                    continue
                cur.execute(sql)
                cur.execute(
                    """
                    insert into schema_migrations(migration_name, checksum)
                    values (%s, %s)
                    on conflict (migration_name)
                    do update set checksum=excluded.checksum, applied_at=now()
                    """,
                    (name, digest),
                )
                print(f"applied: {name}")
        conn.commit()


if __name__ == "__main__":
    run()
