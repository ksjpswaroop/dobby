"""
Members, roles, share links, reviews, mentions, presence
(100-Day Roadmap, Phase 7: D61-D65, D70).

Security notes, because this is the module where getting it wrong matters:

* **Passwords use `hashlib.scrypt`**, the stdlib memory-hard KDF, with a
  per-user random salt. Never a bare SHA — a bare hash of a human password is
  a dictionary attack waiting to happen.
* **Every secret is stored hashed**: passwords, session tokens, invite tokens,
  share tokens. A leaked database yields no working credential of any kind.
* **Comparisons are constant-time** via `hmac.compare_digest`, so a token
  cannot be recovered a byte at a time by timing the response.
* **Share links are read-only by construction.** `resolve_share` returns
  content and nothing else; there is no code path from a share token to a
  write, so the read-only guarantee is structural rather than a check someone
  can forget.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set

import structlog

from src.db.collab_models import (
    MENTION_SOURCES, REVIEW_STATES, ROLE_CAPABILITIES, ROLES,
    Member, MemberSession, Membership, Mention, Presence, ReviewRequest, ShareLink,
)
from src.db.schema import DatabaseManager, Node, Project

logger = structlog.get_logger()

SESSION_DAYS = 14
PRESENCE_TTL_SECONDS = 45
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 14, 8, 1

MENTION_RE = re.compile(r"@([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|[a-z0-9_.-]{2,40})")


class CollabError(Exception):
    pass


class PermissionDenied(CollabError):
    pass


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------
def hash_password(plaintext: str) -> str:
    if len(plaintext or "") < 8:
        raise CollabError("A password needs at least 8 characters.")
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(plaintext.encode(), salt=salt.encode(),
                            n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P).hex()
    return f"{salt}${digest}"


def verify_password(plaintext: str, stored: str) -> bool:
    if not stored or "$" not in stored:
        return False
    salt, digest = stored.split("$", 1)
    candidate = hashlib.scrypt((plaintext or "").encode(), salt=salt.encode(),
                               n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P).hex()
    return hmac.compare_digest(candidate, digest)


def _hash_token(token: str) -> str:
    """Tokens are high-entropy already, so a fast hash is correct here —
    scrypt's cost buys nothing against a 256-bit random string."""
    return hashlib.sha256((token or "").encode()).hexdigest()


# ---------------------------------------------------------------------------
# Roles (D63)
# ---------------------------------------------------------------------------
def _rank(role: str) -> int:
    return ROLES.index(role) if role in ROLES else -1


def capabilities_for(role: str) -> Set[str]:
    return set(ROLE_CAPABILITIES.get(role, set()))


def role_of(db: DatabaseManager, project_id: str, member_id: str) -> Optional[str]:
    with db.get_session() as s:
        m = (s.query(Membership)
             .filter(Membership.project_id == project_id,
                     Membership.member_id == member_id).first())
        return m.role if m else None


def require_capability(db: DatabaseManager, project_id: str, member_id: str,
                       capability: str) -> str:
    role = role_of(db, project_id, member_id)
    if not role:
        raise PermissionDenied("You are not a member of this project.")
    if capability not in capabilities_for(role):
        raise PermissionDenied(
            f"Your role ({role}) cannot {capability.replace('_', ' ')}.")
    return role


# ---------------------------------------------------------------------------
# Members (D63)
# ---------------------------------------------------------------------------
def _member_dict(m: Member, role: Optional[str] = None) -> Dict[str, Any]:
    return {
        "id": m.id, "email": m.email, "display_name": m.display_name,
        "active": bool(m.active), "role": role,
        "has_password": bool(m.password_hash),
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "last_seen_at": m.last_seen_at.isoformat() if m.last_seen_at else None,
    }


