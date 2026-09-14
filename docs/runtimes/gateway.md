# Gateway authorizer — the response shape

A gateway (an API gateway's authorizer, a proxy's request hook, a tool router) asks
`POST /v1/decide` before it forwards an action, inside a two-second budget, and hands its own
rule this shape — `hunter_seeker.runtime.authorizer_response(decide_case(...))`:

```json
{
  "allow": null,
  "band": "act",
  "max_autonomy": "L2",
  "likelihood_direction": "lower",
  "lane": "act",
  "route": "act",
  "arm": "treat",
  "lever_id": "lv_...",
  "receipt": { "...the signed receipt, verbatim..." },
  "reason": "the same action is cheapest across the whole interval",
  "fallback": false
}
```

`allow` is always `null`: the engine states facts (band, autonomy, direction) and the route
the record settled; **the gateway's rule** maps them to allow / deny — we never return `allow`.
Forward on `route: act`; hold for `review` or `human`; `none` is your existing policy. On any
error or timeout the shape carries `route = <your named fallback>` and `fallback: true` with the
reason. `arm` and `lever_id` are present when a lever's trial assigned the case; carry them into
your attestation (`action.attested` with the tool name). Verify the receipt with
`hs_verify_verdict` whenever a decision is worth auditing.
