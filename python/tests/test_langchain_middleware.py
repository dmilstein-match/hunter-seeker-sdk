"""hunter_seeker.langchain_middleware — the dispatch gate, against real LangChain.

No stub. The adapter depends on two LangChain rules that fail SILENTLY — an undeclared `jump_to`
is ignored and an undeclared state key is dropped — and the first version of this adapter broke
both while every stubbed test passed. CI installs langchain through the `test` extra, so these
run there; without langchain the whole module skips.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

pytest.importorskip("langchain.agents.middleware")

from conftest import ACT_L3, ADVERSE, DESIRABLE, ESCALATE, MODEL_REF, FakeScoringClient  # noqa: E402
from langchain.agents import create_agent  # noqa: E402
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402

from hunter_seeker.langchain_middleware import LoopMiddleware  # noqa: E402
from hunter_seeker.loop import Ledger  # noqa: E402


def _row(state, runtime):
    return {"run_id": "r1", "ts": "2026-01-01T00:00:00Z", "agent": "a", "task": "t", "tool": "browser"}


def _loop(entity, verdict, ledger=None):
    hs = FakeScoringClient(entity, verdict)
    return hs, LoopMiddleware(hs, ledger if ledger is not None else Ledger(), model_ref=MODEL_REF,
                              row_from_state=_row, control_fraction=0.0)


def _invoke(loop):
    model = GenericFakeChatModel(messages=iter([AIMessage(content="MODEL_RAN")] * 3))
    out = create_agent(model=model, tools=[], middleware=[loop]).invoke(
        {"messages": [{"role": "user", "content": "go"}]})
    return out, any(getattr(m, "content", None) == "MODEL_RAN" for m in out["messages"])


def test_intercept_means_the_model_never_runs():
    _, loop = _loop(ACT_L3, ADVERSE)
    out, ran = _invoke(loop)
    assert not ran
    assert out["hs_decision"].action == "intercept"


@pytest.mark.parametrize("entity, verdict, action", [(ACT_L3, DESIRABLE, "proceed"), (ESCALATE, ADVERSE, "default")])
def test_proceed_and_default_let_the_run_continue(entity, verdict, action):
    _, loop = _loop(entity, verdict)
    out, ran = _invoke(loop)
    assert ran and out["hs_decision"].action == action


@pytest.mark.parametrize("verdict", [ADVERSE, DESIRABLE])
def test_priors_are_attached_and_every_run_is_recorded_once(verdict):
    """Intercepted at the gate or let through, the run lands in the ledger exactly once."""
    ledger = Ledger()
    ledger.append({"run_id": "r0", "ts": "2025-12-31T00:00:00Z", "agent": "a", "task": "t", "tool": "browser", "failed": 0})
    hs, loop = _loop(ACT_L3, verdict, ledger)
    _invoke(loop)
    assert hs.calls[0]["agent_prior_n"] == 1 and hs.calls[0]["agent_prior_outcome_rate"] == 0.0
    assert [r["run_id"] for r in ledger.rows] == ["r0", "r1"]
    assert ledger.rows[-1]["failed"] is None


@pytest.mark.parametrize("verdict", [ADVERSE, DESIRABLE])
def test_a_run_id_already_recorded_is_refused_before_the_gate_bills_it(verdict):
    """after_agent's append refused a duplicate only at the END of the run: the decision was billed
    and the model had run. before_agent refuses it, before either."""
    ledger = Ledger()
    ledger.append({"run_id": "r1", "ts": "2025-12-31T00:00:00Z", "agent": "a", "task": "t", "tool": "browser", "failed": 0})
    hs, loop = _loop(ACT_L3, verdict, ledger)
    replies = iter([AIMessage(content="MODEL_RAN") for _ in range(3)])
    agent = create_agent(model=GenericFakeChatModel(messages=replies), tools=[], middleware=[loop])
    with pytest.raises(ValueError, match="already in the ledger"):
        agent.invoke({"messages": [{"role": "user", "content": "go"}]})
    assert hs.calls == []                                   # no decision billed
    assert len(list(replies)) == 3                          # and the model never ran
    assert [r["run_id"] for r in ledger.rows] == ["r1"]


def test_a_ts_the_ledger_cannot_parse_is_refused_before_the_gate_bills_it():
    hs = FakeScoringClient(ACT_L3, DESIRABLE)
    loop = LoopMiddleware(hs, Ledger(), model_ref=MODEL_REF, control_fraction=0.0,
                          row_from_state=lambda state, runtime: {**_row(state, runtime), "ts": "03/04/2026"})
    with pytest.raises(ValueError, match="ISO-8601"):
        _invoke(loop)
    assert hs.calls == []


@dataclass
class _Ctx:
    run_id: str


def test_a_checkpointed_thread_records_the_run_after_an_intercept():
    """LangGraph keeps state keys across invokes on one thread_id. hs_recorded=True from an
    intercepted run used to survive into the next run, and after_agent then skipped recording it."""
    from langgraph.checkpoint.memory import InMemorySaver

    ledger = Ledger()
    hs = FakeScoringClient(ACT_L3, ADVERSE)
    loop = LoopMiddleware(hs, ledger, model_ref=MODEL_REF, control_fraction=0.0,
                          row_from_state=lambda state, runtime: {**_row(state, runtime), "run_id": runtime.context.run_id})
    # a separate AIMessage per reply: a repeated instance is deduped by id and hides whether the model ran
    model = GenericFakeChatModel(messages=iter([AIMessage(content="MODEL_RAN") for _ in range(3)]))
    agent = create_agent(model=model, tools=[], middleware=[loop], checkpointer=InMemorySaver(), context_schema=_Ctx)
    config = {"configurable": {"thread_id": "one-thread"}}

    out1 = agent.invoke({"messages": [{"role": "user", "content": "go"}]}, config=config, context=_Ctx("r1"))
    assert out1["hs_decision"].action == "intercept"
    hs.verdict = DESIRABLE
    out2 = agent.invoke({"messages": [{"role": "user", "content": "again"}]}, config=config, context=_Ctx("r2"))
    assert out2["hs_decision"].action == "proceed"
    assert any(getattr(m, "content", None) == "MODEL_RAN" for m in out2["messages"])
    assert [r["run_id"] for r in ledger.rows] == ["r1", "r2"]
