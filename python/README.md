# hunter-seeker

Python client, `hs` CLI and framework adapters for the **Hunter-Seeker Verdict layer** —
deterministic, signed, refusable decisions for AI agents.

> Agents may generate copy. They may not invent the score.

```bash
pip install hunter-seeker
hs signup                    # samples-only key: no account, no email, no card
hs sample                    # ranks a sample dataset and verifies the Verdict
```
```python
import os
from hunter_seeker import Client
hs = Client(api_key=os.environ["HS_API_KEY"])
out = hs.score_entity(model_ref=ref, row=row, subject_kind="org")
out["entity"]["band"]                       # act | escalate | refuse
hs.verify(out["verdict"], out["signature"]) # valid | invalid_signature | expired | unknown_key
```

The governed loop over agent runs — ledger, decision-time priors, gate, control arm, era-lock:

```python
from hunter_seeker import Ledger, gate
ledger = Ledger(); ledger.extend(rows_with_known_outcomes)
d = gate(hs, model_ref, ledger, new_run)    # d.action: "intercept" | "proceed" | "default"
```

Extras:

| extra | for |
|---|---|
| `hunter-seeker[langchain]` | `hunter_seeker.langchain.verdict_tools` — the engine as an agent's tools |
| `hunter-seeker[langchain-middleware]` | `hunter_seeker.langchain_middleware.LoopMiddleware` — the harness gates the agent |
| `hunter-seeker[claude-agent]` | `hunter_seeker.claude_agent.LoopSession` — Claude Agent SDK hooks |
| `hunter-seeker[crewai]` | `hunter_seeker.crewai` |

The client refuses to call an unsigned Verdict valid — a missing signature reports
`invalid_signature`, because production engines will not serve one.

Full docs, the governed-loop guide, the OpenAPI contract, the n8n node and Agent Skills:
https://github.com/dmilstein-match/hunter-seeker-sdk

Apache-2.0.
