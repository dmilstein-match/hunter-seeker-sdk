"""Google ADK callbacks for the governed decision point. `pip install "hunter-seeker[adk]"`.

    from google.adk.agents import LlmAgent
    from hunter_seeker import Client
    from hunter_seeker.adk import decide_before_agent, attest_after_tool

    hs = Client(api_key=os.environ["HS_API_KEY"])
    agent = LlmAgent(
        name="refunds", model="gemini-2.5-flash", tools=[...],
        before_agent_callback=decide_before_agent(hs, "ag_...", case_from_context=my_case, fallback="none"),
        after_tool_callback=attest_after_tool(hs, "urn:my-runtime:refunds"),
    )

`decide_before_agent` runs ONCE before the agent's first model call: it asks `POST /v1/decide`
inside a two-second budget, writes the `RouteDecision` into `callback_context.state["hs_route"]`
(and `hs_decision` as a dict), and branches on ROUTE — `act` and `none` let the agent run;
`review` and `human` end the run before the model is called by returning a Content the harness
routes to a person (the receipt is on the state for it). Any error or timeout is the customer's
named fallback with its reason, never a raised exception and never a denial.

`attest_after_tool` runs after every tool: one `action.attested` CloudEvent with the tool NAME
only, carrying the `arm` and `lever_id` the receipt put on the state — the mechanical attestation
the evidence job keys on (never the tool's arguments or its result).

Both callbacks are plain callables; ADK's own types are imported lazily so this module loads
(and its tests run) without `google-adk`.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping, Optional

from .runtime import RouteDecision, attest, decide_case

CaseFromContext = Callable[[Any], Mapping[str, Any]]

STOP_ROUTES = ("review", "human")


def _content(text: str) -> Any:
    """A `types.Content` when google.genai is installed, else a plain dict of the same shape."""
    try:
        from google.genai import types  # type: ignore

        return types.Content(role="model", parts=[types.Part(text=text)])
    except Exception:  # noqa: BLE001 — the tests run without the package
        return {"role": "model", "parts": [{"text": text}]}


def decide_before_agent(hs: Any, agent_id: str, *, case_from_context: CaseFromContext,
                        fallback: str = "none", timeout: float = 2.0, mode: Optional[str] = None,
                        stop_on: tuple = STOP_ROUTES) -> Callable[[Any], Any]:
    """The `before_agent_callback`: decide, put the route on the state, end the run on a person's route."""

    def before_agent(callback_context: Any) -> Any:
        case = dict(case_from_context(callback_context))
        d = decide_case(hs, agent_id, case, fallback=fallback, timeout=timeout, mode=mode)
        state = getattr(callback_context, "state", None)
        if state is not None:
            state["hs_route"] = d.route
            state["hs_decision"] = d.as_dict()
            state["hs_arm"] = d.arm
            state["hs_lever_id"] = d.lever_id
            state["hs_case_ref"] = d.case_ref or str(case.get("case_id") or "")
        if d.route in stop_on:
            return _content(f"hs route {d.route}: this case goes to a person ({d.reason}); the receipt is on the state.")
        return None

    return before_agent


def attest_after_tool(hs: Any, source: str, *, timeout: float = 2.0) -> Callable[..., Any]:
    """The `after_tool_callback`: one attestation per tool call, the tool name only."""

    def after_tool(tool: Any, args: Any, tool_context: Any, tool_response: Any = None) -> Any:
        state = getattr(tool_context, "state", None) or {}
        case_ref = str(state.get("hs_case_ref") or "")
        name = getattr(tool, "name", None) or str(tool)
        if case_ref:
            attest(hs, source, case_ref, name, arm=state.get("hs_arm"), lever_id=state.get("hs_lever_id"),
                   timeout=timeout)
        return None  # never rewrites the tool's response

    return after_tool


def route_of_state(state: Mapping[str, Any]) -> Optional[RouteDecision]:
    """The decision `decide_before_agent` left on the state, or None."""
    d = state.get("hs_decision") if isinstance(state, Mapping) else None
    return RouteDecision(**d) if isinstance(d, Mapping) else None


__all__ = ["decide_before_agent", "attest_after_tool", "route_of_state", "STOP_ROUTES"]
