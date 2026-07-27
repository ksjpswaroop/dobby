"""
Journal and the app registry.

The rules that matter: one entry per date, an auto-draft assembled from what
actually happened rather than invented, and an entry that stops being a draft
the moment a human edits it.
"""

import os
import tempfile
import uuid
from datetime import datetime, timedelta

import pytest

_TMP_DB = os.path.join(tempfile.gettempdir(), f"dobby_journal_{uuid.uuid4().hex}.db")
os.environ["DOBBY_DB_PATH"] = _TMP_DB
os.environ["DOBBY_DISABLE_SCHEDULER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from src.db.schema import Project  # noqa: E402
from src.main import app  # noqa: E402
from src.services import journal_service as svc  # noqa: E402

TODAY = datetime.now().date().isoformat()


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


@pytest.fixture
def proj(db):
    pid = f"jr-{uuid.uuid4().hex[:8]}"
    with db.get_session() as s:
        s.add(Project(id=pid, name="Journal test"))
        s.commit()
    return pid


class TestWriting:
    def test_write_and_read_back(self, db, proj):
        svc.write(db, proj, "Shipped the thing.", TODAY, "A good day")
        e = svc.get(db, proj, TODAY)
        assert e["body"] == "Shipped the thing."
        assert e["title"] == "A good day"

    def test_one_entry_per_date(self, db, proj):
        svc.write(db, proj, "First version", TODAY)
        svc.write(db, proj, "Corrected version", TODAY)
        entries = svc.list_entries(db, proj)
        # Six half-written entries for one evening is a journal nobody reads.
        assert len([e for e in entries if e["entry_date"] == TODAY]) == 1
        assert svc.get(db, proj, TODAY)["body"] == "Corrected version"

    def test_different_kinds_coexist_on_a_date(self, db, proj):
        svc.write(db, proj, "Daily note", TODAY, kind="reflection")
        svc.write(db, proj, "Week in review", TODAY, kind="weekly")
        assert svc.get(db, proj, TODAY, "reflection")["body"] == "Daily note"
        assert svc.get(db, proj, TODAY, "weekly")["body"] == "Week in review"

    def test_blank_body_rejected(self, db, proj):
        with pytest.raises(svc.JournalError):
            svc.write(db, proj, "   ", TODAY)

    def test_unknown_kind_rejected(self, db, proj):
        with pytest.raises(svc.JournalError):
            svc.write(db, proj, "x", TODAY, kind="diary")

    def test_bad_date_rejected(self, db, proj):
        with pytest.raises(svc.JournalError):
            svc.write(db, proj, "x", entry_date="last thursday")

    def test_unknown_project_rejected(self, db):
        with pytest.raises(svc.JournalError):
            svc.write(db, "no-such-project", "x", TODAY)

    def test_delete(self, db, proj):
        e = svc.write(db, proj, "Temporary", TODAY)
        assert svc.delete(db, e["id"]) is True
        assert svc.get(db, proj, TODAY) is None

    def test_entries_come_back_newest_first(self, db, proj):
        older = (datetime.now().date() - timedelta(days=3)).isoformat()
        svc.write(db, proj, "Older", older)
        svc.write(db, proj, "Newer", TODAY)
        dates = [e["entry_date"] for e in svc.list_entries(db, proj)]
        assert dates == sorted(dates, reverse=True)


class TestAutoDraft:
    def test_draft_is_assembled_from_real_events(self, db, proj):
        from src.services import idea_service

        idea_service.capture(db, proj, "something that happened today")
        draft = svc.auto_entry(db, proj, TODAY)
        assert draft["event_count"] >= 1
        # Built from the timeline, not invented by a model.
        assert "something that happened today" in draft["body"]

    def test_quiet_day_says_so_and_asks(self, db, proj):
        quiet = (datetime.now().date() - timedelta(days=200)).isoformat()
        draft = svc.auto_entry(db, proj, quiet)
        assert draft["event_count"] == 0
        assert "Nothing was recorded" in draft["body"]
        assert "What did you work on?" in draft["body"]

    def test_draft_does_not_save_unless_asked(self, db, proj):
        svc.auto_entry(db, proj, TODAY, save=False)
        assert svc.get(db, proj, TODAY) is None

    def test_draft_can_be_saved(self, db, proj):
        out = svc.auto_entry(db, proj, TODAY, save=True)
        assert out["saved"] is True
        assert svc.get(db, proj, TODAY) is not None

    def test_editing_a_draft_clears_the_draft_flag(self, db, proj):
        svc.auto_entry(db, proj, TODAY, save=True)
        assert svc.get(db, proj, TODAY)["auto_drafted"] is True
        svc.write(db, proj, "My own words about the day.", TODAY)
        # "You have not written today" must stop being true once you have.
        assert svc.get(db, proj, TODAY)["auto_drafted"] is False

    def test_draft_includes_reflection_prompts(self, db, proj):
        from src.services import idea_service

        idea_service.capture(db, proj, "an event")
        draft = svc.auto_entry(db, proj, TODAY)
        assert "What went well?" in draft["body"]


class TestStreak:
    def test_counts_entries_in_the_window(self, db, proj):
        for i in range(3):
            day = (datetime.now().date() - timedelta(days=i)).isoformat()
            svc.write(db, proj, f"Entry {i}", day)
        out = svc.streak(db, proj)
        assert out["in_window"] >= 3

    def test_streak_counts_consecutive_days(self, db, proj):
        for i in range(3):
            day = (datetime.now().date() - timedelta(days=i)).isoformat()
            svc.write(db, proj, f"Day {i}", day)
        assert svc.streak(db, proj)["current_streak"] == 3

    def test_missing_today_does_not_break_the_streak(self, db, proj):
        for i in (1, 2):
            day = (datetime.now().date() - timedelta(days=i)).isoformat()
            svc.write(db, proj, f"Day {i}", day)
        # Not having written yet at 9am is not a broken streak.
        assert svc.streak(db, proj)["current_streak"] == 2

    def test_empty_journal_has_no_streak(self, db, proj):
        assert svc.streak(db, proj)["current_streak"] == 0


class TestAppRegistry:
    def test_lists_the_built_in_apps(self, db, proj):
        reg = svc.app_registry(db, proj)
        slugs = {a["slug"] for a in reg["apps"]}
        assert {"daily_alignment", "work_graph", "decisions", "skill_studio"} <= slugs

    def test_every_app_declares_reads_and_writes(self, db, proj):
        for a in svc.app_registry(db, proj)["apps"]:
            assert "reads" in a and "writes" in a
            assert a["route"].startswith("/")

    def test_shared_substrate_is_described(self, db, proj):
        shared = svc.app_registry(db, proj)["shared"]
        assert {"memory", "permissions", "work_graph"} <= set(shared)
        assert "one approval gate" in shared["permissions"].lower()

    def test_your_skills_are_listed_separately(self, db, proj):
        from src.services import skill_service

        skill_service.create(db, proj, "My own skill", "Do {{input}}")
        reg = svc.app_registry(db, proj)
        assert any(s["name"] == "My own skill" for s in reg["your_skills"])
        # Built-ins are apps, not "your" skills.
        assert all(s["name"] != "Seven-artifact document set"
                   for s in reg["your_skills"])

    def test_unknown_project_rejected(self, db):
        with pytest.raises(svc.JournalError):
            svc.app_registry(db, "no-such-project")


class TestRoutes:
    def test_write_and_list(self, client, proj):
        r = client.post("/api/v1/journal", json={
            "project_id": proj, "body": "Via the API", "entry_date": TODAY})
        assert r.status_code == 200
        listed = client.get(f"/api/v1/journal/project/{proj}").json()
        assert listed["entries"]

    def test_missing_entry_404s(self, client, proj):
        assert client.get(
            f"/api/v1/journal/project/{proj}/2020-01-01").status_code == 404

    def test_blank_body_400s(self, client, proj):
        r = client.post("/api/v1/journal",
                        json={"project_id": proj, "body": " "})
        assert r.status_code == 422 or r.status_code == 400

    def test_auto_endpoint(self, client, proj):
        r = client.post(f"/api/v1/journal/auto/{proj}", json={"save": False})
        assert r.status_code == 200 and "body" in r.json()

    def test_apps_endpoint(self, client, proj):
        r = client.get(f"/api/v1/apps/{proj}")
        assert r.status_code == 200
        assert r.json()["local_first"] is True

    def test_streak_endpoint(self, client, proj):
        assert client.get(f"/api/v1/journal/project/{proj}/streak").status_code == 200
