# Worked example — an agentic GTM system on the Verdict layer

*Observe → Decide → Act → Learn, with six outcomes and four agents. Everything an agent
says about a customer here is copy. Every number comes from Hunter-Seeker and is signed.*

This page uses go-to-market vocabulary because it is familiar. Nothing in it is specific to
marketing: swap the six outcomes for collections, claims, or machine failure and every call
is the same.

---

## The rule the system is built around

Agents never author a score. An outreach agent that wants to know who to work today queries
Hunter-Seeker, or reads a Verdict that Hunter-Seeker already wrote into the CRM, and cites the
`verdict_id`. Research and copy are the agent's. *Who* and *why* are the engine's.

## The six outcomes

Each is one analysis — its own `analysis_id`, its own `model_ref`, its own drift history.

| Outcome column | Entity | Polarity | Refreshed |
|---|---|---|---|
| `converted` | lead | desirable | daily (PLG) / weekly (enterprise) |
| `activated` | account | desirable | weekly |
| `expanded` | account | desirable | monthly |
| `churned` | account | adverse | weekly |
| `replied` | contact | desirable | daily |
| `meeting_attended` | contact | desirable | weekly |

Polarity matters: on `churned`, `band: act` means *likely to churn*; on `converted` it means
*likely to convert*. Every Verdict carries `outcome.polarity` so no agent has to guess.

---

## 1 · Observe — make Hunter-Seeker the sensor

A thin pipeline (n8n, a warehouse job, or an ingest agent) maintains one feature table per
outcome: one row per entity, features that were knowable *before* the outcome, and a
timestamp so the engine can hold out time.

```
account_id, snapshot_at, pricing_views_30d, product_events_30d, sms_reply_latency_min,
tenure_days, last_touch_days, campaign_source, plan, seats, churned
```

Two shapes work. If your data is already one row per account, send it as is. If you only
have an **event log** (page views, emails, replies, logins), send the events with a `reading`
and the engine reduces them to one row per entity as of a cutoff, leakage-safe:

```json
{ "kind": "sequential", "version": 1,
  "roles": { "identifier": "account_id", "time_axis": "ts",
             "event_type": "event", "numeric_metric": "value" },
  "label": { "kind": "expr", "name": "converted",
             "predicate": { "event": "signup_completed", "within_days": 30 } } }
```