def invite_member(db: DatabaseManager, project_id: str, email: str,
                  display_name: str, role: str = "viewer") -> Dict[str, Any]:
    """Create (or reuse) a member and give them a role. Returns a one-time token."""
    email = (email or "").strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise CollabError("That is not a valid email address.")
    if role not in ROLES:
        raise CollabError(f"Unknown role. One of: {', '.join(ROLES)}")
    if role == "owner":
        raise CollabError("There is exactly one owner and it cannot be granted.")

    invite_token = secrets.token_urlsafe(32)

    with db.get_session() as s:
        if not s.get(Project, project_id):
            raise CollabError("Project not found.")

        member = s.query(Member).filter(Member.email == email).first()
        if not member:
            member = Member(
                id=str(uuid.uuid4()), email=email,
                display_name=(display_name or email.split("@")[0])[:120],
                invite_token_hash=_hash_token(invite_token), active=1,
            )
            s.add(member)
            s.flush()
        else:
            member.invite_token_hash = _hash_token(invite_token)

        existing = (s.query(Membership)
                    .filter(Membership.project_id == project_id,
                            Membership.member_id == member.id).first())
        if existing:
            existing.role = role
        else:
            s.add(Membership(id=str(uuid.uuid4()), project_id=project_id,
                             member_id=member.id, role=role))
        s.commit()
        out = _member_dict(member, role)

    out["invite_token"] = invite_token
    out["warning"] = "This invite token is shown once. Send it to them securely."
    return out


def accept_invite(db: DatabaseManager, invite_token: str,
                  password: str) -> Dict[str, Any]:
    """Set a password using a one-time invite token."""
    with db.get_session() as s:
        member = (s.query(Member)
                  .filter(Member.invite_token_hash == _hash_token(invite_token),
                          Member.active == 1).first())
        if not member:
            raise CollabError("That invite is not valid.")
        member.password_hash = hash_password(password)
        member.invite_token_hash = None  # single use
        s.commit()
        return _member_dict(member)


def list_members(db: DatabaseManager, project_id: str) -> List[Dict[str, Any]]:
    with db.get_session() as s:
        rows = (s.query(Membership, Member)
                .join(Member, Member.id == Membership.member_id)
                .filter(Membership.project_id == project_id).all())
        return [_member_dict(m, ms.role) for ms, m in rows]


def set_role(db: DatabaseManager, project_id: str, member_id: str,
             role: str) -> Dict[str, Any]:
    if role not in ROLES:
        raise CollabError(f"Unknown role. One of: {', '.join(ROLES)}")
    if role == "owner":
        raise CollabError("Ownership cannot be granted this way.")
    with db.get_session() as s:
        ms = (s.query(Membership)
              .filter(Membership.project_id == project_id,
                      Membership.member_id == member_id).first())
        if not ms:
            raise CollabError("That member is not on this project.")
        if ms.role == "owner":
            raise CollabError("The owner's role cannot be changed.")
        ms.role = role
        member = s.get(Member, member_id)
        s.commit()
        return _member_dict(member, role)


def remove_member(db: DatabaseManager, project_id: str, member_id: str) -> bool:
    with db.get_session() as s:
        ms = (s.query(Membership)
              .filter(Membership.project_id == project_id,
                      Membership.member_id == member_id).first())
        if not ms:
            return False
        if ms.role == "owner":
            raise CollabError("The owner cannot be removed from their own project.")
        s.delete(ms)
        s.commit()
        return True


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------
def sign_in(db: DatabaseManager, email: str, password: str) -> Dict[str, Any]:
    email = (email or "").strip().lower()
    with db.get_session() as s:
        member = s.query(Member).filter(Member.email == email,
                                        Member.active == 1).first()
        # Same error either way: distinguishing "no such user" from "wrong
        # password" hands an attacker a user-enumeration oracle.
        if not member or not verify_password(password, member.password_hash or ""):
            raise CollabError("Email or password is incorrect.")

        token = secrets.token_urlsafe(32)
        s.add(MemberSession(
            id=str(uuid.uuid4()), member_id=member.id,
            token_hash=_hash_token(token),
            expires_at=datetime.utcnow() + timedelta(days=SESSION_DAYS),
        ))
        member.last_seen_at = datetime.utcnow()
        s.commit()
        out = _member_dict(member)

    out["token"] = token
    out["expires_in_days"] = SESSION_DAYS
    return out


