import os
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row


def database_url() -> str:
    value = os.getenv("DATABASE_URL", "").strip()
    if not value:
        raise RuntimeError("DATABASE_URL is not configured")
    return value


@contextmanager
def connection():
    conn = psycopg.connect(database_url(), row_factory=dict_row)
    try:
        yield conn
    finally:
        conn.close()


def database_ready() -> bool:
    if not os.getenv("DATABASE_URL", "").strip():
        return False
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute("select 1 as ok")
                return cur.fetchone()["ok"] == 1
    except Exception:
        return False
