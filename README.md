# hunter-seeker-sdk

> **Status: live.** `hunter-seeker` 2.1.2 and `hs-verify` 0.2.0 are on PyPI, `@hunter-seeker/verify`
> 0.2.0 is on npm, the remote MCP server at `https://hunter-seeker.io/api/mcp` is serving, and
> `/.well-known/jwks.json` publishes `kid: 2026-q3` — the key the shared `vectors.json` in
> hunter-seeker-verify is signed with. Each was checked on 2026-09-10; a pre-release notice sat
> here saying none of it was true.
>
> This checkout is **ahead of PyPI** (2.2.0, unreleased): `hs signup`, `should_act(run=...)`, the
> governed loop (`hunter_seeker.loop`) and the two harness adapters below are not in 2.1.2. Until
> 2.2.0 is published, install from this repo to use them.

Client libraries, the OpenAPI contract, framework adapters, and Agent Skills for the
**Hunter-Seeker Verdict layer** — deterministic, signed, refusable decisions for AI agents.

> Agents may generate copy. They may not invent the score.

Hunter-Seeker ranks a table by a yes/no outcome, scores one entity at decision time, returns
an engine-authored band (`act · escalate · refuse`) with up to four principal reasons, signs
every result as a Verdict anyone can verify, and refuses when the data has no pattern that
clears the bar. This repo is how you plug it into your stack.

## The five-minute test

```bash
pip install hunter-seeker
hs signup                            # mints a samples-only key: no account, no email, no card
hs sample                            # ranks sample:saas_churn (free) and verifies the Verdict → valid
```

## Pick your surface

| You use | Do this |
|---|---|
| Claude, Codex, ChatGPT, Cursor, VS Code | add the remote MCP server `https://hunter-seeker.io/api/mcp` — see [docs/install.md](docs/install.md) |
| LangGraph / LangChain | `pip install hunter-seeker[langchain]` → `from hunter_seeker.langchain import verdict_tools` (the agent calls the engine) or `from hunter_seeker.langchain_middleware import LoopMiddleware` (the harness gates the agent) |
| Claude Agent SDK | `from hunter_seeker.claude_agent import LoopSession` → `ClaudeAgentOptions(hooks=session.hooks())` |
| CrewAI | `pip install hunter-seeker[crewai]` or `Agent(mcps=["https://hunter-seeker.io/api/mcp#hs_score_entity"])` |
| n8n | the **MCP Client Tool** node today; `n8n-nodes-hunter-seeker` (this repo, `n8n/`) once verified |
| Agentforce, Bedrock AgentCore, Copilot Studio | import `openapi/openapi-agent-actions.json` |
| anything with HTTP | `openapi/openapi.json` (OpenAPI 3.1) |

## What is here

```
python/     PyPI `hunter-seeker`: client, safeguards, the governed loop over agent runs (`loop`),
            LangChain/LangGraph + CrewAI tools, Claude Agent SDK hooks, LangChain middleware, `hs` CLI
openapi/    the contract of record, pulled from the product by tool-contract version
n8n/        n8n-nodes-hunter-seeker (credential, node, example workflow)
skills/     four Agent Skills (SKILL.md) — also published to the skills repository
docs/       a worked example of an agentic system built on the Verdict layer; install guides;
            the governed loop over agent runs
scripts/    pull_spec.sh (pull the published spec by version), check_spec.py (block placeholders)
```

## Versioning

The tool contract is versioned (`2.0.0`). A contract version keeps working for 12 months after
its successor ships. `openapi/openapi.json` is pulled from the product by version and diffed in
CI; it is never hand-edited here.

## The loop, in five calls

```python
import os
from hunter_seeker import Client
hs = Client(api_key=os.environ["HS_API_KEY"])   # `hs signup` writes one; never paste a key inline
run = hs.rank_topk(dataset_id="ds_…", entity_column="account_id", outcome_column="churned", subject_kind="org")
v   = hs.score_entity(run["model_ref"], row, subject_kind="org")     # band, reasons, signed Verdict
assert hs.verify(v["verdict"], v["signature"]) == "valid"
hs.report_outcome(run["model_ref"], [{"entity_id": "acct_4419", "outcome": 0, "observed_at": "2026-09-30", "event_id": "crm-88213"}])
hs.drift_status(run["model_ref"])                                       # keep | refit | abandon
```

## The loop over agent runs — governed, and measured

For a swarm of agents, the entity is the RUN and the outcome is what you observed afterwards
(the tests still pass on main; the ticket stayed closed). `hunter_seeker.loop` is the part the
engine cannot do for you, each piece there for a measured reason — see
[docs/governed-loop.md](docs/governed-loop.md).

```python
from hunter_seeker import Client, Ledger, gate, era_lock

ledger = Ledger()                                        # one row per run; the only state you own
ledger.extend(rows_with_known_outcomes)                  # run_id, ts, agent, task, tool, telemetry, failed

d = gate(hs, model_ref, ledger, new_run)                 # attaches the trace@1 priors the scorecard
if d.action == "intercept":   ...                        #   needs (score_entity refuses without them),
elif d.action == "proceed":   ...                        #   draws the control arm by stable hash, and
else:                         ...                        #   reads the band WITH its polarity

pattern = hs.explain_drivers(ranking_ref)["pattern"]["conditions"]
assert not era_lock(pattern, ledger.rows)["era_locked"]  # the _prior_n emits are counters that only grow
```

Harness adapters: `hunter_seeker.claude_agent.LoopSession` (hooks: builds the row from what the
harness saw, records at `Stop`, gates the finished run) and
`hunter_seeker.langchain_middleware.LoopMiddleware` (the dispatch gate as `before_agent`).

Every production Verdict is signed; a response with no signature is unverifiable and
`verify` reports it as `invalid_signature`. Never act on an unverified Verdict.

Verification is free forever. Ranking costs one run (refunded on honest-empty); scoring costs
one decision per non-refused row. Everything else is free.

Apache-2.0. Verifier libraries live in [hunter-seeker-verify](https://github.com/hunter-seeker/hunter-seeker-verify).