def member_from_token(db: DatabaseManager, token: str) -> Optional[Dict[str, Any]]:
    if not token:
        return None
    with db.get_session() as s:
        sess = (s.query(MemberSession)
                .filter(MemberSession.token_hash == _hash_token(token),
                        MemberSession.revoked_at.is_(None)).first())
        if not sess or sess.expires_at < datetime.utcnow():
            return None
        member = s.get(Member, sess.member_id)
        if not member or not member.active:
            return None
        member.last_seen_at = datetime.utcnow()
        s.commit()
        return _member_dict(member)


def sign_out(db: DatabaseManager, token: str) -> bool:
    with db.get_session() as s:
        sess = (s.query(MemberSession)
                .filter(MemberSession.token_hash == _hash_token(token)).first())
        if not sess:
            return False
        sess.revoked_at = datetime.utcnow()
        s.commit()
        return True


# ---------------------------------------------------------------------------
# Share links (D62)
# ---------------------------------------------------------------------------
def create_share_link(db: DatabaseManager, project_id: str,
                      node_id: Optional[str] = None, label: str = "",
                      expires_in_days: Optional[int] = 30) -> Dict[str, Any]:
    token = secrets.token_urlsafe(32)
    with db.get_session() as s:
        if not s.get(Project, project_id):
            raise CollabError("Project not found.")
        if node_id and not s.get(Node, node_id):
            raise CollabError("Document not found.")
        link = ShareLink(
            id=str(uuid.uuid4()), project_id=project_id, node_id=node_id,
            token_hash=_hash_token(token), prefix=token[:8], label=label[:200],
            expires_at=(datetime.utcnow() + timedelta(days=expires_in_days))
            if expires_in_days else None,
        )
        s.add(link)
        s.commit()
        out = _link_dict(link)

    out["token"] = token
    out["url"] = f"/shared/{token}"
    out["warning"] = "Anyone with this link can read the shared content."
    return out


def _link_dict(link: ShareLink) -> Dict[str, Any]:
    return {
        "id": link.id, "project_id": link.project_id, "node_id": link.node_id,
        "prefix": link.prefix, "label": link.label,
        "expires_at": link.expires_at.isoformat() if link.expires_at else None,
        "revoked": link.revoked_at is not None,
        "view_count": link.view_count,
        "created_at": link.created_at.isoformat() if link.created_at else None,
    }


def list_share_links(db: DatabaseManager, project_id: str) -> List[Dict[str, Any]]:
    with db.get_session() as s:
        return [_link_dict(l) for l in s.query(ShareLink)
                .filter(ShareLink.project_id == project_id).all()]


def revoke_share_link(db: DatabaseManager, link_id: str) -> bool:
    with db.get_session() as s:
        link = s.get(ShareLink, link_id)
        if not link or link.revoked_at:
            return False
        link.revoked_at = datetime.utcnow()
        s.commit()
        return True


def resolve_share(db: DatabaseManager, token: str) -> Dict[str, Any]:
    """Read-only by construction: this returns content and nothing else."""
    with db.get_session() as s:
        link = (s.query(ShareLink)
                .filter(ShareLink.token_hash == _hash_token(token)).first())
        if not link:
            raise CollabError("That link is not valid.")
        if link.revoked_at:
            raise CollabError("That link has been revoked.")
        if link.expires_at and link.expires_at < datetime.utcnow():
            raise CollabError("That link has expired.")

        link.view_count = (link.view_count or 0) + 1
        link.last_viewed_at = datetime.utcnow()

        project = s.get(Project, link.project_id)
        if link.node_id:
            node = s.get(Node, link.node_id)
            if not node:
                raise CollabError("The shared document no longer exists.")
            payload = {
                "kind": "document", "project_name": project.name if project else "",
                "documents": [{"id": node.id, "title": node.title,
                               "node_type": node.node_type,
                               "content": node.content or ""}],
            }
        else:
            nodes = s.query(Node).filter(Node.project_id == link.project_id).all()
            payload = {
                "kind": "project", "project_name": project.name if project else "",
                "documents": [{"id": n.id, "title": n.title,
                               "node_type": n.node_type,
                               "content": n.content or ""} for n in nodes],
            }
        s.commit()

    payload["read_only"] = True
    payload["label"] = link.label
    return payload


