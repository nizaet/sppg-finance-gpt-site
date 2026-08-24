from __future__ import annotations

import io
import json
import os
from functools import lru_cache
from typing import Any

from google.cloud import firestore
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials as UserCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import firebase_admin
from firebase_admin import auth as firebase_auth
from firebase_admin import credentials as firebase_credentials

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/drive",
]
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"

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


class FirestoreDocumentNotFound(RuntimeError):
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


@lru_cache(maxsize=1)
def firebase_admin_app():
    try:
        return firebase_admin.get_app("sppg-core")
    except ValueError:
        credential = firebase_credentials.Certificate(_service_account_info())
        return firebase_admin.initialize_app(
            credential,
            {"projectId": google_project_id()},
            name="sppg-core",
        )


def create_firebase_custom_token(uid: str, claims: dict[str, Any]) -> str:
    token = firebase_auth.create_custom_token(
        uid,
        developer_claims=claims,
        app=firebase_admin_app(),
    )
    return token.decode("utf-8") if isinstance(token, bytes) else str(token)


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


def assert_finance_transaction_exists(site: str, transaction_id: str) -> str:
    doc_ref = firestore_transaction_doc(site, transaction_id)
    snapshot = doc_ref.get()
    if not snapshot.exists:
        raise FirestoreDocumentNotFound(f"Firestore transaction document not found: {doc_ref.path}")
    return doc_ref.path


def upsert_finance_transaction(site: str, transaction_id: str, data: dict[str, Any]) -> str:
    doc_ref = firestore_transaction_doc(site, transaction_id)
    payload = dict(data)
    payload["id"] = transaction_id
    payload["updatedAt"] = firestore.SERVER_TIMESTAMP
    doc_ref.set(payload, merge=True)
    return doc_ref.path


def update_existing_finance_transaction(site: str, transaction_id: str, data: dict[str, Any]) -> str:
    """Update a known legacy Firestore transaction without ever creating a new document."""
    doc_ref = firestore_transaction_doc(site, transaction_id)
    snapshot = doc_ref.get()
    if not snapshot.exists:
        raise FirestoreDocumentNotFound(f"Firestore transaction document not found: {doc_ref.path}")
    payload = dict(data)
    payload["id"] = transaction_id
    payload["updatedAt"] = firestore.SERVER_TIMESTAMP
    doc_ref.set(payload, merge=True)
    return doc_ref.path


def _drive_oauth_info() -> dict[str, str]:
    """Load optional human-user OAuth credentials used only for Google Drive.

    Firestore/Firebase continue using the service account. Personal My Drive
    uploads must be owned by a human OAuth identity because service accounts do
    not have Drive storage quota.
    """
    raw = os.getenv("SPPG_GOOGLE_DRIVE_OAUTH_JSON", "").strip()
    parsed: dict[str, Any] = {}
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise GoogleServicesNotConfigured("SPPG_GOOGLE_DRIVE_OAUTH_JSON is not valid JSON") from exc
    return {
        "client_id": str(parsed.get("client_id") or os.getenv("SPPG_GOOGLE_DRIVE_OAUTH_CLIENT_ID", "")).strip(),
        "client_secret": str(parsed.get("client_secret") or os.getenv("SPPG_GOOGLE_DRIVE_OAUTH_CLIENT_SECRET", "")).strip(),
        "refresh_token": str(parsed.get("refresh_token") or os.getenv("SPPG_GOOGLE_DRIVE_OAUTH_REFRESH_TOKEN", "")).strip(),
        "token_uri": str(parsed.get("token_uri") or "https://oauth2.googleapis.com/token").strip(),
    }


@lru_cache(maxsize=1)
def drive_user_credentials():
    info = _drive_oauth_info()
    if not info["client_id"] and not info["client_secret"] and not info["refresh_token"]:
        return None
    if not info["client_id"] or not info["client_secret"] or not info["refresh_token"]:
        raise GoogleServicesNotConfigured(
            "Drive OAuth incomplete: client_id, client_secret, and refresh_token are all required"
        )
    return UserCredentials(
        token=None,
        refresh_token=info["refresh_token"],
        token_uri=info["token_uri"],
        client_id=info["client_id"],
        client_secret=info["client_secret"],
        scopes=[DRIVE_SCOPE],
    )


def drive_auth_mode() -> str:
    return "USER_OAUTH" if drive_user_credentials() is not None else "SERVICE_ACCOUNT"


@lru_cache(maxsize=1)
def drive_service():
    credentials = drive_user_credentials() or google_credentials()
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def upload_bytes_to_drive(folder_id: str, filename: str, data: bytes, mime_type: str) -> str:
    if not folder_id:
        raise GoogleServicesNotConfigured("Drive folder id is not configured")
    media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime_type, resumable=False)
    created = (
        drive_service()
        .files()
        .create(
            body={"name": filename, "parents": [folder_id]},
            media_body=media,
            fields="id,webViewLink",
            supportsAllDrives=True,
        )
        # Google API transport can occasionally close the TLS connection while
        # Railway is waiting for the response. The client retries SSL/socket
        # transport failures and retryable HTTP responses when num_retries is
        # set; without it a brief EOF becomes a user-facing 503 immediately.
        .execute(num_retries=3)
    )
    return created.get("webViewLink") or f"https://drive.google.com/file/d/{created['id']}/view"


def upload_text_to_drive(folder_id: str, filename: str, text: str, mime_type: str = "text/plain") -> str:
    return upload_bytes_to_drive(folder_id, filename, text.encode("utf-8"), mime_type)