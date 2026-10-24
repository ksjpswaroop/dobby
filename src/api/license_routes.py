"""
Licensing API.

Two roles share this router today, clearly separated by path prefix, because
there is only one running process in development:

* `/license/verify` and `/license/issue` are the **authority** — signature +
  revocation checks and key minting. At real launch these move to a separate
  server and this router shrinks to just the client routes below.
* `/license/status`, `/license/activate`, `/license/deactivate` are the
  **client** — what the desktop app actually calls.
"""

from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.db.schema import DatabaseManager
from src.licensing import authority, client as license_client

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/license", tags=["Licensing"])


def get_db() -> DatabaseManager:
    from src.main import app

    return app.state.db


# ---------------------------------------------------------------------------
# Authority routes (dev-mode; move to a real server at launch)
# ---------------------------------------------------------------------------
class IssueRequest(BaseModel):
    tier: str
    email: str = ""
    seats: int = 1
    update_days: Optional[int] = 365


@router.post("/issue")
async def issue_license(req: IssueRequest, db: DatabaseManager = Depends(get_db)):
    try:
        return authority.issue(db, req.tier, req.email, req.seats, req.update_days)
    except authority.LicenseError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{license_id}")
async def revoke_license(license_id: str, db: DatabaseManager = Depends(get_db)):
    if not authority.revoke(db, license_id):
        raise HTTPException(status_code=404, detail="License not found")
    return {"success": True}


class VerifyRequest(BaseModel):
    token: str = Field(..., min_length=1)


@router.post("/verify")
async def verify_license(req: VerifyRequest, db: DatabaseManager = Depends(get_db)):
    """What the client's `check()` calls. Never 4xx/5xx on an invalid token —
    invalidity is a normal, expected result, not an error."""
    try:
        return authority.verify(db, req.token)
    except authority.LicenseError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# Client routes
# ---------------------------------------------------------------------------
class ActivateRequest(BaseModel):
    token: str = Field(..., min_length=1)


@router.get("/status")
async def license_status():
    """Cached status, no network call — for a fast Settings render."""
    return license_client.status()


@router.post("/activate")
async def activate_license(req: ActivateRequest):
    try:
        license_client.activate(req.token)
    except authority.LicenseError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return await license_client.check()


@router.post("/deactivate")
async def deactivate_license():
    license_client.deactivate()
    return {"success": True}


@router.post("/check")
async def check_license():
    """Force a fresh online re-verification now, rather than the cached status."""
    return await license_client.check()
