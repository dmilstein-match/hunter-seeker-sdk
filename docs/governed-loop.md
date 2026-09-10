# The governed loop over agent runs

*How to wire it, and the three things `hunter_seeker.loop` does for you. The tool-contract claims
here were checked against the product and engine source on 2026-09-10; the two traps in §3 and
§6 were found by running into them.*


The engine does not run your agents and does not retrain itself. It fits a signed,
reproducible scorecard on your run history, scores new runs into a band, and keeps a
ledger of what you did and what happened so it can tell you whether acting worked. **You**
own five small components. Together they are the loop.

```
                ┌──────────────────────────────────────────────────────────┐
                │  YOUR SIDE                                                │
                │                                                           │
   agents ───▶  │  (1) run ledger  ──▶ (2) fit job ──▶ model_ref + verdict  │
                │        ▲                                   │              │
                │        │                                   ▼              │
                │  (5) outcome reporter ◀── observe ◀── (3) score gate ──▶ (4) router
                │                                           │              │
                └───────────────────────────────────────────┼──────────────┘
                                                            │
                                     ENGINE  hs_rank_topk · hs_score_* · hs_report_outcome ·
                                             hs_attest_action · hs_action_evidence · hs_drift_status
```

---

## 0. Credentials, in the order you'll actually do it

1. **Dry run with no account.** `POST https://hunter-seeker.io/api/v1/agents/register` with no
   `Authorization` header returns an `hsk_test_…` key immediately (`hs signup` does this for
   you). It runs the free sample datasets only (`sample:agent_traces` is the one shaped like
   your problem), touches no quota, and is safe to print in a log. Your agent can mint this
   itself and exercise §2–§4 on the samples before a human is involved; §5–§6 write to the
   ledger, which a test key cannot (`403 scope_required`).
2. **Claim it.** The register response carries a `claim_url`. A human opens it, signs in,
   and the **same key** now runs against a workspace they own — every `model_ref` from the
   dry run is preserved. It is still a test key: samples only, read-only against the ledger.
3. **Issue the loop's live key.** A workspace admin issues one on any agent's **Scores & API**
   page; it is shown once. Tick **Can report outcomes** — that is the `write:outcomes` scope
   §5 and §6 need. A key without it is read-only against the ledger (`hs_report_outcome`
   answers `403 scope_required`), which is the right key for a gate that only scores.
4. **Machine vs human principal.** A machine key (`Authorization: Bearer hsk_…`) is for a
   loop with no human present. It never carries a human principal, so an `act` about a
   *person* tops out at `max_autonomy` L0 regardless of claiming. Agent runs are
   `subject_kind: "event"`, and that cap is keyed on `subject_kind: "person"` — but if your
   swarm ever scores a customer or an employee, it binds, and OAuth 2.1 is the path.

MCP is `https://hunter-seeker.io/api/mcp`. REST callers get the same operations under
`/api/v1/<tool>`, plus `fetch_headers` on dataset registration — read a private warehouse
export without publishing it; the MCP schema lists the field, but MCP clients cannot set it.
Public with no credential: `POST /api/v1/verify-verdict`, `GET /.well-known/jwks.json`, and
the `hs-verify` (pip) / `@hunter-seeker/verify` (npm) libraries that do the same check offline.

---

## 1. The run ledger — the only state you own

One row per agent run, append-only. This is the whole data contract:

| column | type | who writes it | note |
|---|---|---|---|
| `run_id` | string | runtime, at start | unique per run, not per agent |
| `ts` | ISO-8601 | runtime, at start | one parser, one format chain; a `ts` the engine can't parse gives that run **NULL** priors and is counted in `reading.report.group_null_rows`. `Ledger.append` refuses anything but ISO-8601 or epoch seconds/millis, so the priors you compute cannot silently disagree with the engine's |
| `agent` | string | runtime | model + config fingerprint, e.g. `claude-opus-5/tools-v3` |
| `task` | string | runtime | task family, not the prompt: `triage`, `pr-review`, `browse-and-extract` |
| `tool` | string | runtime | primary tool or integration |
| `steps`, `retries`, `elapsed_ms`, `tokens_in`, `tokens_out`, `errors`, `repeated_actions`, `hit_cap` | numeric / 0-1 | runtime, at end | telemetry — **required in practice**; on the sample corpus half the selected arms came from telemetry, and on SWE-bench the reading alone landed one arm short |
| `failed` | 0/1, nullable | **observer**, later | the observed binary. Null until known. Never the agent's self-report. |
| `control` | 0/1 | router | `hash(run_id)` → a fixed 15% — fixed forever, see §4 |
| `scored_model_ref`, `scored_band`, `scored_autonomy` | string | score gate | what the loop decided, for your own audit |