# ---------------------------------------------------------------------------
# Review requests (D65)
# ---------------------------------------------------------------------------
def request_review(db: DatabaseManager, project_id: str, node_id: str,
                   reviewer_id: str, note: str = "",
                   requested_by: str = "") -> Dict[str, Any]:
    with db.get_session() as s:
        if not s.get(Node, node_id):
            raise CollabError("Document not found.")
        if not s.get(Member, reviewer_id):
            raise CollabError("Reviewer not found.")
        req = ReviewRequest(
            id=str(uuid.uuid4()), project_id=project_id, node_id=node_id,
            reviewer_id=reviewer_id, requested_by=requested_by,
            note=note[:2000], state="open",
        )
        s.add(req)
        s.commit()
        out = _review_dict(req)

    # A review request is exactly the kind of thing that should reach someone.
    notify_mention(db, project_id, reviewer_id, "review", out["id"], node_id,
                   note or "You were asked to review a document.")
    return out


def _review_dict(r: ReviewRequest) -> Dict[str, Any]:
    return {
        "id": r.id, "project_id": r.project_id, "node_id": r.node_id,
        "reviewer_id": r.reviewer_id, "requested_by": r.requested_by,
        "state": r.state, "note": r.note, "response": r.response,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
    }


def list_reviews(db: DatabaseManager, project_id: str,
                 reviewer_id: Optional[str] = None,
                 state: Optional[str] = None) -> List[Dict[str, Any]]:
    with db.get_session() as s:
        q = s.query(ReviewRequest).filter(ReviewRequest.project_id == project_id)
        if reviewer_id:
            q = q.filter(ReviewRequest.reviewer_id == reviewer_id)
        if state:
            q = q.filter(ReviewRequest.state == state)
        return [_review_dict(r) for r in
                q.order_by(ReviewRequest.created_at.desc()).all()]


def respond_to_review(db: DatabaseManager, review_id: str, state: str,
                      response: str = "", member_id: str = "") -> Dict[str, Any]:
    if state not in ("approved", "changes_requested", "cancelled"):
        raise CollabError("A review is approved, changes_requested, or cancelled.")
    with db.get_session() as s:
        req = s.get(ReviewRequest, review_id)
        if not req:
            raise CollabError("Review request not found.")
        if req.state != "open":
            raise CollabError("That review has already been resolved.")
        # Only the assigned reviewer may decide it; anyone else deciding would
        # make an approval meaningless.
        if member_id and req.reviewer_id != member_id and state != "cancelled":
            raise PermissionDenied("Only the assigned reviewer can decide this.")
        req.state = state
        req.response = response[:2000]
        req.resolved_at = datetime.utcnow()
        node_id, project_id, requester = req.node_id, req.project_id, req.requested_by
        s.commit()
        out = _review_dict(req)

    # Approving a review advances the document, which is the point of asking.
    if state == "approved":
        try:
            from src.services import document_service as docs

            current = docs.get_document(db, node_id)
            if current and current["status"] == "in_review":
                docs.set_status(db, node_id, "approved")
        except Exception:
            logger.warning("review_status_advance_failed", node_id=node_id)

    if requester:
        notify_mention(db, project_id, requester, "review", review_id, node_id,
                       f"Your review request was {state.replace('_', ' ')}.")
    return out


# ---------------------------------------------------------------------------
# Mentions (D70)
# ---------------------------------------------------------------------------
def extract_mentions(db: DatabaseManager, text: str) -> List[Dict[str, str]]:
    """Resolve @handles in text to real members. Unknown handles are ignored."""
    handles = {m.group(1).lower() for m in MENTION_RE.finditer(text or "")}
    if not handles:
        return []
    with db.get_session() as s:
        members = s.query(Member).filter(Member.active == 1).all()
        out = []
        for m in members:
            local = (m.email or "").split("@")[0].lower()
            if (m.email or "").lower() in handles or local in handles:
                out.append({"member_id": m.id, "email": m.email,
                            "display_name": m.display_name})
        return out


