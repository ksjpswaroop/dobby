"""
Approval-gated command execution.

This is the largest increase in blast radius in the app, so the tests are
weighted entirely towards what must *not* happen: no shell interpretation, no
escaping the workspace, no running unapproved programs, and no destructive
command being one click away.
"""

import os
import tempfile
import uuid
from pathlib import Path

import pytest

_TMP_DB = os.path.join(tempfile.gettempdir(), f"dobby_term_{uuid.uuid4().hex}.db")
os.environ["DOBBY_DB_PATH"] = _TMP_DB
os.environ["DOBBY_DISABLE_SCHEDULER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from src.main import app  # noqa: E402
from src.services import inbox_service as inbox  # noqa: E402
from src.services import terminal_service as svc  # noqa: E402

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


@pytest.fixture
def allow(monkeypatch):
    """Put programs on the allowlist for one test."""
    def _set(*programs):
        monkeypatch.setattr(svc, "allowlist", lambda: list(programs))
    return _set


class TestParsing:
    def test_a_plain_command_becomes_argv(self):
        assert svc.parse("ls -la /tmp") == ["ls", "-la", "/tmp"]

    def test_quotes_are_respected(self):
        assert svc.parse('echo "hello world"') == ["echo", "hello world"]

    @pytest.mark.parametrize("bad", [
        "ls; rm -rf /", "ls && whoami", "ls | grep x", "cat < file",
        "echo hi > out.txt", "echo `whoami`", "echo $(whoami)",
    ])
    def test_shell_metacharacters_are_refused(self, bad):
        """No shell means these would be inert argv text — confusing, so reject."""
        with pytest.raises(svc.TerminalError, match="without a shell"):
            svc.parse(bad)

    @pytest.mark.parametrize("bad", ["", "   "])
    def test_empty_input_is_refused(self, bad):
        with pytest.raises(svc.TerminalError, match="Enter a command"):
            svc.parse(bad)

    @pytest.mark.parametrize("ok,expected", [
        ("python3 -c 'import sys; sys.exit(1)'", ["python3", "-c", "import sys; sys.exit(1)"]),
        ('grep "a|b" file.txt', ["grep", "a|b", "file.txt"]),
    ])
    def test_metacharacters_inside_quotes_are_ordinary_text(self, ok, expected):
        """A semicolon in a quoted argument is not shell chaining."""
        assert svc.parse(ok) == expected

    def test_unbalanced_quotes_explain_themselves(self):
        with pytest.raises(svc.TerminalError, match="Could not parse"):
            svc.parse('echo "unclosed')


class TestClassification:
    def test_an_allowlisted_program_runs_without_asking(self, allow):
        allow("ls")
        assert svc.classify(["ls", "-la"])["decision"] == "allowed"

    def test_anything_else_asks(self, allow):
        allow("ls")
        assert svc.classify(["curl", "example.com"])["decision"] == "ask"

    def test_the_allowlist_is_empty_by_default(self, monkeypatch):
        """OW row 53: nothing runs unattended out of the box."""
        monkeypatch.setattr(svc, "_settings", lambda: type("S", (), {})())
        assert svc.allowlist() == []

    @pytest.mark.parametrize("argv,why", [
        (["rm", "-rf", "/"], "recursive delete"),
        (["rm", "-fr", "~"], "recursive delete"),
        (["sudo", "anything"], "privilege escalation"),
        (["dd", "if=/dev/zero"], "disk operation"),
        (["mkfs", "/dev/disk1"], "disk operation"),
        (["shutdown", "-h", "now"], "power control"),
        (["chmod", "-R", "777", "/"], "recursive permission change"),
    ])
    def test_destructive_commands_are_denied_outright(self, argv, why):
        out = svc.classify(argv)
        assert out["decision"] == "denied" and out["reason"] == why

    def test_a_denied_command_is_refused_even_if_allowlisted(self, allow, db):
        """Approval must not be able to unlock these."""
        allow("rm")
        assert svc.classify(["rm", "-rf", "/"])["decision"] == "denied"

    def test_non_recursive_rm_is_not_auto_denied(self):
        # Still needs approval — just not on the hard denylist.
        assert svc.classify(["rm", "one-file.txt"])["decision"] == "ask"

    def test_a_full_path_is_classified_by_program_name(self, allow):
        allow("ls")
        assert svc.classify(["/bin/ls"])["decision"] == "allowed"


class TestWorkspaceScoping:
    def test_the_default_directory_is_the_project_workspace(self):
        root = svc.project_root(PROJECT)
        assert root.is_dir() and PROJECT in str(root)

    def test_a_relative_path_stays_inside(self):
        root = svc.project_root(PROJECT)
        (root / "sub").mkdir(exist_ok=True)
        assert svc._resolve_cwd(PROJECT, "sub") == (root / "sub").resolve()

    @pytest.mark.parametrize("escape", ["..", "../..", "/etc", "../../../"])
    def test_escaping_the_workspace_is_refused(self, escape):
        with pytest.raises(svc.TerminalError, match="stay inside"):
            svc._resolve_cwd(PROJECT, escape)

    def test_a_missing_directory_is_refused(self):
        with pytest.raises(svc.TerminalError, match="No such directory"):
            svc._resolve_cwd(PROJECT, "definitely-not-here")


class TestExecution:
    @pytest.mark.asyncio
    async def test_an_allowlisted_command_runs_and_captures_output(self, db, allow):
        allow("echo")
        out = await svc.run(db, PROJECT, "echo hello")
        assert out["ran"] and out["exit_code"] == 0
        assert out["stdout"].strip() == "hello"
        assert out["run_id"]           # traced like everything else

    @pytest.mark.asyncio
    async def test_a_non_zero_exit_is_reported_not_raised(self, db, allow):
        allow("python3")
        out = await svc.run(db, PROJECT, "python3 -c 'import sys; sys.exit(3)'")
        assert out["ran"] and out["exit_code"] == 3

    @pytest.mark.asyncio
    async def test_stderr_is_captured_separately(self, db, allow):
        allow("python3")
        out = await svc.run(db, PROJECT, "python3 -c 'import sys; sys.stderr.write(\"bad\")'")
        assert "bad" in out["stderr"]

    @pytest.mark.asyncio
    async def test_a_hanging_command_is_killed(self, db, allow):
        allow("python3")
        out = await svc.run(db, PROJECT, "python3 -c 'import time; time.sleep(30)'",
                            timeout=1)
        assert out["timed_out"] is True and out["exit_code"] == -1

    @pytest.mark.asyncio
    async def test_an_unknown_program_is_a_clear_error(self, db, allow):
        allow("definitely-not-a-real-program")
        with pytest.raises(svc.TerminalError, match="not found"):
            await svc.run(db, PROJECT, "definitely-not-a-real-program")

    @pytest.mark.asyncio
    async def test_a_denied_program_never_reaches_execution(self, db, allow):
        allow("rm")
        with pytest.raises(svc.TerminalError, match="refused"):
            await svc.run(db, PROJECT, "rm -rf /")

    @pytest.mark.asyncio
    async def test_an_unapproved_command_does_not_run(self, db, allow, monkeypatch):
        """The gate is the whole point: no approval, no execution."""
        allow()  # empty allowlist

        async def deny(*a, **k):
            return {"allowed": False, "reason": "denied", "ask_id": "x"}

        monkeypatch.setattr(inbox, "require", deny)
        out = await svc.run(db, PROJECT, "echo should-not-run")
        assert out["ran"] is False and out["approved"] is False

    @pytest.mark.asyncio
    async def test_an_approved_command_does_run(self, db, allow, monkeypatch):
        allow()

        async def approve(*a, **k):
            return {"allowed": True, "reason": "approved", "ask_id": "x"}

        monkeypatch.setattr(inbox, "require", approve)
        out = await svc.run(db, PROJECT, "echo approved-path")
        assert out["ran"] and out["stdout"].strip() == "approved-path"

    @pytest.mark.asyncio
    async def test_a_standing_grant_skips_the_prompt(self, db, allow):
        """A real grant, not a stub — proves the two subsystems compose."""
        allow()
        inbox.grant(db, PROJECT, "shell.execute", "echo")
        out = await svc.run(db, PROJECT, "echo granted")
        assert out["ran"] and out["stdout"].strip() == "granted"


class TestApi:
    def test_meta_reports_the_allowlist_and_workspace(self, client):
        r = client.get("/api/v1/terminal/meta")
        assert r.status_code == 200
        assert "workspace" in r.json() and "suggested" in r.json()

    def test_check_classifies_without_running(self, client):
        r = client.post("/api/v1/terminal/check", json={"command": "rm -rf /"})
        assert r.status_code == 200 and r.json()["decision"] == "denied"

    def test_check_rejects_shell_syntax(self, client):
        r = client.post("/api/v1/terminal/check", json={"command": "ls && whoami"})
        assert r.status_code == 400

    def test_check_reflects_a_standing_grant(self, client, db):
        """Saying "will ask" when a grant exists misrepresents what happens."""
        before = client.post("/api/v1/terminal/check",
                             json={"command": "sort x.txt", "project_id": PROJECT}).json()
        assert before["decision"] == "ask"

        inbox.grant(db, PROJECT, "shell.execute", "sort")
        after = client.post("/api/v1/terminal/check",
                            json={"command": "sort x.txt", "project_id": PROJECT}).json()
        assert after["decision"] == "allowed"
        assert "standing permission" in after["reason"]

    def test_running_a_denied_command_is_a_400(self, client):
        r = client.post("/api/v1/terminal/run",
                        json={"project_id": PROJECT, "command": "sudo rm -rf /"})
        assert r.status_code == 400 and "refused" in r.json()["detail"]