Anything — Postgres, a warehouse table, a CSV per day. The engine keeps none of it: a
`dataset_id` is single-use and the raw rows are dropped the moment its run completes.

**What "observed" means.** The ticket closed and stayed closed for 7 days. The PR merged
and the tests still pass on main. The customer did not write back within the horizon.
"The agent said it finished" is not an outcome; `hs_report_outcome` refuses anything but a
0/1 outcome, so this can't quietly become a transcript store.

---

## 2. The fit job — weekly, or every N runs

Runs on a schedule against rows whose `failed` is known. Floors: 500 rows before the
engine can hold any back (`min_rows_for_holdout`); 1,250 for `partitions: 2`. Close to the
floors the lift bar sits near the noise floor, so start the loop nearer 3,000.

```
# 1. ship the table (three doors, pick by your network)
hs_provide_dataset({})                          → { dataset_id, upload_url }
    PUT the CSV to upload_url                      no upload cap; ranking time grows about
                                                   linearly (250k rows ≈ 140 s, measured 2026-09-02)
hs_provide_dataset({ fetch_url })                → server pulls a public https CSV
                                                   (REST: + fetch_headers for a private one)
hs_append_rows({ chunk_index: 0, csv })          → sandboxed / no egress: ~1,500 rows a chunk,
    hs_append_rows({ dataset_id, chunk_index: 1, csv }) …   header row on every csv chunk

# 2. fit — the only call that costs a run
hs_rank_topk({
  data: { dataset_id },
  entity_column: "run_id",
  outcome_column: "failed",
  outcome_is_desirable: false,
  subject_kind: "event",
  reading: { kind: "trace", version: 1,
             roles: { identifier: "run_id", time_axis: "ts", outcome: "failed",
                      agent: "agent", task: "task", tool: "tool" } },
  refit_of: "<previous model_ref>"        # every fit after the first — see below
})
→ { status: "pending", task_id }
hs_poll_task({ task_id })                  # respect retry_after_ms
```

Then, in this order, **the same day** (the `ranking_ref` lives 24 h; the `model_ref` ~90 d):

1. **`usability`** — `actionable` / `unjudged` / `refused`. Not actionable → keep the old
   `model_ref`, log it, do not retry the identical call.
2. **`reading.report.group_null_rows`** — how many runs got null priors because `agent`,
   `task`, `tool` or `ts` was missing or unparsable. A number that grows is a ledger bug.
3. **`hs_explain_drivers`** → the pattern. **Run `era_lock` on it** before it goes live:
   `era_lock(pattern["conditions"], [ledger.with_priors(r) for r in ledger.rows])`.
   `trace@1` emits `agent_prior_n`, `task_prior_n`, `tool_prior_n` (one per bound role), and
   those only ever grow, so a condition that bounds one is a date filter. The sample corpus
   selected `agent_prior_n > 97`. The in-fit test needs no holdout.
4. **`hs_model_quality`**, **`hs_context_brief`** — file the brief; it is the whole
   analysis as one artifact and it costs nothing.
5. **`hs_drift_status({ model_ref })`** → `keep` / `refit` / `abandon`, and
   `pattern_diff` naming what moved. This is your alert, not your switch.
6. **Store** `model_ref`, the verdict, the signature, the brief. Swap the live `model_ref`
   if actionable and era-lock-clean.

**`refit_of` is not optional.** The engine counts every fit of an analysis but compares
only the ones you link. Measured: `cycles_observed: 19`, `pattern: "no_prior"` — nineteen
fits, zero drift history, because none named its predecessor.

