"""The cases an adversarial review found the first test file did not cover.

Every test here failed, or would have passed with the bug in place, before the fixes beside it:

  * `record_decision` called `.update()` on an int — `_by_id` maps a run key to its INDEX, not to
    the row — so the method raised on every call it did not refuse. The only test exercised the
    not-found branch, which is why a method that could never succeed sat behind a green suite.
  * `hs_control` was read with `bool()`. A ledger round-tripped through CSV yields the STRING
    "False", so every treated run landed in the CONTROL cell and the comparison inverted itself
    silently.
  * No test asserted a CI VALUE, so swapping Newcombe for a plain Wald interval changed nothing
    the suite could see — the release's central statistic was unpinned.
  * `actionable` returned True for a change with no feature named: a safeguard failing open on
    the malformed input it exists to distrust.
  * `save` wrote a bare `NaN` token (not JSON) and pandas sentinels as the text "NaT" / "<NA>".
"""
from __future__ import annotations

import csv
import json
import math

import pytest
from conftest import ACT_L3, ADVERSE, MODEL_REF

from hunter_seeker.loop import Ledger, actionable, decide


def _row(i: int, outcome=None):
    return {"run_id": f"r{i}", "ts": f"2026-01-01T00:{i // 60:02d}:{i % 60:02d}Z",
            "agent": "a1", "task": "t1", "tool": "browser", "failed": outcome}


# ── record_decision, on a run that exists ────────────────────────────────────────────────────

def test_record_decision_writes_the_columns_onto_the_run():
    led = Ledger()
    led.append(_row(1, 0))
    led.record_decision("r1", decide(ACT_L3, ADVERSE, run_id="r1"))

    row = led.rows[0]
    assert row["hs_band"] == "act"
    assert row["hs_action"] == "intercept"
    assert row["hs_control"] is False


def test_a_recorded_decision_reaches_the_treated_cell():
    """The end the method exists for: record on an existing run, and `evidence()` can see it."""
    led = Ledger()
    for i in range(30):
        led.append(_row(i, 0))
        led.record_decision(f"r{i}", decide(ACT_L3, ADVERSE, run_id=f"r{i}", control=False))
    for j in range(30):
        i = 100 + j
        led.append(_row(i, 1))
        led.record_decision(f"r{i}", decide(ACT_L3, ADVERSE, run_id=f"r{i}", control=True))

    ev = led.evidence()
    assert (ev["treated"]["n"], ev["control"]["n"]) == (30, 30)
    assert ev["live"] is not None


def test_an_integer_run_id_is_recorded_by_the_same_id():
    led = Ledger()
    led.append({**_row(1, 0), "run_id": 7})
    led.record_decision(7, decide(ACT_L3, ADVERSE, run_id=7))
    assert led.rows[0]["hs_band"] == "act"


# ── the arms survive a CSV round trip ────────────────────────────────────────────────────────

def test_a_control_flag_read_back_from_csv_does_not_invert_the_arms(tmp_path):
    """`csv.DictReader` yields "False", and `bool("False")` is True."""
    led = Ledger()
    for i in range(30):
        led.append_decision(_row(i), decide(ACT_L3, ADVERSE, run_id=f"r{i}", control=False))
        led.observe(f"r{i}", 0)
    for j in range(30):
        i = 100 + j
        led.append_decision(_row(i), decide(ACT_L3, ADVERSE, run_id=f"r{i}", control=True))
        led.observe(f"r{i}", 1)

    path = tmp_path / "ledger.csv"
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=sorted({k for r in led.rows for k in r}))
        w.writeheader()
        w.writerows(led.rows)
    with open(path, encoding="utf-8") as fh:
        back = Ledger()
        for r in csv.DictReader(fh):
            r["failed"] = int(r["failed"])
            back.append(r)

    ev = back.evidence()
    assert (ev["treated"]["n"], ev["control"]["n"]) == (30, 30), \
        "the arms inverted on the way back from CSV"


