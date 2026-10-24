"""
Shared test configuration.

The API is gated behind a per-launch token (`src/security/tokens.py`). Every
suite other than `test_auth.py` is testing something else, so the gate is
disabled by default here rather than threading an Authorization header through
several hundred assertions.

`test_auth.py` turns it back on for its own tests via the `auth_enabled`
fixture below — the middleware reads the environment per request, so this
switches cleanly at runtime rather than at import time.
"""

import os

import pytest

# Off by default for every suite. test_auth.py opts back in.
os.environ.setdefault("DOBBY_DISABLE_AUTH", "1")
# Never let a test tick the real scheduler.
os.environ.setdefault("DOBBY_DISABLE_SCHEDULER", "1")


@pytest.fixture
def auth_enabled():
    """Enforce the token gate for the duration of one test."""
    previous = os.environ.get("DOBBY_DISABLE_AUTH")
    os.environ.pop("DOBBY_DISABLE_AUTH", None)
    try:
        yield
    finally:
        if previous is not None:
            os.environ["DOBBY_DISABLE_AUTH"] = previous
