"""LangChain agent middleware for the governed loop. `pip install "hunter-seeker[langchain-middleware]"`.

    from langchain.agents import create_agent
    from hunter_seeker.langchain_middleware import LoopMiddleware

    loop = LoopMiddleware(hs, ledger, model_ref=model_ref,
                          row_from_state=lambda state, runtime: {
                              "run_id": runtime.context["run_id"], "ts": runtime.context["ts"],
                              "agent": "gpt-5.5/tools-v2", "task": runtime.context["task_family"],
                              "tool": runtime.context.get("primary_tool")})
    agent = create_agent(model="gpt-5.5", tools=[...], middleware=[loop])

This is the DISPATCH gate — it runs in `before_agent`, once, before the first model call — so the
row it scores must contain only what is known before the run starts: identity, task, tool, the
priors (attached here), the request size. Fit the scorecard on those columns. A scorecard fitted
on end-of-run telemetry belongs at the end of the run (see `hunter_seeker.claude_agent`), not here.

On "intercept" (adverse outcome, band act, ceiling permits) it jumps to the end of the graph
before the model is called, with the Decision on the state under `hs_decision`, so the caller can
route the run to a human or a stronger model instead of letting this agent proceed. On "proceed"
or "default" the run continues; the Decision is still on the state. Every run is recorded in the
ledger exactly once with its outcome unknown — an intercepted run at the gate, every other run in
`after_agent` — so each invoke needs its own `run_id`: `Ledger.append` refuses one it already holds,
and `before_agent` makes that refusal (and refuses a `ts` the ledger cannot parse) up front, before
the decision is billed and before the model runs.

With a checkpointer, the Decision is stored in the checkpoint. LangGraph warns when it deserializes
a type it was not told about, and blocks it under `LANGGRAPH_STRICT_MSGPACK=true`; add
`("hunter_seeker.loop", "Decision")` to the serializer's `allowed_msgpack_modules`.

Two LangChain rules this depends on, both SILENT when broken (measured on langchain 1.4.0
`create_agent`): a `jump_to` the hook did not declare with `hook_config(can_jump_to=...)` is
ignored, so the model runs anyway; and a state key the middleware's `state_schema` does not name
is dropped, so `hs_decision` never reaches the caller. Both are declared below, and the tests drive
a real `create_agent`.

This adapter is different in kind from `hunter_seeker.langchain.verdict_tools`: that gives the
AGENT tools to call the engine; this lets the HARNESS gate the agent. Both are legitimate; a
swarm loop wants the second.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Mapping, Optional

try:
    from langchain.agents.middleware import AgentMiddleware, AgentState, hook_config
except ImportError as e:  # pragma: no cover - exercised only without langchain installed
    raise ImportError('hunter_seeker.langchain_middleware needs langchain>=1.0: '
                      'pip install "hunter-seeker[langchain-middleware]"') from e

try:
    from typing import NotRequired
except ImportError:  # Python 3.10
    from typing_extensions import NotRequired

from .loop import Ledger, gate

RowFromState = Callable[[Mapping[str, Any], Any], Mapping[str, Any]]


class LoopState(AgentState):
    """The agent state plus the two keys this middleware writes."""
    hs_decision: NotRequired[Any]
    hs_recorded: NotRequired[bool]


class LoopMiddleware(AgentMiddleware):
    """`gate_kwargs` (subject_kind, needs, control_fraction, salt, acknowledge_decision_support)
    go to `hunter_seeker.loop.gate` unchanged."""

    state_schema = LoopState

    def __init__(self, hs: Any, ledger: Ledger, *, model_ref: str, row_from_state: RowFromState,
                 **gate_kwargs: Any) -> None:
        super().__init__()
        self.hs, self.ledger, self.model_ref = hs, ledger, model_ref
        self.row_from_state, self.gate_kwargs = row_from_state, gate_kwargs

    @hook_config(can_jump_to=["end"])
    def before_agent(self, state: Mapping[str, Any], runtime: Any) -> Optional[Dict[str, Any]]:
        row = dict(self.row_from_state(state, runtime))
        # Every refusal the append below or in after_agent would make (a run_id already recorded, a
        # ts the ledger cannot parse) is made HERE, before gate() bills a decision and the model runs.
        self.ledger._prepare(row)
        d = gate(self.hs, self.model_ref, self.ledger, row, **self.gate_kwargs)
        if d.action != "intercept":
            # Cleared explicitly: on a checkpointed thread the state keeps an earlier run's
            # hs_recorded=True, and after_agent would then skip recording this run.
            return {"hs_decision": d, "hs_recorded": False}
        # Recorded here: an intercepted run is exactly the one hs_action_evidence needs on the
        # acted side of its comparison, and after_agent sees hs_recorded and does not repeat it.
        self.ledger.append(row)
        return {"hs_decision": d, "hs_recorded": True, "jump_to": "end"}

    def after_agent(self, state: Mapping[str, Any], runtime: Any) -> Optional[Dict[str, Any]]:
        if not state.get("hs_recorded"):
            self.ledger.append(dict(self.row_from_state(state, runtime)))
        return None


__all__ = ["LoopMiddleware", "LoopState"]
