# hunter-seeker

Python client, `hs` CLI and framework adapters for the **Hunter-Seeker Verdict layer** —
deterministic, signed, refusable decisions for AI agents.

> Agents may generate copy. They may not invent the score.

```bash
pip install hunter-seeker
export HS_API_KEY=hsk_test_...
hs sample                    # ranks a sample dataset and verifies the Verdict
```
```python
from hunter_seeker import Client
hs = Client()
out = hs.score_entity(model_ref=ref, row=row, subject_kind="org")
out["entity"]["band"]                       # act | escalate | refuse
hs.verify(out["verdict"], out["signature"]) # valid | invalid_signature | expired | unknown_key
```

Extras: `hunter-seeker[langchain]`, `hunter-seeker[crewai]`.

The client refuses to call an unsigned Verdict valid — a missing signature reports
`invalid_signature`, because production engines will not serve one.

**Pre-release:** the hosted service is not serving yet. Full docs, the OpenAPI contract, the
n8n node and Agent Skills: https://github.com/dmilstein-match/hunter-seeker-sdk

Apache-2.0.
