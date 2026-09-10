"""Credentials and hs.yaml — the two ways this CLI used to lose a key.

Both bugs below were found by running the code, not by reading it.

1. `hs.yaml` was parsed by three separate ad-hoc comprehensions, none of which tolerated a
   comment line or an unquoted YAML scalar. One of those copies ran AFTER `hs signup` had
   already called the registration endpoint — so a `#` comment in hs.yaml meant the server
   minted a key, the CLI raised IndexError, and the key (shown exactly once) was gone. The
   tenant it belonged to stays alive and unreachable forever.

2. A credential that is present but fake — the placeholder out of the README — was sent to
   the server, which answered 401. An agent reads that as "my credentials were rejected" and
   retries. Nothing anywhere said "that is the example, not a key."

The key shape pinned here is not invented: `generateKey` in the product repo
(db/partner-keys.ts, KEY_BYTES = 24) emits a `hsk_live_`/`hsk_test_` prefix plus 48 hex
characters, 57 in total.
"""
import json
from pathlib import Path

import pytest

from hunter_seeker import cli

REAL_KEY = "hsk_test_" + "ab12" * 12          # 57 chars, hex body — the real shape
MINTED = {"api_key": REAL_KEY, "agent_id": "ag_1", "mode": "test", "claim_url": "https://x/claim"}


def _fake_register(monkeypatch, payload=MINTED):
    """Stand in for the one unauthenticated call. The server has minted a real key by the time
    this returns — which is exactly why everything after it must not be allowed to lose it."""
    class R:
        def read(self): return json.dumps(payload).encode()
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: R())


# --- hs.yaml is hand-edited, so it must survive being hand-edited ----------------------------

@pytest.mark.parametrize("text, expected", [
    ('csv: "leads.csv"\nk: 20\n',            {"csv": "leads.csv", "k": 20}),
    ('# my project\ncsv: "leads.csv"\n',      {"csv": "leads.csv"}),
    ('subject_kind: org\n',                   {"subject_kind": "org"}),
    ('csv: "leads.csv"\n   \n',               {"csv": "leads.csv"}),
    ('',                                      {}),
])
def test_read_spec_tolerates_what_a_human_writes(tmp_path, monkeypatch, text, expected):
    monkeypatch.chdir(tmp_path)
    Path("hs.yaml").write_text(text)
    assert cli._read_spec() == expected


@pytest.mark.parametrize("line, expected", [
    ('dataset: "C:/data/leads.csv"', "C:/data/leads.csv"),   # a Windows path is mostly colons
    ('dataset: C:/data/leads.csv', "C:/data/leads.csv"),     # ...and often unquoted by hand
    ('dataset: "sample:saas_churn"', "sample:saas_churn"),   # so is a sample id
])
def test_read_spec_splits_on_the_first_colon_only(tmp_path, monkeypatch, line, expected):
    """Every value in this file is liable to contain a colon on this platform."""
    monkeypatch.chdir(tmp_path)
    Path("hs.yaml").write_text(line + "\n")
    assert cli._read_spec()["dataset"] == expected


