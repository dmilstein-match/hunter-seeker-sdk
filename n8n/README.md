# n8n-nodes-hunter-seeker

One node, five operations. Credential type `hunterSeekerApi` (a machine key). The node is
`usableAsTool: true`, so an AI Agent node can call it directly.

Pattern: **CRM trigger → Hunter-Seeker (Score) → IF band == act → action; ELSE approval →
Wait → action → Hunter-Seeker (Report outcome) on the closed-won webhook.**

Zero-build alternative today: n8n's built-in **MCP Client Tool** node pointed at
`https://hunter-seeker.net/api/mcp` with a Bearer credential.

Publishing: from 2026-05-01 n8n requires community nodes to be published via the GitHub
Action with a provenance statement; then submit for verification. A workflow JSON example is
in `examples/`.

## Licence

MIT, not the Apache-2.0 of the repository root — that is deliberate, not an oversight: n8n community nodes are conventionally MIT and n8n's verification process expects it. Everything else in this repository is Apache-2.0.
