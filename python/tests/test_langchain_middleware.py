"""hunter_seeker.langchain_middleware — the dispatch gate, against real LangChain.

No stub. The adapter depends on two LangChain rules that fail SILENTLY — an undeclared `jump_to`
is ignored and an undeclared state key is dropped — and the first version of this adapter broke
both while every stubbed test passed. CI installs langchain through the `test` extra, so these
run there; without langchain the whole module skips.
"""
from __future__ import annotations

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
