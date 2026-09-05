# hunter-seeker-sdk

> ### Status: pre-release
>
> The code here is complete and tested; the hosted service it talks to is not live yet.
> Concretely, **today**:
>
> | Thing the docs below tell you to use | Reality today |
> |---|---|
> | `pip install hs-verify` / `npm install @hunter-seeker/verify` | not on PyPI / npm yet — install from this repo |
> | `pip install hunter-seeker` | not on PyPI yet — install from this repo |
> | `https://hunter-seeker.io/api/mcp` and `/.well-known/jwks.json` | not serving yet |
> | `vectors.json` | signed with a **pre-release test key**, not the production one. Run `python scripts/check_live.py --vectors` and it will say so |
>
> Everything offline works now: both verifiers agree byte for byte on the shared vectors, and
> the canonical form and the signature check are the ones production will use. What is waiting
> is the engine deploy that publishes the JWKS and re-cuts the vectors with the live key.
>
> This notice comes down when the JWKS is live and the packages are published.


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
export HS_API_KEY=hsk_test_…        # a test key reaches the free sample datasets
hs sample                            # ranks sample:saas_churn (free) and verifies the Verdict → valid
```

## Pick your surface

| You use | Do this |
|---|---|
| Claude, Codex, ChatGPT, Cursor, VS Code | add the remote MCP server `https://hunter-seeker.io/api/mcp` — see [docs/install.md](docs/install.md) |
| LangGraph / LangChain | `pip install hunter-seeker[langchain]` → `from hunter_seeker.langchain import verdict_tools` |
| CrewAI | `pip install hunter-seeker[crewai]` or `Agent(mcps=["https://hunter-seeker.io/api/mcp#hs_score_entity"])` |
| n8n | the **MCP Client Tool** node today; `n8n-nodes-hunter-seeker` (this repo, `n8n/`) once verified |
| Agentforce, Bedrock AgentCore, Copilot Studio | import `openapi/openapi-agent-actions.json` |
| anything with HTTP | `openapi/openapi.json` (OpenAPI 3.1) |

## What is here

```
python/     PyPI `hunter-seeker`: client, LangChain/LangGraph + CrewAI tools, `hs` CLI
openapi/    the contract of record, pulled from the product by tool-contract version
n8n/        n8n-nodes-hunter-seeker (credential, node, example workflow)
skills/     four Agent Skills (SKILL.md) — also published to the skills repository
docs/       a worked example of an agentic system built on the Verdict layer; install guides
scripts/    pull_spec.sh (pull the published spec by version), check_spec.py (block placeholders)
```

## Versioning

The tool contract is versioned (`2.0.0`). A contract version keeps working for 12 months after
its successor ships. `openapi/openapi.json` is pulled from the product by version and diffed in
CI; it is never hand-edited here.

## The loop, in five calls

```python
from hunter_seeker import Client
hs = Client(api_key="hsk_…")
run = hs.rank_topk(dataset_id="ds_…", entity_column="account_id", outcome_column="churned", subject_kind="org")
v   = hs.score_entity(run["model_ref"], row, subject_kind="org")     # band, reasons, signed Verdict
assert hs.verify(v["verdict"], v["signature"]) == "valid"
hs.report_outcome(run["model_ref"], [{"entity_id": "acct_4419", "outcome": 0, "observed_at": "2026-09-30", "event_id": "crm-88213"}])
hs.drift_status(run["model_ref"])                                       # keep | refit | abandon
```

Every production Verdict is signed; a response with no signature is unverifiable and
`verify` reports it as `invalid_signature`. Never act on an unverified Verdict.

Verification is free forever. Ranking costs one run (refunded on honest-empty); scoring costs
one decision per non-refused row. Everything else is free.

Apache-2.0. Verifier libraries live in [hunter-seeker-verify](https://github.com/hunter-seeker/hunter-seeker-verify).
