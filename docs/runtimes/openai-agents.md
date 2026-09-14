# OpenAI Agents SDK — an input guardrail and run hooks

`pip install "hunter-seeker[openai-agents]"`

```python
from agents import Agent, Runner
from hunter_seeker import Client
from hunter_seeker.openai_agents import decide_input_guardrail, AttestHooks

hs = Client(api_key=os.environ["HS_API_KEY"])
decisions = {}
agent = Agent(name="refunds", instructions="...", tools=[refund],
              input_guardrails=[decide_input_guardrail(hs, "ag_...", remember=decisions,
                  case_from_input=lambda ctx, agent, inp: {"case_id": ctx.context["case_id"], ...})])
result = await Runner.run(agent, "refund order 41", context={"case_id": "c1"},
                          hooks=AttestHooks(hs, "urn:my-runtime:refunds", decisions=decisions))
```

The guardrail decides once inside a two-second budget and returns
`GuardrailFunctionOutput(output_info=<RouteDecision>, tripwire_triggered=route in trip_on)`. The
tripwire is how this SDK stops a run for a person: by default it trips on `human` only (`review`
lets the agent work while the Approval queue holds the result; `trip_on=("review", "human")` to
stop on both). `AttestHooks.on_tool_end` sends one `action.attested` per tool call with the tool
**name** and the arm / lever id from the decision. Errors and timeouts are the named fallback
(never a tripwire on the engine's say-so, never an exception). Branch on `route`, never on lane.
