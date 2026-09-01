---
name: hs-act-faithfully
description: Use whenever an agent writes ANY text or takes ANY action based on a Hunter-Seeker result — emails, CRM updates, Slack messages, tickets, call scripts, reports. Encodes the copy rules (cite the verdict, never restate a number it does not contain, never reorder drivers), the approval-gate placement per framework, the autonomy ladder, and how the Verdict travels with the action.
---

# Acting on a Verdict without inventing anything

## The rules

1. Cite `verdict_id` in the action's metadata. The Verdict travels with the action.
2. Every number you write must appear in a Hunter-Seeker response. No rounding into a new
   claim, no "roughly", no arithmetic across two responses.
3. Drivers are ONE combination. Never rank them, never report one alone, never add one.
4. Read `likelihood_direction` per lever. On a desirable outcome levers read "higher"; on an
   adverse one "lower". Assuming one inverts every lever you present.
5. Levers are associations. Write "what the model associates with a different outcome",
   never "because", "causes", "will".
6. An expired verdict is re-scored. Never reuse.
7. Never act above `max_autonomy`.

## Where the human gate goes

| Framework | Gate |
|---|---|
| LangGraph | `interrupt({verdict, signature, band, reasons})` in the node before the action; on resume the node re-runs — keep calls idempotent |
| CrewAI | a human-input task between the scoring task and the action task |
| n8n | IF band == act → action; ELSE Slack/email approval → Wait node → action |
| Agentforce | topic instruction: "if band is refuse do not propose; if escalate route to a human; always attach verdict_id"; approval flow before the write |
| Bedrock AgentCore | return-of-control on escalate; the caller's UI shows the Verdict |

Person-level regulated outcomes (`subject_kind: "person"`): the gate is mandatory at every
band; `max_autonomy` is at most L2. Present `principal_reasons` as the reasons; do not add.

## Attaching the Verdict to the action

Put `{verdict_id, model_ref, band, max_autonomy, signature.kid}` in the action's provenance
field (CRM note, ticket custom field, message metadata). A reviewer can then run
`hs_verify_verdict` on the stored verdict and see exactly what the agent saw.

## After acting

Call `hs_attest_action` with the entity's NEW value for the lever you pulled, then
`hs_report_outcome` when you observe the real-world result. This is what makes
`hs_action_evidence` exist. Reporting never changes the model.
