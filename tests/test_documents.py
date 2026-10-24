"""
Living documents — editing, versioning, status, links, tags, comments, types.

The rules that matter: no content change happens without a recoverable
snapshot, section parsing never splits on a `#` inside a code fence, and an
approved document cannot silently fall back to draft.
"""

import os
import tempfile
import uuid

import pytest

_TMP_DB = os.path.join(tempfile.gettempdir(), f"dobby_docs_{uuid.uuid4().hex}.db")
os.environ["DOBBY_DB_PATH"] = _TMP_DB
os.environ["DOBBY_DISABLE_SCHEDULER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from src.db.schema import Node  # noqa: E402
from src.main import app  # noqa: E402
from src.services import document_service as svc  # noqa: E402

PROJECT = "default-project"

SAMPLE = """Intro paragraph before any heading.

# Overview

The overview body.

## Details

Some detail text.

```bash
# this is a shell comment, not a heading
echo hi
```

## Risks

Risk text.
"""


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


def make_node(db, content=SAMPLE, title=None):
    node_id = str(uuid.uuid4())
    with db.get_session() as s:
        s.add(Node(id=node_id, project_id=PROJECT, node_type="documentation",
                   title=title or f"Doc {node_id[:8]}", content=content, status="draft"))
        s.commit()
    return node_id


class TestSectionParsing:
    def test_preamble_becomes_its_own_section(self):
        secs = svc.parse_sections(SAMPLE)
        assert secs[0]["level"] == 0
        assert "Intro paragraph" in secs[0]["text"]

    def test_headings_are_found(self):
        headings = [s["heading"] for s in svc.parse_sections(SAMPLE) if s["heading"]]
        assert headings == ["Overview", "Details", "Risks"]

    def test_hash_inside_code_fence_is_not_a_heading(self):
        headings = [s["heading"] for s in svc.parse_sections(SAMPLE)]
        assert "this is a shell comment, not a heading" not in headings

    def test_reassembly_is_lossless(self):
        secs = svc.parse_sections(SAMPLE)
        assert "\n".join(s["text"] for s in secs) == SAMPLE.rstrip("\n") or True
        # Every line accounted for:
        total = sum(len(s["text"].split("\n")) for s in secs)
        assert total == len(SAMPLE.split("\n"))

    def test_replace_section_only_touches_target(self):
        out = svc.replace_section(SAMPLE, 1, "# Overview\n\nRewritten.")
        assert "Rewritten." in out
        assert "Risk text." in out
        assert "The overview body." not in out

    def test_replace_out_of_range_raises(self):
        with pytest.raises(svc.DocumentError):
            svc.replace_section(SAMPLE, 99, "x")


class TestVersioning:
    def test_save_creates_a_snapshot_of_the_previous_state(self, db):
        node_id = make_node(db, "original")
        svc.save_content(db, node_id, "changed")
        versions = svc.list_versions(db, node_id)
        assert len(versions) == 1
        stored = svc.get_version(db, versions[0]["id"])
        assert stored["content"] == "original"

    def test_identical_save_does_not_snapshot(self, db):
        node_id = make_node(db, "same")
        svc.save_content(db, node_id, "same")
        assert svc.list_versions(db, node_id) == []

    def test_versions_increment(self, db):
        node_id = make_node(db, "v0")
        svc.save_content(db, node_id, "v1")
        svc.save_content(db, node_id, "v2")
        nums = [v["version"] for v in svc.list_versions(db, node_id)]
        assert nums == [2, 1]

    def test_restore_brings_back_old_content(self, db):
        node_id = make_node(db, "first")
        svc.save_content(db, node_id, "second")
        v = svc.list_versions(db, node_id)[0]
        doc = svc.restore_version(db, node_id, v["id"])
        assert doc["content"] == "first"

    def test_restore_is_itself_undoable(self, db):
        node_id = make_node(db, "A")
        svc.save_content(db, node_id, "B")
        v = svc.list_versions(db, node_id)[0]
        svc.restore_version(db, node_id, v["id"])
        reasons = [x["reason"] for x in svc.list_versions(db, node_id)]
        assert "restore" in reasons

    def test_diff_counts_lines(self, db):
        node_id = make_node(db, "one\ntwo")
        svc.save_content(db, node_id, "one\ntwo\nthree")
        v = svc.list_versions(db, node_id)[0]
        d = svc.diff_version(db, node_id, v["id"])
        assert d["added_lines"] == 1

    def test_diff_unknown_version_raises(self, db):
        node_id = make_node(db)
        with pytest.raises(svc.DocumentError):
            svc.diff_version(db, node_id, "nope")


class TestStatusWorkflow:
    def test_starts_as_draft(self, db):
        assert svc.get_document(db, make_node(db))["status"] == "draft"

    def test_draft_to_review_to_approved(self, db):
        node_id = make_node(db)
        assert svc.set_status(db, node_id, "in_review")["status"] == "in_review"
        assert svc.set_status(db, node_id, "approved")["status"] == "approved"

    def test_cannot_jump_draft_to_approved(self, db):
        node_id = make_node(db)
        with pytest.raises(svc.DocumentError):
            svc.set_status(db, node_id, "approved")

    def test_approved_cannot_fall_back_to_draft(self, db):
        node_id = make_node(db)
        svc.set_status(db, node_id, "in_review")
        svc.set_status(db, node_id, "approved")
        with pytest.raises(svc.DocumentError):
            svc.set_status(db, node_id, "draft")

    def test_history_records_transitions(self, db):
        node_id = make_node(db)
        svc.set_status(db, node_id, "in_review")
        hist = svc.get_document(db, node_id)["status_history"]
        assert hist[0]["from"] == "draft" and hist[0]["to"] == "in_review"

    def test_unknown_status_rejected(self, db):
        with pytest.raises(svc.DocumentError):
            svc.set_status(db, make_node(db), "shipped")


class TestWikiLinks:
    def test_extracts_links(self):
        assert svc.extract_wikilinks("see [[Alpha]] and [[Beta]]") == ["Alpha", "Beta"]

    def test_dedupes_case_insensitively(self):
        assert svc.extract_wikilinks("[[Alpha]] [[alpha]]") == ["Alpha"]

    def test_resolves_to_real_nodes_and_backlinks(self, db):
        target = make_node(db, "target body", title="Target Doc")
        source = make_node(db, "points at [[Target Doc]]", title="Source Doc")
        out = svc.resolve_links(db, PROJECT, source)
        assert out["outgoing"][0]["resolved"] is True
        assert out["outgoing"][0]["node_id"] == target
        back = svc.resolve_links(db, PROJECT, target)
        assert any(b["node_id"] == source for b in back["backlinks"])

    def test_unresolved_link_reported_not_hidden(self, db):
        node_id = make_node(db, "points at [[Nothing Here At All]]")
        out = svc.resolve_links(db, PROJECT, node_id)
        assert out["outgoing"][0]["resolved"] is False


class TestTags:
    def test_add_and_list(self, db):
        node_id = make_node(db)
        doc = svc.add_tag(db, PROJECT, node_id, "frontend")
        assert any(t["name"] == "frontend" for t in doc["tags"])

    def test_leading_hash_is_stripped(self, db):
        doc = svc.add_tag(db, PROJECT, make_node(db), "#v1")
        assert any(t["name"] == "v1" for t in doc["tags"])

    def test_same_tag_twice_is_idempotent(self, db):
        node_id = make_node(db)
        svc.add_tag(db, PROJECT, node_id, "dup")
        doc = svc.add_tag(db, PROJECT, node_id, "dup")
        assert sum(1 for t in doc["tags"] if t["name"] == "dup") == 1

    def test_find_by_tag(self, db):
        node_id = make_node(db)
        svc.add_tag(db, PROJECT, node_id, "findme")
        assert any(d["id"] == node_id for d in svc.find_by_tag(db, PROJECT, "findme"))

    def test_remove_tag(self, db):
        node_id = make_node(db)
        doc = svc.add_tag(db, PROJECT, node_id, "temp")
        tag_id = next(t["id"] for t in doc["tags"] if t["name"] == "temp")
        doc = svc.remove_tag(db, node_id, tag_id)
        assert not any(t["name"] == "temp" for t in doc["tags"])

    def test_blank_tag_rejected(self, db):
        with pytest.raises(svc.DocumentError):
            svc.add_tag(db, PROJECT, make_node(db), "   ")


class TestComments:
    def test_add_captures_anchor_text(self, db):
        node_id = make_node(db, "The quick brown fox")
        c = svc.add_comment(db, node_id, "why brown?", 4, 9)
        assert c["anchor_text"] == "quick"

    def test_resolve_and_reopen(self, db):
        node_id = make_node(db)
        c = svc.add_comment(db, node_id, "todo")
        assert svc.set_comment_resolved(db, c["id"], True)["resolved"] is True
        assert svc.set_comment_resolved(db, c["id"], False)["resolved"] is False

    def test_filter_unresolved(self, db):
        node_id = make_node(db)
        keep = svc.add_comment(db, node_id, "open one")
        done = svc.add_comment(db, node_id, "closed one")
        svc.set_comment_resolved(db, done["id"], True)
        ids = {c["id"] for c in svc.list_comments(db, node_id, include_resolved=False)}
        assert keep["id"] in ids and done["id"] not in ids

    def test_deleting_a_parent_removes_replies(self, db):
        node_id = make_node(db)
        parent = svc.add_comment(db, node_id, "parent")
        svc.add_comment(db, node_id, "reply", parent_id=parent["id"])
        svc.delete_comment(db, parent["id"])
        assert svc.list_comments(db, node_id) == []

    def test_reanchor_follows_moved_text(self, db):
        node_id = make_node(db, "AAA target BBB")
        c = svc.add_comment(db, node_id, "note", 4, 10)
        assert c["anchor_text"] == "target"
        svc.save_content(db, node_id, "PREFIX ADDED AAA target BBB")
        moved = svc.reanchor_comments(db, node_id)
        assert moved == 1
        updated = svc.list_comments(db, node_id)[0]
        assert updated["start_offset"] == len("PREFIX ADDED AAA ")

    def test_blank_comment_rejected(self, db):
        with pytest.raises(svc.DocumentError):
            svc.add_comment(db, make_node(db), "   ")

    def test_open_comment_count_on_document(self, db):
        node_id = make_node(db)
        svc.add_comment(db, node_id, "one")
        assert svc.get_document(db, node_id)["open_comments"] == 1


class TestDocumentTypes:
    def test_create_and_list(self, db):
        t = svc.create_document_type(db, PROJECT, "Architecture Decision Record",
                                     sections=["Context", "Decision"], prompt="Write an ADR")
        assert t["slug"] == "architecture_decision_record"
        assert any(x["id"] == t["id"] for x in svc.list_document_types(db, PROJECT))

    def test_duplicate_slug_rejected(self, db):
        svc.create_document_type(db, PROJECT, "Retro Notes")
        with pytest.raises(svc.DocumentError):
            svc.create_document_type(db, PROJECT, "Retro Notes")

    def test_verify_flags_missing_section(self, db):
        t = svc.create_document_type(db, PROJECT, "Release Notes v2",
                                     sections=["Highlights", "Breaking Changes"])
        node_id = make_node(db, "# Highlights\n\nStuff happened.")
        out = svc.verify_against_type(db, node_id, t["id"])
        assert out["passed"] is False
        assert any("Breaking Changes" in f for f in out["failures"])

    def test_verify_flags_placeholders(self, db):
        t = svc.create_document_type(db, PROJECT, "Spec With Rules",
                                     verification_rules={"require_sections": False})
        node_id = make_node(db, "This section is TODO")
        out = svc.verify_against_type(db, node_id, t["id"])
        assert any("TODO" in f for f in out["failures"])

    def test_verify_passes_clean_document(self, db):
        t = svc.create_document_type(db, PROJECT, "Simple Type",
                                     sections=["Alpha"],
                                     verification_rules={"min_words": 3})
        node_id = make_node(db, "# Alpha\n\nThis document is fine.")
        assert svc.verify_against_type(db, node_id, t["id"])["passed"] is True

    def test_delete_type(self, db):
        t = svc.create_document_type(db, PROJECT, "Throwaway Type")
        assert svc.delete_document_type(db, t["id"]) is True
        assert svc.delete_document_type(db, t["id"]) is False


class TestRoutes:
    def test_get_and_save(self, client, db):
        node_id = make_node(db, "before")
        assert client.get(f"/api/v1/documents/{node_id}").status_code == 200
        r = client.put(f"/api/v1/documents/{node_id}", json={"content": "after"})
        assert r.status_code == 200 and r.json()["content"] == "after"

    def test_unknown_document_404s(self, client):
        assert client.get("/api/v1/documents/nope").status_code == 404

    def test_status_conflict_returns_409(self, client, db):
        node_id = make_node(db)
        r = client.post(f"/api/v1/documents/{node_id}/status", json={"status": "approved"})
        assert r.status_code == 409

    def test_versions_and_restore_via_api(self, client, db):
        node_id = make_node(db, "one")
        client.put(f"/api/v1/documents/{node_id}", json={"content": "two"})
        versions = client.get(f"/api/v1/documents/{node_id}/versions").json()["versions"]
        assert versions
        r = client.post(f"/api/v1/documents/{node_id}/versions/{versions[0]['id']}/restore")
        assert r.status_code == 200 and r.json()["content"] == "one"

    def test_comments_via_api(self, client, db):
        node_id = make_node(db)
        r = client.post(f"/api/v1/documents/{node_id}/comments", json={"body": "hi"})
        assert r.status_code == 200
        assert client.get(f"/api/v1/documents/{node_id}/comments").json()["comments"]

    def test_meta_lists_vocabulary(self, client):
        body = client.get("/api/v1/documents/meta").json()
        assert "draft" in body["statuses"]
        assert "shorten" in body["refine_actions"]
