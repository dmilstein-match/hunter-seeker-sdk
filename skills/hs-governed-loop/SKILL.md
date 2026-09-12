---
name: hs-governed-loop
description: Use when an agent, a harness, or a swarm must decide per RUN whether to let a result through, catch it, or hand it to a human — and get measurably better at that over time. Covers the whole closed loop on Hunter-Seeker with no gaps: the one-row-per-run ledger, fitting with trace@1, computing the prior features at score time (the engine does NOT do this for you), the control arm, reading the band WITH its polarity, reporting observed outcomes, era-lock, refit_of, and reading evidence. Works over MCP alone or with the Python SDK. Not for one-off rankings of a table (hs-decision-loop) or for building the ledger from raw traces (hs-trace-audit).
---

# The governed loop over agent runs

One table, five calls, one rule. The table is yours. The calls are `hs_rank_topk`,
`hs_score_entity`, `hs_report_outcome`, and — free — `hs_action_evidence` and `hs_drift_status`.
The rule: **the outcome is what you observed, never what the agent said.**

If you have the Python SDK, `hunter_seeker.loop` does steps 3, 4 and 6 for you. If you only
have MCP, every step below tells you exactly what to compute yourself.

## 0. Credentials — an agent can do this alone

`POST https://hunter-seeker.io/api/v1/agents/register` with **no** Authorization header →
`hsk_test_…`. Runs the free samples only; touches no quota. The response's `claim_url` is how a
human later attaches the same key to a real workspace, keeping every `model_ref`.

**A test key reaches steps 1–4 and 6, not step 5.** Writing to the ledger needs the
`write:outcomes` scope, which a self-minted key never has: `hs_report_outcome` and
`hs_attest_action` answer `403 scope_required`. That scope comes from an OAuth session or from a
live key a workspace admin issues with "Can report outcomes" ticked. So demonstrate fit → score
→ route on `sample:agent_traces` for free, and expect the loop to close only once a human has
issued a key.

## 1. The ledger — one row per run

| column | rule |
|---|---|
| `run_id` | unique per run, **and never reused** — see the identity rule below |
| `ts` | ISO-8601 start time, with an offset (write `Z`). A run whose `ts` does not parse gets **NULL** priors, counted in `reading.report.group_null_rows` |
| `agent` | what produced the run: model × config × prompt version |
| `task` | task family, never the prompt text |
| `tool` | primary tool (optional) |
| telemetry | `steps`, `retries`, `elapsed_ms`, `tokens_in`, `tokens_out`, `errors`, `repeated_actions`, `hit_cap` — from the harness, not the transcript |
| `failed` | 0/1 **observed**; `None` until known. `hs_report_outcome` takes 0/1, true/false, yes/no and refuses anything else (`422 outcome_not_binary`) |

