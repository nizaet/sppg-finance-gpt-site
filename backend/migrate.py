from pathlib import Path

from backend.db import connection

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = [
    ROOT / "schema" / "staging_v05.sql",
    ROOT / "schema" / "core_domain_v05.sql",
]


def run() -> None:
    with connection() as conn:
        with conn.cursor() as cur:
            for path in MIGRATIONS:
                sql = path.read_text(encoding="utf-8")
                cur.execute(sql)
                print(f"applied: {path.relative_to(ROOT)}")
        conn.commit()


if __name__ == "__main__":
    run()
