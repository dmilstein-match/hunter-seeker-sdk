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

## 2.0.0 — unreleased
- Python client for the full tool contract 2.0.0 (rank, score, verify, report, attest, evidence, drift, bundle).
- LangChain/LangGraph and CrewAI tool adapters; `hs` CLI with `init`, `rank`, `score`, `verify`, `sample`.
- n8n community node (unverified until published with provenance).
- Four Agent Skills.
- OpenAPI 3.1 contract pulled from the product; release is blocked by `scripts/check_spec.py` until placeholder schemas are replaced.
- `Client.verify` treats a missing or empty signature as `invalid_signature` (unsigned mode is dev-only on the server).
