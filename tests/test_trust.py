"""
Quality & trust — trash, backup round-trip, consistency, batch operations.

The rules that matter: a delete must be reversible with its dependents
intact, an import must never overwrite existing work, and a batch operation
must report per-item outcomes rather than collapsing a partial failure.
"""

import os
import tempfile
import uuid

import pytest

_TMP_DB = os.path.join(tempfile.gettempdir(), f"dobby_trust_{uuid.uuid4().hex}.db")
os.environ["DOBBY_DB_PATH"] = _TMP_DB
os.environ["DOBBY_DISABLE_SCHEDULER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from src.db.schema import FeatureBacklog, Node, Project  # noqa: E402
from src.main import app  # noqa: E402
from src.services import document_service as docs  # noqa: E402
from src.services import idea_service, trust_service as svc  # noqa: E402

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


def make_node(db, title="Doc", content="Some reasonable content here with enough words to pass the thin check easily."):
    nid = str(uuid.uuid4())
    with db.get_session() as s:
        s.add(Node(id=nid, project_id=PROJECT, node_type="documentation",
                   title=title, content=content, status="draft"))
        s.commit()
    return nid


def make_feature(db, title="Feature"):
    fid = str(uuid.uuid4())
    with db.get_session() as s:
        s.add(FeatureBacklog(id=fid, project_id=PROJECT, title=title,
                             description="d", category="core", impact_score=5,
                             effort_score=5, risk_score=5, pareto_score=1.0,
                             status="backlog"))
        s.commit()
    return fid


class TestTrash:
    def test_document_delete_is_reversible(self, db):
        nid = make_node(db, "Recoverable doc")
        docs.save_content(db, nid, "changed content here")
        docs.add_comment(db, nid, "a note")

        item = svc.trash_document(db, nid)
        assert docs.get_document(db, nid) is None

        svc.restore(db, item["id"])
        restored = docs.get_document(db, nid)
        assert restored is not None
        assert restored["title"] == "Recoverable doc"

    def test_restore_brings_back_versions_and_comments(self, db):
        nid = make_node(db, "With dependents")
        docs.save_content(db, nid, "v2 content")
        docs.add_comment(db, nid, "keep me")

        item = svc.trash_document(db, nid)
        svc.restore(db, item["id"])

        assert len(docs.list_versions(db, nid)) >= 1
        assert any(c["body"] == "keep me" for c in docs.list_comments(db, nid))

    def test_idea_delete_is_reversible(self, db):
        idea = idea_service.capture(db, PROJECT, "trash me")
        item = svc.trash_idea(db, idea["id"])
        assert idea_service.get(db, idea["id"]) is None
        svc.restore(db, item["id"])
        assert idea_service.get(db, idea["id"]) is not None

    def test_feature_delete_is_reversible(self, db):
        fid = make_feature(db, "Recoverable feature")
        item = svc.trash_feature(db, fid)
        with db.get_session() as s:
            assert s.get(FeatureBacklog, fid) is None
        svc.restore(db, item["id"])
        with db.get_session() as s:
            assert s.get(FeatureBacklog, fid) is not None

    def test_double_restore_refused(self, db):
        idea = idea_service.capture(db, PROJECT, "restore once")
        item = svc.trash_idea(db, idea["id"])
        svc.restore(db, item["id"])
        with pytest.raises(svc.TrustError):
            svc.restore(db, item["id"])

    def test_restored_items_leave_the_trash_list(self, db):
        idea = idea_service.capture(db, PROJECT, "leaves list")
        item = svc.trash_idea(db, idea["id"])
        assert any(t["id"] == item["id"] for t in svc.list_trash(db, PROJECT))
        svc.restore(db, item["id"])
        assert not any(t["id"] == item["id"] for t in svc.list_trash(db, PROJECT))

    def test_empty_trash_reports_count(self, db):
        idea_service.capture(db, PROJECT, "to be emptied")
        ideas = idea_service.list_ideas(db, PROJECT)
        svc.trash_idea(db, ideas[0]["id"])
        n = svc.empty_trash(db, PROJECT)
        assert n >= 1
        assert svc.list_trash(db, PROJECT) == []


class TestBackup:
    def test_export_includes_everything(self, db):
        make_node(db, "Exported doc")
        make_feature(db, "Exported feature")
        archive = svc.export_project(db, PROJECT)
        assert archive["archive_version"] == svc.ARCHIVE_VERSION
        assert archive["counts"]["nodes"] >= 1
        assert archive["counts"]["features"] >= 1

    def test_round_trip_creates_a_new_project(self, db):
        make_node(db, "Round trip doc")
        archive = svc.export_project(db, PROJECT)
        out = svc.import_project(db, archive, "Imported copy")

        assert out["project_id"] != PROJECT
        with db.get_session() as s:
            p = s.get(Project, out["project_id"])
            assert p.name == "Imported copy"
            # The original is untouched.
            assert s.get(Project, PROJECT) is not None

    def test_import_never_reuses_ids(self, db):
        nid = make_node(db, "Id check doc")
        archive = svc.export_project(db, PROJECT)
        out = svc.import_project(db, archive)
        with db.get_session() as s:
            imported = (s.query(Node)
                        .filter(Node.project_id == out["project_id"]).all())
            assert all(n.id != nid for n in imported)

    def test_wrong_version_rejected(self, db):
        with pytest.raises(svc.TrustError):
            svc.import_project(db, {"archive_version": 999, "project": {}})

    def test_garbage_rejected(self, db):
        with pytest.raises(svc.TrustError):
            svc.import_project(db, {"archive_version": svc.ARCHIVE_VERSION})

    def test_unknown_project_export_raises(self, db):
        with pytest.raises(svc.TrustError):
            svc.export_project(db, "no-such-project")


class TestConsistency:
    def test_flags_placeholder_text(self, db):
        make_node(db, "Has a TODO", "This section is TODO and needs writing later on.")
        out = svc.check_consistency(db, PROJECT)
        assert any(i["kind"] == "placeholder" for i in out["issues"])

    def test_flags_broken_wiki_link(self, db):
        make_node(db, "Links nowhere",
                  "See [[A Document That Does Not Exist Anywhere]] for details, plus more words here.")
        out = svc.check_consistency(db, PROJECT)
        assert any(i["kind"] == "broken_link" and i["severity"] == "error"
                   for i in out["issues"])

    def test_flags_thin_document(self, db):
        make_node(db, "Stub doc", "Too short.")
        out = svc.check_consistency(db, PROJECT)
        assert any(i["kind"] == "thin_document" for i in out["issues"])

    def test_flags_duplicate_titles(self, db):
        make_node(db, "Duplicate Title Here", "Content one with plenty of words to avoid the thin flag entirely.")
        make_node(db, "Duplicate Title Here", "Content two with plenty of words to avoid the thin flag entirely.")
        out = svc.check_consistency(db, PROJECT)
        assert any(i["kind"] == "duplicate_title" for i in out["issues"])

    def test_rerun_replaces_rather_than_accumulates(self, db):
        svc.check_consistency(db, PROJECT)
        first = len(svc.list_issues(db, PROJECT))
        svc.check_consistency(db, PROJECT)
        assert len(svc.list_issues(db, PROJECT)) == first


class TestBatch:
    def test_batch_tag_applies_to_all(self, db):
        a, b = make_node(db, "Batch A"), make_node(db, "Batch B")
        out = svc.run_batch(db, PROJECT, "tag", [a, b], {"name": "batched"})
        assert out["completed"] == 2 and out["failed"] == 0
        assert any(t["name"] == "batched" for t in docs.get_document(db, a)["tags"])

    def test_partial_failure_is_visible(self, db):
        good = make_node(db, "Real doc")
        out = svc.run_batch(db, PROJECT, "tag", [good, "no-such-node"], {"name": "x"})
        assert out["completed"] == 1
        assert out["failed"] == 1
        statuses = {i["target_id"]: i["status"] for i in out["items"]}
        assert statuses["no-such-node"] == "failed"

    def test_batch_verify_flags_thin_documents(self, db):
        thin = make_node(db, "Thin one", "tiny")
        out = svc.run_batch(db, PROJECT, "verify", [thin])
        assert out["items"][0]["status"] == "failed"
        assert "short" in out["items"][0]["detail"]

    def test_batch_delete_goes_to_trash(self, db):
        nid = make_node(db, "Batch deleted")
        svc.run_batch(db, PROJECT, "delete", [nid], {"kind": "document"})
        assert docs.get_document(db, nid) is None
        assert any(t["original_id"] == nid for t in svc.list_trash(db, PROJECT))

    def test_unknown_operation_rejected(self, db):
        with pytest.raises(svc.TrustError):
            svc.run_batch(db, PROJECT, "nonsense", ["x"])

    def test_empty_selection_rejected(self, db):
        with pytest.raises(svc.TrustError):
            svc.run_batch(db, PROJECT, "tag", [], {"name": "x"})

    def test_jobs_are_listed(self, db):
        nid = make_node(db, "Job listed")
        svc.run_batch(db, PROJECT, "verify", [nid])
        assert svc.list_jobs(db, PROJECT)


class TestRoutes:
    def test_export_endpoint(self, client):
        r = client.get(f"/api/v1/trust/export/{PROJECT}")
        assert r.status_code == 200 and "archive_version" in r.json()

    def test_round_trip_via_api(self, client):
        archive = client.get(f"/api/v1/trust/export/{PROJECT}").json()
        r = client.post("/api/v1/trust/import",
                        json={"archive": archive, "new_project_name": "API import"})
        assert r.status_code == 200 and r.json()["project_id"]

    def test_consistency_endpoint(self, client):
        r = client.post(f"/api/v1/trust/consistency/{PROJECT}")
        assert r.status_code == 200 and "issues" in r.json()

    def test_trash_endpoint(self, client):
        assert client.get(f"/api/v1/trust/trash/{PROJECT}").status_code == 200

    def test_bad_batch_returns_400(self, client):
        r = client.post("/api/v1/trust/batch",
                        json={"project_id": PROJECT, "operation": "nope", "target_ids": ["a"]})
        assert r.status_code == 400
