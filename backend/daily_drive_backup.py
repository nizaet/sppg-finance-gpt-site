"""Daily full backup of SPPG calculator and operational data to Google Drive.

Run this module as a Railway Cron Job:
    python -m backend.daily_drive_backup

The job deliberately does not modify Firestore, PostgreSQL, or existing Drive
files. Each execution writes one timestamped ZIP snapshot and a matching
manifest into SPPG_DRIVE_BACKUP_FOLDER_ID.
"""

from __future__ import annotations

import hashlib
import tempfile
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
from backend.google_services import SITE_TARGETS, upload_bytes_to_drive, upload_file_to_drive

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
    public_collection = client.collection("artifacts").document(target["site_id"]).collection("public")
    public_documents = _export_collection(public_collection)
    documents_by_id = {str(document["id"]): document for document in public_documents}
    # The calculator's normal local backup is rooted at the public/data document.
    # Keep its data shape intact so local recovery can use one combined payload.
    primary_document = documents_by_id.get("data")
    primary_payload = dict((primary_document or {}).get("data") or {})
    if not primary_payload and len(public_documents) == 1:
        primary_payload = dict(public_documents[0].get("data") or {})

    master_data = primary_payload.get("masterData") or {}
    split_files = {
        "master-harga.json": {
            "format": "sppg-calculator-section-v1",
            "site": site,
            "section": "masterHarga",
            "data": {
                "masterData": master_data,
                "priceList": master_data.get("priceList", primary_payload.get("priceList", [])),
            },
        },
        "gramasi.json": {
            "format": "sppg-calculator-section-v1",
            "site": site,
            "section": "gramasi",
            "data": primary_payload.get("customGramasi", {}),
        },
        "resep.json": {
            "format": "sppg-calculator-section-v1",
            "site": site,
            "section": "resep",
            "data": primary_payload.get("recipes", {}),
        },
        "bumbu.json": {
            "format": "sppg-calculator-section-v1",
            "site": site,
            "section": "bumbu",
            "data": primary_payload.get("bumbuList", {}),
        },
        "rencana-harian.json": {
            "format": "sppg-calculator-section-v1",
            "site": site,
            "section": "rencanaHarian",
            "data": primary_payload.get("dailyPlans", {}),
        },
        "kalkulator-restore.json": primary_payload,
        # Keep every document/subcollection too; this is the forensic fallback
        # and protects data added by a future Calculator version.
        "firestore-snapshot.json": {
            "site": site,
            "firestoreProject": client.project,
            "databaseId": target["database_id"],
            "calculatorRoot": f"artifacts/{target['site_id']}/public",
            "documents": public_documents,
        },
    }
    # Finance ledger is separate from Calculator data; retain it for recovery
    # of invoice and accounting-side records stored in Firestore.
    ledger_root = client.collection("gpt_sites").document(target["site_id"])
    ledger_snapshot = ledger_root.get()
    split_files["operasional-finance-ledger.json"] = {
        "format": "sppg-firestore-site-ledger-v1",
        "site": site,
        "document": {
            "path": ledger_snapshot.reference.path,
            "id": ledger_snapshot.id,
            "data": _json_safe(ledger_snapshot.to_dict() or {}),
        },
        "subcollections": {
            child.id: _export_collection(child)
            for child in ledger_root.collections()
        },
    }
    return split_files


def iter_postgres_exports():
    """Yield one JSON payload per table to keep Railway memory bounded."""
    table_index: list[dict[str, Any]] = []
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
            for table in cur.fetchall():
                schema_name = str(table["table_schema"])
                table_name = str(table["table_name"])
                statement = sql.SQL("select to_jsonb(record) as row from {}.{} as record").format(
                    sql.Identifier(schema_name),
                    sql.Identifier(table_name),
                )
                cur.execute(statement)
                rows = [_json_safe(item["row"]) for item in cur.fetchall()]
                file_path = f"{schema_name}/{table_name}.json"
                table_index.append(
                    {
                        "schema": schema_name,
                        "table": table_name,
                        "rowCount": len(rows),
                        "path": file_path,
                    }
                )
                yield file_path, {
                    "format": "sppg-postgres-table-v1",
                    "schema": schema_name,
                    "table": table_name,
                    "rowCount": len(rows),
                    "rows": rows,
                }
            conn.rollback()
    yield "table-index.json", {
        "format": "sppg-postgres-table-index-v1",
        "tables": table_index,
    }

def build_backup(work_directory: str) -> tuple[str, dict[str, Any], str]:
    created_at = datetime.now(timezone.utc)
    local_stamp = created_at.astimezone(JAKARTA)
    batch = local_stamp.strftime("%Y-%m-%d_%H%M%S-WIB")
    archive_path = os.path.join(work_directory, f"SPPG_FULL_BACKUP_{batch}.zip")
    file_records: list[dict[str, Any]] = []

    def write_json(bundle: zipfile.ZipFile, path: str, payload: Any) -> None:
        data = _json_bytes(payload)
        bundle.writestr(path, data)
        file_records.append({"path": path, "bytes": len(data), "sha256": _sha256(data)})

    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        print(json.dumps({"status": "running", "stage": "firestore_maja"}), flush=True)
        for filename, payload in export_calculator_site("MAJA").items():
            write_json(bundle, f"calculator/maja/{filename}", payload)

        print(json.dumps({"status": "running", "stage": "firestore_cemplang"}), flush=True)
        for filename, payload in export_calculator_site("CEMPLANG").items():
            write_json(bundle, f"calculator/cemplang/{filename}", payload)

        print(json.dumps({"status": "running", "stage": "postgres"}), flush=True)
        for filename, payload in iter_postgres_exports():
            write_json(bundle, f"postgres/{filename}", payload)

        manifest = {
            "formatVersion": BACKUP_FORMAT_VERSION,
            "createdAt": created_at.isoformat(),
            "timezone": "Asia/Jakarta",
            "backupBatch": batch,
            "scope": {
                "calculator": [
                    "MAJA: separate master-harga, gramasi, resep, bumbu, rencana-harian, and restore JSON",
                    "CEMPLANG: separate master-harga, gramasi, resep, bumbu, rencana-harian, and restore JSON",
                ],
                "postgres": "all non-system tables, one JSON file per table",
            },
            "files": sorted(file_records, key=lambda item: item["path"]),
            "restoreNote": (
                "This is a read-only recovery snapshot. Restore only through a reviewed "
                "recovery procedure; never overwrite live data directly from this file."
            ),
        }
        print(json.dumps({"status": "running", "stage": "archive"}), flush=True)
        bundle.writestr("manifest.json", _json_bytes(manifest))

    return archive_path, manifest, batch

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
    with tempfile.TemporaryDirectory(prefix="sppg-backup-") as work_directory:
        archive_path, manifest, batch = build_backup(work_directory)
        archive_name = f"SPPG_FULL_BACKUP_{batch}.zip"
        manifest_name = f"SPPG_FULL_BACKUP_{batch}.manifest.json"
        archive_size = os.path.getsize(archive_path)

        print(json.dumps({"status": "running", "stage": "drive_upload"}), flush=True)
        archive_url = upload_file_to_drive(folder_id, archive_name, archive_path, "application/zip")
        manifest_url = upload_bytes_to_drive(
            folder_id,
            manifest_name,
            _json_bytes(manifest),
            "application/json; charset=utf-8",
        )
    result = {
        "status": "ok",
        "batch": batch,
        "archive": {"name": archive_name, "url": archive_url, "bytes": archive_size},
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
