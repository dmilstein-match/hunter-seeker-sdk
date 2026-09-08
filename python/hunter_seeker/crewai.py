"""CrewAI tools. `pip install hunter-seeker[crewai]`. Or point CrewAI at the MCP server:
    Agent(..., mcps=["https://hunter-seeker.io/api/mcp#hs_score_entity"])

`verdict_tools(hs)` returns ALL SIXTEEN operations. This module used to expose exactly one -
hs_score_entity - which is not a thin surface, it is an unusable one: the model_ref that tool
requires as its first argument can only come from hs_rank_topk, so nothing built from this file
could ever call the tool it shipped.

The tools are built from one table rather than sixteen hand-written classes. That is deliberate:
the failure this file is recovering from is a surface that drifted from the client behind it, and
a table that is walked once cannot drift the way sixteen near-identical copies can.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Type

from .client import Client


def _specs(hs: Client) -> List[tuple]:
    """(name, description, {field: (type, default)}, fn). `...` as a default means required."""
    return [
        ("hs_describe_capabilities",
         "Free. The input contract, limits, reading kinds and free sample dataset ids. Call this "
         "when you are unsure whether the problem is a yes/no ranking problem or how to shape the input.",
         {},
         lambda: hs.describe_capabilities()),

        ("hs_provide_dataset",
         "Free; no run starts. Register a larger dataset and get a dataset_id for hs_rank_topk.",
         {"fetch_url": (Optional[str], None), "name": (Optional[str], None)},
         lambda fetch_url=None, name=None: hs.provide_dataset(fetch_url=fetch_url, name=name)),

        ("hs_append_rows",
         "Free; no run starts. Send a large table in chunks over this same connection. Open on "
         "chunk 0, then pass the returned dataset_id to hs_rank_topk.",
         {"rows": (List[Dict[str, Any]], ...), "chunk_index": (int, ...),
          "dataset_id": (Optional[str], None)},
         lambda rows, chunk_index, dataset_id=None: hs.append_rows(rows, chunk_index, dataset_id=dataset_id)),

        ("hs_rank_topk",
         "Costs ONE RUN - the only tool that does. Rank rows by likelihood of a binary outcome. "
         "Returns ranked entities with bands, a model_ref for decision-time scoring, and a signed "
         "Verdict. Below the lift bar it returns {result: 'none', reasons} - a real answer, not a "
         "failure: relay the reasons and do not retry. State outcome_is_desirable when you know it; "
         "left out, the engine guesses from the outcome column NAME and a wrong guess inverts every "
         "lever direction.",
         {"entity_column": (str, ...), "outcome_column": (str, ...), "subject_kind": (str, ...),
          "dataset_id": (Optional[str], None), "rows": (Optional[List[Dict[str, Any]]], None),
          "csv": (Optional[str], None), "fetch_url": (Optional[str], None), "k": (int, 20),
          "outcome_is_desirable": (Optional[bool], None), "horizon": (Optional[str], None),
          "acknowledge_decision_support": (bool, False),
          "reading": (Optional[Dict[str, Any]], None), "refit_of": (Optional[str], None),
          "idempotency_key": (Optional[str], None)},
         lambda **kw: hs.rank_topk(**kw)),

        ("hs_poll_task",
         "Free. Check a long-running ranking. Returns status 'pending' (respect retry_after_ms; do "
         "not tight-loop) or the completed envelope. Pending progress is leak-firewalled: report it, "
         "never quote it as a result.",
         {"task_id": (str, ...)},
         lambda task_id: hs.poll_task(task_id)),

        ("hs_model_quality",
         "Free. Diagnostics for a ranking, to judge how far to trust it BEFORE acting. Stop if "
         "top_decile_lift is null or below 1.5, or if any leak_guard entry has status "
         "'leakage_suspected'. A status of 'excluded' is a routine identifier or date column and is "
         "NOT a reason to stop.",
         {"ranking_ref": (str, ...)},
         lambda ranking_ref: hs.model_quality(ranking_ref)),

        ("hs_explain_drivers",
         "Free. THE PATTERN behind a ranking: the conditions that TOGETHER predict the outcome. Read "
         "them as one joint profile, never as independent per-feature effects.",
         {"ranking_ref": (str, ...)},
         lambda ranking_ref: hs.explain_drivers(ranking_ref)),

        ("hs_explain_levers",
         "Free. Per-entity minimal changes, each with the direction it moves PREDICTED LIKELIHOOD. "
         "Read likelihood_direction PER LEVER; whether 'lower' is what you want depends on the "
         "outcome's polarity, which you hold and the engine does not. Also the ONLY source of the "
         "lever_token hs_attest_action requires - the field is absent when none was minted, and an "
         "empty lever list is legitimate even on a strongly-cleared ranking.",
         {"ranking_ref": (str, ...), "entity_ids": (List[str], ...)},
         lambda ranking_ref, entity_ids: hs.explain_levers(ranking_ref, entity_ids)),

        ("hs_context_brief",
         "Free. The whole analysis as one portable artifact, to hand to another agent or file for later.",
         {"ranking_ref": (str, ...)},
         lambda ranking_ref: hs.context_brief(ranking_ref)),

        ("hs_score_entity",
         "Score one row against a fitted scorecard; costs one decision. Returns score, band "
         "(act|escalate|refuse), max_autonomy, principal_reasons and a signed Verdict. Read band; "
         "never reconstruct thresholds. Person-level requires acknowledge_decision_support=True. "
         "Supply every column the analysis used; extras are ignored, a missing one is refused by name.",
         {"model_ref": (str, ...), "row": (Dict[str, Any], ...), "subject_kind": (str, ...),
          "acknowledge_decision_support": (bool, False), "entity_id": (Optional[str], None)},
         lambda model_ref, row, subject_kind, acknowledge_decision_support=False, entity_id=None:
             hs.score_entity(model_ref, row, subject_kind=subject_kind, entity_id=entity_id,
                             acknowledge_decision_support=acknowledge_decision_support)),

        ("hs_score_batch",
         "Costs one decision PER ROW. The same fitted scorecard as hs_score_entity, on many rows.",
         {"model_ref": (str, ...), "rows": (List[Dict[str, Any]], ...), "subject_kind": (str, ...),
          "acknowledge_decision_support": (bool, False)},
         lambda model_ref, rows, subject_kind, acknowledge_decision_support=False:
             hs.score_batch(model_ref, rows, subject_kind=subject_kind,
                            acknowledge_decision_support=acknowledge_decision_support)),

        ("hs_verify_verdict",
         "Free, keyless. Returns valid | invalid_signature | expired | unknown_key. An expired "
         "verdict is re-scored, never reused.",
         {"verdict": (Dict[str, Any], ...), "signature": (Dict[str, str], ...)},
         lambda verdict, signature: hs.verify(verdict, signature)),

        ("hs_attest_action",
         "Free. Record that you pulled a lever, using the lever_token from hs_explain_levers and the "
         "entity's NEW value for that feature. This is what lets hs_action_evidence compare acted "
         "against not-acted entities. Attest AFTER the change happened, and pass the new value.",
         {"model_ref": (str, ...), "entity_id": (str, ...), "lever_token": (str, ...),
          "post_value": (Any, ...), "acted_at": (str, ...), "event_id": (Optional[str], None)},
         lambda model_ref, entity_id, lever_token, post_value, acted_at, event_id=None:
             hs.attest_action(model_ref=model_ref, entity_id=entity_id, lever_token=lever_token,
                              post_value=post_value, acted_at=acted_at, event_id=event_id)),

        ("hs_report_outcome",
         "Free. Report the REAL-WORLD binary outcome you observed for an entity you scored. "
         "Idempotent by event_id. Never changes the model.",
         {"model_ref": (str, ...), "entity_id": (str, ...), "outcome": (bool, ...),
          "observed_at": (str, ...), "event_id": (Optional[str], None)},
         lambda model_ref, entity_id, outcome, observed_at, event_id=None:
             hs.report_outcome(model_ref, [{k: v for k, v in
                                            {"entity_id": entity_id, "outcome": outcome,
                                             "observed_at": observed_at, "event_id": event_id}.items()
                                            if v is not None}])),

        ("hs_action_evidence",
         "Free. Did acting on this pattern work? Returns holdout and live blocks (never merged); "
         "live is null below the statistical floor.",
         {"model_ref": (str, ...)},
         lambda model_ref: hs.action_evidence(model_ref)),

        ("hs_drift_status",
         "Free. Has the pattern changed since the prior run? recommendation keep | refit | abandon. "
         "Never diff two briefs yourself.",
         {"model_ref": (str, ...)},
         lambda model_ref: hs.drift_status(model_ref)),
    ]


def verdict_tools(hs: Client) -> List[Any]:
    """Every operation the REST surface exposes, as CrewAI tools."""
    from crewai.tools import BaseTool  # type: ignore
    from pydantic import BaseModel, create_model

    tools: List[Any] = []
    for op_name, desc, fields, fn in _specs(hs):
        args_model = create_model(f"{op_name}_Args", **fields) if fields else create_model(f"{op_name}_Args")
        tools.append(type(
            f"HS_{op_name}",
            (BaseTool,),
            {
                # pydantic builds the model from this namespace and reads __module__ off it.
                "__module__": __name__,
                "__qualname__": f"HS_{op_name}",
                "__annotations__": {"name": str, "description": str, "args_schema": Type[BaseModel]},
                "name": op_name,
                "description": desc,
                "args_schema": args_model,
                "_run": (lambda _fn: lambda self, **kw: _fn(**kw))(fn),
            },
        )())
    return tools


def score_entity_tool(hs: Client):
    """The original single-tool factory, kept so existing code does not break."""
    return next(t for t in verdict_tools(hs) if t.name == "hs_score_entity")
