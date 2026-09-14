"""OpenAI Agents SDK: an input guardrail for the decision point, run hooks for attestation.
`pip install "hunter-seeker[openai-agents]"`.

    from agents import Agent, Runner
    from hunter_seeker import Client
    from hunter_seeker.openai_agents import decide_input_guardrail, AttestHooks

    hs = Client(api_key=os.environ["HS_API_KEY"])
    agent = Agent(name="refunds", instructions=..., tools=[...],
                  input_guardrails=[decide_input_guardrail(hs, "ag_...", case_from_input=my_case)])
    result = await Runner.run(agent, "refund order 41", hooks=AttestHooks(hs, "urn:my-runtime:refunds"))

The guardrail asks `POST /v1/decide` once, inside a two-second budget, and returns
`GuardrailFunctionOutput(output_info=<RouteDecision as a dict>, tripwire_triggered=route in trip_on)`.
The tripwire is the SDK's way of stopping a run so the harness routes it to a person; by default
it trips on `human` only (`review` lets the agent work while the Approval queue holds the result;
pass `trip_on=("review", "human")` to stop on both). Any error or timeout is the customer's
named fallback with its reason — never an exception, never a denial from the engine's say-so.

`AttestHooks.on_tool_end` sends one `action.attested` CloudEvent per tool call with the tool
NAME only, carrying `arm` and `lever_id` from the guardrail's decision (kept on the hooks object
by case). The SDK's types are imported lazily; without `openai-agents` the factory returns a
plain callable with the same contract, so the tests run without the package.
"""
from __future__ import annotations

import inspect
from typing import Any, Callable, Dict, Mapping, Optional

from .runtime import RouteDecision, attest, decide_case

CaseFromInput = Callable[[Any, Any, Any], Mapping[str, Any]]  # (ctx, agent, input) -> case

TRIP_ROUTES = ("human",)


def _output(decision: RouteDecision, tripped: bool) -> Any:
    try:
        from agents import GuardrailFunctionOutput  # type: ignore

        return GuardrailFunctionOutput(output_info=decision.as_dict(), tripwire_triggered=tripped)
    except Exception:  # noqa: BLE001 — the tests run without the package
        return {"output_info": decision.as_dict(), "tripwire_triggered": tripped}


def decide_input_guardrail(hs: Any, agent_id: str, *, case_from_input: CaseFromInput,
                           fallback: str = "none", timeout: float = 2.0, mode: Optional[str] = None,
                           trip_on: tuple = TRIP_ROUTES, remember: Optional[Dict[str, RouteDecision]] = None,
                           name: str = "hunter_seeker_decide") -> Any:
    """An `InputGuardrail` (or, without the SDK, the async guardrail function itself)."""
    decisions: Dict[str, RouteDecision] = remember if remember is not None else {}

    async def guardrail(ctx: Any, agent: Any, input: Any) -> Any:  # noqa: A002 — the SDK's parameter name
        case = dict(case_from_input(ctx, agent, input))
        d = decide_case(hs, agent_id, case, fallback=fallback, timeout=timeout, mode=mode)
        key = d.case_ref or str(case.get("case_id") or "")
        decisions[key] = d
        context = getattr(ctx, "context", None)
        if isinstance(context, dict):
            context["hs_route"] = d.route
            context["hs_decision"] = d.as_dict()
        return _output(d, d.route in trip_on)

    guardrail.decisions = decisions  # type: ignore[attr-defined]
    try:
        from agents import InputGuardrail  # type: ignore

        g = InputGuardrail(guardrail_function=guardrail, name=name)
        g.decisions = decisions  # type: ignore[attr-defined]
        return g
    except Exception:  # noqa: BLE001
        return guardrail


class AttestHooks:
    """`RunHooks` for the OpenAI Agents SDK: `on_tool_end` attests the tool name for the case.

    `case_ref_from_context(context)` names the case (default: `context.context["hs_case_ref"]` or
    `context.context["case_id"]`); `decisions` is the dict the guardrail fills, so the arm and the
    lever id travel from the receipt to the attestation.
    """

    def __init__(self, hs: Any, source: str, *, decisions: Optional[Mapping[str, RouteDecision]] = None,
                 case_ref_from_context: Optional[Callable[[Any], str]] = None, timeout: float = 2.0) -> None:
        self.hs, self.source, self.timeout = hs, source, timeout
        self.decisions: Mapping[str, RouteDecision] = decisions if decisions is not None else {}
        self.case_ref_from_context = case_ref_from_context
        self.attested: list = []

    def _case_ref(self, context: Any) -> str:
        if self.case_ref_from_context:
            return str(self.case_ref_from_context(context) or "")
        inner = getattr(context, "context", None)
        if isinstance(inner, Mapping):
            return str(inner.get("hs_case_ref") or inner.get("case_id") or "")
        return ""

    async def on_tool_end(self, context: Any, agent: Any, tool: Any, result: Any = None) -> None:
        case_ref = self._case_ref(context)
        if not case_ref:
            return
        d = self.decisions.get(case_ref)
        name = getattr(tool, "name", None) or str(tool)
        ok = attest(self.hs, self.source, case_ref, name, arm=d.arm if d else None,
                    lever_id=d.lever_id if d else None, timeout=self.timeout)
        self.attested.append({"case_ref": case_ref, "tool": name, "sent": ok})

    # the rest of the RunHooks surface: no-ops that keep the SDK's calling convention
    async def on_agent_start(self, context: Any, agent: Any) -> None:
        return None

    async def on_agent_end(self, context: Any, agent: Any, output: Any) -> None:
        return None

    async def on_handoff(self, context: Any, from_agent: Any, to_agent: Any) -> None:
        return None

    async def on_tool_start(self, context: Any, agent: Any, tool: Any) -> None:
        return None


def is_coroutine_guardrail(g: Any) -> bool:
    fn = getattr(g, "guardrail_function", g)
    return inspect.iscoroutinefunction(fn)


__all__ = ["decide_input_guardrail", "AttestHooks", "TRIP_ROUTES", "is_coroutine_guardrail"]
