"""hunter_seeker.loop — the ledger, the priors, the control arm, the gate, and era-lock.

The priors are pinned to `fixtures/trace_priors_golden.json`, which the ENGINE generated
(`worker/src/readings/trace.py`, engine 0.3.6) over the rows it contains. The fixture was
checked against deliberate wrong implementations; it catches a tie counted as earlier
(11 mismatches), a zero-filled rate (8) and second-resolution timestamps (5). It cannot see two
others, so they have their own tests below: an unlabelled row counting toward `_n`, and a run's
own row seeing its own label.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pytest
from conftest import ACT_L2, ACT_L3, ADVERSE, DESIRABLE, ESCALATE, MODEL_REF, REFUSE, FakeScoringClient

from hunter_seeker import Autonomy, MissingSafeguard
from hunter_seeker.loop import (Decision, Ledger, control_arm, decide, era_lock, gate, parse_ts,
                                prior_feature_names)

GOLDEN = json.loads((Path(__file__).parent / "fixtures" / "trace_priors_golden.json").read_text())
PARSABLE = [r for r in GOLDEN["rows"] if parse_ts(r["ts"]) is not None]   # the ledger refuses the rest


def _same(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return math.isclose(a, b)


def _golden_ledger() -> Ledger:
    ledger = Ledger()
    ledger.extend(PARSABLE)
    return ledger


# ── priors ─────────────────────────────────────────────────────────────────────────────────

def test_priors_match_the_engine_on_every_row_and_feature():
    """Every row, the unparsable one included: the engine excludes it from everyone's windows and
    gives it NULL, which is exactly what leaving it out of the ledger and scoring it produces."""
    ledger = _golden_ledger()
    mismatches = []
    for row, expected in zip(GOLDEN["rows"], GOLDEN["expected"]):
        got = ledger.priors(row)
        for f in prior_feature_names():
            if not _same(got[f], expected[f]):
                mismatches.append((row["run_id"], f, got[f], expected[f]))
    assert not mismatches, mismatches[:10]


def test_the_fixture_exercises_the_cases_that_matter():
    """If the fixture is ever regenerated without these, the golden test goes soft."""
    rows = {r["run_id"]: r for r in GOLDEN["rows"]}
    exp = {e["run_id"]: e for e in GOLDEN["expected"]}
    # a same-instant pair sharing every group: neither is EARLIER than the other
    assert rows["r010"]["ts"] == rows["r011"]["ts"]
    assert all(rows["r010"][g] == rows["r011"][g] for g in ("agent", "task", "tool"))
    assert exp["r010"] == {**exp["r011"], "run_id": "r010"}
    # one microsecond later IS earlier: r031 sees r030
    assert exp["r031"]["tool_prior_n"] == exp["r030"]["tool_prior_n"] + 1
    # an unparsable timestamp gives NULL everywhere
    assert rows["r020"]["ts"] == "not a time"
    assert all(exp["r020"][f] is None for f in prior_feature_names())
    # a missing group value gives NULL for that group only
    null_agent = next(r["run_id"] for r in GOLDEN["rows"] if r["agent"] is None and r["run_id"] != "r020")
    assert exp[null_agent]["agent_prior_n"] is None and exp[null_agent]["task_prior_n"] is not None


def test_the_ledger_refuses_a_timestamp_it_cannot_parse():
    """The engine parses more formats than this does, so a silently-NULL prior here could differ
    from the one the engine computed at fit. Refused at the boundary instead."""
    with pytest.raises(ValueError, match="ISO-8601"):
        Ledger().append({"run_id": "a", "ts": "03/04/2026", "agent": "x", "failed": 0})


def test_unlabelled_rows_do_not_count_toward_anyone_s_priors():
    """The fit sees a fully labelled table; the decision-time equivalent is 'earlier runs whose
    outcome I know'. An in-flight run must not inflate `_n` — the golden cannot see this because
    every row in it is labelled."""
    ledger = Ledger()
    ledger.append({"run_id": "a", "ts": "2026-01-01T00:00:00Z", "agent": "x", "task": "t", "tool": "u", "failed": 1})
    ledger.append({"run_id": "b", "ts": "2026-01-01T00:01:00Z", "agent": "x", "task": "t", "tool": "u", "failed": None})
    p = ledger.priors({"run_id": "c", "ts": "2026-01-01T00:02:00Z", "agent": "x", "task": "t", "tool": "u"})
    assert p["agent_prior_n"] == 1 and p["agent_prior_outcome_rate"] == 1.0
    ledger.observe("b", 0)
    p = ledger.priors({"run_id": "c", "ts": "2026-01-01T00:02:00Z", "agent": "x", "task": "t", "tool": "u"})
    assert p["agent_prior_n"] == 2 and p["agent_prior_outcome_rate"] == 0.5


def test_a_run_never_sees_its_own_label():
    ledger = Ledger()
    ledger.append({"run_id": "a", "ts": "2026-01-01T00:00:00Z", "agent": "x", "task": "t", "tool": "u", "failed": 1})
    # scoring the recorded run again, even with a later timestamp on the request, excludes itself
    p = ledger.priors({"run_id": "a", "ts": "2026-01-01T00:05:00Z", "agent": "x", "task": "t", "tool": "u"})
    assert p["agent_prior_n"] == 0 and p["agent_prior_outcome_rate"] is None


def test_first_run_in_a_group_is_zero_and_null_never_zero_and_zero():
    ledger = Ledger()
    p = ledger.priors({"run_id": "a", "ts": "2026-01-01T00:00:00Z", "agent": "new", "task": "t", "tool": "u"})
    assert p["agent_prior_n"] == 0
    assert p["agent_prior_outcome_rate"] is None       # a rate over nothing is not a measurement


def test_the_ledger_refuses_a_self_reported_outcome():
    with pytest.raises(ValueError, match="observed outcome"):
        Ledger().append({"run_id": "a", "ts": "2026-01-01T00:00:00Z", "failed": "done"})


def test_group_binding_is_explicit():
    with pytest.raises(ValueError, match="unknown group role"):
        Ledger(groups={"model": "model"})
    with pytest.raises(ValueError, match="at least one"):
        Ledger(groups={})
    ledger = Ledger(groups={"task": "task_family"})
    assert set(ledger.priors({"run_id": "a", "ts": "2026-01-01", "task_family": "x"})) == {
        "task_prior_n", "task_prior_outcome_rate"}


# ── timestamps ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value, expect", [
    ("2026-03-04T10:00:00Z", datetime(2026, 3, 4, 10, 0, 0)),
    ("2026-03-04T10:00:00+02:00", datetime(2026, 3, 4, 8, 0, 0)),          # the instant, offset dropped
    ("2026-03-04 10:00:00", datetime(2026, 3, 4, 10, 0, 0)),               # naive passes through
    ("2026-03-04", datetime(2026, 3, 4, 0, 0, 0)),
    ("2026-03-04T10:00:00.123456789Z", datetime(2026, 3, 4, 10, 0, 0, 123456)),  # µs, like the engine
    (1772618400, datetime(2026, 3, 4, 10, 0, 0)),                           # epoch seconds
    ("1772618400000", datetime(2026, 3, 4, 10, 0, 0)),                      # epoch millis, as a string
    (datetime(2026, 3, 4, 10, 0, tzinfo=timezone.utc), datetime(2026, 3, 4, 10, 0, 0)),
    ("not a time", None),
    ("03/04/2026", None),      # US date: refused rather than mirrored; write ISO in your ledger
    (20260304, None),          # compact date is below both epoch bands, as the engine declares
    (None, None),
])
def test_parse_ts(value, expect):
    assert parse_ts(value) == expect


# ── the control arm ────────────────────────────────────────────────────────────────────────

def test_control_arm_is_stable_and_near_the_fraction():
    ids = [f"run_{i:05d}" for i in range(20_000)]
    picked = [control_arm(i, fraction=0.15) for i in ids]
    assert picked == [control_arm(i, fraction=0.15) for i in ids]            # same answer, always
    share = sum(picked) / len(ids)
    assert 0.14 < share < 0.16, share
    assert not any(control_arm(i, fraction=0.0) for i in ids[:100])
    assert all(control_arm(i, fraction=1.0) for i in ids[:100])


def test_salt_draws_a_different_slice_over_the_same_ids():
    ids = [f"run_{i:05d}" for i in range(5_000)]
    a = {i for i in ids if control_arm(i, salt="loop-a")}
    b = {i for i in ids if control_arm(i, salt="loop-b")}
    assert a != b
    # independent draws: the overlap is about `fraction` of either slice, not most of it
    assert 0.05 < len(a & b) / len(a) < 0.30, len(a & b) / len(a)


# ── decide / gate ──────────────────────────────────────────────────────────────────────────

def test_the_band_is_read_with_its_polarity():
    """Fitted on `failed`, a certified row is a run to CATCH. Fitted on `succeeded`, to let through.
    A router that assumes one of these is wrong on the other."""
    assert decide(ACT_L3, ADVERSE, run_id="r1").action == "intercept"
    assert decide(ACT_L3, DESIRABLE, run_id="r1").action == "proceed"


def test_everything_that_is_not_certified_is_your_default_policy():
    assert decide(ESCALATE, ADVERSE, run_id="r1").action == "default"
    assert decide(REFUSE, ADVERSE, run_id="r1").action == "default"
    d = decide(ACT_L2, ADVERSE, run_id="r1", needs=Autonomy.L3)
    assert d.action == "default" and "ceiling" in d.reason


def test_control_arm_is_recorded_but_never_acted_on():
    d = decide(ACT_L3, ADVERSE, run_id="r1", control=True)
    assert d.action == "default" and d.band == "act" and d.control is True


def test_missing_safeguards_raise_rather_than_default():
    with pytest.raises(MissingSafeguard):
        decide({"entity_id": "r1", "score": 0.9}, ADVERSE, run_id="r1")          # no band
    with pytest.raises(MissingSafeguard):
        decide(ACT_L3, {"outcome": {"column": "failed"}}, run_id="r1")           # no polarity


def test_gate_attaches_the_priors_before_scoring():
    ledger = _golden_ledger()
    hs = FakeScoringClient(ACT_L3, ADVERSE)
    new_run = {"run_id": "r_new", "ts": "2026-02-01T00:00:00Z", "agent": "a1", "task": "t2", "tool": "shell",
               "input_tokens": 2100}
    d = gate(hs, MODEL_REF, ledger, new_run, control_fraction=0.0)
    sent = hs.calls[0]
    assert set(prior_feature_names()) <= set(sent), "the scorecard's arm features must be on the row"
    assert sent["agent_prior_n"] == sum(1 for r in PARSABLE if r["agent"] == "a1")
    assert isinstance(d, Decision) and d.action == "intercept" and d.signature["kid"] == "test"
    assert d.row_scored == sent


def test_gate_scores_a_control_run_but_returns_default():
    hs = FakeScoringClient(ACT_L3, ADVERSE)
    row = {"run_id": "r_ctl", "ts": "2026-02-01T00:00:00Z", "agent": "a1", "task": "t2", "tool": "shell"}
    d = gate(hs, MODEL_REF, Ledger(), row, control_fraction=1.0)
    assert len(hs.calls) == 1                     # the comparison needs its band
    assert d.action == "default" and d.control and d.band == "act"


# ── era-lock ───────────────────────────────────────────────────────────────────────────────

def _rows_with_counter(n=600):
    """A ledger where `agent_prior_n` is a clock and `input_tokens` is not."""
    import random
    rnd = random.Random(3)
    out = []
    for i in range(n):
        out.append({"run_id": f"r{i}", "ts": f"2026-01-{1 + i // 40:02d}T{(i % 40) // 2:02d}:{(i % 2) * 30:02d}:00Z",
                    "agent_prior_n": float(i), "input_tokens": rnd.randint(500, 5000),
                    "tool": rnd.choice(["browser", "shell"])})
    return out


def test_a_condition_bounding_a_monotone_counter_from_above_is_era_locked():
    rows = _rows_with_counter()
    pattern = [{"feature": "agent_prior_n", "direction": "lower", "threshold": 60, "operator": "<=",
                "missing_values": "included"},
               {"feature": "tool", "direction": "different", "threshold": None, "categories": ["browser"],
                "category_match": "is_one_of"}]
    r = era_lock(pattern, rows)                                  # in-fit: no holdout needed
    counter = next(c for c in r["conditions"] if c["feature"] == "agent_prior_n")
    assert counter["verdict"] == "DECLINING (in-fit)" and r["era_locked"]
    assert counter["rho_vs_time"] and counter["rho_vs_time"] > 0.9
    r2 = era_lock(pattern, rows, cutoff="2026-01-10")                # forward: dead after the cutoff
    assert next(c for c in r2["conditions"] if c["feature"] == "agent_prior_n")["verdict"] == "DEAD"
    assert r2["joint_coverage_holdout"] == 0.0


def test_a_counter_bounded_from_below_is_clock_like_not_dead():
    rows = _rows_with_counter()
    pattern = [{"feature": "agent_prior_n", "direction": "higher", "threshold": 97, "operator": ">",
                "missing_values": "excluded"}]
    r = era_lock(pattern, rows)
    assert r["conditions"][0]["verdict"] == "CLOCK-LIKE" and r["clock_like"] and not r["era_locked"]


def test_a_stable_feature_is_ok():
    rows = _rows_with_counter()
    pattern = [{"feature": "input_tokens", "direction": "lower", "threshold": 2793.5, "operator": "<=",
                "missing_values": "included"}]
    r = era_lock(pattern, rows, cutoff="2026-01-10")
    assert r["conditions"][0]["verdict"] == "ok" and not r["era_locked"]


def test_conditions_are_rebuilt_from_the_predicate_not_the_direction_word():
    """'lower' means `<=` with missing INCLUDED. A row with the feature missing is INSIDE."""
    rows = [{"run_id": "a", "ts": "2026-01-01T00:00:00Z", "x": None},
            {"run_id": "b", "ts": "2026-01-01T01:00:00Z", "x": 5.0},
            {"run_id": "c", "ts": "2026-01-01T02:00:00Z", "x": 50.0}]
    lower = [{"feature": "x", "direction": "lower", "threshold": 10, "operator": "<=", "missing_values": "included"}]
    higher = [{"feature": "x", "direction": "higher", "threshold": 10, "operator": ">", "missing_values": "excluded"}]
    assert era_lock(lower, rows)["joint_coverage_fit"] == pytest.approx(2 / 3, abs=1e-4)
    assert era_lock(higher, rows)["joint_coverage_fit"] == pytest.approx(1 / 3, abs=1e-4)
