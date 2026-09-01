"""LangChain / LangGraph tools. `pip install hunter-seeker[langchain]`.

    from hunter_seeker.langchain import verdict_tools
    tools = verdict_tools(Client(api_key=...))

The approval-gate pattern (LangGraph):

    def gate(state):
        v = hs.score_entity(state["model_ref"], state["row"], subject_kind="person",
                            acknowledge_decision_support=True)
        if v["entity"]["band"] != "act":
            decision = interrupt({"verdict": v["verdict"], "signature": v["signature"],
                                  "band": v["entity"]["band"], "reasons": v["entity"]["principal_reasons"]})
        ...

interrupt() re-runs the node on resume: pass the same idempotency_key to rank_topk, and
score_entity is idempotent, so a resumed node never double-bills.
"""
from __future__ import annotations

from typing import Any, Dict, List

from .client import Client


def verdict_tools(hs: Client) -> List[Any]:
    try:
        from langchain_core.tools import tool
    except ImportError as e:  # pragma: no cover
        raise ImportError("pip install langchain-core") from e

    @tool
    def hs_score_entity(model_ref: str, row: Dict[str, Any], subject_kind: str,
                        acknowledge_decision_support: bool = False, entity_id: str | None = None) -> Dict[str, Any]:
        """Score ONE row against a fitted scorecard (model_ref from a cleared hs_rank_topk). Costs one decision. Returns score, band (act|escalate|refuse), max_autonomy (L0-L4), up to four principal_reasons, and a signed Verdict. Never reconstruct thresholds; read band. person-level requires acknowledge_decision_support=True."""
        return hs.score_entity(model_ref, row, subject_kind=subject_kind, entity_id=entity_id,
                               acknowledge_decision_support=acknowledge_decision_support)

    @tool
    def hs_verify_verdict(verdict: Dict[str, Any], signature: Dict[str, str]) -> str:
        """Free, keyless. Returns valid | invalid_signature | expired | unknown_key. An expired verdict is re-scored, never reused."""
        return hs.verify(verdict, signature)

    @tool
    def hs_report_outcome(model_ref: str, entity_id: str, outcome: bool, observed_at: str, event_id: str | None = None) -> Dict[str, Any]:
        """Free. Report the REAL-WORLD binary outcome you observed for an entity you scored. Idempotent by event_id. Never changes the model."""
        o: Dict[str, Any] = {"entity_id": entity_id, "outcome": outcome, "observed_at": observed_at}
        if event_id: o["event_id"] = event_id
        return hs.report_outcome(model_ref, [o])

    @tool
    def hs_action_evidence(model_ref: str) -> Dict[str, Any]:
        """Free. Did acting on this pattern work? Returns holdout and live blocks (never merged); live is null below the statistical floor."""
        return hs.action_evidence(model_ref)

    @tool
    def hs_drift_status(model_ref: str) -> Dict[str, Any]:
        """Free. Has the pattern changed since the prior run? recommendation keep | refit | abandon. Never diff two briefs yourself."""
        return hs.drift_status(model_ref)

    return [hs_score_entity, hs_verify_verdict, hs_report_outcome, hs_action_evidence, hs_drift_status]
