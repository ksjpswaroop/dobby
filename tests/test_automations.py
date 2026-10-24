"""
Scheduled automations.

Two things carry risk here and are tested hardest: the cron arithmetic (a
wrong next-fire silently runs work at the wrong time, or never) and the loop's
overlap/catch-up rules (which decide whether closing your laptop loses work or
buries you in it).
"""

import os
import tempfile
import uuid
from datetime import datetime, timedelta, timezone

import pytest

_TMP_DB = os.path.join(tempfile.gettempdir(), f"dobby_auto_{uuid.uuid4().hex}.db")
os.environ["DOBBY_DB_PATH"] = _TMP_DB
os.environ["DOBBY_DISABLE_SCHEDULER"] = "1"  # never tick during tests

from fastapi.testclient import TestClient  # noqa: E402

from src.main import app  # noqa: E402
from src.scheduler import cron  # noqa: E402
from src.services import automation_service as svc  # noqa: E402

PROJECT = "default-project"
# A Sunday, 08:30 UTC.
BASE = datetime(2026, 7, 26, 8, 30, tzinfo=timezone.utc)


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


class TestCronParsing:
    @pytest.mark.parametrize("expr,expected", [
        ("* * * * *", "2026-07-26T08:31"),
        ("*/15 * * * *", "2026-07-26T08:45"),
        ("0 * * * *", "2026-07-26T09:00"),
        ("0 9 * * *", "2026-07-26T09:00"),
        ("0 9 * * 1-5", "2026-07-27T09:00"),      # Sunday -> Monday
        ("30 8 * * 0", "2026-08-02T08:30"),        # this minute passed; next Sunday
        ("0 0 1 * *", "2026-08-01T00:00"),
        ("@hourly", "2026-07-26T09:00"),
        ("@daily", "2026-07-27T00:00"),
    ])
    def test_next_fire(self, expr, expected):
        got = cron.next_fire(expr, BASE, "UTC")
        assert got.strftime("%Y-%m-%dT%H:%M") == expected

    def test_names_are_accepted(self):
        assert cron.next_fire("0 9 * * mon", BASE, "UTC").weekday() == 0
        assert cron.next_fire("0 0 1 jan *", BASE, "UTC").month == 1

    def test_sunday_is_both_0_and_7(self):
        assert cron.next_fire("0 9 * * 0", BASE, "UTC") == cron.next_fire("0 9 * * 7", BASE, "UTC")

    def test_schedule_is_evaluated_in_its_own_timezone(self):
        """9am must mean 9am where the user is, not 9am UTC."""
        ny = cron.next_fire("0 9 * * *", BASE, "America/New_York")
        assert ny.hour == 13  # 09:00 EDT == 13:00 UTC

    def test_unknown_timezone_falls_back_to_utc(self):
        assert cron.next_fire("0 9 * * *", BASE, "Mars/Olympus").hour == 9

    def test_an_impossible_schedule_never_fires(self):
        assert cron.next_fire("0 0 30 2 *", BASE, "UTC") is None

    def test_either_or_rule_when_both_day_fields_restricted(self):
        # Vixie-cron: day-of-month OR day-of-week when both are restricted.
        s = cron.parse("0 0 1 * 1")
        assert s.dom_restricted and s.dow_restricted
        assert s.matches(datetime(2026, 9, 1, 0, 0))    # the 1st, a Tuesday
        assert s.matches(datetime(2026, 9, 7, 0, 0))    # a Monday, not the 1st

    @pytest.mark.parametrize("bad,fragment", [
        ("", "Enter a schedule"),
        ("* * *", "5 fields"),
        ("99 * * * *", "out of range"),
        ("0 9 * * abc", "not valid"),
        ("5-1 * * * *", "backwards"),
        ("*/0 * * * *", "positive whole number"),
    ])
    def test_invalid_expressions_explain_themselves(self, bad, fragment):
        with pytest.raises(cron.CronError, match=fragment):
            cron.parse(bad)

    def test_describe_is_human_readable(self):
        assert "09:00" in cron.describe("0 9 * * 1-5", "UTC")
        assert "Mon" in cron.describe("0 9 * * 1-5", "UTC")
        assert cron.describe("@daily") == "Every day at midnight"