> `sequential@1` produces event counts, tenure, top event types, top transitions, and a
> numeric summary. It does not compute the latency *between* two event types ("replied to SMS
> within 5 minutes"); derive that column in the pipeline for now.

Two rules from `hs-observe`: the outcome column is the caller's binary, never inferred by the
engine; and any column completed *after* the outcome (`cancel_date`, `closed_lost_reason`) is
leakage — the leak guard will quarantine it and say why. Hash person-level ids before upload.

**The Discover call**, per outcome, on its cadence:

```json
hs_rank_topk({
  "data": { "dataset_id": "ds_gtm_churn_2026w35" },
  "entity_column": "account_id", "outcome_column": "churned",
  "subject_kind": "org", "horizon": "30 days",
  "refit_of": "mr1_…prior…"            // present from the second cycle on
})
```

What comes back, when the finding clears the bar:

- `entities[]` — the ranked list, each with `score`, `band`, `max_autonomy`
- `model_ref` (90 days) for decision-time scoring; `ranking_ref` (1 hour) for free interrogation
- `verdict` + `signature` — the signed record every downstream agent cites
- `leak_guard[]` — quarantined columns with plain-English reasons
- `drift` — because `refit_of` was passed: did the pattern change since last cycle

And what comes back when it doesn't: an **honest-empty** with reasons, no verdict, no
`model_ref`, and the run refunded. *That is an Observe signal.* "No churn pattern cleared 1.5×
this week" is a fact the whole system reacts to (§4).

Then, free, as often as needed:

```
hs_model_quality({ ranking_ref })     → stop if top_decile_lift < 1.5 or leak_guard non-empty
hs_explain_drivers({ ranking_ref })   → the ONE joint pattern
hs_context_brief({ ranking_ref })     → the portable brief for the orchestrator's context
```

The pattern comes back structured, for the agent to phrase as one unit:

> "Accounts with two or more pricing views in 30 days, an SMS reply latency under five
> minutes, and fewer than four seats, *together*, convert at 12× the base rate."

The `12×` is `pattern.lift`, the engine's number. The conditions carry `operator` and
`missing_values`; the campaign agent builds its audience filter from those, not from the
English direction word.

---

## 2 · Decide — one lead at a time

Batch ranking tells the team who to work today. Agents work one entity at a time, so the
outreach agent scores at the moment of decision:

```json
hs_score_entity({
  "model_ref": "mr1_8c2e…", "entity_id": "acct_4419",
  "row": { "pricing_views_30d": 3, "product_events_30d": 41, "sms_reply_latency_min": 4,
           "tenure_days": 210, "last_touch_days": 2, "campaign_source": "webinar",
           "plan": "basic", "seats": 3 },
  "subject_kind": "org"
})
```

```json
{ "entity": { "entity_id": "acct_4419", "score": 0.838, "band": "act",
              "band_reason": "certified", "max_autonomy": "L3",
              "principal_reasons": [
                { "feature_label": "seats", "direction": "increase", "magnitude": "notable",
                  "likelihood_direction": "higher", "association_not_causal": true },
                { "feature_label": "pricing_views_30d", "direction": "increase",
                  "magnitude": "slight", "likelihood_direction": "higher",
                  "association_not_causal": true } ] },
  "verdict": { "verdict_id": "01J6X…", "kind": "entity_score", "model_ref": "mr1_8c2e…",
               "outcome": { "column": "converted", "polarity": "desirable" }, "…": "…" },
  "signature": { "protected": "…", "signature": "…", "kid": "2026-q3" },
  "billable_decisions": 1 }
```

The band is a fact about likelihood; the autonomy hint is how much rope this decision earns.
`refuse` bills nothing and carries a reason (`low_likelihood`, `no_clearance`,
`validation_none`, `honest_empty`). Before anything downstream relies on it:

```
hs_verify_verdict({ verdict, signature })  → "valid"
```

---

## 3 · Act — the agents, and what each may do

| Agent | May | May not | The gate |
|---|---|---|---|
| **SDR / outreach** | pick from today's ranking or score the lead in front of it; write the email; research the account | choose an account outside the scored population; state a number the Verdict does not contain | acts at `max_autonomy`; on `escalate` a human sees the Verdict beside the draft |
| **Campaign optimiser** | use `pattern.conditions` as the audience definition; test creative and channel | invent a segment; reorder or drop a condition | audience filters are built from `operator` + `missing_values` |
| **CS / expansion** | work the `churned` and `expanded` rankings; use `principal_reasons` and levers as the starting point for a play | present a lever as a cause or a promise | `subject_kind` "org" here; if contacts are people, `L2` at most |
| **QA / governance** | verify every Verdict, attach `verdict_id` to any customer-facing or spend action, pull `hs_export_bundle` on dispute | approve an action whose Verdict fails verification or has expired | this agent is the last step before the outbox |

The Verdict travels with the action:

```json
{ "action": "send_sequence", "account_id": "acct_4419",
  "provenance": { "verdict_id": "01J6X…", "model_ref": "mr1_8c2e…", "band": "act",
                  "max_autonomy": "L3", "kid": "2026-q3" } }
```

**Where the drafted play comes from.** On this channel the engine returns levers and
principal reasons; the play ("call — offer the annual plan") is copy, written by the CS agent
or by the operator's own playbook layer. The engine does not draft actions here.

**The human gate**, per framework, from `hs-act-faithfully`: LangGraph `interrupt({verdict,
signature, band, reasons})` before the action node (keep the call idempotent — the node
re-runs on resume); n8n IF `band == act` → send, ELSE Slack approval → Wait → send;
Agentforce topic instruction "if band is refuse do not propose; if escalate route to a
human; always attach verdict_id".

---

## 4 · Learn — close the loop with agent outcomes

Most agentic GTM systems "learn" by putting more text in a vector store. That is memory. The
learner here is the engine, and it learns only through two explicit steps.

**Attest what you did.** When the CS agent's play changes a feature the lever named:

```json
hs_attest_action({ "model_ref": "mr1_8c2e…", "entity_id": "acct_4419",
                   "lever_token": "lt_…", "post_value": 5,
                   "acted_at": "2026-09-02T10:00:00Z" })
→ { "compliant": true, "dose_fraction": 0.67 }
```

**Report what happened.** When the real-world outcome lands — from the CRM webhook, the
billing system, the calendar:

```json
hs_report_outcome({ "model_ref": "mr1_8c2e…", "outcomes": [
  { "entity_id": "acct_4419", "outcome": 1, "observed_at": "2026-09-30",
    "event_id": "crm-evt-88213" } ] })
```

The outcome is the observed binary — never the agent's opinion, never read from the trace.
`event_id` makes retries safe. **Reporting never changes the model.** Outcomes are evidence.

**Read the evidence.** Weeks later:

```
hs_action_evidence({ model_ref })
→ live { rate_acted: 0.31, n_acted: 84, rate_not_acted: 0.19, n_not_acted: 212,
         diff: 0.12, ci_low: 0.02, ci_high: 0.22, small_n: true }
```

The run's own out-of-sample estimate lives in `hs_model_quality`; the two are never merged.
`live` is null until each cell has 30 rows; `small_n` until 100.

**Read the drift.** On every refresh:

```
hs_drift_status({ model_ref })
→ { pattern: "changed",
    pattern_diff: { conditions_added: ["plan"], conditions_removed: [],
                    thresholds_moved: [{ feature: "tenure_days", direction: "raised" }] },
    cusum_fired: true, recommendation: "refit" }
```

Labels and directions only. The orchestrator reacts to `recommendation`, not to a
coefficient it never sees. A pricing change or product launch shows up here first.

**Rediscovery replaces prompt-tweaking.** On `refit`, the next cycle's `hs_rank_topk(refit_of)`
finds the new pattern; the orchestrator retires the audience definitions built on the old
one and adopts the new `pattern.conditions`. On `abandon` (two consecutive honest-empties)
the system stops working that outcome until the data changes.

**Refusals are negative knowledge.** An honest-empty on `churned` this week means the CS
agent does not run the win-back sequence this week. A `refuse` band on an account means the
SDR does not call it. Both are recorded, both are cited.

---

## 5 · The Observe event bus

Everything the engine emits that the orchestrator should react to:

| Event | Source | Typical reaction |
|---|---|---|
| `run.completed` (cleared) | refresh | update rankings in CRM; refresh audiences from `pattern.conditions` |
| `run.honest_empty` | refresh | pause plays on that outcome; log negative knowledge |
| `verdict.drift` with `refit` | `hs_schedule_refresh` (Enterprise) or a refresh run | freeze old playbooks; force ICP review; refit |
| `verdict.drift` with `abandon` | two empties | stop working the outcome; escalate to a human |
| `evidence.updated` | ledger | report lift to the team; keep or drop the play |
| `escalate` band | any decision | route to a human; record the answer (it becomes a label) |

---

## 6 · Cadence and cost

| Step | Tool | Cost |
|---|---|---|
| Discover / refit, per outcome, per cycle | `hs_rank_topk` | one run (refunded on honest-empty) |
| Interrogate, brief, verify, evidence, drift, bundle | the rest | free |
| Decision-time scoring | `hs_score_entity` / `hs_score_batch` | one decision per non-refused row |

Six outcomes refreshed weekly is six runs a week. A thousand SDR decisions a day is a
thousand decisions. Verification is free forever, so the QA agent checks everything.

---

## 7 · What generalises, and what to change

Swap the table and this page is a collections system (`paid_in_full`, `promise_kept`,
`right_party_contact`), a claims desk (`fast_track_eligible`, `siu_referral`), or a fleet
(`failed_within_30d`). The constraints are the engine's, not the domain's: one binary
outcome per analysis, features knowable before the outcome, roughly a thousand rows or more,
an outcome rate between 2% and 98%, and timestamps for out-of-time holdout. It does not
predict continuous values, does multi-class only as one analysis per class, and never claims
causation.

Two tools proposed to make this page fully mechanical:

- `hs_find_analysis({ entity_column, outcome_column })` — the latest `model_ref` and drift for
  an outcome, so orchestrators don't carry refs between cycles.
- `hs_export_outcomes({ model_ref })` — the ledger as CSV, so the next feature snapshot picks
  up reported labels without a warehouse join written by hand.

Until they ship, the orchestrator stores `model_ref` per outcome and the pipeline joins
outcomes from the CRM directly.
