"""Claude Agent SDK hooks for the governed loop. `pip install claude-agent-sdk` (optional).

    from claude_agent_sdk import query, ClaudeAgentOptions
    from hunter_seeker import Client
    from hunter_seeker.loop import Ledger
    from hunter_seeker.claude_agent import LoopSession

    session = LoopSession(hs, ledger, run_id=run_id, agent="claude-opus-5/tools-v3", task="pr-review",
                          model_ref=model_ref, on_decision=route)      # route(Decision) is YOUR policy
    async for msg in query(prompt=..., options=ClaudeAgentOptions(hooks=session.hooks())):
        ...
    # later, when you OBSERVE the outcome (tests pass on main, ticket stayed closed, ...):
    ledger.observe(run_id, failed)
    hs.report_outcome(model_ref, [{"entity_id": run_id, "outcome": failed, "observed_at": ..., "event_id": f"{run_id}:outcome"}])

One `LoopSession` per agent run. It listens to four hook events — `PreToolUse`, `PostToolUse`,
`PostToolUseFailure`, `Stop` — and does three things:

  1. ACCUMULATES the run's telemetry (steps, errors, repeated actions, first tool) from the events
     themselves, so the ledger row is built from what the harness saw, never from what the agent
     said. Token counts do not arrive through hooks; set them from the result message if you have
     them (`session.tokens_in = ...`) before `Stop` fires, or leave them None.
  2. RECORDS the run in the ledger at `Stop`, with the outcome unknown (None). The outcome is
     yours to observe later; nothing here infers it from the transcript.
  3. GATES at `Stop` when a `model_ref` is given: computes the six priors from the ledger, scores
     the finished run, and hands the `Decision` to `on_decision`. The hook itself returns `{}` —
     at `Stop` the run is already over, so "intercept" means *do not auto-approve its result*,
     and what that means (hold the PR, route to review, re-run on a stronger model) is the
     harness's policy, not this module's.

Two things it does NOT do, on purpose:

  * It does not gate at `PreToolUse` with a run-level scorecard. A scorecard fitted on
    end-of-run telemetry (`steps`, `tokens_out`, ...) scored mid-run with partial counts is a
    distribution mismatch dressed as a prediction. To gate at DISPATCH, fit a scorecard on
    columns known before the run starts (agent, task, tool, the priors, the request size) and
    call `hunter_seeker.loop.gate` before you call `query()` — the row is yours to build.
  * It never returns `permissionDecision: "deny"` on the engine's say-so. A band is a fact about
    likelihood; blocking a tool call is an action, and the policy that maps one to the other is
    yours (`hs-act-faithfully` has the ladder).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Mapping, Optional

from .loop import Decision, Ledger, gate
from .safeguards import Autonomy


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class LoopSession:
    def __init__(self, hs: Any, ledger: Ledger, *, run_id: str, agent: str, task: str,
                 tool: Optional[str] = None, ts: Optional[str] = None,
                 model_ref: Optional[str] = None, subject_kind: str = "event",
                 needs: Autonomy = Autonomy.L3, control_fraction: float = 0.15, salt: str = "",
                 on_decision: Optional[Callable[[Decision], Any]] = None,
                 extra: Optional[Mapping[str, Any]] = None) -> None:
        self.hs, self.ledger = hs, ledger
        self.run_id, self.agent, self.task = str(run_id), agent, task
        self.tool = tool                      # None → the first tool the run calls
        self.ts = ts or _now()
        self.model_ref, self.subject_kind, self.needs = model_ref, subject_kind, needs
        self.control_fraction, self.salt, self.on_decision = control_fraction, salt, on_decision
        self.extra: Dict[str, Any] = dict(extra or {})
        # telemetry — from the hooks, never from the transcript
        self.steps = 0
        self.errors = 0
        self.repeated_actions = 0
        self.tokens_in: Optional[int] = None
        self.tokens_out: Optional[int] = None
        self.hit_cap: Optional[int] = None
        self.started = datetime.now(timezone.utc)
        self.elapsed_ms: Optional[int] = None
        self._seen: set = set()
        self.decision: Optional[Decision] = None
        self.recorded = False

    # -- the row -------------------------------------------------------------------------------
    def row(self) -> Dict[str, Any]:
        """The ledger row as it stands. Outcome is None: it is observed later, by you."""
        L = self.ledger
        r: Dict[str, Any] = {
            L.identifier: self.run_id, L.time_axis: self.ts,
            L.groups.get("agent", "agent"): self.agent,
            L.groups.get("task", "task"): self.task,
            L.groups.get("tool", "tool"): self.tool,
            "steps": self.steps, "errors": self.errors, "repeated_actions": self.repeated_actions,
            "tokens_in": self.tokens_in, "tokens_out": self.tokens_out, "hit_cap": self.hit_cap,
            "elapsed_ms": self.elapsed_ms,
            L.outcome: None,
        }
        r.update(self.extra)
        return r

    # -- hook callbacks (async, the SDK's calling convention) ----------------------------------
    async def pre_tool(self, input_data: Mapping[str, Any], tool_use_id: Any = None, context: Any = None) -> Dict[str, Any]:
        name = str(input_data.get("tool_name", ""))
        if self.tool is None and name:
            self.tool = name
        self.steps += 1
        key = hashlib.sha256((name + "\x1f" + json.dumps(input_data.get("tool_input", {}), sort_keys=True,
                                                          default=str)).encode()).hexdigest()
        if key in self._seen:
            self.repeated_actions += 1
        self._seen.add(key)
        return {}

    async def post_tool(self, input_data: Mapping[str, Any], tool_use_id: Any = None, context: Any = None) -> Dict[str, Any]:
        return {}

    async def post_tool_failure(self, input_data: Mapping[str, Any], tool_use_id: Any = None, context: Any = None) -> Dict[str, Any]:
        self.errors += 1
        return {}

    async def stop(self, input_data: Mapping[str, Any], tool_use_id: Any = None, context: Any = None) -> Dict[str, Any]:
        if self.recorded:            # Stop can fire more than once in a multi-turn session
            return {}
        self.elapsed_ms = int((datetime.now(timezone.utc) - self.started).total_seconds() * 1000)
        row = self.row()
        if self.model_ref:
            self.decision = gate(self.hs, self.model_ref, self.ledger, row, subject_kind=self.subject_kind,
                                 needs=self.needs, control_fraction=self.control_fraction, salt=self.salt)
        self.ledger.append(row)
        self.recorded = True
        if self.decision is not None and self.on_decision is not None:
            self.on_decision(self.decision)
        return {}

    # -- wiring --------------------------------------------------------------------------------
    def hooks(self) -> Dict[str, Any]:
        """The `hooks=` value for `ClaudeAgentOptions`. Needs `claude-agent-sdk` for HookMatcher."""
        try:
            from claude_agent_sdk import HookMatcher  # type: ignore
        except ImportError as e:  # pragma: no cover - exercised only without the SDK installed
            raise ImportError("hunter_seeker.claude_agent.LoopSession.hooks() needs `pip install "
                              "claude-agent-sdk`; or wire the four coroutines yourself: pre_tool, "
                              "post_tool, post_tool_failure, stop") from e
        return {
            "PreToolUse": [HookMatcher(hooks=[self.pre_tool])],
            "PostToolUse": [HookMatcher(hooks=[self.post_tool])],
            "PostToolUseFailure": [HookMatcher(hooks=[self.post_tool_failure])],
            "Stop": [HookMatcher(hooks=[self.stop])],
        }


__all__ = ["LoopSession"]