**Cost.** One run per fit. Honest-empty and errors are refunded. Everything in steps 1–5
is free against the `ranking_ref`.

---

## 3. The score gate — synchronous, in your runtime

Where it sits depends on what you're gating: before a run is dispatched (route to a
model tier), before an auto-approve (merge, send, execute), or before a retry. One call:

```
hs_score_entity({
  model_ref, entity_id: run_id, subject_kind: "event",
  row: { run_id, ts, agent, task, tool,
         steps, retries, elapsed_ms, tokens_in, tokens_out, errors, repeated_actions, hit_cap,
         agent_prior_n, agent_prior_outcome_rate,        # ← you compute these; see the trap
         task_prior_n,  task_prior_outcome_rate,
         tool_prior_n,  tool_prior_outcome_rate }
})
→ { entity: { entity_id, score, band, band_reason, max_autonomy, principal_reasons },
    verdict, signature, billable_decisions }
```

One decision from quota per non-refused row. For a cycle of more than a few hundred runs,
or a nightly re-score, `hs_score_batch` takes up to 10,000 rows under one signature. (The
ranking Verdict from §2 lists its first 100 entities inline and covers the rest only through
`score_set_hash`; a batch score gives every NEW run its own band under one signature.)

### The trap: the reading does not run at score time

`trace@1` derives the prior features during the fit. `hs_score_entity` does not
re-derive them — it reads the scorecard's arm features off the row you send, and refuses
if one is missing. Verified:

```
row without agent_prior_n  →  422 row_not_scoreable
                              "scorecard feature 'agent_prior_n' not found in frame columns [...]"
row with the six priors    →  band act, max_autonomy L3, signed verdict
```

`hunter_seeker.loop.Ledger.priors` computes them with the reading's definition — over runs
**strictly earlier** than this one's `ts` (a same-instant peer is not an earlier run), for
the same `agent` / `task` / `tool` value, over rows whose outcome is known; `_n` is the
count, `_outcome_rate` the mean; a group with no earlier runs gets `_n = 0` and rate
**NULL**, not 0; a missing group value or unparsable `ts` gives NULL for both. Two features
per bound role — six with all three bound. It is pinned to a fixture the engine's own
`trace.run` generated, and `gate()` attaches them before scoring.

```python
from hunter_seeker import Ledger, gate
ledger = Ledger()                      # or Ledger(groups={"agent": "model_cfg", "task": "task_family"})
ledger.extend(labelled_rows)
d = gate(hs, model_ref, ledger, new_run, subject_kind="event")
```

---

## 4. The router — and the control arm

```python
d = gate(hs, model_ref, ledger, row)         # Decision
d.action      # "intercept" — adverse outcome, band act, ceiling permits: catch this run
              # "proceed"   — desirable outcome, band act, ceiling permits: let it run
              # "default"   — escalate, refuse, ceiling too low, or the control arm: YOUR policy
d.control     # True on the stable 15% held out by sha256(run_id) — scored, recorded, never acted on
d.verdict, d.signature, d.row_scored          # keep them
```

`decide()` raises `MissingSafeguard` rather than defaulting when band, ceiling or polarity is
absent — those fields exist to stop an action.

Read the polarity. On an adverse outcome, `act` is the run to *catch*. Fit `succeeded`
instead and `act` becomes "let it run" — both are fine, and a router that assumes one of
them is wrong on the other. `max_autonomy` (L0–L4) is how much rope this specific decision
earns; treat it as a ceiling on what the intercept may do unattended.

**The control arm is what makes the loop measurable.** Acting on the score destroys the
data the score needs: once a prediction causes a reroute, you stop observing what would
have happened. Exempt a fixed 10–20% of runs from the intervention, permanently, tagged in
the ledger. `hs_action_evidence` compares acted vs not-acted *within the same pattern* and
returns `live: null` until each cell has 30 rows, `small_n` under 100. No control arm, no
evidence — the loop runs blind while reporting confidence.

---

## 5. The outcome reporter — closes the loop

When the observed binary lands, however long that takes:

```
hs_report_outcome({ model_ref, outcomes: [
  { entity_id: run_id, outcome: failed, observed_at, event_id: run_id + ":outcome" } ]})
```

