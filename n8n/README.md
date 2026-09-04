# n8n-nodes-hunter-seeker

One node, **all fifteen published operations**. Credential type `hunterSeekerApi` (a machine
key). The node is `usableAsTool: true`, so an AI Agent node can call it directly.

Exactly one operation costs anything you have to think about: **Rank** consumes one run from the
monthly quota, and it is refunded on an honest-empty or an error. Scoring costs a decision per
non-refused row. The other twelve are free, and the four that take a `ranking_ref` reuse one
analysis for an hour — run once, interrogate freely.

| | operations |
|---|---|
| Orient | Describe capabilities |
| Supply | Provide dataset |
| Run | **Rank** · Poll a task |
| Interrogate (free) | Model quality · Explain drivers · Explain levers · Context brief |
| Decide | Score one entity · Score many entities · Verify a Verdict |
| Close the loop (free) | **Attest an action** · Report outcome · **Action evidence** · Drift status |

**It shipped with five, and five was not enough to use the product.** `Attest an action` was
missing, so an integrator could never record that they acted; `Explain levers` was missing, so
they could not obtain the `lever_token` an attestation needs; and `Action evidence` was missing,
so they could never ask whether acting worked. Every step of attest → report → evidence was
unreachable except the middle one — which meant the node let someone write outcomes into a ledger
they could not query. `Poll a task` was missing too, and that one is structural: without it the
node could only run synchronous inline data, so no `dataset_id`, no `fetch_url`, and therefore no
`reading` at all.

`scripts/hs-surface-parity.mjs` in this repository compares this node's `/v1/...` paths against
the published OpenAPI document and fails CI when they diverge, so the gap cannot silently reopen.

### Patterns

**Decide:** CRM trigger → Hunter-Seeker (Score) → IF `band == act` → action; ELSE approval →
Wait → action. See `examples/score-then-gate.json`.

**Learn:** Rank → Explain levers → hold out a random 10–20% → Attest (treated only) → Report
outcome (BOTH arms) → Action evidence. See `examples/close-the-loop.json`, and read
[the control-arm page](https://hunter-seeker.net/docs/control-arm) first — without the holdout the
evidence is observational, because the acted group was selected by the model's own score.

**Readings.** A `reading` reduces an event table to one row per entity before ranking, and needs
an async source (`dataset_id` or `fetch_url`) — so it is Rank → Poll, not a single call. Call
Describe capabilities for the published kinds, their roles and their param bounds.

Zero-build alternative today: n8n's built-in **MCP Client Tool** node pointed at
`https://hunter-seeker.net/api/mcp` with a Bearer credential.

Publishing: from 2026-05-01 n8n requires community nodes to be published via the GitHub
Action with a provenance statement; then submit for verification. A workflow JSON example is
in `examples/`.

## Licence

MIT, not the Apache-2.0 of the repository root — that is deliberate, not an oversight: n8n community nodes are conventionally MIT and n8n's verification process expects it. Everything else in this repository is Apache-2.0.
