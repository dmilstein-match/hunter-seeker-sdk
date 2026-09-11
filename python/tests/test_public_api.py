"""The names and the version a user sees, checked from the checkout on every push.

Every other test imports from `hunter_seeker.loop`, so deleting the top-level re-export of the loop
passed the whole suite while the README, the package docstring and the governed-loop guide all tell
users to write `from hunter_seeker import Ledger, gate, era_lock`. And the version is read three
ways — pyproject, `__version__`, the User-Agent — that once drifted apart for four releases;
registry-installs-clean only sees what PyPI serves, so this catches the drift at push time.
"""
from __future__ import annotations

import re
import urllib.request
from pathlib import Path

import pytest

import hunter_seeker
from hunter_seeker import Decision, Ledger, control_arm, decide, era_lock, gate  # the documented form

ROOT = Path(__file__).resolve().parents[2]


def test_every_name_in___all___resolves():
    missing = [n for n in hunter_seeker.__all__ if not hasattr(hunter_seeker, n)]
    assert missing == []


def test_loop_reexports_are_the_loop_objects():
    from hunter_seeker import loop
    for obj in (Decision, Ledger, control_arm, decide, era_lock, gate):
        assert getattr(loop, obj.__name__) is obj


def test_version_agrees_with_pyproject_and_the_changelog():
    pyproject = (ROOT / "python" / "pyproject.toml").read_text(encoding="utf-8")
    want = re.search(r'^version = "([^"]+)"$', pyproject, re.M).group(1)   # the line CI greps
    assert hunter_seeker.__version__ == want
    assert re.search(rf"^## {re.escape(want)} ", (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), re.M)


def test_the_user_agent_carries_the_version(monkeypatch):
    sent = {}

    class Stop(Exception):
        pass

    def fake_urlopen(req, timeout=None):
        sent["ua"] = req.get_header("User-agent")
        raise Stop

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(Stop):
        hunter_seeker.Client(api_key="hsk_test_x", base_url="http://127.0.0.1:9").describe_capabilities()
    assert sent["ua"] == f"hunter-seeker-python/{hunter_seeker.__version__}"
