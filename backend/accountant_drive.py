from __future__ import annotations

import os
import re
from typing import Any

from backend.google_services import drive_auth_mode, ensure_drive_folder, upload_bytes_to_drive

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


def _friendly_drive_error(exc: Exception) -> tuple[str, bool]:
    raw = str(exc)
    lowered = raw.lower()
    if "service accounts do not have storage quota" in lowered or "storagequotaexceeded" in lowered:
        return (
            "Folder tujuan berada di My Drive pribadi, tetapi backend masih mengunggah sebagai Service Account. "
            "Service Account tidak memiliki kuota penyimpanan Drive. Hubungkan Drive sebagai USER_OAUTH "
            "(akun pemilik folder, mis. jack&bear@gmail.com) atau pindahkan folder ke Shared Drive. "
            f"Mode Drive backend saat ini: {drive_auth_mode()}.",
            True,
        )
    if "drive api has not been used" in lowered or "drive.googleapis.com" in lowered and "disabled" in lowered:
        match = re.search(r"project(?:=|\s+)(\d{6,})", raw, re.IGNORECASE)
        project_number = match.group(1) if match else "tidak terdeteksi"
        return (
            "Google Drive API belum aktif pada Google Cloud project "
            f"{project_number}. Aktifkan API drive.googleapis.com pada project credential SPPG, "
            "tunggu propagasi beberapa menit, lalu klik Coba Upload Drive Lagi.",
            True,
        )
    if "insufficient permissions" in lowered or "permission" in lowered and "403" in lowered:
        return (
            "Identitas Google Drive backend tidak memiliki izin tulis ke folder tujuan. "
            "Pastikan akun OAuth pemilik Drive atau service account memiliki akses Editor/Contributor.",
            False,
        )
    if any(marker in lowered for marker in (
        "unexpected_eof_while_reading", "unexpected eof while reading",
        "sslerror", "connection reset", "connection aborted", "timed out",
    )):
        return (
            "Koneksi ke Google Drive terputus sementara saat upload. Sistem sudah mencoba ulang otomatis 3 kali; "
            "data invoice belum dicatat bila upload Drive belum berhasil. Silakan coba upload kembali.",
            False,
        )
    return (raw[:900], False)


def upload_accountant_artifact(
    *,
    kind: str,
    filename: str,
    data: bytes,
    mime_type: str,
    site: str | None = None,
    bucket: str | None = None,
) -> dict[str, Any]:
    normalized = kind.strip().lower()
    if normalized == "excel":
        env_name = "SPPG_DRIVE_ACCOUNTANT_FOLDER_ID"
        fallback_id = DEFAULT_ACCOUNTANT_EXCEL_FOLDER_ID
    elif normalized in {"invoice", "approval", "paid"}:
        env_name = "SPPG_DRIVE_ACCOUNTANT_INVOICE_FOLDER_ID"
        fallback_id = DEFAULT_ACCOUNTANT_INVOICE_FOLDER_ID
    else:
        raise ValueError(f"unsupported accountant artifact kind: {kind}")

    attempts: list[dict[str, Any]] = []
    for folder_id in _candidate_folder_ids(env_name, fallback_id):
        try:
            target_folder_id = folder_id
            drive_path = None
            site_key = str(site or "").strip().upper()
            if site_key in {"MAJA", "CEMPLANG"}:
                artifact_bucket = str(bucket or normalized).strip().upper().replace(" ", "_")
                artifact_bucket = {
                    "EXCEL": "EXCEL",
                    "INVOICE": "INVOICE",
                    "APPROVAL": "BUKTI_APPROVAL",
                    "PAID": "BUKTI_PAID",
                }.get(artifact_bucket, artifact_bucket)
                site_folder_id = ensure_drive_folder(folder_id, site_key)
                target_folder_id = ensure_drive_folder(site_folder_id, artifact_bucket)
                drive_path = f"{site_key}/{artifact_bucket}"
            uri = upload_bytes_to_drive(target_folder_id, filename, data, mime_type)
            return {
                "driveUri": uri,
                "folderId": target_folder_id,
                "rootFolderId": folder_id,
                "drivePath": drive_path,
                "driveAuthMode": drive_auth_mode(),
                "usedFallbackFolder": folder_id == fallback_id and os.getenv(env_name, "").strip() not in {"", fallback_id},
                "attempts": attempts,
            }
        except Exception as exc:  # Drive API errors vary by google client version.
            friendly, global_configuration_error = _friendly_drive_error(exc)
            attempts.append({
                "folderId": folder_id,
                "errorType": type(exc).__name__,
                "error": friendly,
            })
            # Disabled API and service-account storage quota are global for the
            # credential; trying a second personal folder cannot fix them.
            if global_configuration_error:
                raise AccountantDriveUploadError(friendly, attempts) from exc

    detail = "; ".join(
        f"{row['folderId']}: {row['errorType']} {row['error']}" for row in attempts
    ) or "no Drive folder configured"
    raise AccountantDriveUploadError(f"Accountant Drive upload failed: {detail}", attempts)
