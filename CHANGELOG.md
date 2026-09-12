# Changelog

## 2.3.0 — unreleased

The half of the loop the engine cannot do for you: whether ROUTING on the band helped. New
public API, hence a minor bump.

- **`Ledger.evidence()`** — acted vs control, WITHIN the act band, with the engine's own floors
  (30 per cell, `small_n` under 100) and a Newcombe interval on the difference. This is not a
  convenience wrapper over `hs_action_evidence`: that tool splits on lever ATTESTATION, so a
  routing decision, which has no `lever_token`, never reaches its acted cell — and everything
  else, including refused rows, escalated rows and your own control arm, lands in its comparison
  arm. The treated cell here is every band-`act` run the loop acted on and did not hold out.
  Keying it on `action == "intercept"` would have left it permanently empty for every
  desirable-outcome loop, where a certified run is one to let PROCEED.
- **`Ledger.record_decision` / `append_decision`** write the six `hs_*` decision columns onto the
  run's row, which is what `evidence()` later reads; **`fit_rows()`** strips them again, because a
  model fitted on its predecessor's bands is learning its own echo. **`save` / `load`** are JSON
  Lines round trips through `append`, so a reloaded ledger is refused the same way a live one is.
- **`actionable(lever)`** — False when every change a lever asks for is on a `*_prior_n` or
  `*_prior_outcome_rate` feature. Measured on the sample corpus: the top-ranked run's lever read
  "decrease `agent_prior_n`" — a count of how many runs that agent has already done.
- **`hs report` / `hs evidence` / `hs drift`** close the loop from a shell. All three are free.
- **New skill `hs-governed-loop`** (five skills now), and two corrections to `hs-decision-loop`:
  stop only on `leak_guard` `status: "leakage_suspected"` (halting on a non-empty guard stops on
  almost every real table), and refit on YOUR cadence — "when drift says so" is circular, since
  the CUSUM cannot fire before four linked cycles.

Three claims in the skill were corrected against source before it shipped: the control-arm recipe
(the published hash is over `salt + 0x1f + run_id`, first four bytes — a `sha256(run_id) % 10000`
variant disagrees on about a quarter of ids), `trace@1` emitting two features per BOUND role
rather than a flat six, and the ranking Verdict listing 100 entities inline rather than binding
500.

## 2.2.3 — 2026-09-11

Fixes from a second review of the governed loop. Three of them raise where 2.2.2 did not
(**new refusal**); each was a wrong result, or a failure later where it cost more. One changes
priors 2.2.2 returned: a group cell pandas reads as NA is NULL.

- `gate()` sends a NaN, pandas `NA` or `NaT` cell as JSON `null`, which the engine reads as NULL.
  `json.dumps` wrote NaN as a bare `NaN` token, which is not JSON, so the product answered
  `422 invalid_request` ("The request body is not valid JSON.") on exactly the pandas rows 2.2.2's
  NaN-group fix covered; NA and NaT raised `TypeError`. Everywhere else (`score_batch`,
  `append_rows`, `upload_rows`) the client raises `ValueError` on a NaN before sending, rather than
  taking the server's 422: send `df.where(df.notna(), None)` on those paths.
- A group cell holding exactly one of pandas' default CSV NA strings (`''`, `NA`, `N/A`, `n/a`,
  `NULL`, `null`, `NaN`, `nan`, `None`, `<NA>`, `#N/A`, ... — `STR_NA_VALUES`) is NULL, as it is to
  the engine, which reads every fit table with `pd.read_csv` defaults. The ledger counted it as a
  group, so gate() scored other runs in it with real counts where the fit saw NULL. Matched
  exactly: `' NA'` and `'na'` stay groups.
- `parse_ts` reads pandas `NaT` as NULL. NaT is a `datetime` subclass, so it came back as a time,
  and `Ledger.append` took a NaT-timed row and counted it as an earlier peer in every other run's
  priors; the engine drops a NULL-time row before any window. `append` now refuses it
  (**new refusal**), and `priors()` gives NULL for a NaT-timed run.
- A NaN or pandas NA outcome is unknown (None), as `df.to_dict('records')` writes it for a run still
  in flight. The ledger refused it, so `extend()` on a ledger with unlabelled runs raised.
- `Ledger.extend` is all or nothing: every row is checked before any is written, and a `run_id`
  repeated inside the batch is refused. A refused batch kept the rows before the bad one, so
  re-running the corrected batch failed on the first of them as a duplicate.
- `era_lock` reads its rows once, so a generator or `map` works again (2.2.2 consumed it, then
  reported every feature absent), and raises `ValueError` on no rows (**new refusal**): graded over
  nothing, every condition was 'ok' and the pattern read as clean.
