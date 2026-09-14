# LangChain / LangGraph — `DecideMiddleware`

`pip install "hunter-seeker[langchain-middleware]"`

```python
from langchain.agents import create_agent
from hunter_seeker import Client
from hunter_seeker.langchain_middleware import DecideMiddleware

hs = Client(api_key=os.environ["HS_API_KEY"])
gate = DecideMiddleware(hs, "ag_...", source="urn:my-runtime:refunds", fallback="none",
                        case_from_state=lambda state, runtime: {
                            "case_id": runtime.context["run_id"],
                            "kind": {"task": runtime.context["task"]},
                            "actor": {"kind": "agent", "name": "refunds-bot"},
                            "opened_at": runtime.context["ts"]})
agent = create_agent(model="gpt-5.5", tools=[...], middleware=[gate])
out = agent.invoke({"messages": [("user", "refund order 41")]}, context={...})
out["hs_route"]            # act | review | human | none — the only thing to branch on
out["hs_decision"]         # the RouteDecision: lane, band, arm, lever_id, receipt, fallback, reason
```

`before_agent` asks `POST /v1/decide` once, inside a two-second budget, and branches on
**route**: `act` and `none` let the agent run; `review` and `human` jump to the end before the
model is called, with the decision on the state for your router. `after_agent` sends one
`action.attested` per tool the run called (the tool **name**, read from the messages' tool
calls — never the arguments), carrying the `arm` and `lever_id` the receipt put on the decision.
Any error or timeout is the named fallback with its reason; nothing raises into the graph and
nothing denies.

`LoopMiddleware` (the scorecard gate over a run ledger) is unchanged and still the right tool
when you gate on a fitted scorecard rather than a governed agent's record.
