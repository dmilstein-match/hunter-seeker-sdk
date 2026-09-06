# n8n-nodes-hunter-seeker

One node, **all sixteen published operations**. Credential type `hunterSeekerApi` (a machine
key). The node is `usableAsTool: true`, so an AI Agent node can call it directly.

Exactly one operation costs anything you have to think about: **Rank** consumes one run from the
monthly quota, and it is refunded on an honest-empty or an error. Scoring costs a decision per
non-refused row. The other thirteen are free, and the four that take a `ranking_ref` reuse one
analysis for 24 hours — run once, interrogate freely.

| | operations |
|---|---|
| Orient | Describe capabilities |
| Supply | Provide dataset · **Upload a table from a file** |
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

### Big tables: use a file, not items

**Upload a table from a file** takes a **binary CSV property**, not JSON items, and that is the
whole point of it. If you feed 68,000 items into a node, n8n has already materialized every row in
memory and the workflow is fragile before Hunter-Seeker is involved at all. Put a file in front of
it instead — Postgres → *Convert to File*, or *Read/Write Files from Disk* — and the node streams
it up in chunks. That is the difference between a workflow that handles a million rows and one
that dies at fifty thousand.

It also needs no network access beyond this API. The alternative large-data path is a presigned
`upload_url` on `s3.amazonaws.com`, which n8n Cloud or a corporate egress proxy may not reach;
this one travels the same connection your credential already uses. It is slower than a single PUT
and that is the right trade.

Register-and-upload happen in ONE operation on purpose. A `dataset_id` is single-use and expires
24h unrun, so a workflow that registers in one node and uploads in another strands the id the
moment anything between them fails. Here a retry simply starts a fresh upload — there is no
half-finished dataset to reason about.

**Pattern:** Postgres → Convert to File → Hunter-Seeker (Upload a table) → Hunter-Seeker (Rank,
Data Source = Dataset ID) → Hunter-Seeker (Poll).

### "No finding" is an output, not an error

The node has **two outputs**: *Result* and *No finding*. Hunter-Seeker refuses when nothing clears
its bar, and that refusal (`result: "none"`) arrives as an ordinary HTTP 200 — so on a single
output it is indistinguishable from a finding, and the usual reflex is to wrap the node in a retry
loop. Retrying is useless: the same call returns the same answer, every time. Route the second
output instead — notify, log, collect more data — and treat it as the real result it is.

A `pending` task leaves by the *Result* output, not this one: it is a run in flight, not a
non-finding.

### Reading private data without publishing it

**Fetch URL** has a **Fetch Headers** field. Hunter-Seeker fetches the URL server-side, so without
headers it had to be public — meaning the only way to use it on real data was to publish that data
for a minute. With headers you hand over a read token instead: `{"Authorization": "Bearer …"}`
against a private object or a signed export. The URL must still be public `https` and redirects
are still refused; headers change authorization, not which hosts we will reach.

### Patterns

**Decide:** CRM trigger → Hunter-Seeker (Score) → IF `band == act` → action; ELSE approval →
Wait → action. See `examples/score-then-gate.json`.

**Learn:** Rank → Explain levers → hold out a random 10–20% → Attest (treated only) → Report
outcome (BOTH arms) → Action evidence. See `examples/close-the-loop.json`, and read
[the control-arm page](https://hunter-seeker.io/docs/control-arm) first — without the holdout the
evidence is observational, because the acted group was selected by the model's own score.

**Readings.** A `reading` reduces an event table to one row per entity before ranking, and needs
an async source (`dataset_id` or `fetch_url`) — so it is Rank → Poll, not a single call. Call
Describe capabilities for the published kinds, their roles and their param bounds.

Zero-build alternative today: n8n's built-in **MCP Client Tool** node pointed at
`https://hunter-seeker.io/api/mcp` with a Bearer credential.

Publishing: from 2026-05-01 n8n requires community nodes to be published via the GitHub
Action with a provenance statement; then submit for verification. A workflow JSON example is
in `examples/`.

## Licence

MIT, not the Apache-2.0 of the repository root — that is deliberate, not an oversight: n8n community nodes are conventionally MIT and n8n's verification process expects it. Everything else in this repository is Apache-2.0.