- `LoopSession` refuses a `run_id` the ledger already holds, or a `ts` it cannot parse, in its
  constructor, before `query()` starts (**new refusal**); both used to fail at `Stop`, after the
  run. An append refused at `Stop` (a run_id another session recorded after this one was built) is
  kept on `session.gate_error` with `recorded` False, so the documented check `decision is None and
  gate_error is not None` sees a run that was neither recorded nor gated.
- `LoopMiddleware` makes the same two refusals in `before_agent`, before `gate()` bills a decision
  and before the model runs. They came from `after_agent`'s append, after both.
- n8n 2.2.2: republishes the node so npm serves the corrected `examples/close-the-loop.json`
  (`meta.requires`, `meta.levers_on_this_sample`, the "Lever token minted?" node, and the 24-hour
  `ranking_ref` lifetime); npm's 2.2.1 still carries the old example. No node code changed.
- Docs: the 2.2.2 entry below said two of its fixes refuse input 2.2.1 accepted. There are three:
  `era_lock` refusing a condition whose feature is on none of the rows is one.

## 2.2.2 — 2026-09-11

Fixes from a review of the 2.2.0 loop. Three of them refuse input 2.2.1 accepted; all three refuse
input that was producing wrong results without saying so.

- `era_lock` raises `ValueError` when a condition's feature is on none of the rows
  (**new refusal**); `era_lock(pattern, ledger.rows)`, as the 2.2.1 README wrote it, now raises. The README
  and the package docstring passed `ledger.rows`, which carries no `_prior_*` features, so every
  condition on a prior graded 'ok' — `agent_prior_n > 97`, the pattern the check exists to catch,
  included. Both now pass `[ledger.with_priors(r) for r in ledger.rows]` and check `clock_like`
  as well as `era_locked`.
- `Ledger.append` refuses a `run_id` it already holds (**new refusal**). A second row stayed
  unlabelled forever, because `observe` labelled only the first, and reached the fit as a
  duplicate entity with a null outcome. Fill in a run's outcome with `observe`.
- `parse_ts` accepts an offset (`Z`, `+02:00`, `-0500`) only directly after `HH:MM:SS[.frac]`
  (**new refusal**). The engine reads `2026-03-04 10:00:00 +02:00`, `2026-03-04Z` and
  `2026-03-04T10:00Z` as NULL; the ledger accepted them, so OTHER runs were scored with priors the
  fit never saw.
- A NaN or pandas NA group value is NULL, as it is to the engine, not a group called `'nan'`.
- `Ledger` priors stay correct when a write lands while another thread builds a prior table
  (`LoopSession` computes priors in a worker thread): a cached table is tagged with the write
  generation it came from and never served after a later write.
- `LoopSession` records the run BEFORE gating, so the ledger row survives a gate that raises
  (an engine 4xx/5xx, a timeout, `MissingSafeguard`); the exception is kept on
  `session.gate_error`, because the Claude Agent SDK swallows hook exceptions.
- `LoopMiddleware` clears `hs_recorded` on every run it lets through, so on a checkpointed thread
  a run after an intercept is recorded instead of silently skipped.
- The client serialises `datetime`/`date` values as ISO-8601. The ledger accepts a `datetime` ts,
  and gate() died in `json.dumps` on it. Anything else unencodable still raises `TypeError`.
- The `claude-agent` extra needs `claude-agent-sdk>=0.1.26`, the first release with the
  `PostToolUseFailure` event `LoopSession` counts errors from.
- `__version__` lives in one module, `hunter_seeker/_version.py`, and the User-Agent is built from
  it; a test asserts it agrees with `pyproject.toml` and this file.
- Docs: `hs_action_evidence` splits reported outcomes into attested (compliant
  `hs_attest_action`) and everything else, with no pattern filter and no control input — the
  2.2.0 text said it compared acted with not-acted "within the same pattern", against the control
  arm. `control_arm` is for YOUR comparison; the engine does not read it, and `gate()` intercepts
  never reach its acted cell. `fetch_headers` works over MCP as well as REST.

## 2.2.1 — 2026-09-10

Text only; no behaviour change.

- `hs signup` no longer says a second signup would strand the first tenant's "reported outcomes".
  `hs signup` mints a `hsk_test_` key, which holds read scopes only and stays a test key after a
  claim, so its tenant has the model_refs it produced and nothing else to strand.

## 2.2.0 — 2026-09-10

Everything below landed after 2.1.2 was uploaded to PyPI (2026-09-08 18:23 UTC). PyPI versions
are immutable, so it ships as 2.2.0 — new modules, no breaking change.