`event_id` is the idempotency key; the same id on retry writes once. Up to 10,000 per
call. This never retrains anything — it is evidence for `hs_action_evidence` and a drift
signal for `hs_drift_status`. Report **every** run, control arm included; the comparison
needs both sides.

Then, once cells fill: `hs_action_evidence({ model_ref })` → rates, n, difference, and a
Newcombe interval. `null` means not enough evidence yet, not zero effect.

---

## 6. The second loop — where "self-improving" actually happens

Everything above makes the *routing* track a changing pattern: which runs get
auto-approved shifts as the fitted pattern shifts. That is governed, but it is not the
agents getting better. The agents get better when you change their configuration on the
engine's levers and measure it against the control arm:

```
hs_explain_levers({ ranking_ref, entity_ids: [...] })
→ per lever: { changes: [{ feature, direction, … }], magnitude, likelihood_direction,
               lever_token (present only when minted), association_not_causal: true }
```

On the sample corpus the pattern was `tool=browser ∧ agent_prior_n>97 ∧
input_tokens≤2793 ∧ tool_prior_outcome_rate>0.0625`. The actionable lever there is
`input_tokens` — a context-budget knob you control. Change it for the acted arm, then:

```
hs_attest_action({ model_ref, entity_id, lever_token, acted_at, post_value })   # value AFTER the change
→ { compliant, dose_fraction }
```

Attest with the *new* value, after the change actually happened. The threshold never
crosses the wire; the engine says whether you crossed it and how far. Then
`hs_action_evidence` tells you whether runs you moved failed less than the control arm
that you didn't. That is the number that justifies keeping the change — and every lever
is labelled `association_not_causal`, which is why the control arm, not the lever, is the
evidence.

**Trap:** `likelihood_direction` is per lever and follows the polarity. On `failed`
(adverse) a lever reads `lower` — it moves the run *out* of the failing pattern. On
`succeeded` it reads `higher`. Read the field; do not assume.

---

## 7. Proof, for whoever has to sign off

Every fit and every score returns a verdict plus an Ed25519 signature over its RFC 8785
canonical form. Store both. Anyone — an approver, an auditor, another vendor's agent —
verifies with no account:

```
curl -X POST https://hunter-seeker.io/api/v1/verify-verdict \
     -H 'Content-Type: application/json' -d '{"verdict": …, "signature": …}'
→ { "status": "valid" | "invalid_signature" | "expired" | "unknown_key" }
```

or offline with `hs-verify` against `/.well-known/jwks.json`. `expired` means re-score,
never reuse. Pass the object as received; the verifier canonicalises it.

The verdict carries `core_hash` (what code computed it), `dataset_content_hash` and
`spec_hash` (what it was computed from). The engine's `GET /health` publishes the remaining
input: `numeric_env` — the BLAS kernel, thread count and numpy SIMD dispatch the floats were
computed on (live since 2026-09-10: Haswell, one thread, AVX-512 off). On the engine's own
hosts, equal inputs under that environment reproduce the scores byte for byte. A re-run
anywhere else — a laptop, another OS — should be compared on bands, patterns and ordering,
which did not move in any configuration measured.

---

## The minimum viable version, in one afternoon

1. Mint an `hsk_test_` key (`hs signup`). Run §2 against `sample:agent_traces` with
   `refit_of` omitted. Read `usability`, `group_null_rows`, drivers. Run the era-lock check.
   You will see `agent_prior_n > 97`. Good — now you know what it looks like.
2. Score one synthetic row with and without the priors. Watch the 422. Now your gate
   code knows what it has to compute.
3. Start writing the ledger from your real runtime today. Do nothing else for a month.
4. At 3,000 rows with known outcomes, issue a live key with outcome reporting (§0.3), fit for real, and turn on the gate
   with the control arm from the first request. Report every outcome.
5. First `hs_action_evidence` at ~200 acted rows. First lever change after that, not before.

What improves is which runs you let through, and — once you act on levers — how your
agents are configured. The scorecard itself never learns from its own decisions; that is
the property that lets you prove any of this to someone who wasn't in the room.
