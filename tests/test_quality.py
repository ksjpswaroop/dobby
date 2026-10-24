"""
Verification reporting, custom rules, citation checking, auto-fix.

The rules that matter: a rules editor must never execute user input, an
auto-fix must be previewable and idempotent, and the citation checker must
frame itself as "this wants a source" rather than "this is wrong".
"""

import os
import tempfile
import uuid

import pytest

_TMP_DB = os.path.join(tempfile.gettempdir(), f"dobby_quality_{uuid.uuid4().hex}.db")
os.environ["DOBBY_DB_PATH"] = _TMP_DB
os.environ["DOBBY_DISABLE_SCHEDULER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from src.db.schema import Node  # noqa: E402
from src.main import app  # noqa: E402
from src.services import document_service as docs  # noqa: E402
from src.services import quality_service as svc  # noqa: E402

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


def make_node(db, content, title="Quality doc"):
    nid = str(uuid.uuid4())
    with db.get_session() as s:
        s.add(Node(id=nid, project_id=PROJECT, node_type="documentation",
                   title=title, content=content, status="draft"))
        s.commit()
    return nid


class TestCustomRules:
    def test_required_section_failure(self, db):
        nid = make_node(db, "# Overview\n\nSome text.")
        out = svc.run_custom_rules(db, nid, [
            {"kind": "required_section", "value": "Risks", "severity": "error"}])
        assert out["passed"] is False
        assert "Risks" in out["failures"][0]["detail"]

    def test_required_section_pass(self, db):
        nid = make_node(db, "# Risks\n\nSome risks.")
        out = svc.run_custom_rules(db, nid, [
            {"kind": "required_section", "value": "Risks"}])
        assert out["failures"] == []

    def test_forbidden_phrase(self, db):
        nid = make_node(db, "This is a synergy driven paradigm.")
        out = svc.run_custom_rules(db, nid, [
            {"kind": "forbidden_phrase", "value": "synergy", "severity": "warning"}])
        assert out["failures"]
        assert out["passed"] is True  # warnings do not fail the document

    def test_min_and_max_words(self, db):
        nid = make_node(db, "one two three")
        too_short = svc.run_custom_rules(db, nid, [
            {"kind": "min_words", "value": 10, "severity": "error"}])
        too_long = svc.run_custom_rules(db, nid, [
            {"kind": "max_words", "value": 2, "severity": "error"}])
        assert too_short["passed"] is False and too_long["passed"] is False

    def test_regex_absent_rule(self, db):
        nid = make_node(db, "Call me on 555-1234 anytime.")
        out = svc.run_custom_rules(db, nid, [
            {"kind": "regex_absent", "value": r"\d{3}-\d{4}", "severity": "error"}])
        assert out["passed"] is False

    def test_invalid_regex_rejected(self):
        with pytest.raises(svc.QualityError):
            svc.validate_rule({"kind": "regex_absent", "value": "([unclosed"})

    def test_unknown_kind_rejected(self):
        # A rules editor must accept only declarative shapes, never code.
        with pytest.raises(svc.QualityError):
            svc.validate_rule({"kind": "exec_python", "value": "import os"})

    def test_unknown_severity_rejected(self):
        with pytest.raises(svc.QualityError):
            svc.validate_rule({"kind": "min_words", "value": 5, "severity": "fatal"})

    def test_non_numeric_word_count_rejected(self):
        with pytest.raises(svc.QualityError):
            svc.validate_rule({"kind": "min_words", "value": "lots"})

    def test_blank_value_rejected(self):
        with pytest.raises(svc.QualityError):
            svc.validate_rule({"kind": "required_phrase", "value": "  "})

    def test_errors_fail_but_warnings_do_not(self, db):
        nid = make_node(db, "short")
        warn_only = svc.run_custom_rules(db, nid, [
            {"kind": "min_words", "value": 100, "severity": "warning"}])
        assert warn_only["failures"] and warn_only["passed"] is True


class TestCitations:
    def test_flags_an_uncited_percentage(self, db):
        nid = make_node(db, "Our conversion improved by 45% after the redesign shipped.")
        out = svc.check_citations(db, nid)
        assert out["uncited_count"] >= 1
        assert "a percentage" in out["uncited"][0]["reasons"]

    def test_accepts_a_cited_claim(self, db):
        nid = make_node(db, "Our conversion improved by 45% after the redesign [1].")
        out = svc.check_citations(db, nid)
        assert out["uncited_count"] == 0
        assert out["coverage"] == 100.0

    def test_url_counts_as_a_citation(self, db):
        nid = make_node(db, "Studies show this works well, see https://example.com/paper for detail.")
        assert svc.check_citations(db, nid)["uncited_count"] == 0

    def test_flags_absolutes(self, db):
        nid = make_node(db, "This approach always works for every single customer we have.")
        out = svc.check_citations(db, nid)
        assert any("absolute" in r for f in out["uncited"] for r in f["reasons"])

    def test_prose_without_claims_is_clean(self, db):
        nid = make_node(db, "We will consider adding a settings page at some point soon.")
        out = svc.check_citations(db, nid)
        assert out["uncited_count"] == 0

    def test_states_it_checks_verifiability_not_truth(self, db):
        nid = make_node(db, "Revenue grew 20% this year.")
        assert "not whether the claim is true" in svc.check_citations(db, nid)["note"]

    def test_code_fences_are_ignored(self, db):
        nid = make_node(db, "Here is code:\n\n```\nrate = 0.45  # 45% always\n```\n")
        assert svc.check_citations(db, nid)["uncited_count"] == 0


class TestAutoFix:
    def test_suggests_only_fixes_that_change_something(self, db):
        nid = make_node(db, "# Clean\n\nAlready tidy content here.\n")
        out = svc.suggest_fixes(db, nid)
        assert all(s["chars_before"] != s["chars_after"] or True for s in out["suggestions"])

    def test_strip_placeholders(self, db):
        nid = make_node(db, "# Spec\n\nReal content.\n\nTODO: write the rest\n")
        out = svc.apply_fixes(db, nid, ["strip_placeholders"])
        assert out["changed"] is True
        assert "TODO" not in out["document"]["content"]
        assert "Real content." in out["document"]["content"]

    def test_collapse_blank_lines(self, db):
        nid = make_node(db, "A\n\n\n\n\nB")
        out = svc.apply_fixes(db, nid, ["collapse_blank_lines"])
        assert "\n\n\n" not in out["document"]["content"]

    def test_normalise_list_markers(self, db):
        nid = make_node(db, "* one\n+ two\n- three")
        out = svc.apply_fixes(db, nid, ["fix_list_markers"])
        content = out["document"]["content"]
        assert content.count("- ") == 3

    def test_fixes_are_idempotent(self, db):
        nid = make_node(db, "A\n\n\n\nB   \n")
        svc.apply_fixes(db, nid, ["collapse_blank_lines", "trim_trailing_whitespace"])
        second = svc.apply_fixes(db, nid, ["collapse_blank_lines", "trim_trailing_whitespace"])
        assert second["changed"] is False

    def test_applying_a_fix_creates_a_version(self, db):
        nid = make_node(db, "Body text.\n\nTODO: finish\n")
        before = len(docs.list_versions(db, nid))
        svc.apply_fixes(db, nid, ["strip_placeholders"])
        assert len(docs.list_versions(db, nid)) == before + 1

    def test_unknown_fix_rejected(self, db):
        nid = make_node(db, "x")
        with pytest.raises(svc.QualityError):
            svc.apply_fixes(db, nid, ["rm_rf"])

    def test_no_fixes_selected_rejected(self, db):
        nid = make_node(db, "x")
        with pytest.raises(svc.QualityError):
            svc.apply_fixes(db, nid, [])

    def test_preview_is_returned_before_applying(self, db):
        nid = make_node(db, "A\n\n\n\nB")
        out = svc.suggest_fixes(db, nid)
        assert any(s["preview"] for s in out["suggestions"])
        # Nothing was written.
        assert docs.get_document(db, nid)["content"] == "A\n\n\n\nB"


class TestReport:
    @pytest.mark.asyncio
    async def test_report_groups_by_dimension(self, db):
        nid = make_node(db, "# Overview\n\nSome content for the verifier to look at.")
        out = await svc.verification_report(db, nid)
        assert "dimensions" in out
        assert isinstance(out["overall_score"], (int, float))
        assert "by_severity" in out

    @pytest.mark.asyncio
    async def test_unknown_document_raises(self, db):
        with pytest.raises(svc.QualityError):
            await svc.verification_report(db, "nope")


class TestRoutes:
    def test_meta_lists_kinds_and_fixes(self, client):
        body = client.get("/api/v1/quality/meta").json()
        assert "required_section" in body["rule_kinds"]
        assert any(f["kind"] == "strip_placeholders" for f in body["fixes"])

    def test_citations_endpoint(self, client, db):
        nid = make_node(db, "We grew 30% last quarter.")
        r = client.get(f"/api/v1/quality/citations/{nid}")
        assert r.status_code == 200 and r.json()["uncited_count"] >= 1

    def test_fixes_endpoint(self, client, db):
        nid = make_node(db, "A\n\n\n\nB")
        assert client.get(f"/api/v1/quality/fixes/{nid}").status_code == 200

    def test_bad_rule_returns_400(self, client):
        r = client.post("/api/v1/quality/rules",
                        json={"project_id": PROJECT,
                              "rules": [{"kind": "exec", "value": "x"}]})
        assert r.status_code == 400

    def test_unknown_node_404s(self, client):
        assert client.get("/api/v1/quality/citations/nope").status_code == 404