- New `hunter_seeker.loop`: the governed loop over agent runs. `Ledger` computes the `trace@1`
  prior features at decision time — `hs_score_entity` does not run the reading and refuses a row
  without them (`422 row_not_scoreable: scorecard feature 'agent_prior_n' not found`) — with the
  reading's exact definition, pinned to `tests/fixtures/trace_priors_golden.json`, which the
  engine's own `readings/trace.py` generated. `control_arm` holds out a stable hashed slice so
  `hs_action_evidence` has a comparison. `decide`/`gate` read the band WITH its polarity: on an
  adverse outcome a certified row is a run to CATCH, on a desirable one a run to let through.
  `era_lock` grades a pattern's conditions against time, rebuilt from `operator` and
  `missing_values`, because the `_prior_n` emits are monotone counters and `agent_prior_n > 97`
  is a date filter wearing a feature's name.
  `Ledger.append` refuses a timestamp that is not ISO-8601 or epoch seconds/millis, rather than
  give a run priors that could disagree with the engine's.
- New `hunter_seeker.claude_agent.LoopSession` (`hunter-seeker[claude-agent]`): Claude Agent SDK
  hooks (`PreToolUse`, `PostToolUseFailure`, `Stop`) that build the ledger row from what the
  harness saw, record it at `Stop`, and gate the finished run off the event loop. Never returns
  `permissionDecision: "deny"` on the engine's say-so.
- New `hunter_seeker.langchain_middleware.LoopMiddleware` (`hunter-seeker[langchain-middleware]`,
  langchain >= 1.0): the DISPATCH gate as `before_agent` — on intercept the model never runs — and
  every run recorded exactly once. Tested inside a real `create_agent`.
- CI and the publish workflow install one `test` extra, which includes the real frameworks, so a
  release runs the adapter tests CI runs.
- `should_act(entity, run=envelope)` checks the RUN's `usability` before the row and raises
  `MissingSafeguard` when the run is not actionable; `usability_of` and `run_is_actionable` are
  exported.
- `hs signup` mints a samples-only key from the command line. The CLI stops losing stored keys,
  catches an obviously fake key before sending it, and says when `hs.yaml` is tracked by git
  without touching the user's `.gitignore`.

## 2.1.2 — 2026-09-08

A version bump is REQUIRED here, not cosmetic: the repo's content now differs from what PyPI
serves as 2.1.1, and a PyPI version is immutable.

- `hunter_seeker.__version__` now reports the real version. It read `2.0.0` through four releases
  while `pyproject.toml` and the User-Agent both said otherwise, so the published 2.1.1 reports
  itself as 2.0.0 to every caller that asks. `registry-installs-clean` now asserts the two agree.
- `rank_topk` accepts `outcome_is_desirable`, forwarded ONLY when stated. There was previously no
  way to state polarity from Python at all, so the engine fell back to guessing from the outcome
  column NAME — which it documents as unreliable, and a wrong guess inverts every lever direction.
- `rank_topk` accepts `offset`, so entities beyond the first page are reachable.
- `rank_topk(wait=True)` is bounded: `timeout_s` defaults to the engine's published 3,600s run
  ceiling. The loop previously had no deadline and no attempt cap, so a stalled task hung an
  unattended agent indefinitely.
- `rank_topk(on_progress=...)` surfaces each pending envelope, carrying `stage` and `facts_so_far`.
  Those were discarded on every iteration, which made a forty-minute run and a hung process look
  identical from Python. They are firewalled PROGRESS — report them, never quote them as a result.
- An empty `rows`/`csv` is a local `ValueError` instead of being silently dropped into an empty
  request body; a pending envelope with no `task_id` raises `HunterSeekerError`, not `KeyError`.
- New `hunter_seeker.safeguards`: `Band`, `Autonomy`, `should_act`, `ceiling`, `lever_helps`,
  `polarity_of`, `attestable`. Each RAISES rather than defaulting when the field it needs is
  absent — these fields exist to stop an action, and a default turns a missing stop signal into
  permission. `lever_helps` refuses without a polarity for that reason.
- `hs rank` / `hs sample` print an honest-empty properly. They printed three keys, one of which
  (`honest_empty`) is not a field of that response, so a refusal rendered as three nulls with every
  reason dropped — and then wrote `model_ref: null` into `hs.yaml`, aiming the next `hs score` at a
  null. `model_ref` is now persisted only when one came back.
- The LangChain and CrewAI adapters expose all 16 operations. They shipped 5 and 1, neither
  including `rank_topk`, so an agent built from either could never obtain the `model_ref` its own
  `score_entity` tool requires. `hs-surface-parity.mjs` gained a fourth leg and `--strict-python`.