Never put on a row: anything known only after the outcome (decision latency, final status, the
agent's own "done"). `leak_guard` will flag it; do not wait for that.

**One id, everywhere.** The same string must identify a run in `hs_rank_topk`, `hs_score_entity`
(`entity_id`), `hs_report_outcome` and `hs_attest_action`. Nothing checks this: an id that never
appears in the ranking is accepted and quietly becomes its own subject in the evidence. A reused
id is worse — it can inherit another row's fit-time `principal_reasons` inside a signed verdict.

Floors: 500 labelled rows before the engine can hold any back. Below 500 the engine does **not**
refuse — it ranks and gates by bootstrap instead of a held-out slice (`validation.scheme` reads
`none` and `n_holdout` is null; the engine reports a STATE, never the technique, so do not look
for the word "bootstrap"),
and can still clear the bar and mint a `model_ref`. That is the trap: a table of pure noise a
couple of thousand rows long clears 1.5 far more often than feels possible. Start the loop at
~3,000 rows, and treat any fit below that as unjudged for routing whatever `usability` says.

## 2. Fit — one run of quota, on your cadence, always linked

```
hs_rank_topk({ data: { dataset_id },            # hs_provide_dataset + PUT, or hs_append_rows
  entity_column: "run_id", outcome_column: "failed", outcome_is_desirable: false,
  subject_kind: "event",
  reading: { kind: "trace", version: 1, roles: { identifier: "run_id", time_axis: "ts",
             outcome: "failed", agent: "agent", task: "task", tool: "tool" } },
  refit_of: "<previous model_ref>" })              # EVERY fit after the first
```

Then, the same day (the `ranking_ref` lives 24 h):

1. `usability` — `actionable` / `unjudged` / `refused`. Not actionable → keep the old
   `model_ref`, do not retry the identical call.
2. `leak_guard` — stop only on `status: "leakage_suspected"`. `excluded` is an id/time column
   and is routine; it is NOT a reason to stop.
3. `reading.report.group_null_rows` — rising numbers are a ledger bug.
4. `hs_explain_drivers` → the pattern. **Era-lock check**: `agent_prior_n`, `task_prior_n`,
   `tool_prior_n` only ever grow, so a condition that bounds one (`agent_prior_n > 97`,
   `task_prior_n <= 9`) is a date filter, not a finding. SDK: `era_lock(conditions, rows)`.
   MCP-only: for each numeric condition, compute the feature's firing rate per time-sextile over
   the fit rows; a rate that falls to ≤10 % of its first bin, or a feature with |Spearman ρ| >
   0.7 against `ts`, is era-locked. Do not route on that pattern.
5. `hs_model_quality`, `hs_context_brief` — free; file the brief.
6. The `drift` block (on the fit response when `refit_of` was passed; same as
   `hs_drift_status`). Engine rule, verbatim: `abandon` if ≥2 consecutive honest-empties;
   `refit` if the CUSUM fired AND the pattern changed, or the coefficient drifted across ≥2
   cycles; else `keep`. A pattern change alone is `keep`. Without `refit_of` on every fit this
   stays `no_prior` for ever.
7. **Adopt on `refit`, hold on `keep`.** `refit` → era-lock check this cycle's pattern, then
   swap the live `model_ref` to this cycle's. `keep` → keep serving the live ref. `abandon` →
   stop routing on this analysis. First fit → adopt if `actionable` and era-lock-clean. Either
   way, the next fit's `refit_of` is THIS cycle's ref, so the chain stays continuous.

**Adopting costs you your evidence.** Outcomes and attestations are scanned per `model_ref`, so
a new ref starts with an empty ledger and the 30-per-cell floor restarts from zero. The drift
chain survives a swap (it is keyed on the chain root); the evidence does not. That is the real
argument for holding on `keep`.

**Cadence is yours.** Hourly, daily, monthly — nothing here assumes time passed between fits.
Two consequences worth knowing: the CUSUM needs four linked cycles before it can fire at all, so
a monthly loop cannot see coefficient drift for four months; and a refit on unchanged data is
recorded as a cycle and marked redundant rather than dropped, so the clock still advances.

**`refit_of` is not optional.** In a loop the data changes every cycle, so the ref changes every
cycle, and only the runs you link get compared. A `404 model_ref_missing` on a ref you hold means
the engine will not serve that scorecard to you — refit now, do not retry. (Historically this has
also happened without any data change: before owned refs carried their tenant, callers ranking
identical bytes shared one ref, and the deploy that fixed that froze the old ones. Same remedy.)

## 3. Score a new run — one decision of quota

The scorecard reads the `trace@1` features off the row you send, and **the engine does not
compute them at score time**:

```
422 row_not_scoreable: scorecard feature 'agent_prior_n' not found in frame columns [...]
```

`trace@1` emits **two features per bound role** — `<role>_prior_n` and
`<role>_prior_outcome_rate` — so six only when `agent`, `task` and `tool` are all bound. Bind two
roles and there are four. You compute them, with this exact definition, from your ledger:

> For each bound role: take the labelled rows whose value equals this run's value **and** whose
> `ts` is **strictly earlier** than this run's `ts` (a same-instant run is not earlier).
> `<role>_prior_n` = their count. `<role>_prior_outcome_rate` = mean of `failed` over them,
> **NULL when the count is 0** (never 0.0). If this run's value for the role is missing, or its
> `ts` does not parse, both are NULL.

Compute every emitted feature even if the pattern uses two; the set changes on refit. SDK:
`Ledger.priors(row)` / `gate(...)` — pinned to a fixture the engine generated.

```
hs_score_entity({ model_ref, entity_id: run_id, subject_kind: "event",
                  row: { ...raw columns, ...the priors } })
→ { entity: { band, max_autonomy, principal_reasons }, verdict, signature }
```

For more than a few hundred runs a cycle, `hs_score_batch` (≤10,000 rows, one signature over all
of them). The ranking Verdict from step 2 lists its first **100** entities inline and covers the
rest — every decision unit the run emitted, up to the engine's cap of 500 — through
`score_set_hash`; `entities_total` says how many there are. Anything beyond that cap is not bound
by it, so score the population you actually route on.

## 4. Route — on the band, with its polarity, minus the control arm

**Control arm first.** Before reading the band, hold out a fixed slice:

> `bucket = int.from_bytes(sha256(f"{salt}\x1f{run_id}".encode()).digest()[:4], "big") % 10_000`,
> and the run is control when `bucket < round(fraction * 10_000)`. Default `fraction` 0.15,
> default `salt` the empty string.

Score it, record the band, **act as if the engine had said nothing**. The same ids fall in the
same slice for ever, on every machine. SDK: `control_arm(run_id)` — use it rather than
re-deriving, because a recipe that differs in the salt or the byte width picks a different 15 %.

Then read `verdict.outcome.polarity`:

| polarity | band `act` means | do |
|---|---|---|
| `adverse` (fitted on `failed`) | certified likely to **fail** | **intercept**: human, stronger model, no auto-approve |
| `desirable` (fitted on `succeeded`) | certified likely to **succeed** | **proceed** |
| either | `escalate` / `refuse` | your default policy; never cite the engine |

Respect `max_autonomy`: L0 record · L1 suggest · L2 act behind a human gate · L3 act and log. An
`act` at L2 is not permission to auto-approve. A missing band is not permission either — raise,
never default.

Keep `verdict` + `signature` on every decision. `hs_verify_verdict` (or the keyless REST
endpoint) is how anyone checks it later. Note the verdict's `expires_at` currently tracks the
model's 90-day handle, so an old verdict verifies as `expired` — the signature was still genuine;
archive the payload if you may need to show it later.

## 5. Report the outcome — free, when it lands

```
hs_report_outcome({ model_ref, outcomes: [
  { entity_id: run_id, outcome: 0|1, observed_at, event_id: run_id + ":outcome" } ] })
```

Every run, control arm included. `event_id` makes retries safe — but it is derived from
`observed_at`, so the same observation sent with two spellings of the timestamp writes two rows,
and a correction sent at the same timestamp is discarded as a duplicate (`written: 0`). Send one
canonical instant per observation. This never retrains anything; it is evidence.

## 6. Read the evidence — free

Two comparisons, and they are different:

- **Did a lever help?** If you changed a knob a lever named (`hs_explain_levers`) — a token
  budget, a tool — `hs_attest_action(lever_token, post_value)` after the change, then
  `hs_action_evidence(model_ref)`. Read what that compares: entities with a compliant
  attestation against **every other entity with a reported outcome under the model_ref** — no
  pattern filter and no control-arm input, so refused rows, escalated rows and your control arm
  are all in the comparison arm. It is observational; treat it as such.
  Ignore levers whose only change is on a `*_prior_n` / `*_prior_outcome_rate` feature — those
  are history, not knobs (SDK: `actionable(lever)`). Three traps, measured: `hs_explain_levers`
  silently OMITS an entity it has no lever for (ask for two, get one, no note); a lever with two
  `changes` carries ONE token, and `hs_attest_action` returns `compliant: false,
  dose_fraction: 0` with no reason if `post_value` is not what it expected — treat a silent
  `false` as "not evaluated"; and a `lever_token` exists only for entities in a ranking and only
  while that `ranking_ref` lives (24 h), so a run scored later cannot be attested at all.
- **Did routing help?** `hs_action_evidence` compares by lever attestation, and a routing
  decision has no lever — so this number is not in the engine. Compute it from your ledger: among
  band-`act` runs, the outcome rate of the ones you acted on vs the control arm, once each side
  has 30 labelled rows. SDK: `Ledger.evidence()`. MCP-only: two rates, their difference, and a
  Newcombe interval.

**How drift is actually judged.** Over the chain of fits you linked with `refit_of`: each fit is
a cycle, the engine records its calibration coefficient, and a CUSUM runs over that series —
`pattern` moved or not from cycle 2, the CUSUM can fire only after four cycles, `abandon` on two
consecutive honest-empties. The flag reflects the CURRENT state: a coefficient that recovers
drains it and the recommendation returns to `keep`. Reported outcomes do **not** feed drift (they
feed `hs_action_evidence`), so the engine cannot notice drift between fits — refit to ask.
`404 model_ref_expired` means the handle timed out; `404 model_ref_missing` means the engine will
not serve it to you — both mean refit now.

## Never

- Score a run without its priors, or with priors computed over runs at or after its `ts`.
- Zero-fill a prior rate. `0.0` means "never failed"; NULL means "never ran".
- Read `act` without `polarity`. On an adverse outcome it is the run to catch.
- Act on a control-arm run. Its whole value is that you didn't.
- Re-derive the control-arm hash from a description instead of the published recipe.
- Reuse a `run_id`, or report an outcome under an id that was never scored.
- Fit on rows that carry the loop's own decision columns. A model fitted on its predecessor's
  bands learns its own echo.
- Infer `failed` from the trace. Observe it.
