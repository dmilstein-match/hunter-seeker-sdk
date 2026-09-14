# Google ADK — callbacks

`pip install "hunter-seeker[adk]"`

```python
from google.adk.agents import LlmAgent
from hunter_seeker import Client
from hunter_seeker.adk import decide_before_agent, attest_after_tool

hs = Client(api_key=os.environ["HS_API_KEY"])
agent = LlmAgent(
    name="refunds", model="gemini-2.5-flash", tools=[refund, lookup],
    before_agent_callback=decide_before_agent(hs, "ag_...", fallback="none",
        case_from_context=lambda ctx: {"case_id": ctx.state["run_id"], "kind": {"task": "refunds"},
                                       "actor": {"kind": "agent", "name": "refunds"},
                                       "opened_at": ctx.state["ts"]}),
    after_tool_callback=attest_after_tool(hs, "urn:my-runtime:refunds"),
)
```

`before_agent` decides once, writes `hs_route`, `hs_decision`, `hs_arm`, `hs_lever_id`,
`hs_case_ref` into `callback_context.state`, and on `review` / `human` returns a Content that
ends the run (your app routes it to a person from the state). `after_tool` attests every tool
by **name** with the arm and lever id from the state. Any error or timeout → the named
fallback; no exception, no denial. Branch on `state["hs_route"]`, never on the lane.