- `hs-surface-parity.mjs` sets `process.exitCode` instead of calling `process.exit()`, which
  aborted Node on Windows and made every local run report 127 whether it passed or failed.
- New `hs signup`: one unauthenticated POST to `/v1/agents/register` mints a samples-only
  `hsk_test_` key and writes it to `hs.yaml`, so the five-minute test needs no account, no email
  and no card. It refuses to overwrite an existing key — a second registration would strand the
  first one's tenant, its `model_ref`s and its reported outcomes, and the raw key is shown once
  and stored nowhere else. `--force` says you meant it.
- `hs signup` no longer loses the key it just minted. The re-parse of an existing `hs.yaml` ran
  AFTER the registration call and raised on a comment line or an unquoted YAML scalar — so a `#`
  in that file meant the server minted a key, the CLI raised `IndexError`, and a credential shown
  exactly once was gone, leaving its tenant alive and permanently unreachable. The key is now
  printed before anything that can fail, and the write is atomic.
- `hs rank`, `hs score` and `hs verify` no longer crash on a hand-edited `hs.yaml`. They shared
  that same fragile parse, unguarded, on their hot path.
- `hs init` no longer deletes the key `hs signup` just wrote. It rewrote `hs.yaml` wholesale; it
  now carries `api_key`/`agent_id` forward while still dropping a stale `model_ref`, which was
  fitted on whatever dataset was configured before the call.
- One `_read_spec`/`_write_spec` pair replaces five ad-hoc parsers and writers of `hs.yaml`. The
  reader tolerates comments, blank lines and unquoted scalars, because `hs init` proposes and a
  human edits; the writer is atomic and keeps the user's comments.
- A credential is checked locally before it is sent. `HS_API_KEY` is stripped — a key pasted into
  CI or a `.env` arrives carrying a newline — and then matched against the published key shape
  (`hsk_live_`/`hsk_test_` plus 48 hex characters). A documentation placeholder is now named as
  one: previously it was sent, answered with a bare 401, and an agent read that as "my credentials
  were rejected" and retried. Every credential failure leaves by the CLI's existing
  `{error, detail, remedy}` door, because the caller is usually an agent parsing stderr.
- The README five-minute test and the Python quickstart use `hs signup` instead of handing out a
  pasteable fake key; `README.md` had carried a literal U+2026 in one. `python/README.md` showed
  `Client()`, which raises — the constructor requires a credential.
- `hs-surface-parity.mjs` honours `x-hs-surface-exempt`, declared on the operation in the spec.
  `register_agent` was failing four rules at once — the `/v1/<kebab>` naming rule, the live
  `tools/list` leg (latent: it only passes today because `HS_KEY` is usually unset), and n8n and
  Python adapter coverage. All four readings were correct and none of them should apply: it is the
  call you make BEFORE you hold a credential, and both "missing" surfaces are reached only by
  presenting one. Invariant 1 is amended to "every AUTHENTICATED operation" so the doc matches.
  The mechanism is built to resist rot: an exemption must name the rules it claims and carry a
  non-empty written reason or it FAILS rather than being honoured, an unknown rule name is an
  error rather than a silent no-op, an exempt surface prints as `exempt` and never as `yes`, and
  every exemption prints with its reason on every run.
  `scripts/hs-surface-parity.test.mjs` pins all of that with deliberate violations.
- `hs signup` says when `hs.yaml` is inside a git repository and not ignored, and never edits
  `.gitignore` itself. The note is deliberately not an alarm: the key it just wrote is a TEST key
  and committing it is harmless by design, so claiming a leak would be false — and false warnings
  are how real ones get ignored. What it says instead is the thing that is true later, at the only
  moment the user is looking at that file: this is also where a live key goes. Silent when git is
  absent, when there is no repository, or when the file is already ignored.
- `hs signup` flags a minted key that this client would refuse. The client requires the full
  57-character shape while the server accepts any `hsk_` prefix, so if the format ever moves,
  signup would otherwise write a key every later command rejects locally. It warns and still saves
  it: a key that cannot be used is recoverable, a key that was never written down is not.

## 2.0.0 — unreleased
- Python client for the full tool contract 2.0.0 (rank, score, verify, report, attest, evidence, drift, bundle).
- LangChain/LangGraph and CrewAI tool adapters; `hs` CLI with `init`, `rank`, `score`, `verify`, `sample`.
- n8n community node (unverified until published with provenance).
- Four Agent Skills.
- OpenAPI 3.1 contract pulled from the product; release is blocked by `scripts/check_spec.py` until placeholder schemas are replaced.
- `Client.verify` treats a missing or empty signature as `invalid_signature` (unsigned mode is dev-only on the server).