class TestCrud:
    def test_create_computes_the_next_run(self, db):
        a = svc.create(db, PROJECT, "Morning digest", "digest", cron_expr="0 9 * * *")
        assert a["enabled"] and a["next_run"]
        assert a["schedule_text"]

    def test_a_bad_cron_is_rejected_before_saving(self, db):
        with pytest.raises(svc.AutomationError, match="5 fields"):
            svc.create(db, PROJECT, "Broken", "digest", cron_expr="not a cron")

    def test_an_unknown_action_is_rejected(self, db):
        with pytest.raises(svc.AutomationError, match="Unknown action"):
            svc.create(db, PROJECT, "X", "teleport", cron_expr="@daily")

    def test_a_one_off_needs_a_time(self, db):
        with pytest.raises(svc.AutomationError, match="date and time"):
            svc.create(db, PROJECT, "Once", "digest", trigger="once")

    def test_a_one_off_does_not_reschedule_itself(self, db):
        when = (datetime.utcnow() + timedelta(hours=1)).isoformat()
        a = svc.create(db, PROJECT, "One shot", "digest", trigger="once", run_at=when)
        assert a["next_run"] is not None

        from src.db.automation_models import Automation

        with db.get_session() as s:
            row = s.get(Automation, a["id"])
            row.run_count = 1
            assert svc.compute_next(row) is None

    def test_disable_clears_the_next_run_and_enable_rearms_it(self, db):
        a = svc.create(db, PROJECT, "Toggle me", "digest", cron_expr="@hourly")
        off = svc.set_enabled(db, a["id"], False)
        assert off["enabled"] is False and off["next_run"] is None
        on = svc.set_enabled(db, a["id"], True)
        assert on["enabled"] is True and on["next_run"] is not None

    def test_delete_removes_it(self, db):
        a = svc.create(db, PROJECT, "Temp", "digest", cron_expr="@daily")
        assert svc.delete(db, a["id"]) is True
        assert svc.get(db, a["id"]) is None


