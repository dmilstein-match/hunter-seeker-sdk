---
name: hs-observe
description: Use when preparing data for Hunter-Seeker — shaping CRM, product, ads, billing, or event exports into an entity table or an event-log "reading", choosing a legitimate outcome column, avoiding leakage, and hashing identifiers. Trigger on "what columns do I need", "is this outcome column ok", "how do I turn events into rows", "leakage".
---

# Shaping data the engine can be honest about

## Two shapes it accepts

1. **Entity table** — one row per thing (customer, lead, machine). Needs an entity id column,
   a yes/no outcome column, and features known BEFORE the outcome.
2. **Event log** — one row per event (login, ticket, invoice, tool call). Send it with a
   `reading` block and the engine reduces it to one row per entity as of a cutoff, with a
   leakage-safe time split: `{"kind":"sequential","version":1,"roles":{"identifier":…,
   "time_axis":…,"event_type":…,"numeric_metric":…},"label":{…}}`.

## The outcome column

- Must be binary (0/1, yes/no, true/false).
- Must have been knowable historically, not derived after the outcome. `cancel_date`,
  `refund_issued`, `closed_lost_reason` are the outcome itself or its aftermath — leakage.
  The engine's leak guard will quarantine them and say why; do not fight it.
- For event logs, the label is yours: `{"kind":"lapsed"}` (no events in the window) or
  `{"kind":"expr","name":"converted","predicate":{…}}`. The engine never infers meaning.

## The denylist, per outcome

A field is usable for a given outcome only if it is complete before that outcome is known.
Ask of every column: "at the moment I would act, do I know this?" If not, drop it. Over-
quarantine is also a defect: do not drop columns you would legitimately know.

## Identifiers

Hash person-level ids before upload: `HMAC-SHA256(your_salt, canonical_id)[:32]`. The engine
treats the id as a join key; it never needs the raw value. Raw rows are deleted after the run.

## Size

Inline up to a few hundred rows; otherwise upload via `hs_provide_dataset` (no row cap). Aim
for ≥ 1,000 rows and an outcome rate between 2% and 98%; outside that the honest-empty is likely.
