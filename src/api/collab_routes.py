"""
Collaboration API (Phase 7: D61-D70).

`/api/v1/shared/{token}` is deliberately in the auth-gate's open-path list:
a share link is *for* people who have no account on this install. The safety
comes from the token being high-entropy, hashed at rest, revocable, expirable,
and — most importantly — from `resolve_share` having no write path at all.
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, Field

from src.db.collab_models import ROLE_CAPABILITIES, ROLES
from src.db.schema import DatabaseManager
from src.services import collab_service as svc
from src.services import publish_service as pub

router = APIRouter(prefix="/api/v1/collab", tags=["Collaboration"])


def get_db() -> DatabaseManager:
    from src.main import app

    return app.state.db


def current_member(db: DatabaseManager,
                   authorization: Optional[str]) -> Optional[Dict[str, Any]]:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    return svc.member_from_token(db, authorization.split(" ", 1)[1].strip())


class InviteBody(BaseModel):
    project_id: str
    email: str
    display_name: str = ""
    role: str = "viewer"


class AcceptBody(BaseModel):
    invite_token: str
    password: str = Field(..., min_length=8)


class SignInBody(BaseModel):
    email: str
    password: str


class RoleBody(BaseModel):
    role: str


class ShareBody(BaseModel):
    project_id: str
    node_id: Optional[str] = None
    label: str = ""
    expires_in_days: Optional[int] = 30


class ReviewBody(BaseModel):
    project_id: str
    node_id: str
    reviewer_id: str
    note: str = ""


class ReviewResponse(BaseModel):
    state: str
    response: str = ""


class PresenceBody(BaseModel):
    project_id: str
    member_id: str
    display_name: str = ""
    node_id: Optional[str] = None


class MentionScan(BaseModel):
    project_id: str
    text: str
    source: str = "comment"
    source_id: str = ""
    node_id: str = ""


@router.get("/meta")
async def meta():
    return {"roles": list(ROLES),
            "capabilities": {r: sorted(c) for r, c in ROLE_CAPABILITIES.items()}}


# --- Members & auth (D63) ----------------------------------------------------
@router.get("/members/{project_id}")
async def list_members(project_id: str, db: DatabaseManager = Depends(get_db)):
    return {"members": svc.list_members(db, project_id)}


@router.post("/members/invite")
async def invite(req: InviteBody, db: DatabaseManager = Depends(get_db)):
    try:
        return svc.invite_member(db, req.project_id, req.email,
                                 req.display_name, req.role)
    except svc.CollabError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/members/accept")
async def accept(req: AcceptBody, db: DatabaseManager = Depends(get_db)):
    try:
        return svc.accept_invite(db, req.invite_token, req.password)
    except svc.CollabError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/auth/sign-in")
async def sign_in(req: SignInBody, db: DatabaseManager = Depends(get_db)):
    try:
        return svc.sign_in(db, req.email, req.password)
    except svc.CollabError as e:
        raise HTTPException(status_code=401, detail=str(e))


@router.get("/auth/me")
async def me(authorization: Optional[str] = Header(None),
             db: DatabaseManager = Depends(get_db)):
    member = current_member(db, authorization)
    if not member:
        raise HTTPException(status_code=401, detail="Not signed in")
    return member


@router.post("/auth/sign-out")
async def sign_out(authorization: Optional[str] = Header(None),
                   db: DatabaseManager = Depends(get_db)):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Not signed in")
    svc.sign_out(db, authorization.split(" ", 1)[1].strip())
    return {"success": True}


@router.put("/members/{project_id}/{member_id}/role")
async def set_role(project_id: str, member_id: str, req: RoleBody,
                   db: DatabaseManager = Depends(get_db)):
    try:
        return svc.set_role(db, project_id, member_id, req.role)
    except svc.CollabError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/members/{project_id}/{member_id}")
async def remove_member(project_id: str, member_id: str,
                        db: DatabaseManager = Depends(get_db)):
    try:
        if not svc.remove_member(db, project_id, member_id):
            raise HTTPException(status_code=404, detail="Not a member")
    except svc.CollabError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"success": True}


# --- Share links (D62) -------------------------------------------------------
@router.get("/share/{project_id}")
async def list_links(project_id: str, db: DatabaseManager = Depends(get_db)):
    return {"links": svc.list_share_links(db, project_id)}


@router.post("/share")
async def create_link(req: ShareBody, db: DatabaseManager = Depends(get_db)):
    try:
        return svc.create_share_link(db, req.project_id, req.node_id,
                                     req.label, req.expires_in_days)
    except svc.CollabError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/share/{link_id}")
async def revoke_link(link_id: str, db: DatabaseManager = Depends(get_db)):
    if not svc.revoke_share_link(db, link_id):
        raise HTTPException(status_code=404, detail="Link not found or already revoked")
    return {"success": True}


# --- Reviews (D65) -----------------------------------------------------------
@router.get("/reviews/{project_id}")
async def list_reviews(project_id: str, reviewer_id: Optional[str] = None,
                       state: Optional[str] = None,
                       db: DatabaseManager = Depends(get_db)):
    return {"reviews": svc.list_reviews(db, project_id, reviewer_id, state)}


@router.post("/reviews")
async def request_review(req: ReviewBody, authorization: Optional[str] = Header(None),
                         db: DatabaseManager = Depends(get_db)):
    member = current_member(db, authorization)
    try:
        return svc.request_review(db, req.project_id, req.node_id, req.reviewer_id,
                                  req.note, member["id"] if member else "")
    except svc.CollabError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/reviews/{review_id}/respond")
async def respond(review_id: str, req: ReviewResponse,
                  authorization: Optional[str] = Header(None),
                  db: DatabaseManager = Depends(get_db)):
    member = current_member(db, authorization)
    try:
        return svc.respond_to_review(db, review_id, req.state, req.response,
                                     member["id"] if member else "")
    except svc.PermissionDenied as e:
        raise HTTPException(status_code=403, detail=str(e))
    except svc.CollabError as e:
        code = 404 if "not found" in str(e).lower() else 409
        raise HTTPException(status_code=code, detail=str(e))


# --- Mentions (D70) ----------------------------------------------------------
@router.get("/mentions/{member_id}")
async def mentions(member_id: str, unread_only: bool = False,
                   db: DatabaseManager = Depends(get_db)):
    return {"mentions": svc.list_mentions(db, member_id, unread_only)}


@router.post("/mentions/scan")
async def scan(req: MentionScan, db: DatabaseManager = Depends(get_db)):
    return {"created": svc.mention_in_text(db, req.project_id, req.text,
                                           req.source, req.source_id, req.node_id)}


@router.post("/mentions/{mention_id}/read")
async def mark_read(mention_id: str, db: DatabaseManager = Depends(get_db)):
    if not svc.mark_mention_read(db, mention_id):
        raise HTTPException(status_code=404, detail="Mention not found")
    return {"success": True}


# --- Presence (D64) ----------------------------------------------------------
@router.post("/presence/beat")
async def beat(req: PresenceBody, db: DatabaseManager = Depends(get_db)):
    return svc.heartbeat(db, req.project_id, req.member_id,
                         req.display_name or req.member_id, req.node_id)


@router.get("/presence/{project_id}")
async def presence(project_id: str, node_id: Optional[str] = None,
                   db: DatabaseManager = Depends(get_db)):
    return svc.who_is_here(db, project_id, node_id)


@router.post("/presence/leave")
async def leave(req: PresenceBody, db: DatabaseManager = Depends(get_db)):
    return {"left": svc.leave(db, req.member_id, req.node_id)}


# --- Publishing (D66, D67, D68, D69) -----------------------------------------
@router.get("/changelog/{project_id}")
async def changelog(project_id: str, days: int = 30,
                    db: DatabaseManager = Depends(get_db)):
    try:
        return pub.changelog(db, project_id, days)
    except pub.PublishError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/site/{project_id}")
async def site(project_id: str, db: DatabaseManager = Depends(get_db)):
    """The generated docs site as {filename: html}."""
    try:
        files = pub.build_site(db, project_id)
    except pub.PublishError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"files": list(files), "count": len(files)}


@router.get("/site/{project_id}/{filename}")
async def site_page(project_id: str, filename: str,
                    db: DatabaseManager = Depends(get_db)):
    try:
        files = pub.build_site(db, project_id)
    except pub.PublishError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if filename not in files:
        raise HTTPException(status_code=404, detail="No such page")
    return Response(content=files[filename], media_type="text/html")


@router.get("/bundle/{project_id}")
async def bundle(project_id: str, db: DatabaseManager = Depends(get_db)):
    try:
        data = pub.build_bundle(db, project_id)
    except pub.PublishError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return Response(content=data, media_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="{project_id}-site.zip"'})


@router.get("/pdf/{project_id}")
async def pdf(project_id: str, node_id: Optional[str] = None,
              db: DatabaseManager = Depends(get_db)):
    try:
        data = pub.build_pdf(db, project_id, node_id)
    except pub.PublishError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return Response(content=data, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="{project_id}.pdf"'})


# --- Public share resolution (no account required) ---------------------------
public_router = APIRouter(prefix="/api/v1/shared", tags=["Shared"])


@public_router.get("/{token}")
async def resolve(token: str, db: DatabaseManager = Depends(get_db)):
    try:
        return svc.resolve_share(db, token)
    except svc.CollabError as e:
        raise HTTPException(status_code=404, detail=str(e))
