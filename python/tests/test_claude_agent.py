"""hunter_seeker.claude_agent.LoopSession — the four hook coroutines, driven directly.

No claude-agent-sdk needed: the coroutines take the SDK's (input_data, tool_use_id, context) and
return the SDK's output dict, and that contract is what is tested. `hooks()` is the only thing
that needs the package, and it is exercised in test_framework_adapters style only when present.
"""
from __future__ import annotations

import asyncio

from hunter_seeker.claude_agent import LoopSession
from hunter_seeker.loop import Ledger

ACT_L3 = {"entity_id": "r1", "score": 0.53, "band": "act", "band_reason": "certified", "max_autonomy": "L3"}
ADVERSE = {"outcome": {"column": "failed", "polarity": "adverse"}}


class _FakeClient:
    def __init__(self):
        self.calls = []

    def score_entity(self, model_ref, row, *, subject_kind, entity_id=None, acknowledge_decision_support=False):
        self.calls.append(dict(row))
        return {"entity": dict(ACT_L3), "verdict": dict(ADVERSE),
                "signature": {"kid": "test", "protected": "x", "signature": "y"}}


def _drive(session: LoopSession, events):
    async def run():
        for name, payload in events:
            await getattr(session, name)(payload, "tu_1", None)
    asyncio.run(run())


def test_telemetry_comes_from_the_hooks_not_the_transcript():
    ledger = Ledger()
    s = LoopSession(_FakeClient(), ledger, run_id="r1", agent="a", task="t")
    _drive(s, [
        ("pre_tool", {"tool_name": "Bash", "tool_input": {"command": "pytest"}}),
        ("post_tool", {"tool_name": "Bash"}),
        ("pre_tool", {"tool_name": "Edit", "tool_input": {"file": "x.py"}}),
        ("post_tool_failure", {"tool_name": "Edit", "error": "boom"}),
        ("pre_tool", {"tool_name": "Bash", "tool_input": {"command": "pytest"}}),   # the same action again
        ("post_tool", {"tool_name": "Bash"}),
        ("stop", {"stop_reason": "end_turn"}),
    ])
    row = ledger.rows[0]
    assert row["tool"] == "Bash"                 # the first tool the run called
    assert row["steps"] == 3 and row["errors"] == 1 and row["repeated_actions"] == 1
    assert row["failed"] is None                 # the outcome is observed later, by you
    assert row["elapsed_ms"] is not None and row["tokens_in"] is None


def test_stop_records_once_even_when_it_fires_twice():
    ledger = Ledger()
    s = LoopSession(_FakeClient(), ledger, run_id="r1", agent="a", task="t")
    _drive(s, [("stop", {}), ("stop", {})])
    assert len(ledger.rows) == 1


def test_stop_gates_with_priors_and_hands_the_decision_to_your_policy():
    ledger = Ledger()
    ledger.append({"run_id": "r0", "ts": "2026-01-01T00:00:00Z", "agent": "a", "task": "t", "tool": "Bash", "failed": 1})
    hs = _FakeClient()
    seen = []
    s = LoopSession(hs, ledger, run_id="r1", agent="a", task="t", ts="2026-01-02T00:00:00Z",
                    model_ref="mr1_" + "0" * 32, on_decision=seen.append, control_fraction=0.0)
    _drive(s, [("pre_tool", {"tool_name": "Bash", "tool_input": {}}), ("stop", {})])
    sent = hs.calls[0]
    assert sent["agent_prior_n"] == 1 and sent["agent_prior_outcome_rate"] == 1.0
    assert sent["tool_prior_n"] == 1
    assert seen and seen[0].action == "intercept" and s.decision is seen[0]
    assert ledger.rows[-1]["run_id"] == "r1"


def test_no_model_ref_means_record_only():
    ledger = Ledger()
    hs = _FakeClient()
    s = LoopSession(hs, ledger, run_id="r1", agent="a", task="t")
    _drive(s, [("stop", {})])
    assert hs.calls == [] and s.decision is None and len(ledger.rows) == 1


def test_hook_outputs_never_block_on_the_engine_s_say_so():
    # control_fraction=0 so the run cannot land in the control arm ("r1" does, at the default 15%)
    s = LoopSession(_FakeClient(), Ledger(), run_id="r1", agent="a", task="t", model_ref="mr1_" + "0" * 32,
                    control_fraction=0.0)
    outs = []

    async def run():
        outs.append(await s.pre_tool({"tool_name": "Bash", "tool_input": {}}, "tu", None))
        outs.append(await s.stop({}, "tu", None))
    asyncio.run(run())
    assert outs == [{}, {}]
    assert s.decision is not None and s.decision.action == "intercept"     # the fact is there; the policy is yours


def test_group_columns_follow_the_ledger_binding():
    ledger = Ledger(groups={"agent": "model_cfg", "task": "task_family"})
    s = LoopSession(_FakeClient(), ledger, run_id="r1", agent="a", task="t")
    _drive(s, [("stop", {})])
    row = ledger.rows[0]
    assert row["model_cfg"] == "a" and row["task_family"] == "t" and "agent" not in row