@pytest.mark.parametrize("raw,expect_control", [
    ("False", False), ("false", False), ("0", False), ("", False), ("None", False),
    ("True", True), ("true", True), ("1", True),
])
def test_a_stringified_control_flag_is_read_as_its_value(raw, expect_control):
    led = Ledger()
    led.append({**_row(1, 0), "hs_band": "act", "hs_action": "intercept", "hs_control": raw})
    ev = led.evidence()
    assert (ev["control"]["n"] == 1) is expect_control
    assert (ev["treated"]["n"] == 1) is not expect_control


# ── the interval itself ──────────────────────────────────────────────────────────────────────

def test_the_interval_is_newcombe_and_not_a_wald_approximation():
    """A pinned value. Thirty controls that all failed against thirty treated that all did not:
    the Wald interval on a difference of 1.0 has zero width, which is the tell."""
    led = Ledger()
    for i in range(30):
        led.append_decision(_row(i), decide(ACT_L3, ADVERSE, run_id=f"r{i}", control=False))
        led.observe(f"r{i}", 0)
    for j in range(30):
        i = 100 + j
        led.append_decision(_row(i), decide(ACT_L3, ADVERSE, run_id=f"r{i}", control=True))
        led.observe(f"r{i}", 1)

    live = led.evidence()["live"]
    assert live["difference_control_minus_treated"] == pytest.approx(1.0)
    lo, hi = live["ci95"]
    assert (lo, hi) == pytest.approx((0.8394678176173436, 1.0), abs=1e-12)


def test_small_n_turns_off_exactly_at_the_floor():
    """`small_n` is True BELOW `small_n_below`, so 100 per cell is not small."""
    led = Ledger()
    for i in range(100):
        led.append_decision(_row(i), decide(ACT_L3, ADVERSE, run_id=f"r{i}", control=False))
        led.observe(f"r{i}", 0)
    for j in range(100):
        i = 1000 + j
        led.append_decision(_row(i), decide(ACT_L3, ADVERSE, run_id=f"r{i}", control=True))
        led.observe(f"r{i}", 1)

    assert led.evidence()["live"]["small_n"] is False
    assert led.evidence(small_n_below=101)["live"]["small_n"] is True


# ── persistence ──────────────────────────────────────────────────────────────────────────────

def test_save_writes_json_a_stranger_can_parse(tmp_path):
    """A bare NaN token is not JSON. Anything that is missing goes out as null."""
    led = Ledger()
    led.append({**_row(1, 0), "latency": float("nan")})
    path = tmp_path / "ledger.jsonl"
    led.save(str(path))

    line = path.read_text(encoding="utf-8").strip()
    assert "NaN" not in line
    parsed = json.loads(line, parse_constant=lambda c: pytest.fail(f"non-JSON constant {c!r}"))
    assert parsed["latency"] is None


def test_load_applies_the_same_refusals_as_a_live_append(tmp_path):
    """Rows go back through `append`, so a reloaded ledger cannot hold what a live one refuses."""
    path = tmp_path / "ledger.jsonl"
    rows = [_row(1, 0), _row(1, 0)]          # the same run_id twice
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    with pytest.raises(Exception):
        Ledger.load(str(path))

    bad_ts = tmp_path / "bad.jsonl"
    bad_ts.write_text(json.dumps({**_row(2, 0), "ts": "03/04/2026"}) + "\n", encoding="utf-8")
    with pytest.raises(Exception):
        Ledger.load(str(bad_ts))


# ── the safeguard fails closed ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("changes", [
    [{}],
    [{"feature": ""}],
    [{"feature": "   "}],
    [{"feature": None}],
], ids=["no-key", "empty", "blank", "null"])
def test_a_change_that_names_no_feature_is_not_a_knob(changes):
    """It used to read as "", match no history suffix, and come back actionable — a safeguard
    failing open on exactly the malformed input it should distrust."""
    assert actionable({"entity_id": "r1", "changes": changes}) is False
