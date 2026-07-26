"""
Sandboxed, approval-gated command execution (OW rows 14, 53, and Next Task 3).

Dobby has never executed a shell command. Adding that is the single largest
increase in blast radius in the app's history, so the design is deliberately
paranoid:

* **No shell.** Commands are parsed with `shlex` and executed as an argv list.
  There is no `shell=True` anywhere here, so `;`, `&&`, backticks and `$(...)`
  are inert text rather than instructions.
* **Empty allowlist by default** (OW 53). Nothing runs unattended out of the
  box. The allowlist holds *program names*, never whole command lines.
* **Everything else asks.** A command not on the allowlist goes through
  `inbox_service.require(shell.execute, ...)` and does not run without a human
  yes. Denial and timeout both mean no.
* **Hard denylist that approval cannot override.** Some things should not be
  one tired click away. `rm -rf /`, disk writes, fork bombs and shutdown are
  refused outright — the user can still run them in a real terminal, which is
  the point: Dobby should not be the easiest path to them.
* **Scoped working directory.** Execution is confined to the project directory;
  a path that escapes it is rejected before the process starts.
* **Bounded.** Wall-clock timeout, output cap, and the process group is killed
  on timeout so children do not survive their parent.

Every run is traced, so a command executed by an automation at 3am is
inspectable in Logs & Traces beside everything else.
"""

from __future__ import annotations

import asyncio
import os
import re
import shlex
import signal
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from src.db.schema import DatabaseManager
from src.observability.tracer import Tracer

logger = structlog.get_logger()

DEFAULT_TIMEOUT = 60
MAX_TIMEOUT = 600
MAX_OUTPUT = 100_000        # bytes per stream before truncation

# Programs safe enough to offer as a starting allowlist. Not enabled by
# default — the user opts in per program. Read-only or clearly bounded.
SUGGESTED_ALLOWLIST = [
    "ls", "pwd", "cat", "head", "tail", "wc", "grep", "find", "file", "stat",
    "git", "python3", "node", "npm", "pytest", "tree", "du", "df", "echo",
    "which", "env", "date",
]

# Refused even with approval. These are not "risky", they are destructive in a
# way no confirmation dialog makes acceptable inside a document tool.
_DENY_PATTERNS = [
    (re.compile(r"^rm$", re.I), ("-rf", "-fr", "-r"), "recursive delete"),
    (re.compile(r"^(mkfs|fdisk|diskutil|dd)$", re.I), None, "disk operation"),
    (re.compile(r"^(shutdown|reboot|halt|poweroff)$", re.I), None, "power control"),
    (re.compile(r"^(sudo|su|doas)$", re.I), None, "privilege escalation"),
    (re.compile(r"^(chown|chmod)$", re.I), ("-R", "--recursive"), "recursive permission change"),
    (re.compile(r"^:$", re.I), None, "fork bomb"),
]

# Shell operators, checked as whole *tokens* after parsing rather than as
# substrings of the raw line. Without a shell these would be passed through as
# inert argv text, which is more confusing than an error — but only when the
# user meant them as operators. `python3 -c 'import sys; sys.exit(1)'` keeps its
# semicolon inside a quoted argument, where it is ordinary text, and must run.
_SHELL_OPERATORS = frozenset({";", "&&", "||", "|", "&", ">", ">>", "<", "<<"})


class TerminalError(Exception):
    """The command was refused before it ran. Message is user-facing."""


def _settings():
    from src.settings import get_settings

    return get_settings()


def allowlist() -> List[str]:
    raw = getattr(_settings(), "shell_allowlist", "") or ""
    return [p.strip() for p in raw.split(",") if p.strip()]


def project_root(project_id: str) -> Path:
    """Where commands for a project may run.

    Configurable, defaulting to a per-project directory under ~/.dobby. It is
    created on demand so the first command does not fail on a missing folder.
    """
    base = getattr(_settings(), "workspace_root", "") or str(Path.home() / ".dobby" / "workspaces")
    root = (Path(base).expanduser() / project_id).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _resolve_cwd(project_id: str, cwd: Optional[str]) -> Path:
    root = project_root(project_id)
    if not cwd:
        return root
    candidate = (root / cwd).resolve() if not os.path.isabs(cwd) else Path(cwd).resolve()
    # `resolve()` collapses .. before this check, so traversal cannot slip past.
    if candidate != root and root not in candidate.parents:
        raise TerminalError(
            f"Working directory must stay inside the project workspace ({root})."
        )
    if not candidate.is_dir():
        raise TerminalError(f"No such directory: {candidate}")
    return candidate


