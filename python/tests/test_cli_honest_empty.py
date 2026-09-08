"""The refusal path through `hs rank` — the first command a new user runs.

`cli.py` printed the three keys ranking_ref / model_ref / honest_empty. There is no top-level
`honest_empty` field on a rank response: a refusal is {result, reasons, retry, guidance}. So an
honest-empty — the product's headline guarantee — rendered as three nulls with every reason
dropped, and then wrote `model_ref: null` into hs.yaml so the next `hs score` fired at a null.

The payloads below are the REAL shapes, captured from production (engine 0.3.6) rather than
invented: `sample:agent_traces` ranked raw for the refusal, `sample:saas_churn` for the finding.
"""
import json
from pathlib import Path
import pytest
from hunter_seeker.cli import main

REFUSAL = {
    "result": "none",
    "reasons": ["Insufficient features: found 2 viable arms, need 4."],
    "gate_verdicts": ["not cleared: the signal did not clear the published lift >= 1.5 bar"],
    "retry": "unproductive",
    "guidance": "Retrying the identical call will return the identical result.",
    "provenance": {"engine_version": "0.3.6"},
}
FINDING = {"ranking_ref": "rank_abc", "model_ref": "mr1_" + "0" * 32, "top_decile_lift": 4.444444}
# Cleared the bar, but below the 500-row holdout floor the engine caches no scorecard.
CLEARED_NO_MODEL = {"ranking_ref": "rank_def", "model_ref": None, "top_decile_lift": None}


def _spec(tmp_path, monkeypatch, out):
    monkeypatch.chdir(tmp_path)
    Path("d.csv").write_text("a,b\n1,0\n")
    Path("hs.yaml").write_text(
        'dataset: "d.csv"\nentity_column: "a"\noutcome_column: "b"\nsubject_kind: "org"\n'
        'model_ref: "mr1_' + "e" * 32 + '"\n'
    )
    class FakeClient:
        def rank_topk(self, **kw): return out
        def verify(self, *a, **k): return "valid"
    monkeypatch.setattr("hunter_seeker.cli._client", lambda: FakeClient())


def test_a_refusal_prints_its_reasons_not_three_nulls(tmp_path, monkeypatch, capsys):
    _spec(tmp_path, monkeypatch, REFUSAL)
    rc = main(["rank"])
    printed = json.loads(capsys.readouterr().out)
    assert printed["result"] == "none"
    assert printed["reasons"] == REFUSAL["reasons"], "the reasons are the whole answer"
    assert printed["retry"] == "unproductive"
    assert "honest_empty" not in printed, "a field the response never carries must not be printed"
    assert rc != 0, "a refusal is a real answer, but it is not a successful rank"


def test_a_refusal_does_not_clobber_a_good_model_ref(tmp_path, monkeypatch, capsys):
    _spec(tmp_path, monkeypatch, REFUSAL)
    main(["rank"]); capsys.readouterr()
    spec = dict(l.split(": ", 1) for l in Path("hs.yaml").read_text().splitlines() if l.strip())
    assert json.loads(spec["model_ref"]) == "mr1_" + "e" * 32, "the previous model_ref survived"


def test_a_cleared_run_with_no_scorecard_says_so_and_persists_nothing(tmp_path, monkeypatch, capsys):
    # `model_ref: null` on a run that CLEARED is not a refusal and has no `reasons` to print.
    # Writing it would be just as fatal to the next `hs score`.
    _spec(tmp_path, monkeypatch, CLEARED_NO_MODEL)
    main(["rank"])
    printed = json.loads(capsys.readouterr().out)
    assert printed["ranking_ref"] == "rank_def"
    assert "note" in printed and "hs score" in printed["note"]
    spec = dict(l.split(": ", 1) for l in Path("hs.yaml").read_text().splitlines() if l.strip())
    assert json.loads(spec["model_ref"]) == "mr1_" + "e" * 32


def test_a_real_finding_still_persists_its_model_ref(tmp_path, monkeypatch, capsys):
    _spec(tmp_path, monkeypatch, FINDING)
    assert main(["rank"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["model_ref"] == FINDING["model_ref"]
    spec = dict(l.split(": ", 1) for l in Path("hs.yaml").read_text().splitlines() if l.strip())
    assert json.loads(spec["model_ref"]) == FINDING["model_ref"]
