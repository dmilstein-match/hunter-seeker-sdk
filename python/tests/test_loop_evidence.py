"""Routing evidence from your own ledger, and the decision columns it needs.

WHY THIS EXISTS AT ALL. `hs_action_evidence` splits on lever ATTESTATION: acted means a
compliant `hs_attest_action`, and everything else — refused rows, escalated rows, your control
arm, entities nobody looked at — lands in the comparison arm. A loop that ROUTES on the band
pulls no lever, so it can never reach that acted cell, and the number it does return answers a
different question than the one asked. `Ledger.evidence` is the comparison the control arm was
held out for: same band, acted vs held back.

THE BUG THIS PINS. The treated cell used to require `hs_action == "intercept"`. On a DESIRABLE
outcome a certified row is one to let through, so `decide()` returns "proceed" — meaning the
treated cell stayed permanently empty for every desirable-outcome loop, and `live` stayed None
for ever with nothing saying why.
"""
from __future__ import annotations

import json

import pytest
from conftest import ACT_L3, ADVERSE, DESIRABLE, MODEL_REF, REFUSE

from hunter_seeker.loop import Ledger, actionable, decide


def _row(i: int, outcome=None):
    return {"run_id": f"r{i}", "ts": f"2026-01-01T00:{i // 60:02d}:{i % 60:02d}Z",
            "agent": "a1", "task": "t1", "tool": "browser", "failed": outcome}


def _ledger_with(n_treated, n_control, *, verdict=ADVERSE, treated_outcome=0, control_outcome=1):
    """n runs through the real `decide()` path, half held out by the control arm."""
    led = Ledger()
    for i in range(n_treated):
        d = decide(ACT_L3, verdict, run_id=f"r{i}", control=False)
        led.append_decision(_row(i), d)
        led.observe(f"r{i}", treated_outcome)
    for j in range(n_control):
        i = 1000 + j
        d = decide(ACT_L3, verdict, run_id=f"r{i}", control=True)
        led.append_decision(_row(i), d)
        led.observe(f"r{i}", control_outcome)
    return led


def test_an_adverse_loop_compares_intercepted_runs_against_the_held_out_ones():
    ev = _ledger_with(30, 30).evidence()
    assert ev["treated"]["n"] == 30 and ev["control"]["n"] == 30
    assert ev["live"] is not None
    assert ev["live"]["difference_control_minus_treated"] == pytest.approx(1.0)
    assert ev["live"]["small_n"] is True          # 30 per cell is above the floor, below 100


def test_a_desirable_loop_fills_the_treated_cell_too():
    """The regression: `decide()` returns "proceed" here, not "intercept"."""
    ev = _ledger_with(30, 30, verdict=DESIRABLE).evidence()
    assert ev["treated"]["n"] == 30, "the treated cell is empty on a desirable outcome"
    assert ev["live"] is not None


def test_below_the_floor_there_is_no_number():
    ev = _ledger_with(29, 30).evidence()
    assert ev["live"] is None
    assert ev["treated"]["n"] == 29, "the counts are still reported, so you can see how far off you are"


def test_a_run_the_loop_did_not_act_on_is_in_neither_cell():
    """`default` is your own policy, not the engine's call: refused and escalated rows are
    evidence about nothing here."""
    led = Ledger()
    for i in range(40):
        led.append_decision(_row(i), decide(REFUSE, ADVERSE, run_id=f"r{i}"))
        led.observe(f"r{i}", 1)
    ev = led.evidence()
    assert ev["treated"]["n"] == 0 and ev["control"]["n"] == 0


def test_evidence_is_scoped_to_one_model_ref():
    led = _ledger_with(30, 30)
    assert led.evidence(model_ref="mr1_" + "9" * 32)["treated"]["n"] == 0
    # the fixture verdict carries no model_ref, so an unscoped call still sees the rows
    assert led.evidence()["treated"]["n"] == 30


def test_a_run_with_no_outcome_yet_counts_in_neither_cell():
    led = _ledger_with(30, 30)
    led.append_decision(_row(2000), decide(ACT_L3, ADVERSE, run_id="r2000"))
    assert led.evidence()["treated"]["n"] == 30


def test_record_decision_refuses_a_run_that_is_not_there():
    with pytest.raises(KeyError):
        Ledger().record_decision("nobody", decide(ACT_L3, ADVERSE, run_id="nobody"))


def test_fit_rows_strip_the_loop_s_own_columns_and_unlabelled_runs():
    """A model fitted on its predecessor's bands is learning its own echo."""
    led = _ledger_with(2, 1)
    led.append_decision(_row(3000), decide(ACT_L3, ADVERSE, run_id="r3000"))   # no outcome yet
    rows = led.fit_rows()
    assert len(rows) == 3
    assert not any(k.startswith("hs_") for r in rows for k in r)


def test_save_and_load_round_trip(tmp_path):
    led = _ledger_with(3, 2)
    path = tmp_path / "ledger.jsonl"
    led.save(str(path))
    assert len(path.read_text(encoding="utf-8").strip().splitlines()) == 5
    back = Ledger.load(str(path))
    assert [r["run_id"] for r in back.rows] == [r["run_id"] for r in led.rows]
    assert back.evidence()["treated"]["n"] == led.evidence()["treated"]["n"]
    # the decision columns survive the trip, or the comparison cannot be rebuilt
    assert json.loads(path.read_text(encoding="utf-8").splitlines()[0])["hs_band"] == "act"


@pytest.mark.parametrize("changes,expect", [
    ([{"feature": "agent_prior_n", "direction": "decrease"}], False),
    ([{"feature": "task_prior_outcome_rate", "direction": "decrease"}], False),
    ([{"feature": "agent_prior_n", "direction": "decrease"},
      {"feature": "retries", "direction": "decrease"}], True),
    ([{"feature": "input_tokens", "direction": "decrease"}], True),
    ([], False),
], ids=["counter", "rate", "mixed", "real-knob", "empty"])
def test_a_lever_on_history_is_not_a_lever(changes, expect):
    """Measured on the sample corpus: the top-ranked run's lever was "decrease agent_prior_n" —
    a count of how many runs that agent has already done."""
    assert actionable({"entity_id": "r1", "changes": changes}) is expect