class TestFiring:
    @pytest.mark.asyncio
    async def test_a_digest_run_succeeds_and_records_history(self, db):
        a = svc.create(db, PROJECT, "Digest", "digest", cron_expr="@daily")
        result = await svc.fire(db, a["id"], source="manual")
        assert result["success"], result.get("error")

        runs = svc.list_runs(db, a["id"])
        assert len(runs) == 1
        assert runs[0]["status"] == "ok" and runs[0]["trigger_source"] == "manual"

        after = svc.get(db, a["id"])
        assert after["run_count"] == 1 and after["last_status"] == "ok"
        assert after["next_run"] is not None      # rescheduled
        assert after["unread_count"] == 1         # asks for attention

    @pytest.mark.asyncio
    async def test_overlap_is_skipped_and_recorded(self, db):
        """A firing already in flight must not stack up another."""
        from src.db.automation_models import Automation

        a = svc.create(db, PROJECT, "Busy", "digest", cron_expr="@hourly")
        with db.get_session() as s:
            s.get(Automation, a["id"]).is_running = True
            s.commit()

        result = await svc.fire(db, a["id"])
        assert result["success"] is False and result["skipped"] is True
        assert svc.list_runs(db, a["id"])[0]["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_the_max_runs_cap_disables_the_automation(self, db):
        a = svc.create(db, PROJECT, "Twice only", "digest",
                       cron_expr="@hourly", max_runs=1)
        await svc.fire(db, a["id"])
        assert svc.get(db, a["id"])["enabled"] is False

        blocked = await svc.fire(db, a["id"])
        assert blocked["success"] is False and "limit" in blocked["error"]

    @pytest.mark.asyncio
    async def test_a_failing_action_is_recorded_not_raised(self, db):
        """One broken automation must not be able to stop the loop."""
        from src.db.automation_models import Automation

        a = svc.create(db, PROJECT, "Breaks", "digest", cron_expr="@daily")
        with db.get_session() as s:
            s.get(Automation, a["id"]).action = "nonexistent"
            s.commit()

        result = await svc.fire(db, a["id"])
        assert result["success"] is False
        assert svc.get(db, a["id"])["last_status"] == "failed"

    @pytest.mark.asyncio
    async def test_marking_read_clears_the_badge(self, db):
        a = svc.create(db, PROJECT, "Unread", "digest", cron_expr="@daily")
        await svc.fire(db, a["id"])
        assert svc.get(db, a["id"])["unread_count"] == 1
        svc.mark_read(db, a["id"])
        assert svc.get(db, a["id"])["unread_count"] == 0
        assert all(r["read"] for r in svc.list_runs(db, a["id"]))

    @pytest.mark.asyncio
    async def test_firing_writes_to_the_audit_log(self, db):
        from src.db.schema import AuditEntry

        a = svc.create(db, PROJECT, "Audited", "digest", cron_expr="@daily")
        await svc.fire(db, a["id"])
        with db.get_session() as s:
            actions = [e.action for e in s.query(AuditEntry).all()]
        assert any(x.startswith("automation.") for x in actions)


class TestLoopSelection:
    def test_only_due_enabled_automations_are_picked_up(self, db):
        from src.db.automation_models import Automation

        due = svc.create(db, PROJECT, "Due now", "digest", cron_expr="@hourly")
        later = svc.create(db, PROJECT, "Later", "digest", cron_expr="@yearly")
        off = svc.create(db, PROJECT, "Disabled", "digest", cron_expr="@hourly")
        svc.set_enabled(db, off["id"], False)

        with db.get_session() as s:
            s.get(Automation, due["id"]).next_run = datetime.utcnow() - timedelta(minutes=1)
            s.commit()

        ids = svc.due_automations(db)
        assert due["id"] in ids
        assert later["id"] not in ids and off["id"] not in ids

    def test_catchup_runs_recent_misses_and_rearms_stale_ones(self, db):
        from src.db.automation_models import Automation

        recent = svc.create(db, PROJECT, "Missed an hour ago", "digest", cron_expr="@hourly")
        stale = svc.create(db, PROJECT, "Missed last month", "digest", cron_expr="@hourly")
        with db.get_session() as s:
            s.get(Automation, recent["id"]).next_run = datetime.utcnow() - timedelta(hours=2)
            s.get(Automation, stale["id"]).next_run = datetime.utcnow() - timedelta(days=30)
            s.commit()

        targets = svc.catch_up_targets(db)
        assert recent["id"] in targets
        # Too old to be worth running — re-armed into the future instead.
        assert stale["id"] not in targets
        assert svc.get(db, stale["id"])["next_run"] is not None

    def test_catchup_clears_a_stuck_running_flag(self, db):
        """A crash mid-run would otherwise block the automation forever."""
        from src.db.automation_models import Automation

        a = svc.create(db, PROJECT, "Stuck", "digest", cron_expr="@hourly")
        with db.get_session() as s:
            row = s.get(Automation, a["id"])
            row.is_running = True
            row.next_run = datetime.utcnow() - timedelta(minutes=5)
            s.commit()

        svc.catch_up_targets(db)
        assert svc.get(db, a["id"])["is_running"] is False


class TestApi:
    def test_meta_lists_actions_and_presets(self, client):
        r = client.get("/api/v1/automations/meta")
        assert r.status_code == 200
        body = r.json()
        assert {a["id"] for a in body["actions"]} >= {"research", "digest"}
        assert body["presets"]

    def test_preview_validates_and_describes(self, client):
        r = client.post("/api/v1/automations/preview",
                        json={"cron": "0 9 * * 1-5", "timezone": "UTC"})
        assert r.status_code == 200
        assert r.json()["next_run"] and "09:00" in r.json()["description"]

    def test_preview_rejects_a_bad_expression(self, client):
        r = client.post("/api/v1/automations/preview", json={"cron": "nope"})
        assert r.status_code == 400

    def test_preview_flags_a_schedule_that_never_fires(self, client):
        r = client.post("/api/v1/automations/preview", json={"cron": "0 0 30 2 *"})
        assert r.json()["never"] is True

    def test_create_list_and_delete(self, client):
        r = client.post("/api/v1/automations", json={
            "project_id": PROJECT, "name": "Via API", "action": "digest",
            "cron": "@daily",
        })
        assert r.status_code == 200, r.text
        aid = r.json()["id"]

        listing = client.get(f"/api/v1/automations/project/{PROJECT}").json()
        assert any(a["id"] == aid for a in listing["automations"])
        assert "unread" in listing

        assert client.delete(f"/api/v1/automations/{aid}").status_code == 200

    def test_a_bad_cron_is_a_400_with_the_reason(self, client):
        r = client.post("/api/v1/automations", json={
            "project_id": PROJECT, "name": "Bad", "action": "digest", "cron": "* * *",
        })
        assert r.status_code == 400 and "5 fields" in r.json()["detail"]

    def test_missing_automation_is_404(self, client):
        assert client.get("/api/v1/automations/nope").status_code == 404
        assert client.post("/api/v1/automations/nope/run").status_code == 404
