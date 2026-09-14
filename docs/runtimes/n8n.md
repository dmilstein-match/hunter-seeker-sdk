# n8n — the Trigger node and the four-port Decide

**Decide** (the action node) leaves by the receipt's **route** port — `act`, `review`, `human`,
`none` — never by `lane`; wire each port to what your business does on that route. An error or a
timeout on the node is n8n's own error path: route it to the same branch your fallback names.

**Hunter-Seeker Trigger** starts a workflow on a signed webhook from the event bus:

1. Add the trigger; copy its production webhook URL.
2. Settings → Notifications → Webhooks (or `hs_register_webhook`): register the URL with the
   events you want; copy the secret (shown once).
3. Paste the secret into the node's `Hunter-Seeker Webhook` credential; pick the events.

Every delivery carries `webhook-id`, `webhook-timestamp` and `webhook-signature`
(`v1,<base64 HMAC-SHA256(secret, "<id>.<timestamp>.<body>")>`); the node verifies them (five-minute
tolerance) and answers 401 to anything else, starting nothing. The body is
`{ id, type, ledger_kind, ref, at, workspace_id, version }` — names, ids and timestamps; fetch
the thing by `ref` with the action node.
