# Changelog

## 2.1.2 — unreleased

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