def parse(command: str) -> List[str]:
    """Split a command line into argv, refusing anything shell-dependent."""
    text = (command or "").strip()
    if not text:
        raise TerminalError("Enter a command.")
    # `punctuation_chars=True` makes shlex split shell operators into tokens of
    # their own *only when unquoted* — which is exactly the distinction that
    # matters. Plain `shlex.split` glues `;` onto the preceding word, hiding it.
    try:
        lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError as e:
        raise TerminalError(f"Could not parse that command: {e}")
    if not tokens:
        raise TerminalError("Enter a command.")

    if any(token in _SHELL_OPERATORS for token in tokens):
        raise TerminalError(
            "Pipes, redirects and command chaining are not supported — commands "
            "run without a shell. Run one command at a time."
        )
    # Command substitution is different: it never becomes its own token, so it
    # has to be caught in the raw text. Unlike the operators above it is a
    # genuine injection vector in any downstream tool that *does* use a shell.
    if "$(" in text or "`" in text:
        raise TerminalError(
            "Command substitution is not supported — commands run without a shell."
        )
    return tokens


def classify(argv: List[str]) -> Dict[str, Any]:
    """Decide how a command may proceed: denied, allowed, or needs approval."""
    program = Path(argv[0]).name

    for pattern, flags, why in _DENY_PATTERNS:
        if pattern.match(program):
            if flags is None or any(f in argv[1:] for f in flags):
                return {"decision": "denied", "program": program, "reason": why}

    if program in allowlist():
        return {"decision": "allowed", "program": program, "reason": "on the allowlist"}
    return {"decision": "ask", "program": program, "reason": "not on the allowlist"}


async def run(db: DatabaseManager, project_id: str, command: str,
              cwd: Optional[str] = None, timeout: int = DEFAULT_TIMEOUT,
              source: str = "manual") -> Dict[str, Any]:
    """Execute a command, gating it behind approval unless allowlisted."""
    argv = parse(command)
    verdict = classify(argv)
    if verdict["decision"] == "denied":
        raise TerminalError(
            f"`{verdict['program']}` is refused as a {verdict['reason']}. "
            "Dobby will not run this even with approval — use a real terminal "
            "if you genuinely need it."
        )

    working = _resolve_cwd(project_id, cwd)
    timeout = max(1, min(int(timeout or DEFAULT_TIMEOUT), MAX_TIMEOUT))

    if verdict["decision"] == "ask":
        from src.services import inbox_service as inbox

        approval = await inbox.require(
            db, project_id, "shell.execute", verdict["program"],
            title=f"Run `{command[:80]}`?",
            detail=(f"Program: {verdict['program']}\nArguments: "
                    f"{' '.join(argv[1:]) or '(none)'}\nDirectory: {working}"),
            risk="high", source=source, timeout=180,
        )
        if not approval["allowed"]:
            return {
                "ran": False, "approved": False,
                "reason": approval["reason"], "ask_id": approval.get("ask_id"),
                "command": command,
            }

    tracer = Tracer(db, kind="shell", label=command[:80], project_id=project_id,
                    total_steps=1)
    tracer.event("shell.start", command[:200], program=verdict["program"],
                 cwd=str(working))
    started = datetime.utcnow()

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=str(working),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            # Own process group, so a timeout kills children too rather than
            # orphaning them.
            start_new_session=True,
        )
    except FileNotFoundError:
        tracer.finish("failed", error="command not found")
        raise TerminalError(f"`{verdict['program']}` was not found on this system.")
    except PermissionError:
        tracer.finish("failed", error="permission denied")
        raise TerminalError(f"Not permitted to run `{verdict['program']}`.")

    timed_out = False
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        timed_out = True
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
        stdout, stderr = b"", b""

    duration = int((datetime.utcnow() - started).total_seconds() * 1000)

    def decode(raw: bytes) -> tuple[str, bool]:
        truncated = len(raw) > MAX_OUTPUT
        return raw[:MAX_OUTPUT].decode("utf-8", errors="replace"), truncated

    out, out_trunc = decode(stdout or b"")
    err, err_trunc = decode(stderr or b"")
    code = -1 if timed_out else (proc.returncode if proc.returncode is not None else -1)

    status = "failed" if (timed_out or code != 0) else "ok"
    tracer.event("shell.done", f"exit {code}", advance=True, exit_code=code,
                 duration_ms=duration)
    tracer.finish(status, error=("timed out" if timed_out else None))

    logger.info("shell_executed", program=verdict["program"], exit_code=code,
                ms=duration, timed_out=timed_out)
    return {
        "ran": True, "approved": True, "command": command,
        "argv": argv, "cwd": str(working),
        "exit_code": code, "stdout": out, "stderr": err,
        "truncated": out_trunc or err_trunc,
        "timed_out": timed_out, "duration_ms": duration,
        "run_id": tracer.run_id,
    }
