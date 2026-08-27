"""Daily full backup of SPPG calculator and operational data to Google Drive.

Run this module as a Railway Cron Job:
    python -m backend.daily_drive_backup

The job deliberately does not modify Firestore, PostgreSQL, or existing Drive
files. Each execution writes one timestamped ZIP snapshot and a matching
manifest into SPPG_DRIVE_BACKUP_FOLDER_ID.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import zipfile
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from psycopg import sql

from backend.db import connection
from backend.google_services import SITE_TARGETS, upload_bytes_to_drive

JAKARTA = ZoneInfo("Asia/Jakarta")
BACKUP_FORMAT_VERSION = 1


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return {"encoding": "base64-unavailable", "length": len(value)}
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(
        _json_safe(payload),
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    ).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _export_collection(collection_ref) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for snapshot in collection_ref.stream():
        document: dict[str, Any] = {
            "path": snapshot.reference.path,
            "id": snapshot.id,
            "data": _json_safe(snapshot.to_dict() or {}),
            "subcollections": {},
        }
        for child_collection in snapshot.reference.collections():
            document["subcollections"][child_collection.id] = _export_collection(child_collection)
        documents.append(document)
    return documents


def export_calculator_site(site: str) -> dict[str, Any]:
    target = SITE_TARGETS[site]
    from backend.google_services import firestore_client

    client = firestore_client(target["database_id"])
    # This exact root contains priceList, customGramasi, recipes, bumbuList,
    # and dailyPlans used by the calculator.
    public_collection = client.collection("artifacts").document(target["site_id"]).collection("public")
    public_documents = _export_collection(public_collection)
    return {
        "site": site,
        "firestoreProject": client.project,
        "databaseId": target["database_id"],
        "calculatorRoot": f"artifacts/{target['site_id']}/public",
        "documents": public_documents,
    }


def export_postgres() -> dict[str, Any]:
    exported_tables: list[dict[str, Any]] = []
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            cur.execute(
                """
                select table_schema, table_name
                from information_schema.tables
                where table_type = 'BASE TABLE'
                  and table_schema not in ('pg_catalog', 'information_schema')
                order by table_schema, table_name
                """
            )
            tables = cur.fetchall()
            for table in tables:
                schema_name = str(table["table_schema"])
                table_name = str(table["table_name"])
                statement = sql.SQL("select to_jsonb(record) as row from {}.{} as record").format(
                    sql.Identifier(schema_name),
                    sql.Identifier(table_name),
                )
                cur.execute(statement)
                rows = [_json_safe(item["row"]) for item in cur.fetchall()]
                exported_tables.append(
                    {
                        "schema": schema_name,
                        "table": table_name,
                        "rowCount": len(rows),
                        "rows": rows,
                    }
                )
            conn.rollback()
    return {
        "format": "postgres-json-snapshot-v1",
        "tables": exported_tables,
    }


def build_backup() -> tuple[bytes, dict[str, Any], str]:
    created_at = datetime.now(timezone.utc)
    local_stamp = created_at.astimezone(JAKARTA)
    batch = local_stamp.strftime("%Y-%m-%d_%H%M%S-WIB")

    files: dict[str, bytes] = {}
    print(json.dumps({"status": "running", "stage": "firestore_maja"}), flush=True)
    files["calculator/maja.json"] = _json_bytes(export_calculator_site("MAJA"))
    print(json.dumps({"status": "running", "stage": "firestore_cemplang"}), flush=True)
    files["calculator/cemplang.json"] = _json_bytes(export_calculator_site("CEMPLANG"))
    print(json.dumps({"status": "running", "stage": "postgres"}), flush=True)
    files["postgres/public.json"] = _json_bytes(export_postgres())
    print(json.dumps({"status": "running", "stage": "archive"}), flush=True)
    manifest = {
        "formatVersion": BACKUP_FORMAT_VERSION,
        "createdAt": created_at.isoformat(),
        "timezone": "Asia/Jakarta",
        "backupBatch": batch,
        "scope": {
            "calculator": [
                "MAJA: prices, gramasi, recipes, bumbu, all daily plans",
                "CEMPLANG: prices, gramasi, recipes, bumbu, all daily plans",
            ],
            "postgres": "all non-system tables",
        },
        "files": [
            {
                "path": path,
                "bytes": len(data),
                "sha256": _sha256(data),
            }
            for path, data in sorted(files.items())
        ],
        "restoreNote": (
            "This is a read-only recovery snapshot. Restore only through a reviewed "
            "recovery procedure; never overwrite live data directly from this file."
        ),
    }
    files["manifest.json"] = _json_bytes(manifest)

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for path, data in files.items():
            bundle.writestr(path, data)

    return archive.getvalue(), manifest, batch


def run() -> dict[str, Any]:
    folder_id = os.getenv("SPPG_DRIVE_BACKUP_FOLDER_ID", "").strip()
    if not folder_id:
        raise RuntimeError("SPPG_DRIVE_BACKUP_FOLDER_ID is not configured")

    print(
        json.dumps(
            {
                "status": "started",
                "driveFolderConfigured": True,
                "databaseConfigured": bool(os.getenv("DATABASE_URL", "").strip()),
            }
        ),
        flush=True,
    )
    archive, manifest, batch = build_backup()
    archive_name = f"SPPG_FULL_BACKUP_{batch}.zip"
    manifest_name = f"SPPG_FULL_BACKUP_{batch}.manifest.json"

    archive_url = upload_bytes_to_drive(folder_id, archive_name, archive, "application/zip")
    manifest_url = upload_bytes_to_drive(
        folder_id,
        manifest_name,
        _json_bytes(manifest),
        "application/json; charset=utf-8",
    )
    result = {
        "status": "ok",
        "batch": batch,
        "archive": {"name": archive_name, "url": archive_url, "bytes": len(archive)},
        "manifest": {"name": manifest_name, "url": manifest_url},
    }
    print(json.dumps(result, ensure_ascii=False))
    return result


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise
