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
