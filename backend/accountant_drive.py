from __future__ import annotations

import os
from typing import Any

from backend.google_services import upload_bytes_to_drive

# Canonical folders already shared with the SPPG service account.
DEFAULT_ACCOUNTANT_EXCEL_FOLDER_ID = "1DDVtg6U7_2SI_iJVW5vk4UYPRIyiEvn6"  # 04 EXCEL AKUNTAN
DEFAULT_ACCOUNTANT_INVOICE_FOLDER_ID = "19EcARPcCBzvwQpcxSbxXGXifO7a-DfCX"  # 03_INVOICE_AKUNTAN


class AccountantDriveUploadError(RuntimeError):
    def __init__(self, message: str, attempts: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.attempts = attempts or []


def _candidate_folder_ids(env_name: str, fallback_id: str) -> list[str]:
    configured = os.getenv(env_name, "").strip()
    values: list[str] = []
    for value in (configured, fallback_id):
        if value and value not in values:
            values.append(value)
    return values


def upload_accountant_artifact(
    *,
    kind: str,
    filename: str,
    data: bytes,
    mime_type: str,
) -> dict[str, Any]:
    normalized = kind.strip().lower()
    if normalized == "excel":
        env_name = "SPPG_DRIVE_ACCOUNTANT_FOLDER_ID"
        fallback_id = DEFAULT_ACCOUNTANT_EXCEL_FOLDER_ID
    elif normalized == "invoice":
        env_name = "SPPG_DRIVE_ACCOUNTANT_INVOICE_FOLDER_ID"
        fallback_id = DEFAULT_ACCOUNTANT_INVOICE_FOLDER_ID
    else:
        raise ValueError(f"unsupported accountant artifact kind: {kind}")

    attempts: list[dict[str, Any]] = []
    for folder_id in _candidate_folder_ids(env_name, fallback_id):
        try:
            uri = upload_bytes_to_drive(folder_id, filename, data, mime_type)
            return {
                "driveUri": uri,
                "folderId": folder_id,
                "usedFallbackFolder": folder_id == fallback_id and os.getenv(env_name, "").strip() not in {"", fallback_id},
                "attempts": attempts,
            }
        except Exception as exc:  # Drive API errors vary by google client version.
            attempts.append({
                "folderId": folder_id,
                "errorType": type(exc).__name__,
                "error": str(exc)[:700],
            })

    detail = "; ".join(
        f"{row['folderId']}: {row['errorType']} {row['error']}" for row in attempts
    ) or "no Drive folder configured"
    raise AccountantDriveUploadError(f"Accountant Drive upload failed: {detail}", attempts)
