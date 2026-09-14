# Claude Code / Claude Agent SDK — the decision point as hooks

Three hooks, one endpoint, no Python where you do not want it (`hooks/claude-code/`):

| Hook | What it does |
|---|---|
| `SessionStart` | `POST /v1/decide` for the case (`HS_CASE_ID`, else the hook's `session_id`); writes `HS_ROUTE`, `HS_LANE`, `HS_ARM`, `HS_LEVER_ID`, `HS_CASE_REF`, `HS_VERDICT_ID`, `HS_FALLBACK_APPLIED` to `$CLAUDE_ENV_FILE`, so every later command in the session reads the route |
| `PostToolUse` | `POST /v1/ingest-events` — one `action.attested` with the tool **name** only (`data.tool`), carrying `HS_ARM` / `HS_LEVER_ID` |
| `Stop` | `POST /v1/ingest-events` — `case.closed` |

Two flavours of the same thing: `hs-hook.sh` (bash + curl, `--max-time 2`) and `hs hook <event>`
(`pip install hunter-seeker`). Copy `hooks.json` into `.claude/settings.json` (it points at
`.claude/hooks/hs-hook.sh`; swap the command for `hs hook …` if you prefer Python).

Environment: `HS_API_KEY` (a live key with `run` and `ingest`), `HS_AGENT_ID`, `HS_SOURCE` (the
event-stream source URI you registered for attestations), `HS_CASE_ID` (optional), `HS_KIND_JSON`
(the case's kind attributes, optional), `HS_FALLBACK` (`act` · `review` · `human` · `none`; default
`none`), `HS_BASE_URL` (default `https://hunter-seeker.io/api`).

**Rules.** The hook exits 0 whatever happens — a decision point that fails must not stop the
session. It never returns `permissionDecision: deny`: the route is written for **your** policy
to read (`if [ "$HS_ROUTE" = human ]; then …`). Any error or a two-second timeout is the named
fallback with `HS_FALLBACK_APPLIED=1`. Branch on `HS_ROUTE`, never on `HS_LANE`.

Sandbox check: `HS_CASE_ID=demo-1 HS_API_KEY=… HS_AGENT_ID=… claude` → the session's first
`echo $HS_ROUTE` prints the route; the Runs tab shows the receipt; the case's attestations
arrive as tools run (the terminal capture is `python/tests/test_runtime_wrappers.py`'s
end-to-end hook test against a local door).
