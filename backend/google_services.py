from __future__ import annotations

import io
import json
import os
from functools import lru_cache
from typing import Any

from google.cloud import firestore
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/drive",
]

SITE_TARGETS = {
    "MAJA": {
        "site_id": "sppg-maja-gpt-site",
        "database_id": "(default)",
    },
    "CEMPLANG": {
        "site_id": "sppg-cemplang2-gpt-site",
        "database_id": "cemplang2",
    },
}


class GoogleServicesNotConfigured(RuntimeError):
    pass


def _service_account_info() -> dict[str, Any]:
    raw = os.getenv("SPPG_GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        raise GoogleServicesNotConfigured("SPPG_GOOGLE_SERVICE_ACCOUNT_JSON is not configured")
    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GoogleServicesNotConfigured("SPPG_GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON") from exc
    if not info.get("client_email") or not info.get("private_key"):
        raise GoogleServicesNotConfigured("service account JSON is incomplete")
    return info


@lru_cache(maxsize=1)
def google_credentials():
    info = _service_account_info()
    return service_account.Credentials.from_service_account_info(info, scopes=GOOGLE_SCOPES)


def google_project_id() -> str:
    explicit = os.getenv("SPPG_FIRESTORE_PROJECT_ID", "").strip()
    if explicit:
        return explicit
    return str(_service_account_info().get("project_id") or "sppg-finance-gpt")


@lru_cache(maxsize=4)
def firestore_client(database_id: str):
    return firestore.Client(
        project=google_project_id(),
        credentials=google_credentials(),
        database=database_id,
    )


def firestore_transaction_doc(site: str, transaction_id: str):
    site_key = site.upper().strip()
    if site_key not in SITE_TARGETS:
        raise ValueError(f"unsupported site: {site}")
    target = SITE_TARGETS[site_key]
    client = firestore_client(target["database_id"])
    return (
        client.collection("gpt_sites")
        .document(target["site_id"])
        .collection("ledger")
        .document("meta")
        .collection("transactions")
        .document(transaction_id)
    )


def upsert_finance_transaction(site: str, transaction_id: str, data: dict[str, Any]) -> str:
    doc_ref = firestore_transaction_doc(site, transaction_id)
    payload = dict(data)
    payload["id"] = transaction_id
    payload["updatedAt"] = firestore.SERVER_TIMESTAMP
    doc_ref.set(payload, merge=True)
    return doc_ref.path


@lru_cache(maxsize=1)
def drive_service():
    return build("drive", "v3", credentials=google_credentials(), cache_discovery=False)


def upload_text_to_drive(folder_id: str, filename: str, text: str, mime_type: str = "text/plain") -> str:
    if not folder_id:
        raise GoogleServicesNotConfigured("Drive folder id is not configured")
    media = MediaIoBaseUpload(io.BytesIO(text.encode("utf-8")), mimetype=mime_type, resumable=False)
    created = (
        drive_service()
        .files()
        .create(
            body={"name": filename, "parents": [folder_id]},
            media_body=media,
            fields="id,webViewLink",
            supportsAllDrives=True,
        )
        .execute()
    )
    return created.get("webViewLink") or f"https://drive.google.com/file/d/{created['id']}/view"