def notify_mention(db: DatabaseManager, project_id: str, member_id: str,
                   source: str, source_id: str = "", node_id: str = "",
                   text: str = "") -> Optional[Dict[str, Any]]:
    if source not in MENTION_SOURCES:
        source = "comment"
    with db.get_session() as s:
        if not s.get(Member, member_id):
            return None
        mention = Mention(
            id=str(uuid.uuid4()), project_id=project_id, member_id=member_id,
            source=source, source_id=source_id, node_id=node_id or None,
            text=(text or "")[:2000],
        )
        s.add(mention)
        s.commit()
        return _mention_dict(mention)


def mention_in_text(db: DatabaseManager, project_id: str, text: str,
                    source: str, source_id: str = "",
                    node_id: str = "") -> List[Dict[str, Any]]:
    """Find @mentions in some text and notify each one."""
    created = []
    for target in extract_mentions(db, text):
        out = notify_mention(db, project_id, target["member_id"], source,
                             source_id, node_id, text)
        if out:
            created.append(out)
    return created


def _mention_dict(m: Mention) -> Dict[str, Any]:
    return {
        "id": m.id, "project_id": m.project_id, "member_id": m.member_id,
        "source": m.source, "source_id": m.source_id, "node_id": m.node_id,
        "text": m.text, "read": m.read_at is not None,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


def list_mentions(db: DatabaseManager, member_id: str,
                  unread_only: bool = False) -> List[Dict[str, Any]]:
    with db.get_session() as s:
        q = s.query(Mention).filter(Mention.member_id == member_id)
        if unread_only:
            q = q.filter(Mention.read_at.is_(None))
        return [_mention_dict(m) for m in
                q.order_by(Mention.created_at.desc()).limit(100).all()]


def mark_mention_read(db: DatabaseManager, mention_id: str) -> bool:
    with db.get_session() as s:
        m = s.get(Mention, mention_id)
        if not m:
            return False
        m.read_at = datetime.utcnow()
        s.commit()
        return True


# ---------------------------------------------------------------------------
# Presence (D64)
# ---------------------------------------------------------------------------
def heartbeat(db: DatabaseManager, project_id: str, member_id: str,
              display_name: str, node_id: Optional[str] = None) -> Dict[str, Any]:
    with db.get_session() as s:
        row = (s.query(Presence)
               .filter(Presence.member_id == member_id,
                       Presence.node_id == node_id).first())
        if row:
            row.last_beat_at = datetime.utcnow()
            row.project_id = project_id
            row.display_name = display_name[:120]
        else:
            s.add(Presence(id=str(uuid.uuid4()), project_id=project_id,
                           node_id=node_id, member_id=member_id,
                           display_name=display_name[:120],
                           last_beat_at=datetime.utcnow()))
        s.commit()
    return who_is_here(db, project_id, node_id)


def who_is_here(db: DatabaseManager, project_id: str,
                node_id: Optional[str] = None) -> Dict[str, Any]:
    """Live presence, sweeping stale beats on read.

    Sweeping on read rather than on a timer means presence is correct even
    after the app has been closed for a week — there is no background job that
    could have missed a tick.
    """
    cutoff = datetime.utcnow() - timedelta(seconds=PRESENCE_TTL_SECONDS)
    with db.get_session() as s:
        for stale in s.query(Presence).filter(Presence.last_beat_at < cutoff).all():
            s.delete(stale)
        s.flush()

        q = s.query(Presence).filter(Presence.project_id == project_id)
        if node_id is not None:
            q = q.filter(Presence.node_id == node_id)
        rows = q.all()
        s.commit()

        return {
            "here": [{"member_id": p.member_id, "display_name": p.display_name,
                      "node_id": p.node_id,
                      "since": p.last_beat_at.isoformat() if p.last_beat_at else None}
                     for p in rows],
            "count": len(rows),
            "ttl_seconds": PRESENCE_TTL_SECONDS,
        }


def leave(db: DatabaseManager, member_id: str,
          node_id: Optional[str] = None) -> bool:
    with db.get_session() as s:
        rows = (s.query(Presence)
                .filter(Presence.member_id == member_id,
                        Presence.node_id == node_id).all())
        for r in rows:
            s.delete(r)
        s.commit()
        return bool(rows)
