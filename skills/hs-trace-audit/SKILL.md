---
name: hs-trace-audit
description: Use when a team wants to learn which of their AGENT RUNS succeed and why, from traces (OpenTelemetry GenAI spans, LangSmith, Langfuse, n8n executions, Claude Code / Codex exports) — deterministic pattern discovery instead of an LLM judge. Covers export, role mapping, the mandatory free self-gate, running, reading the pattern as one unit, changing the agent (copy), refitting, and drift. Operational traces only; never end-user conversation content.
---

# Trace audit: the engine over your agent's own runs

An agent trace is an event log. The `sequential@1` reading turns it into one row per run.
The engine then finds which combination of run features predicts success. No judge; a
reproducible pattern with lift, coverage, and a signed verdict.

## Roles

| role | OpenTelemetry GenAI field |
|---|---|
| identifier | `trace_id` (one run) — or your `thread_id` / `config_version` for a coarser grain |
| time_axis | span start |
| event_type | `gen_ai.operation.name` (`invoke_agent`, `chat`, `execute_tool`), `gen_ai.tool.name` |
| numeric_metric | `gen_ai.usage.input_tokens`, duration, cost |
| label | YOURS, from outside the trace: "meeting booked", "draft accepted", "ticket resolved" |

Use `POST /trace/otel` (or the loader in the SDK) to flatten spans; it refuses spans that
carry message content (`gen_ai.prompt`, `gen_ai.completion`, …). Strip them first. v1 accepts
operational traces only.

## The self-gate comes first — always

Runs cluster by session, tenant, and agent version, so the effective sample is far smaller
than the row count. Before any billed run, the engine computes three free numbers: base
rate, cluster design effect, and the maximum lift a perfect ranker could reach. If any refuses,
stop: more data, a different grain, or a different label. Measured on a synthetic corpus: a
design effect of 3.97 turned 750 rows into 189, and a single run "cleared" the bar with a
pattern that was half noise and fired on 2.9% of rows. The gate exists so that never ships.

## Reading the result

The pattern is ONE joint profile: "runs with ≥ 2 research calls before the first draft, under
N tokens of context, and no retry loop". Do not rank conditions or report one alone.

## Changing the agent

The engine never rewrites prompts or graphs. A human (or a builder agent) edits the prompt,
tool policy, or graph — that is copy. Then `hs_rank_topk(refit_of)` on the next window and
`hs_drift_status`: did the coefficient move? A second grain that makes this crisp:
`identifier = config_version` (prompt hash × model × tool policy) so a prompt change is a
lever the drift detector can watch.

## Never

- Infer the label from the trace itself (`final_status`, `error`) — that is the outcome leaking in.
- Treat one honest-empty as failure. Two consecutive → abandon this framing.
- Upload conversation content.
