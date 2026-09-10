"""hunter_seeker.langchain_middleware — the dispatch gate.

Two layers. The decision logic and the state-update shape are tested with `AgentMiddleware`
stubbed, like test_framework_adapters, so they run in CI without the framework. That layer
CANNOT see the two LangChain rules the adapter depends on — an undeclared `jump_to` is ignored
and an undeclared state key is dropped, both silently — and the first version of this adapter
broke both while every stubbed test passed. So the last test drives a real `create_agent`
whenever langchain is installed.
"""
from __future__ import annotations

import sys
import types

import pytest

from hunter_seeker.loop import Ledger

ACT_L3 = {"entity_id": "r1", "score": 0.53, "band": "act", "band_reason": "certified", "max_autonomy": "L3"}
ESCALATE = {"entity_id": "r1", "score": 0.51, "band": "escalate", "band_reason": "uncertain", "max_autonomy": "L1"}
ADVERSE = {"outcome": {"column": "failed", "polarity": "adverse"}}
DESIRABLE = {"outcome": {"column": "succeeded", "polarity": "desirable"}}


class _FakeClient:
    def __init__(self, entity, verdict):
        self.entity, self.verdict, self.calls = entity, verdict, []

    def score_entity(self, model_ref, row, *, subject_kind, entity_id=None, acknowledge_decision_support=False):
        self.calls.append(dict(row))
        return {"entity": dict(self.entity), "verdict": dict(self.verdict),
                "signature": {"kid": "test", "protected": "x", "signature": "y"}}


@pytest.fixture
def middleware_module(monkeypatch):
    """Import the module with a stub `langchain.agents.middleware.AgentMiddleware` in place."""
    base = types.ModuleType("langchain.agents.middleware")

    class AgentMiddleware:  # the stub records that super().__init__ was reached
        def __init__(self):
            self._base_init = True

    base.AgentMiddleware = AgentMiddleware
    pkg = types.ModuleType("langchain"); agents = types.ModuleType("langchain.agents")
    pkg.agents, agents.middleware = agents, base
    monkeypatch.setitem(sys.modules, "langchain", pkg)
    monkeypatch.setitem(sys.modules, "langchain.agents", agents)
    monkeypatch.setitem(sys.modules, "langchain.agents.middleware", base)
    sys.modules.pop("hunter_seeker.langchain_middleware", None)
    import hunter_seeker.langchain_middleware as m
    yield m
    sys.modules.pop("hunter_seeker.langchain_middleware", None)


def _row(state, runtime):
    return {"run_id": runtime["run_id"], "ts": runtime["ts"], "agent": "a", "task": state["task"], "tool": "browser"}


def test_intercept_jumps_to_end_and_leaves_the_decision_on_state(middleware_module):
    m = middleware_module
    ledger = Ledger()
    loop = m.LoopMiddleware(_FakeClient(ACT_L3, ADVERSE), ledger, model_ref="mr1_" + "0" * 32,
                            row_from_state=_row, control_fraction=0.0)
    assert getattr(loop, "_base_init", False), "must chain to AgentMiddleware.__init__"
    upd = loop.before_agent({"task": "t"}, {"run_id": "r1", "ts": "2026-01-01T00:00:00Z"})
    assert upd["jump_to"] == "end" and upd["hs_decision"].action == "intercept"


def test_proceed_and_default_do_not_jump(middleware_module):
    m = middleware_module
    for entity, verdict in ((ACT_L3, DESIRABLE), (ESCALATE, ADVERSE)):
        loop = m.LoopMiddleware(_FakeClient(entity, verdict), Ledger(), model_ref="mr1_" + "0" * 32,
                                row_from_state=_row, control_fraction=0.0)
        upd = loop.before_agent({"task": "t"}, {"run_id": "r1", "ts": "2026-01-01T00:00:00Z"})
        assert "jump_to" not in upd and upd["hs_decision"].action in ("proceed", "default")


def test_priors_are_attached_and_every_run_is_recorded_once(middleware_module):
    m = middleware_module
    for verdict in (ADVERSE, DESIRABLE):          # intercepted at the gate, and let through
        ledger = Ledger()
        ledger.append({"run_id": "r0", "ts": "2025-12-31T00:00:00Z", "agent": "a", "task": "t", "tool": "browser", "failed": 0})
        hs = _FakeClient(ACT_L3, verdict)
        loop = m.LoopMiddleware(hs, ledger, model_ref="mr1_" + "0" * 32, row_from_state=_row, control_fraction=0.0)
        rt = {"run_id": "r1", "ts": "2026-01-01T00:00:00Z"}
        state = {"task": "t"}
        state.update(loop.before_agent(state, rt))
        assert hs.calls[0]["agent_prior_n"] == 1 and hs.calls[0]["agent_prior_outcome_rate"] == 0.0
        assert loop.after_agent(state, rt) is None
        assert [r["run_id"] for r in ledger.rows] == ["r0", "r1"], verdict
        assert ledger.rows[-1]["failed"] is None


def test_an_intercepted_run_is_recorded_even_if_after_agent_never_runs(middleware_module):
    m = middleware_module
    ledger = Ledger()
    loop = m.LoopMiddleware(_FakeClient(ACT_L3, ADVERSE), ledger, model_ref="mr1_" + "0" * 32,
                            row_from_state=_row, control_fraction=0.0)
    loop.before_agent({"task": "t"}, {"run_id": "r1", "ts": "2026-01-01T00:00:00Z"})
    assert [r["run_id"] for r in ledger.rows] == ["r1"]


def test_module_imports_without_langchain():
    sys.modules.pop("hunter_seeker.langchain_middleware", None)
    import hunter_seeker.langchain_middleware as m
    assert m.LoopMiddleware.__mro__[1].__name__ in ("_Base", "AgentMiddleware")


def test_inside_a_real_create_agent():
    """The contract as LangChain enforces it: intercept means the model never runs."""
    pytest.importorskip("langchain.agents.middleware")
    from langchain.agents import create_agent
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain_core.messages import AIMessage

    sys.modules.pop("hunter_seeker.langchain_middleware", None)
    import hunter_seeker.langchain_middleware as m

    def row(state, runtime):
        return {"run_id": "r1", "ts": "2026-01-01T00:00:00Z", "agent": "a", "task": "t", "tool": "browser"}

    for verdict, action, model_runs in ((ADVERSE, "intercept", False), (DESIRABLE, "proceed", True)):
        ledger = Ledger()
        loop = m.LoopMiddleware(_FakeClient(ACT_L3, verdict), ledger, model_ref="mr1_" + "0" * 32,
                                row_from_state=row, control_fraction=0.0)
        model = GenericFakeChatModel(messages=iter([AIMessage(content="MODEL_RAN")] * 3))
        out = create_agent(model=model, tools=[], middleware=[loop]).invoke(
            {"messages": [{"role": "user", "content": "go"}]})
        ran = any(getattr(msg, "content", None) == "MODEL_RAN" for msg in out["messages"])
        assert ran is model_runs, action
        assert out["hs_decision"].action == action
        assert [r["run_id"] for r in ledger.rows] == ["r1"], action
