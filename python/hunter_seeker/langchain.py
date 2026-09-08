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

interrupt() re-runs the node on resume: pass the same idempotency_key to hs_rank_topk, and
score_entity is idempotent, so a resumed node never double-bills.

verdict_tools() returns ALL SIXTEEN operations. It used to return five - the decision half only -
which meant an agent built from this file could never obtain the model_ref hs_score_entity
requires, nor the lever_token hs_attest_action requires, and so could not run the loop this very
docstring describes. The n8n node shipped with the same shape of gap and the repo made it a red
build; scripts/hs-surface-parity.mjs now covers this file too.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .client import Client


def verdict_tools(hs: Client) -> List[Any]:
    try:
        from langchain_core.tools import tool
    except ImportError as e:  # pragma: no cover
        raise ImportError("pip install langchain-core") from e

    # ── the analysis half ──────────────────────────────────────────────────────────────────────

    @tool
    def hs_describe_capabilities() -> Dict[str, Any]:
        """Free. The input contract, limits, reading kinds, and the free sample dataset ids. Call this first when you are unsure whether the user's problem is a yes/no ranking problem or how to shape the input."""
        return hs.describe_capabilities()

    @tool
    def hs_provide_dataset(fetch_url: Optional[str] = None, name: Optional[str] = None) -> Dict[str, Any]:
        """Free; no run starts. Register a larger dataset and get back a dataset_id to pass to hs_rank_topk."""
        return hs.provide_dataset(fetch_url=fetch_url, name=name)

    @tool
    def hs_append_rows(rows: List[Dict[str, Any]], chunk_index: int,
                       dataset_id: Optional[str] = None) -> Dict[str, Any]:
        """Free; no run starts. Send a large table in chunks over this same connection, so no other network access is needed. Open on chunk 0, then pass the returned dataset_id to hs_rank_topk."""
        return hs.append_rows(rows, chunk_index, dataset_id=dataset_id)

    @tool
    def hs_rank_topk(entity_column: str, outcome_column: str, subject_kind: str,
                     dataset_id: Optional[str] = None, rows: Optional[List[Dict[str, Any]]] = None,
                     csv: Optional[str] = None, fetch_url: Optional[str] = None, k: int = 20,
                     outcome_is_desirable: Optional[bool] = None, horizon: Optional[str] = None,
                     acknowledge_decision_support: bool = False,
                     reading: Optional[Dict[str, Any]] = None, refit_of: Optional[str] = None,
                     idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        """Costs ONE RUN - the only tool that does. Rank rows by likelihood of a binary outcome; returns ranked entities with bands, a model_ref for decision-time scoring, and a signed Verdict. Below the lift bar it returns {result: "none", reasons} - a real answer, not a failure: relay the reasons and do not retry. State outcome_is_desirable when you know it; leave it out and the engine guesses from the outcome column NAME, and a wrong guess inverts every lever direction. Pass the same idempotency_key when resuming an interrupted node so a retry never double-bills."""
        return hs.rank_topk(entity_column=entity_column, outcome_column=outcome_column,
                            subject_kind=subject_kind, dataset_id=dataset_id, rows=rows, csv=csv,
                            fetch_url=fetch_url, k=k, outcome_is_desirable=outcome_is_desirable,
                            horizon=horizon,
                            acknowledge_decision_support=acknowledge_decision_support,
                            reading=reading, refit_of=refit_of, idempotency_key=idempotency_key)

    @tool
    def hs_poll_task(task_id: str) -> Dict[str, Any]:
        """Free. Check a long-running ranking. Returns status "pending" (respect retry_after_ms; do not tight-loop) or the completed envelope. A pending response may carry leak-firewalled progress: report it, never quote it as a result."""
        return hs.poll_task(task_id)

    @tool
    def hs_model_quality(ranking_ref: str) -> Dict[str, Any]:
        """Free. Diagnostics for a ranking, to judge how far to trust it BEFORE acting: top_decile_lift, calibration_error, validation shape, lift curve, leak_guard. Stop if top_decile_lift is null or below 1.5, or if any leak_guard entry has status "leakage_suspected". A status of "excluded" is a routine identifier or date column and is NOT a reason to stop."""
        return hs.model_quality(ranking_ref)

    @tool
    def hs_explain_drivers(ranking_ref: str) -> Dict[str, Any]:
        """Free. THE PATTERN behind a ranking: the combination of conditions that TOGETHER predict the outcome. Read the conditions as one joint profile, never as independent per-feature effects, and never rank them against each other."""
        return hs.explain_drivers(ranking_ref)

    @tool
    def hs_explain_levers(ranking_ref: str, entity_ids: List[str]) -> Dict[str, Any]:
        """Free. Per-entity minimal changes, each with the direction it moves PREDICTED LIKELIHOOD. Read likelihood_direction PER LEVER: it is a fact, not a recommendation, and whether "lower" is what you want depends on the outcome's polarity (verdict.outcome.polarity), which you hold and the engine does not. This is also the ONLY source of the lever_token hs_attest_action requires; the field is absent when the engine minted none, and an empty lever list is a legitimate answer even on a strongly-cleared ranking."""
        return hs.explain_levers(ranking_ref, entity_ids)

    @tool
    def hs_context_brief(ranking_ref: str) -> Dict[str, Any]:
        """Free. The whole analysis as one portable artifact, to hand to another agent or file for later."""
        return hs.context_brief(ranking_ref)

    # ── the decision half ──────────────────────────────────────────────────────────────────────

    @tool
    def hs_score_entity(model_ref: str, row: Dict[str, Any], subject_kind: str,
                        acknowledge_decision_support: bool = False,
                        entity_id: Optional[str] = None) -> Dict[str, Any]:
        """Score ONE row against a fitted scorecard (model_ref from a cleared hs_rank_topk). Costs one decision. Returns score, band (act|escalate|refuse), max_autonomy (L0-L4), up to four principal_reasons, and a signed Verdict. Never reconstruct thresholds; read band. person-level requires acknowledge_decision_support=True. Supply every column the analysis used; extra columns are ignored and a missing one is refused by name."""
        return hs.score_entity(model_ref, row, subject_kind=subject_kind, entity_id=entity_id,
                               acknowledge_decision_support=acknowledge_decision_support)

    @tool
    def hs_score_batch(model_ref: str, rows: List[Dict[str, Any]], subject_kind: str,
                       acknowledge_decision_support: bool = False) -> Dict[str, Any]:
        """Costs one decision PER ROW. The same fitted scorecard as hs_score_entity, evaluated on many rows at once."""
        return hs.score_batch(model_ref, rows, subject_kind=subject_kind,
                              acknowledge_decision_support=acknowledge_decision_support)

    @tool
    def hs_verify_verdict(verdict: Dict[str, Any], signature: Dict[str, str]) -> str:
        """Free, keyless. Returns valid | invalid_signature | expired | unknown_key. An expired verdict is re-scored, never reused."""
        return hs.verify(verdict, signature)

    @tool
    def hs_attest_action(model_ref: str, entity_id: str, lever_token: str, post_value: Any,
                         acted_at: str, event_id: Optional[str] = None) -> Dict[str, Any]:
        """Free. Record that you pulled a lever, using the lever_token from hs_explain_levers and the entity's NEW value for that feature. This is what lets hs_action_evidence compare acted against not-acted entities. Attest AFTER the change actually happened, and pass the new value, not the old one."""
        return hs.attest_action(model_ref=model_ref, entity_id=entity_id, lever_token=lever_token,
                                post_value=post_value, acted_at=acted_at, event_id=event_id)

    @tool
    def hs_report_outcome(model_ref: str, entity_id: str, outcome: bool, observed_at: str,
                          event_id: Optional[str] = None) -> Dict[str, Any]:
        """Free. Report the REAL-WORLD binary outcome you observed for an entity you scored. Idempotent by event_id. Never changes the model."""
        o: Dict[str, Any] = {"entity_id": entity_id, "outcome": outcome, "observed_at": observed_at}
        if event_id:
            o["event_id"] = event_id
        return hs.report_outcome(model_ref, [o])

    @tool
    def hs_action_evidence(model_ref: str) -> Dict[str, Any]:
        """Free. Did acting on this pattern work? Returns holdout and live blocks (never merged); live is null below the statistical floor."""
        return hs.action_evidence(model_ref)

    @tool
    def hs_drift_status(model_ref: str) -> Dict[str, Any]:
        """Free. Has the pattern changed since the prior run? recommendation keep | refit | abandon. Never diff two briefs yourself."""
        return hs.drift_status(model_ref)

    # Every operation the REST surface exposes, which is what the parity gate checks.
    return [hs_describe_capabilities, hs_provide_dataset, hs_append_rows, hs_rank_topk,
            hs_poll_task, hs_model_quality, hs_explain_drivers, hs_explain_levers,
            hs_context_brief, hs_score_entity, hs_score_batch, hs_verify_verdict,
            hs_attest_action, hs_report_outcome, hs_action_evidence, hs_drift_status]
