"""`hs signup` says hs.yaml is tracked — and never touches .gitignore.

Two ways to get this wrong, both worse than saying nothing:

  · Claim a secret has leaked. The key `hs signup` writes is a TEST key: it reaches the free
    sample datasets, consumes no quota and can read nobody's data, so committing it is harmless
    BY DESIGN. A false alarm here is how a real one later gets ignored.
  · Edit the user's .gitignore. Writing to a file the caller did not ask us to touch is not ours
    to do, and a repo may have policy about that file we cannot see.

So: say the true thing — this file is also where a LIVE key goes — exactly once, at the only
moment the user is looking at it, and only when git would really track it.
"""
import json
import subprocess
from pathlib import Path

import pytest

from hunter_seeker import cli

REAL_KEY = "hsk_test_" + "ab12" * 12
MINTED = {"api_key": REAL_KEY, "agent_id": "ag_1", "mode": "test", "claim_url": "https://x/claim"}


def _fake_register(monkeypatch):
    class R:
        def read(self): return json.dumps(MINTED).encode()
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: R())


def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def _repo(tmp_path):
    """A real git repository. `git check-ignore` is what we are testing against, so faking it
    would only prove that the fake agrees with itself."""
    if _git("--version", cwd=tmp_path).returncode != 0:
        pytest.skip("git is not available")
    _git("init", "-q", cwd=tmp_path)
    return tmp_path


def test_warns_when_hs_yaml_would_be_tracked(tmp_path, monkeypatch, capsys):
    _repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    _fake_register(monkeypatch)

    assert cli._signup("hs-cli", force=False) == 0
    err = capsys.readouterr().err
    assert "not ignored" in err
    assert ".gitignore" in err, "it names the fix"
    assert "TEST key" in err and "harmless" in err, "it does not claim a leak that has not happened"
    assert "live key" in err, "it says what is actually at stake, later"


def test_says_nothing_when_hs_yaml_is_already_ignored(tmp_path, monkeypatch, capsys):
    _repo(tmp_path)
    (tmp_path / ".gitignore").write_text("hs.yaml\n")
    monkeypatch.chdir(tmp_path)
    _fake_register(monkeypatch)

    assert cli._signup("hs-cli", force=False) == 0
    assert "gitignore" not in capsys.readouterr().err.lower(), "nothing to warn about"


def test_says_nothing_outside_a_git_repository(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)          # no `git init`
    _fake_register(monkeypatch)

    assert cli._signup("hs-cli", force=False) == 0
    assert "gitignore" not in capsys.readouterr().err.lower()


def test_NEVER_writes_to_the_users_gitignore(tmp_path, monkeypatch, capsys):
    """The warning is a sentence, not an edit. This is the whole point of the design."""
    _repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    _fake_register(monkeypatch)

    assert cli._signup("hs-cli", force=False) == 0
    assert not (tmp_path / ".gitignore").exists(), "we do not create it"


def test_an_existing_gitignore_is_left_byte_for_byte_alone(tmp_path, monkeypatch, capsys):
    _repo(tmp_path)
    gi = tmp_path / ".gitignore"
    gi.write_text("node_modules/\n*.log\n")
    before = gi.read_bytes()
    monkeypatch.chdir(tmp_path)
    _fake_register(monkeypatch)

    assert cli._signup("hs-cli", force=False) == 0
    assert gi.read_bytes() == before, "not one byte of the user's file may move"


def test_a_missing_git_binary_is_silent_not_a_crash(tmp_path, monkeypatch, capsys):
    """`hs signup` must not fail because git is absent — the key matters, the note does not."""
    monkeypatch.chdir(tmp_path)
    _fake_register(monkeypatch)

    def no_git(*a, **k):
        raise FileNotFoundError("git")
    monkeypatch.setattr(subprocess, "run", no_git)

    assert cli._signup("hs-cli", force=False) == 0
    assert cli._read_spec()["api_key"] == REAL_KEY, "the key still landed"


def test_the_note_never_precedes_the_key(tmp_path, monkeypatch, capsys):
    """Ordering is a safety property: the credential is shown once, so nothing may be printed
    before it that could fail or distract."""
    _repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    _fake_register(monkeypatch)

    cli._signup("hs-cli", force=False)
    err = capsys.readouterr().err
    assert err.index(REAL_KEY) < err.index("not ignored"), "the key is printed first"