def test_write_spec_round_trips_a_value_holding_colons(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cli._write_spec({"dataset": "C:/data/leads.csv", "api_key": REAL_KEY})
    assert cli._read_spec() == {"dataset": "C:/data/leads.csv", "api_key": REAL_KEY}


def test_read_spec_on_a_missing_file_is_empty_not_an_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert cli._read_spec() == {}


def test_write_spec_keeps_comments_and_drops_keys_it_was_not_given(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("hs.yaml").write_text('# keep me\ndataset: "old.csv"\nmodel_ref: "mr1_old"\n')
    cli._write_spec({"dataset": "new.csv"})
    out = Path("hs.yaml").read_text()
    assert "# keep me" in out, "a comment is the user's, not ours to delete"
    assert cli._read_spec() == {"dataset": "new.csv"}, "model_ref was not in the spec, so it goes"


def test_write_spec_is_atomic_and_leaves_no_temp_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cli._write_spec({"api_key": REAL_KEY})
    assert cli._read_spec()["api_key"] == REAL_KEY
    assert list(tmp_path.glob("*.tmp")) == [], "the temp file is renamed over, never left behind"


# --- the minted key must reach the caller no matter what happens next ------------------------

def test_signup_does_not_lose_the_key_when_hs_yaml_holds_a_comment(tmp_path, monkeypatch, capsys):
    """THE BUG: this raised IndexError after the key was minted, and wrote nothing."""
    monkeypatch.chdir(tmp_path)
    Path("hs.yaml").write_text('# my churn project\ndataset: "leads.csv"\n')
    _fake_register(monkeypatch)

    assert cli._signup("hs-cli", force=False) == 0
    assert cli._read_spec()["api_key"] == REAL_KEY, "the minted key is on disk"
    assert "# my churn project" in Path("hs.yaml").read_text()
    assert 'dataset: "leads.csv"' in Path("hs.yaml").read_text(), "the rest of the spec survived"


def test_signup_survives_an_unquoted_scalar_in_hs_yaml(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    Path("hs.yaml").write_text("subject_kind: org\n")
    _fake_register(monkeypatch)
    assert cli._signup("hs-cli", force=False) == 0
    assert cli._read_spec()["api_key"] == REAL_KEY


def test_signup_prints_the_key_before_it_persists_it(tmp_path, monkeypatch, capsys):
    """The server shows the key once. If the write fails the key must still be on the terminal,
    with a remedy saying so — otherwise the tenant is minted and permanently unreachable."""
    monkeypatch.chdir(tmp_path)
    _fake_register(monkeypatch)

    def boom(*a, **k):
        raise OSError("read-only file system")
    monkeypatch.setattr(cli, "_write_spec", boom)

    rc = cli._signup("hs-cli", force=False)
    err = capsys.readouterr().err
    assert rc == 1, "a key that could not be persisted is not a success"
    assert REAL_KEY in err, "the key reached the caller anyway"
    assert "not recoverable" in err, "and the caller is told to save it now"


def test_signup_refuses_to_strand_an_existing_key(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    Path("hs.yaml").write_text(f'api_key: "{REAL_KEY}"\n')
    _fake_register(monkeypatch, {"api_key": "hsk_test_" + "ff99" * 12, "agent_id": "ag_2"})
    assert cli._signup("hs-cli", force=False) == 1
    assert cli._read_spec()["api_key"] == REAL_KEY, "the first key is untouched"
    assert "key_exists" in capsys.readouterr().err


def test_signup_reports_a_response_with_no_key_instead_of_raising(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _fake_register(monkeypatch, {"agent_id": "ag_3"})       # no api_key
    with pytest.raises(SystemExit):
        cli._signup("hs-cli", force=False)
    assert "no_key_in_response" in capsys.readouterr().err


# --- a fake key is caught here, not by a 401 --------------------------------------------------

@pytest.mark.parametrize("placeholder", [
    "hsk_live_...",             # from a shell example
    "hsk_live_YOURACTUALKEY",
    "hsk_live_abc123...",
    "hsk_test_…",          # README.md carried a literal U+2026
    "hsk_test_...",
    "hsk_<your key here>",
])
def test_a_documentation_placeholder_is_named_as_one(placeholder, monkeypatch):
    monkeypatch.setenv("HS_API_KEY", placeholder)
    with pytest.raises(SystemExit):
        cli._client()
    problem = cli._key_problem(placeholder, "HS_API_KEY")
    assert problem and "placeholder" in problem, f"{placeholder!r} must be named as the example"


def test_a_real_key_passes(monkeypatch):
    assert cli._key_problem(REAL_KEY, "HS_API_KEY") is None


@pytest.mark.parametrize("wrapped", [
    REAL_KEY + "\n",     # a CI secret pasted with a trailing newline
    REAL_KEY + "\r",     # ...on Windows
    REAL_KEY + " ",
    " " + REAL_KEY,
])
def test_stray_whitespace_is_tolerated_not_a_401(wrapped, monkeypatch):
    """These reached the server verbatim and came back 401 — the least debuggable failure here."""
    monkeypatch.setenv("HS_API_KEY", wrapped)
    monkeypatch.setattr(cli, "Client", lambda **kw: kw)
    assert cli._client()["api_key"] == REAL_KEY


def test_a_key_of_the_right_length_but_not_hex_is_told_the_truth():
    """The body is hex. Saying "wrong length" about a 57-character key would be a false answer."""
    problem = cli._key_problem("hsk_test_" + "z" * 48, "HS_API_KEY")
    assert problem and "hex" in problem and "57 characters" not in problem


def test_something_that_is_not_a_key_at_all_says_so():
    problem = cli._key_problem("sk-proj-1234", "HS_API_KEY")
    assert problem and "hsk_live_" in problem


def test_no_credential_is_a_parseable_error_with_a_remedy(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("HS_API_KEY", raising=False)
    with pytest.raises(SystemExit):
        cli._client()
    err = json.loads(capsys.readouterr().err)
    assert err["error"] == "no_credential"
    assert "hs signup" in err["remedy"], "an agent needs the next command, not just the diagnosis"


def test_a_malformed_key_is_never_echoed_in_full(monkeypatch):
    """The error text goes into logs. A live key must not follow it there."""
    live = "hsk_live_" + "9" * 40          # wrong length, but plausibly a real secret
    problem = cli._key_problem(live, "HS_API_KEY")
    assert problem and live not in problem


# --- the rest of the CLI reads the same file ---------------------------------------------------

def test_rank_no_longer_crashes_on_a_commented_hs_yaml(tmp_path, monkeypatch, capsys):
    """`hs rank` and `hs score` shared the fragile parse, so a comment broke them too."""
    monkeypatch.chdir(tmp_path)
    Path("d.csv").write_text("a,b\n1,0\n")
    Path("hs.yaml").write_text(
        '# the churn pull, refreshed every Monday\n'
        'dataset: "d.csv"\nentity_column: "a"\noutcome_column: "b"\nsubject_kind: "org"\n'
    )

    class FakeClient:
        def rank_topk(self, **kw): return {"ranking_ref": "r1", "model_ref": "mr1_" + "0" * 32,
                                           "top_decile_lift": 2.0}
        def verify(self, *a, **k): return "valid"
    monkeypatch.setattr(cli, "_client", lambda: FakeClient())

    assert cli.main(["rank"]) == 0
    assert cli._read_spec()["model_ref"] == "mr1_" + "0" * 32
    assert "# the churn pull" in Path("hs.yaml").read_text()


def test_init_keeps_the_key_signup_just_wrote(tmp_path, monkeypatch, capsys):
    """`hs signup` then `hs init` used to overwrite hs.yaml wholesale and delete the key."""
    monkeypatch.chdir(tmp_path)
    Path("hs.yaml").write_text(f'api_key: "{REAL_KEY}"\nagent_id: "ag_1"\nmodel_ref: "mr1_stale"\n')
    Path("d.csv").write_text("id,won\n1,1\n2,0\n")

    assert cli.main(["init", "d.csv"]) == 0
    spec = cli._read_spec()
    assert spec["api_key"] == REAL_KEY, "the credential survives a re-init"
    assert "model_ref" not in spec, "but the old model_ref does not — it was fitted on another dataset"
def test_a_minted_key_this_client_would_refuse_is_flagged_but_still_saved(tmp_path, monkeypatch, capsys):
    """The client requires the full 57-character shape; the server accepts any hsk_ prefix.

    Safe today - one code path mints keys and the format has never moved - but if it ever does,
    signup would write a key that every later command refuses LOCALLY, and the tool would sit there
    contradicting itself with no explanation. It says so, and still saves the key: one that cannot
    be used is recoverable, one that was never written down is not.
    """
    monkeypatch.chdir(tmp_path)
    odd = 'hsk_test_' + 'ZZ' * 24          # right prefix, wrong body
    _fake_register(monkeypatch, {'api_key': odd, 'agent_id': 'ag_9', 'mode': 'test'})

    assert cli._signup('hs-cli', force=False) == 0
    err = capsys.readouterr().err
    assert odd in err, 'the key still reached the caller'
    assert cli._read_spec()['api_key'] == odd, 'and was still saved - never lose a minted key'
    assert 'out of date' in err and 'refuse it locally' in err, 'and the dead end is explained'
