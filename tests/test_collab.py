"""
Collaboration & sharing — members, roles, share links, reviews, mentions,
presence, and publishing.

The rules that matter here are security rules: no secret is recoverable from
the database, sign-in must not leak whether an account exists, a share link
must be read-only and revocable, and a role must actually gate what it claims
to gate.
"""

import os
import tempfile
import uuid
import zipfile
from datetime import datetime, timedelta

import pytest

_TMP_DB = os.path.join(tempfile.gettempdir(), f"dobby_collab_{uuid.uuid4().hex}.db")
os.environ["DOBBY_DB_PATH"] = _TMP_DB
os.environ["DOBBY_DISABLE_SCHEDULER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from src.db.collab_models import Member, ShareLink  # noqa: E402
from src.db.schema import Node  # noqa: E402
from src.main import app  # noqa: E402
from src.services import collab_service as svc  # noqa: E402
from src.services import document_service as docs  # noqa: E402
from src.services import publish_service as pub  # noqa: E402

PROJECT = "default-project"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(_TMP_DB + suffix)
        except OSError:
            pass


@pytest.fixture
def db(client):
    return app.state.db


def make_node(db, title="Shared doc", content="# Heading\n\nSome real content here."):
    nid = str(uuid.uuid4())
    with db.get_session() as s:
        s.add(Node(id=nid, project_id=PROJECT, node_type="documentation",
                   title=title, content=content, status="draft"))
        s.commit()
    return nid


def a_member(db, email=None, role="editor"):
    email = email or f"user-{uuid.uuid4().hex[:8]}@example.com"
    return svc.invite_member(db, PROJECT, email, "Test User", role)


class TestPasswordHashing:
    def test_round_trip(self):
        stored = svc.hash_password("correct horse battery")
        assert svc.verify_password("correct horse battery", stored) is True
        assert svc.verify_password("wrong", stored) is False

    def test_salt_makes_hashes_unique(self):
        # Two identical passwords must not produce identical stored values,
        # or a rainbow table cracks both at once.
        assert svc.hash_password("same password") != svc.hash_password("same password")

    def test_plaintext_never_appears_in_the_hash(self):
        stored = svc.hash_password("supersecret123")
        assert "supersecret123" not in stored

    def test_short_password_rejected(self):
        with pytest.raises(svc.CollabError):
            svc.hash_password("short")

    def test_malformed_stored_value_fails_closed(self):
        assert svc.verify_password("anything", "") is False
        assert svc.verify_password("anything", "no-dollar-sign") is False


class TestMembersAndRoles:
    def test_invite_returns_a_one_time_token(self, db):
        out = a_member(db)
        assert out["invite_token"]
        assert "shown once" in out["warning"]

    def test_invite_token_is_stored_hashed(self, db):
        out = a_member(db)
        with db.get_session() as s:
            row = s.get(Member, out["id"])
            assert row.invite_token_hash != out["invite_token"]

    def test_accept_invite_sets_a_password_and_burns_the_token(self, db):
        out = a_member(db)
        svc.accept_invite(db, out["invite_token"], "a good password")
        # Single use.
        with pytest.raises(svc.CollabError):
            svc.accept_invite(db, out["invite_token"], "another password")

    def test_invalid_email_rejected(self, db):
        with pytest.raises(svc.CollabError):
            svc.invite_member(db, PROJECT, "not-an-email", "X")

    def test_owner_role_cannot_be_granted(self, db):
        with pytest.raises(svc.CollabError):
            svc.invite_member(db, PROJECT, "owner@example.com", "X", "owner")

    def test_role_capabilities_are_ordered(self):
        assert "write" not in svc.capabilities_for("viewer")
        assert "write" in svc.capabilities_for("editor")
        assert "manage_members" in svc.capabilities_for("admin")
        assert "comment" in svc.capabilities_for("commenter")

    def test_require_capability_enforces(self, db):
        viewer = a_member(db, role="viewer")
        svc.require_capability(db, PROJECT, viewer["id"], "read")
        with pytest.raises(svc.PermissionDenied):
            svc.require_capability(db, PROJECT, viewer["id"], "write")

    def test_non_member_is_denied(self, db):
        with pytest.raises(svc.PermissionDenied):
            svc.require_capability(db, PROJECT, "not-a-member", "read")

    def test_set_role_changes_capability(self, db):
        m = a_member(db, role="viewer")
        svc.set_role(db, PROJECT, m["id"], "editor")
        svc.require_capability(db, PROJECT, m["id"], "write")

    def test_remove_member(self, db):
        m = a_member(db)
        assert svc.remove_member(db, PROJECT, m["id"]) is True
        assert svc.role_of(db, PROJECT, m["id"]) is None


class TestSignIn:
    def test_sign_in_returns_a_token(self, db):
        m = a_member(db)
        svc.accept_invite(db, m["invite_token"], "a good password")
        out = svc.sign_in(db, m["email"], "a good password")
        assert out["token"]

    def test_token_resolves_to_the_member(self, db):
        m = a_member(db)
        svc.accept_invite(db, m["invite_token"], "a good password")
        token = svc.sign_in(db, m["email"], "a good password")["token"]
        assert svc.member_from_token(db, token)["id"] == m["id"]

    def test_wrong_password_and_unknown_user_give_the_same_error(self, db):
        m = a_member(db)
        svc.accept_invite(db, m["invite_token"], "a good password")
        with pytest.raises(svc.CollabError) as wrong:
            svc.sign_in(db, m["email"], "bad password")
        with pytest.raises(svc.CollabError) as missing:
            svc.sign_in(db, "nobody@example.com", "bad password")
        # Distinguishing them would be a user-enumeration oracle.
        assert str(wrong.value) == str(missing.value)

    def test_sign_out_invalidates_the_token(self, db):
        m = a_member(db)
        svc.accept_invite(db, m["invite_token"], "a good password")
        token = svc.sign_in(db, m["email"], "a good password")["token"]
        svc.sign_out(db, token)
        assert svc.member_from_token(db, token) is None

    def test_garbage_token_resolves_to_nothing(self, db):
        assert svc.member_from_token(db, "not-a-real-token") is None


class TestShareLinks:
    def test_token_is_stored_hashed(self, db):
        link = svc.create_share_link(db, PROJECT)
        with db.get_session() as s:
            row = s.get(ShareLink, link["id"])
            assert row.token_hash != link["token"]

    def test_resolve_returns_content_and_is_read_only(self, db):
        make_node(db, "Publicly shared")
        link = svc.create_share_link(db, PROJECT)
        out = svc.resolve_share(db, link["token"])
        assert out["read_only"] is True
        assert any(d["title"] == "Publicly shared" for d in out["documents"])

    def test_single_document_link_shares_only_that_document(self, db):
        nid = make_node(db, "Only this one")
        make_node(db, "Not this one")
        link = svc.create_share_link(db, PROJECT, node_id=nid)
        out = svc.resolve_share(db, link["token"])
        assert len(out["documents"]) == 1
        assert out["documents"][0]["title"] == "Only this one"

    def test_revoked_link_stops_working(self, db):
        link = svc.create_share_link(db, PROJECT)
        svc.revoke_share_link(db, link["id"])
        with pytest.raises(svc.CollabError):
            svc.resolve_share(db, link["token"])

    def test_expired_link_stops_working(self, db):
        link = svc.create_share_link(db, PROJECT, expires_in_days=1)
        with db.get_session() as s:
            row = s.get(ShareLink, link["id"])
            row.expires_at = datetime.utcnow() - timedelta(hours=1)
            s.commit()
        with pytest.raises(svc.CollabError):
            svc.resolve_share(db, link["token"])

    def test_unknown_token_rejected(self, db):
        with pytest.raises(svc.CollabError):
            svc.resolve_share(db, "made-up-token")

    def test_view_count_increments(self, db):
        make_node(db)
        link = svc.create_share_link(db, PROJECT)
        svc.resolve_share(db, link["token"])
        svc.resolve_share(db, link["token"])
        row = next(l for l in svc.list_share_links(db, PROJECT) if l["id"] == link["id"])
        assert row["view_count"] == 2


class TestReviews:
    def test_request_and_approve_advances_the_document(self, db):
        nid = make_node(db, "Needs review")
        docs.set_status(db, nid, "in_review")
        reviewer = a_member(db)
        req = svc.request_review(db, PROJECT, nid, reviewer["id"], "please look")
        svc.respond_to_review(db, req["id"], "approved", "looks good",
                              member_id=reviewer["id"])
        assert docs.get_document(db, nid)["status"] == "approved"

    def test_only_the_assigned_reviewer_can_decide(self, db):
        nid = make_node(db, "Guarded review")
        reviewer = a_member(db)
        other = a_member(db)
        req = svc.request_review(db, PROJECT, nid, reviewer["id"])
        with pytest.raises(svc.PermissionDenied):
            svc.respond_to_review(db, req["id"], "approved", member_id=other["id"])

    def test_review_cannot_be_decided_twice(self, db):
        nid = make_node(db)
        reviewer = a_member(db)
        req = svc.request_review(db, PROJECT, nid, reviewer["id"])
        svc.respond_to_review(db, req["id"], "changes_requested",
                              member_id=reviewer["id"])
        with pytest.raises(svc.CollabError):
            svc.respond_to_review(db, req["id"], "approved", member_id=reviewer["id"])

    def test_requesting_a_review_notifies_the_reviewer(self, db):
        nid = make_node(db)
        reviewer = a_member(db)
        svc.request_review(db, PROJECT, nid, reviewer["id"], "have a look")
        assert svc.list_mentions(db, reviewer["id"], unread_only=True)

    def test_unknown_reviewer_rejected(self, db):
        nid = make_node(db)
        with pytest.raises(svc.CollabError):
            svc.request_review(db, PROJECT, nid, "nobody")


class TestMentions:
    def test_extracts_by_email_and_handle(self, db):
        m = svc.invite_member(db, PROJECT, "mentionme@example.com", "Mention Me")
        by_email = svc.extract_mentions(db, "hey @mentionme@example.com look")
        by_handle = svc.extract_mentions(db, "hey @mentionme look")
        assert any(x["member_id"] == m["id"] for x in by_email)
        assert any(x["member_id"] == m["id"] for x in by_handle)

    def test_unknown_handles_are_ignored(self, db):
        assert svc.extract_mentions(db, "hi @nobody_at_all_here") == []

    def test_mention_in_text_creates_notifications(self, db):
        m = svc.invite_member(db, PROJECT, "notified@example.com", "Notified")
        created = svc.mention_in_text(db, PROJECT, "ping @notified please",
                                      "comment", "c1", "n1")
        assert created
        assert svc.list_mentions(db, m["id"], unread_only=True)

    def test_mark_read(self, db):
        m = svc.invite_member(db, PROJECT, "reader@example.com", "Reader")
        svc.notify_mention(db, PROJECT, m["id"], "comment", text="hi")
        mention = svc.list_mentions(db, m["id"])[0]
        svc.mark_mention_read(db, mention["id"])
        assert not any(x["id"] == mention["id"]
                       for x in svc.list_mentions(db, m["id"], unread_only=True))


class TestPresence:
    def test_heartbeat_shows_who_is_here(self, db):
        m = a_member(db)
        out = svc.heartbeat(db, PROJECT, m["id"], "Test User", node_id="doc-1")
        assert any(p["member_id"] == m["id"] for p in out["here"])

    def test_stale_beats_are_swept_on_read(self, db):
        from src.db.collab_models import Presence

        m = a_member(db)
        svc.heartbeat(db, PROJECT, m["id"], "Stale User", node_id="doc-stale")
        with db.get_session() as s:
            row = (s.query(Presence)
                   .filter(Presence.member_id == m["id"]).first())
            row.last_beat_at = datetime.utcnow() - timedelta(minutes=5)
            s.commit()
        out = svc.who_is_here(db, PROJECT, "doc-stale")
        assert out["count"] == 0

    def test_leaving_removes_presence(self, db):
        m = a_member(db)
        svc.heartbeat(db, PROJECT, m["id"], "Leaver", node_id="doc-leave")
        svc.leave(db, m["id"], "doc-leave")
        assert svc.who_is_here(db, PROJECT, "doc-leave")["count"] == 0

    def test_repeated_beats_do_not_duplicate(self, db):
        m = a_member(db)
        svc.heartbeat(db, PROJECT, m["id"], "Beater", node_id="doc-beat")
        out = svc.heartbeat(db, PROJECT, m["id"], "Beater", node_id="doc-beat")
        assert len([p for p in out["here"] if p["member_id"] == m["id"]]) == 1


class TestPublishing:
    def test_markdown_escapes_html(self):
        out = pub.markdown_to_html("<script>alert(1)</script>")
        # A bundle gets opened in a browser; unescaped markup would be stored XSS.
        assert "<script>" not in out
        assert "&lt;script&gt;" in out

    def test_markdown_renders_structure(self):
        out = pub.markdown_to_html("## Title\n\n- one\n- two\n\n**bold**")
        assert "<h3>Title</h3>" in out
        assert "<ul>" in out and "<li>one</li>" in out
        assert "<strong>bold</strong>" in out

    def test_site_builds_a_page_per_document(self, db):
        make_node(db, "Site page one")
        files = pub.build_site(db, PROJECT)
        assert "index.html" in files
        assert len(files) >= 2

    def test_site_pages_are_self_contained(self, db):
        make_node(db, "Offline page")
        files = pub.build_site(db, PROJECT)
        page = files["index.html"]
        # No external stylesheet or script — it must render from a USB stick.
        assert "<style>" in page
        assert "http://" not in page.replace("http://www.w3.org", "")

    def test_duplicate_titles_get_distinct_filenames(self, db):
        make_node(db, "Same Name Here")
        make_node(db, "Same Name Here")
        files = pub.build_site(db, PROJECT)
        assert len([f for f in files if f.startswith("same-name-here")]) >= 2

    def test_bundle_is_a_valid_zip(self, db):
        make_node(db, "Bundled doc")
        data = pub.build_bundle(db, PROJECT)
        with zipfile.ZipFile(__import__("io").BytesIO(data)) as z:
            names = z.namelist()
            assert "index.html" in names
            assert "README.txt" in names
            assert z.testzip() is None

    def test_pdf_has_a_pdf_header(self, db):
        make_node(db, "PDF doc", "# Title\n\nBody text here.")
        data = pub.build_pdf(db, PROJECT)
        assert data.startswith(b"%PDF")
        assert len(data) > 800

    def test_pdf_of_a_single_document(self, db):
        nid = make_node(db, "Just me", "Only this one should appear.")
        data = pub.build_pdf(db, PROJECT, node_id=nid)
        assert data.startswith(b"%PDF")

    def test_changelog_is_built_from_real_events(self, db):
        out = pub.changelog(db, PROJECT, days=30)
        assert out["markdown"].startswith("#")
        assert "real status transitions" in out["basis"]

    def test_empty_project_cannot_be_published(self, db):
        from src.db.schema import Project

        with db.get_session() as s:
            s.add(Project(id="empty-pub", name="Empty"))
            s.commit()
        with pytest.raises(pub.PublishError):
            pub.build_site(db, "empty-pub")


class TestRoutes:
    def test_meta_lists_roles_and_capabilities(self, client):
        body = client.get("/api/v1/collab/meta").json()
        assert "editor" in body["roles"]
        assert "write" in body["capabilities"]["editor"]

    def test_shared_endpoint_needs_no_auth(self, client, db):
        make_node(db, "Route shared doc")
        link = svc.create_share_link(db, PROJECT)
        r = client.get(f"/api/v1/shared/{link['token']}")
        assert r.status_code == 200
        assert r.json()["read_only"] is True

    def test_shared_path_is_in_the_open_allowlist(self):
        from src.security.tokens import is_open_path

        assert is_open_path("/api/v1/shared/sometoken") is True
        # But the authenticated collab surface is NOT open.
        assert is_open_path("/api/v1/collab/members/default-project") is False

    def test_bad_share_token_404s(self, client):
        assert client.get("/api/v1/shared/nope").status_code == 404

    def test_sign_in_with_bad_credentials_401s(self, client):
        r = client.post("/api/v1/collab/auth/sign-in",
                        json={"email": "nobody@example.com", "password": "x"})
        assert r.status_code == 401

    def test_pdf_endpoint_serves_a_pdf(self, client, db):
        make_node(db, "Endpoint PDF")
        r = client.get(f"/api/v1/collab/pdf/{PROJECT}")
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/pdf"
        assert r.content.startswith(b"%PDF")

    def test_bundle_endpoint_serves_a_zip(self, client, db):
        make_node(db, "Endpoint bundle")
        r = client.get(f"/api/v1/collab/bundle/{PROJECT}")
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/zip"

    def test_changelog_endpoint(self, client):
        assert client.get(f"/api/v1/collab/changelog/{PROJECT}").status_code == 200

    def test_site_page_endpoint_serves_html(self, client, db):
        make_node(db, "Site route doc")
        r = client.get(f"/api/v1/collab/site/{PROJECT}/index.html")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")
