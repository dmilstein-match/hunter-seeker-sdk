"""LangChain agent middleware for the governed loop. `pip install hunter-seeker[langchain]`.

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
ledger exactly once with its outcome unknown — an intercepted run at the gate (a jump to the end
is not guaranteed to pass through `after_agent`), every other run in `after_agent`.

Two LangChain rules this depends on, both SILENT when broken (measured on langchain 1.4.0
`create_agent`): a `jump_to` the hook did not declare with `hook_config(can_jump_to=...)` is
ignored, so the model runs anyway; and a state key the middleware's `state_schema` does not name
is dropped, so `hs_decision` never reaches the caller. Both are declared below, and
`tests/test_langchain_middleware.py` runs a real `create_agent` whenever langchain is installed.

This adapter is different in kind from `hunter_seeker.langchain.verdict_tools`: that gives the
AGENT tools to call the engine; this lets the HARNESS gate the agent. Both are legitimate; a
swarm loop wants the second.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Mapping, Optional

from .loop import Decision, Ledger, gate
from .safeguards import Autonomy

try:  # pragma: no cover - which branch runs depends on the environment
    from langchain.agents import middleware as _lc  # type: ignore
    _Base = _lc.AgentMiddleware
except Exception:  # ImportError, or an incompatible langchain
    _lc = None

    class _Base:  # type: ignore[no-redef]  # importable without langchain; only usable as middleware with it
        pass

_hook_config = getattr(_lc, "hook_config", None) or (lambda **_kw: (lambda fn: fn))
_AgentState = getattr(_lc, "AgentState", None)

if _AgentState is not None:  # pragma: no cover - needs langchain
    try:
        from typing import NotRequired
    except ImportError:  # Python 3.10
        from typing_extensions import NotRequired

    class LoopState(_AgentState):  # type: ignore[misc, valid-type]
        """The agent state plus the two keys this middleware writes."""
        hs_decision: NotRequired[Any]
        hs_recorded: NotRequired[bool]
else:
    LoopState = None  # type: ignore[assignment,misc]


RowFromState = Callable[[Mapping[str, Any], Any], Mapping[str, Any]]


def _record(ledger: Ledger, row: Dict[str, Any]) -> None:
    row.setdefault(ledger.outcome, None)
    ledger.append(row)


def gate_state(hs: Any, ledger: Ledger, model_ref: str, row_from_state: RowFromState,
               state: Mapping[str, Any], runtime: Any, *, subject_kind: str = "event",
               needs: Autonomy = Autonomy.L3, control_fraction: float = 0.15,
               salt: str = "") -> Dict[str, Any]:
    """The `before_agent` body. Returns the state update (possibly with `jump_to`)."""
    row = dict(row_from_state(state, runtime))
    d = gate(hs, model_ref, ledger, row, subject_kind=subject_kind, needs=needs,
             control_fraction=control_fraction, salt=salt)
    update: Dict[str, Any] = {"hs_decision": d}
    if d.action == "intercept":
        # Recorded here rather than in after_agent: the jump may skip it, and an intercepted run is
        # exactly the one hs_action_evidence needs on the acted side of its comparison.
        _record(ledger, row)
        update["hs_recorded"] = True
        update["jump_to"] = "end"
    return update


def record_state(ledger: Ledger, row_from_state: RowFromState, state: Mapping[str, Any],
                 runtime: Any) -> Dict[str, Any]:
    """The `after_agent` body. Records the run with its outcome unknown, unless the gate already did."""
    if not state.get("hs_recorded"):
        _record(ledger, dict(row_from_state(state, runtime)))
    return {}


class LoopMiddleware(_Base):
    if LoopState is not None:  # pragma: no cover - needs langchain
        state_schema = LoopState

    def __init__(self, hs: Any, ledger: Ledger, *, model_ref: str, row_from_state: RowFromState,
                 subject_kind: str = "event", needs: Autonomy = Autonomy.L3,
                 control_fraction: float = 0.15, salt: str = "") -> None:
        super().__init__()
        self.hs, self.ledger, self.model_ref = hs, ledger, model_ref
        self.row_from_state = row_from_state
        self.subject_kind, self.needs = subject_kind, needs
        self.control_fraction, self.salt = control_fraction, salt

    @_hook_config(can_jump_to=["end"])
    def before_agent(self, state: Mapping[str, Any], runtime: Any) -> Optional[Dict[str, Any]]:
        return gate_state(self.hs, self.ledger, self.model_ref, self.row_from_state, state, runtime,
                          subject_kind=self.subject_kind, needs=self.needs,
                          control_fraction=self.control_fraction, salt=self.salt)

    def after_agent(self, state: Mapping[str, Any], runtime: Any) -> Optional[Dict[str, Any]]:
        return record_state(self.ledger, self.row_from_state, state, runtime) or None


__all__ = ["LoopMiddleware", "gate_state", "record_state", "Decision"]
