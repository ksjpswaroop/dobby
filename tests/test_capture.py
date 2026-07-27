"""
Capture++ — bulk import, email, OCR, URL, meeting notes, dedupe.

The rules that matter: re-running an import must not double the inbox, a
merge must not lose the distinct half of a duplicate, and URL fetching must
refuse to touch the network unless the user opted in.
"""

import os
import tempfile
import uuid

import pytest

_TMP_DB = os.path.join(tempfile.gettempdir(), f"dobby_capture_{uuid.uuid4().hex}.db")
os.environ["DOBBY_DB_PATH"] = _TMP_DB
os.environ["DOBBY_DISABLE_SCHEDULER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from src.main import app  # noqa: E402
from src.services import capture_service as svc  # noqa: E402
from src.services import idea_service  # noqa: E402

PROJECT = "default-project"

EML = """From: Alice <alice@example.com>
To: Bob <bob@example.com>
Subject: Idea for the export feature
Date: Mon, 27 Jul 2026 10:00:00 +0000
Content-Type: text/plain; charset="utf-8"

We should let people export the audit log as CSV.
Compliance keeps asking for it.
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


class TestParsers:
    def test_csv_uses_a_recognised_title_column(self):
        out = svc.parse_csv("id,title,notes\n1,First idea,x\n2,Second idea,y")
        assert out == ["First idea", "Second idea"]

    def test_csv_without_header_uses_longest_cell(self):
        out = svc.parse_csv("1,A much longer descriptive cell\n2,Short")
        assert "A much longer descriptive cell" in out

    def test_markdown_takes_headings_and_bullets(self):
        out = svc.parse_markdown("# Alpha\n\n- Beta\n* Gamma\n\n## Delta")
        assert out == ["Alpha", "Beta", "Gamma", "Delta"]

    def test_markdown_ignores_code_fences(self):
        out = svc.parse_markdown("# Real\n\n```\n# Not a heading\n- not a bullet\n```")
        assert out == ["Real"]

    def test_markdown_strips_checkboxes(self):
        assert svc.parse_markdown("- [ ] Do the thing") == ["Do the thing"]

    def test_notion_detects_csv(self):
        assert svc.parse_notion("title,notes\nFrom notion,x") == ["From notion"]


class TestBulkImport:
    def test_imports_ideas(self, db):
        out = svc.bulk_import(db, PROJECT, "# One\n# Two\n# Three", "markdown")
        assert out["imported"] == 3

    def test_rerunning_the_same_import_skips_duplicates(self, db):
        text = "# Unique alpha item\n# Unique beta item"
        first = svc.bulk_import(db, PROJECT, text, "markdown")
        second = svc.bulk_import(db, PROJECT, text, "markdown")
        assert first["imported"] == 2
        assert second["imported"] == 0
        assert second["skipped_as_duplicate"] == 2

    def test_within_batch_duplicates_collapse(self, db):
        out = svc.bulk_import(db, PROJECT,
                              "# Repeated thing here\n# Repeated thing here", "markdown")
        assert out["imported"] == 1

    def test_dry_run_writes_nothing(self, db):
        before = len(idea_service.list_ideas(db, PROJECT))
        out = svc.bulk_import(db, PROJECT, "# Dry run only item", "markdown", dry_run=True)
        assert out["dry_run"] is True
        assert len(idea_service.list_ideas(db, PROJECT)) == before

    def test_empty_content_rejected(self, db):
        with pytest.raises(svc.CaptureError):
            svc.bulk_import(db, PROJECT, "   ", "markdown")

    def test_unknown_format_rejected(self, db):
        with pytest.raises(svc.CaptureError):
            svc.bulk_import(db, PROJECT, "x", "xml")


class TestEmail:
    def test_parses_headers_and_body(self):
        out = svc.parse_eml(EML)
        assert out["subject"] == "Idea for the export feature"
        assert "audit log" in out["body"]

    def test_import_creates_an_idea(self, db):
        out = svc.import_email(db, PROJECT, EML)
        assert "Idea for the export feature" in out["idea"]["text"]

    def test_garbage_still_parses_without_crashing(self, db):
        # An empty/garbage message parses to empty headers rather than raising;
        # capture then rejects it for being blank.
        out = svc.parse_eml("not really an email")
        assert out["subject"] == ""


class TestDedupe:
    def test_similar_text_scores_high(self):
        assert svc.similarity("add csv export", "add CSV export!") > 0.9

    def test_different_text_scores_low(self):
        assert svc.similarity("add csv export", "rewrite the auth layer") < 0.5

    def test_finds_duplicate_pairs(self, db):
        idea_service.capture(db, PROJECT, "Add a dark mode toggle to settings")
        idea_service.capture(db, PROJECT, "Add a dark mode toggle to Settings.")
        pairs = svc.find_duplicates(db, PROJECT)
        assert any("dark mode" in p["keep_text"].lower() for p in pairs)

    def test_merge_keeps_distinct_content(self, db):
        a = idea_service.capture(db, PROJECT, "Ship the widget")
        b = idea_service.capture(db, PROJECT, "Ship the widget by Friday please")
        out = svc.merge_ideas(db, a["id"], [b["id"]])
        assert "Friday" in out["text"]
        assert idea_service.get(db, b["id"]) is None

    def test_merging_identical_text_does_not_duplicate_it(self, db):
        a = idea_service.capture(db, PROJECT, "Exactly the same sentence")
        b = idea_service.capture(db, PROJECT, "Exactly the same sentence")
        out = svc.merge_ideas(db, a["id"], [b["id"]])
        assert out["text"].count("Exactly the same sentence") == 1

    def test_merge_with_nothing_rejected(self, db):
        a = idea_service.capture(db, PROJECT, "Nothing to merge into me")
        with pytest.raises(svc.CaptureError):
            svc.merge_ideas(db, a["id"], [])


class TestUrlImport:
    @pytest.mark.asyncio
    async def test_refuses_without_network_opt_in(self, db, monkeypatch):
        class FakeSettings:
            search_provider = "none"

        monkeypatch.setattr("src.settings.get_settings", lambda: FakeSettings())
        with pytest.raises(svc.CaptureError) as e:
            await svc.import_url(db, PROJECT, "https://example.com")
        assert "off by default" in str(e.value)

    @pytest.mark.asyncio
    async def test_rejects_non_http(self, db):
        with pytest.raises(svc.CaptureError):
            await svc.import_url(db, PROJECT, "ftp://example.com")

    def test_html_stripping_extracts_title_and_text(self):
        title, body = svc._strip_html(
            "<html><head><title>My Page</title></head>"
            "<body><script>bad()</script><p>Hello &amp; welcome</p></body></html>")
        assert title == "My Page"
        assert "Hello & welcome" in body
        assert "bad()" not in body


class TestOCR:
    def test_capabilities_report_honestly(self):
        caps = svc.ocr_capabilities()
        assert "ready" in caps
        if not caps["ready"]:
            assert "tesseract" in caps["reason"].lower()

    def test_missing_file_rejected(self):
        if not svc.ocr_capabilities()["ready"]:
            pytest.skip("tesseract not installed")
        with pytest.raises(svc.CaptureError):
            svc.ocr_image("/nonexistent/image.png")


class TestMeetingNotes:
    @pytest.mark.asyncio
    async def test_extract_proposes_without_writing(self, db, monkeypatch):
        async def fake_call(*a, **k):
            return ('[{"kind":"action","text":"Send the report","owner":"Alice"},'
                    '{"kind":"decision","text":"We ship on Friday"}]')

        monkeypatch.setattr("src.services.model_routing.call", fake_call)
        before = len(idea_service.list_ideas(db, PROJECT))
        out = await svc.extract_action_items(db, PROJECT, "some notes")
        assert out["counts"]["action"] == 1
        assert len(idea_service.list_ideas(db, PROJECT)) == before

    @pytest.mark.asyncio
    async def test_unknown_kind_falls_back_to_action(self, db, monkeypatch):
        async def fake_call(*a, **k):
            return '[{"kind":"banana","text":"Something"}]'

        monkeypatch.setattr("src.services.model_routing.call", fake_call)
        out = await svc.extract_action_items(db, PROJECT, "notes")
        assert out["items"][0]["kind"] == "action"

    @pytest.mark.asyncio
    async def test_blank_notes_rejected(self, db):
        with pytest.raises(svc.CaptureError):
            await svc.extract_action_items(db, PROJECT, "  ")

    @pytest.mark.asyncio
    async def test_unparseable_output_raises(self, db, monkeypatch):
        async def fake_call(*a, **k):
            return "We talked about a few things"

        monkeypatch.setattr("src.services.model_routing.call", fake_call)
        with pytest.raises(svc.CaptureError):
            await svc.extract_action_items(db, PROJECT, "notes")

    def test_parser_accepts_a_bare_object(self):
        # Local models in JSON mode routinely return one object rather than
        # the requested array; llama3.2 does exactly this.
        out = svc._extract_json_array('{"kind":"decision","text":"Ship it"}')
        assert out == [{"kind": "decision", "text": "Ship it"}]

    def test_parser_accepts_a_wrapped_array(self):
        out = svc._extract_json_array('{"items":[{"kind":"idea","text":"Maybe"}]}')
        assert out[0]["text"] == "Maybe"

    def test_parser_accepts_a_fenced_array(self):
        out = svc._extract_json_array('```json\n[{"text":"Fenced"}]\n```')
        assert out[0]["text"] == "Fenced"

    def test_parser_rejects_prose(self):
        assert svc._extract_json_array("I think we should ship it") is None

    def test_accept_creates_labelled_ideas(self, db):
        out = svc.accept_action_items(db, PROJECT, [
            {"kind": "action", "text": "Book the venue", "owner": "Bob"},
        ])
        assert out["created"] == 1
        assert "[action] (Bob)" in out["ideas"][0]["text"]


class TestTemplates:
    def test_gallery_lists_templates(self):
        slugs = {t["slug"] for t in svc.list_templates()}
        assert {"feature_idea", "bug_report", "meeting_notes"} <= slugs

    def test_get_by_slug(self):
        assert svc.get_template("bug_report")["name"] == "Bug report"

    def test_unknown_slug_rejected(self):
        with pytest.raises(svc.CaptureError):
            svc.get_template("nope")


class TestRoutes:
    def test_meta_reports_ocr_state(self, client):
        body = client.get("/api/v1/capture/meta").json()
        assert "ocr" in body and "csv" in body["formats"]

    def test_templates_endpoint(self, client):
        assert client.get("/api/v1/capture/templates").json()["templates"]

    def test_bulk_endpoint(self, client):
        r = client.post("/api/v1/capture/bulk", json={
            "project_id": PROJECT, "text": "# Via the API route", "format": "markdown"})
        assert r.status_code == 200

    def test_email_endpoint(self, client):
        r = client.post("/api/v1/capture/email",
                        json={"project_id": PROJECT, "raw": EML})
        assert r.status_code == 200

    def test_duplicates_endpoint(self, client):
        assert client.get(f"/api/v1/capture/duplicates/{PROJECT}").status_code == 200

    def test_bad_format_returns_400(self, client):
        r = client.post("/api/v1/capture/bulk", json={
            "project_id": PROJECT, "text": "x", "format": "xml"})
        assert r.status_code == 400
