from __future__ import annotations

import io
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from googleapiclient.http import MediaIoBaseUpload

from backend.accountant_drive import AccountantDriveUploadError, _friendly_drive_error
from backend.google_services import drive_auth_mode, drive_service


def _drive_file_id(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("Drive file URI kosong")
    if re.fullmatch(r"[A-Za-z0-9_-]{10,}", raw):
        return raw
    match = re.search(r"/d/([A-Za-z0-9_-]+)", raw)
    if match:
        return match.group(1)
    parsed = urlparse(raw)
    query_id = (parse_qs(parsed.query).get("id") or [None])[0]
    if query_id:
        return str(query_id)
    raise ValueError("Drive file ID tidak dapat dibaca dari URI")


def replace_accountant_drive_file(
    *,
    drive_uri: str,
    filename: str,
    data: bytes,
    mime_type: str,
) -> dict[str, Any]:
    """Replace an existing accountant Drive file without changing its file ID/link."""
    file_id = _drive_file_id(drive_uri)
    media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime_type, resumable=False)
    try:
        updated = (
            drive_service()
            .files()
            .update(
                fileId=file_id,
                body={"name": filename},
                media_body=media,
                fields="id,webViewLink,name",
                supportsAllDrives=True,
            )
            .execute()
        )
    except Exception as exc:
        friendly, _ = _friendly_drive_error(exc)
        raise AccountantDriveUploadError(friendly, [{"fileId": file_id, "error": friendly}]) from exc

    uri = updated.get("webViewLink") or f"https://drive.google.com/file/d/{updated['id']}/view"
    return {
        "driveUri": uri,
        "fileId": updated["id"],
        "filename": updated.get("name") or filename,
        "driveAuthMode": drive_auth_mode(),
        "replacedExisting": True,
    }
