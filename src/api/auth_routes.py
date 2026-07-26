"""
Handshake endpoint — how the app's own frontend obtains the launch token.

Deliberately the only unauthenticated route that returns a secret. Its safety
rests on CORS rather than on the request itself: a hostile page can *send* this
request, but the browser will refuse to let it *read* the response unless its
origin is one of ours. An untrusted origin is rejected outright so the failure
is explicit rather than a silent CORS error in someone's console.
"""

import structlog
from fastapi import APIRouter, HTTPException, Request

from src.security.tokens import get_token_manager, origin_is_trusted

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])


@router.get("/handshake")
async def handshake(request: Request):
    """Return this launch's API token to a first-party caller."""
    origin = request.headers.get("origin")
    if not origin_is_trusted(origin):
        logger.warning("handshake_rejected", origin=origin)
        raise HTTPException(
            status_code=403,
            detail="This origin is not allowed to obtain an API token.",
        )
    return {
        "token": get_token_manager().token,
        "scheme": "Bearer",
        # So the client knows to re-handshake rather than cache across launches.
        "ephemeral": True,
    }
