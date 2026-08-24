from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Header, HTTPException

from backend.auth_api import session_role
from backend.google_services import GoogleServicesNotConfigured, create_firebase_custom_token


router = APIRouter(prefix="/firebase", tags=["firebase-auth"])


@router.get("/custom-token")
def firebase_custom_token(
    site: Literal["MAJA", "CEMPLANG"],
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    role = session_role(authorization)
    if role != "OWNER" and role != site:
        raise HTTPException(403, f"akun {role} tidak boleh membuka Firebase {site}")
    uid = f"sppg-{role.lower()}-{site.lower()}"
    try:
        token = create_firebase_custom_token(uid, {
            "sppg_role": role,
            "sppg_site": site,
        })
    except GoogleServicesNotConfigured as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"Firebase custom token gagal dibuat: {type(exc).__name__}") from exc
    return {"token": token, "role": role, "site": site}
