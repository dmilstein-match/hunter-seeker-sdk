# hunter-seeker-sdk — working rules

This repo is **every surface an integrator touches that is not the MCP server**: the Python client,
the CLI, the LangChain and CrewAI adapters, the n8n community node, the OpenAPI contract and the
Agent Skills. The engine's contract with the outside world is not the engine — it is these.

## The two invariants

**1. Every surface reaches every AUTHENTICATED operation.** A surface that covers part of the
contract is not a thin surface, it is a broken one. The n8n node shipped covering 5 of 15
operations, and the 5 did not include `attest_action` or `explain_levers` — so an integrator could
score and report but never attest, and never obtain the `lever_token` an attestation needs. The
governance loop the product exists to provide was unreachable from its own integration, and nothing
failed. The Python adapters then shipped in exactly the same shape (`langchain` 5 of 16, `crewai`
1) with zero tests, and the parity script had no leg that could see them.

`scripts/hs-surface-parity.mjs` now compares four surfaces — spec, live MCP, n8n node, Python
adapters — and CI runs it with `--strict-node --strict-python`.

The word "authenticated" is doing work. `register_agent` is the one operation you call BEFORE you
hold a credential, so it cannot be a gap in a credentialed workflow — which is the harm above. n8n
is configured through a stored `HunterSeekerApi` credential and the Python adapters take an
already-authenticated `Client`, so neither has a coherent place for it; Python does reach it, via
`hs signup`, which this script has no leg for. It is therefore exempt, and the exemption is
declared **on the operation in the spec** (`x-hs-surface-exempt`, generated from
`packages/mcp/scripts/build-openapi.mts` in the product repo) rather than as a list inside the
script — an exception belongs with the thing it excuses.

The mechanism is deliberately hard to abuse: an exemption must name the rules it claims
(`naming` · `mcp` · `n8n` · `python-adapters`) and carry a non-empty written reason, or it FAILS
rather than being honoured; an unknown rule name is an error, not a silent no-op; and every
exemption prints with its reason on every run. `scripts/hs-surface-parity.test.mjs` pins this with
deliberate violations — the same spec with the exemption removed must go red, and one operation's
exemption must not excuse another's gap. Do not add an exemption to make a gate green. There is
exactly one, and it took a written argument.

**2. What the registries serve equals what this repo says.** `hunter_seeker.__version__` read
`2.0.0` through four releases while `pyproject.toml` and the User-Agent said otherwise, so the
published package misreports itself to every caller that asks. `registry-installs-clean` installs
from PyPI and npm rather than the checkout and asserts they agree.

## Gates — every change

```
cd python && PYTHONPATH=. python -m pytest -q
cd n8n && npm ci && npm run build && npm test
node scripts/hs-surface-parity.mjs n8n/dist/nodes/HunterSeeker/HunterSeeker.node.js \
     --strict-node --strict-python
node --test scripts/hs-surface-parity.test.mjs
python scripts/check_spec.py
```

## Rules that are not style preferences

- **Never author a polarity the caller did not give.** `outcome_is_desirable` is forwarded only
  when stated, in the client and in the n8n node, and `bodies.test.mjs` pins the omission by name.
  Sending a default makes the engine's lever directions authoritative-looking and wrong: a lever
  reading `lower` is good news on churn and bad news on conversion. The same rule is why
  `safeguards.lever_helps` RAISES without a polarity instead of picking one.
- **A safeguard field that is absent must never default to permission.** `band`, `max_autonomy` and
  `likelihood_direction` all exist to stop an action. `hunter_seeker.safeguards` raises
  `MissingSafeguard` for each. An unbanded entity carries no `band` key at all — not null, not a
  default — so membership is the test, never truthiness.
- **An honest-empty is an ANSWER, not a failure.** `{result: "none", reasons, retry, guidance}` —
  there is no top-level `honest_empty` field and never has been. Route it somewhere the caller can
  see it (the n8n node gives it its own output; the CLI prints the reasons) and never retry it: the
  response says `retry: "unproductive"` because the identical call returns the identical result.
- **A cleared run can still carry `model_ref: null`.** Below the holdout floor the engine caches no
  scorecard, so the ranking is real and the decision tools are unavailable for it. Never persist a
  null `model_ref`; the next `score` call will fire at it.
- **Bound every wait.** `rank_topk(wait=True)` uses the engine's published 3,600s run ceiling. The
  loop previously had no deadline and no attempt cap. Surface `stage`/`facts_so_far` through
  `on_progress` rather than discarding them — but they are firewalled PROGRESS, so report them and
  never quote them as a result.

## Publishing

Both publish workflows are `workflow_dispatch`-only. PyPI versions are immutable: if the repo's
content differs from what a published version serves, the version must bump — that is what happened
to 2.1.1 once `__version__` was corrected.

Order matters: **release first, then land the registry gate**, which is correctly red until the
published artifact catches up.

## The OpenAPI spec is not authored here

`openapi/*.json` is generated from the product repo's tool schemas
(`packages/mcp/scripts/export-tool-schemas.mts`) and pulled by `scripts/pull_spec.sh`. Fix a tool
description in the product repo and regenerate; editing the copy here makes the two disagree, which
is the drift the parity gate exists to catch.
