# Adding Hunter-Seeker to your agent host

The server is remote (Streamable HTTP) at `https://hunter-seeker.net/api/mcp`. It supports
OAuth 2.1 (sign in when the host asks) and machine keys (`Authorization: Bearer hsk_…`).

| Host | How |
|---|---|
| **Claude Code** | `claude mcp add --transport http hunter-seeker https://hunter-seeker.net/api/mcp` |
| **Claude.ai / Claude Desktop** | Settings → Connectors → Add custom connector → paste the URL (paid plans; the Connectors Directory listing removes this step) |
| **Codex CLI** | `codex mcp add hunter-seeker --url https://hunter-seeker.net/api/mcp --bearer-token-env-var HS_API_KEY` |
| **ChatGPT** | Settings → Apps → Advanced → Developer mode → add the URL (Plus/Pro/Business/Enterprise) |
| **Cursor** | `cursor://anysphere.cursor-deeplink/mcp/install?name=hunter-seeker&config=<base64 of {"url":"https://hunter-seeker.net/api/mcp"}>` |
| **VS Code** | `vscode:mcp/install?{"name":"hunter-seeker","type":"http","url":"https://hunter-seeker.net/api/mcp"}` (URL-encoded) |
| **n8n** | MCP Client Tool node → endpoint URL + Bearer credential |
| **LangGraph** | `MultiServerMCPClient({"hs": {"url": "https://hunter-seeker.net/api/mcp", "transport": "http"}})` |
| **CrewAI** | `Agent(mcps=["https://hunter-seeker.net/api/mcp#hs_rank_topk", "…#hs_score_entity"])` |

Once connected, ask your agent to call `hs_describe_capabilities`, then rank `sample:saas_churn`.
Both are free. The response includes a signed Verdict; `hs_verify_verdict` should say `valid`.

Free Claude Desktop accounts cannot add custom connectors; use `npx @hunter-seeker/mcp` (a
stdio shim that proxies the remote server) — coming with the TypeScript SDK.
