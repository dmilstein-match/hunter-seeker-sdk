---
name: hs-decision-loop
description: Use whenever an agent needs a defensible yes/no prediction over a table (who will churn, convert, default, fail) or must decide on ONE entity right now with a score it can prove it did not invent. Covers the full Hunter-Seeker loop — rank, score, act (in your stack), attest, report outcome, read evidence, check drift, refit — and the cost of each step. Not for continuous forecasts, time-series-only problems, or causal guarantees.
---

# The decision loop

Hunter-Seeker is a deterministic engine that finds the combination of conditions predicting a
yes/no outcome, scores every row, and REFUSES when nothing clears the bar. It signs every
answer. You bring the domain and the words; it brings the number.

**Rule you must never break:** never state a number, factor, or direction that a Hunter-Seeker
response does not contain. Rephrase; never author.

## The loop, in order

| Step | Tool | Cost |
|---|---|---|
| 1 Orient | `hs_describe_capabilities` — contract, limits, free sample datasets | free |
| 2 Supply | `hs_provide_dataset` — upload or public URL | free |
| 3 Rank | `hs_rank_topk` — entity column, outcome column, subject_kind | **one run** (refunded on honest-empty) |
| 4 Gate | `hs_model_quality` — stop if top_decile_lift < 1.5 or leak_guard is non-empty | free |
| 5 Understand | `hs_explain_drivers` (one joint pattern), `hs_explain_levers` (per entity) | free |
| 6 Carry | `hs_context_brief` — the portable brief for your own context | free |
| 7 Decide | `hs_score_entity(model_ref, row)` — one lead at a time | **one decision** |
| 8 Act | in YOUR stack, behind a human gate when band ≠ act or autonomy ≤ L2 | — |
| 9 Attest | `hs_attest_action(lever_token, post_value)` | free |
| 10 Report | `hs_report_outcome` — the real-world binary you observed | free |
| 11 Judge | `hs_action_evidence`, `hs_drift_status` | free |
| 12 Refit | `hs_rank_topk(refit_of: model_ref)` when drift says so | **one run** |

## Reading a Verdict

- `band`: `act` = the engine certifies this entity is likely to have the outcome; `escalate` =
  uncertain, ask a human and record their answer; `refuse` = the engine will not vouch (read
  `band_reason`). A band is a fact about likelihood, not advice.
- `verdict.outcome.polarity` tells you whether "likely" is good news (`desirable`) or bad
  (`adverse`). Decide the good/bad reading yourself; the engine does not.
- `max_autonomy`: L0 observe · L1 suggest · L2 act with approval first · L3 act then review.
  Never act above it.
- `principal_reasons`: up to four engine-ordered levers. Present them as "what the model
  associates with a different outcome", never as causes.
- Verify before you trust: `hs_verify_verdict` must say `valid`. `expired` means re-score.

## Honest-empty and refusals

An honest-empty is a real result: the data has no pattern that clears the bar. Report it as
such and do not retry. A `refuse` band bills nothing. Two consecutive honest-empties on a
refit mean the analysis should be abandoned, and `hs_drift_status` will say so.

## Person-level outcomes

If entities are people and the outcome is regulated (hiring, credit, education, insurance,
benefits, justice): set `subject_kind: "person"` and `acknowledge_decision_support: true`,
keep a human gate, and never present the score as the decision. `max_autonomy` will be at most L2.
