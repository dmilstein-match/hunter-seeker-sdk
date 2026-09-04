/**
 * What each operation actually PUTS ON THE WIRE.
 *
 * `hs-surface-parity` proves the node reaches all fifteen paths. It says nothing about whether the
 * body it sends to each one is the body that endpoint accepts — and a node that POSTs to the right
 * URL with the wrong shape is a 422 the user reads as "Hunter-Seeker is broken".
 *
 * So this drives the real `execute()` with a stubbed n8n context and captures the request. Every
 * assertion below is about a field REACHING the wire, or about one deliberately NOT reaching it.
 */
import test from "node:test";
import assert from "node:assert/strict";

import { HunterSeeker } from "../dist/nodes/HunterSeeker/HunterSeeker.node.js";

/** A minimal IExecuteFunctions that records the request instead of sending it. */
function ctx(params, items = [{ json: {} }]) {
  const sent = [];
  const self = {
    getInputData: () => items,
    getExecutionId: () => "exec-1",
    getCredentials: async () => ({ baseUrl: "https://hunter-seeker.net/api" }),
    getNodeParameter: (name, _i, fallback) => (name in params ? params[name] : fallback),
    helpers: {
      httpRequestWithAuthentication: {
        async call(_self, _cred, req) { sent.push(req); return { ok: true }; },
      },
    },
  };
  return { self, sent };
}

async function run(params) {
  const { self, sent } = ctx(params);
  await new HunterSeeker().execute.call(self);
  assert.equal(sent.length, 1);
  return sent[0];
}

test("every operation posts to its own /v1 path", async () => {
  const cases = [
    ["describe", "/v1/describe-capabilities"], ["provide", "/v1/provide-dataset"],
    ["rank", "/v1/rank-topk"], ["poll", "/v1/poll-task"],
    ["quality", "/v1/model-quality"], ["drivers", "/v1/explain-drivers"],
    ["levers", "/v1/explain-levers"], ["brief", "/v1/context-brief"],
    ["score", "/v1/score-entity"], ["scoreBatch", "/v1/score-batch"],
    ["verify", "/v1/verify-verdict"], ["attest", "/v1/attest-action"],
    ["report", "/v1/report-outcome"], ["evidence", "/v1/action-evidence"],
    ["drift", "/v1/drift-status"],
  ];
  assert.equal(cases.length, 15, "the node must cover all fifteen published operations");
  for (const [operation, path] of cases) {
    const req = await run({ operation, dataSource: "datasetId", outcomeIsDesirable: "unstated", reading: "{}", row: "{}", rows: "[]", batchRows: "[]", verdict: "{}", signature: "{}", entityIds: "", postValue: "" });
    assert.equal(req.url, path, `${operation} posted to ${req.url}`);
    assert.equal(req.method, "POST");
  }
});

/* ── the loop that was unreachable ────────────────────────────────────────────────────────── */

test("attest sends the lever_token and a NUMERIC post_value", async () => {
  const req = await run({
    operation: "attest", modelRef: "mr1_x", entityId: "acct_1",
    leverToken: "lt_abc", postValue: "5", actedAt: "2026-09-04T00:00:00Z", eventId: "e1",
  });
  assert.deepEqual(req.body, {
    model_ref: "mr1_x", entity_id: "acct_1", lever_token: "lt_abc",
    post_value: 5, acted_at: "2026-09-04T00:00:00Z", event_id: "e1",
  });
  // A number, not the string "5": the engine compares post_value against the lever's own scale.
  assert.equal(typeof req.body.post_value, "number");
});

test("attest keeps a non-numeric post_value as text", async () => {
  const req = await run({
    operation: "attest", modelRef: "mr1_x", entityId: "a", leverToken: "lt",
    postValue: "enterprise", actedAt: "t", eventId: "e",
  });
  assert.equal(req.body.post_value, "enterprise");
});

test("levers splits the entity list and drops blanks", async () => {
  const req = await run({ operation: "levers", rankingRef: "rank_1", entityIds: "a, b ,, c " });
  assert.deepEqual(req.body, { ranking_ref: "rank_1", entity_ids: ["a", "b", "c"] });
});

test("evidence and drift take only a model_ref", async () => {
  for (const operation of ["evidence", "drift"]) {
    const req = await run({ operation, modelRef: "mr1_x" });
    assert.deepEqual(req.body, { model_ref: "mr1_x" });
  }
});

/* ── the async surface, and therefore readings ────────────────────────────────────────────── */

test("a dataset_id rank forwards a reading, and poll can follow it", async () => {
  const reading = { kind: "panel", version: 1, roles: { identifier: "account_id", time_axis: "period" } };
  const req = await run({
    operation: "rank", dataSource: "datasetId", datasetId: "sample:usage_panel",
    entityColumn: "account_id", outcomeColumn: "usage_declining", subjectKind: "org",
    ack: false, topK: 20, outcomeIsDesirable: "no", reading: JSON.stringify(reading),
    horizon: "", refitOf: "",
  });
  assert.deepEqual(req.body.data, { dataset_id: "sample:usage_panel" });
  assert.deepEqual(req.body.reading, reading);
  assert.equal(req.body.outcome_is_desirable, false);

  const poll = await run({ operation: "poll", taskId: "rank_abc" });
  assert.deepEqual(poll.body, { task_id: "rank_abc" });
});

test("an EMPTY reading is omitted, not sent as {}", async () => {
  // `{}` is the field's default and means "not supplied". Sending it would be a stated empty
  // reading, which the engine would be right to reject.
  const req = await run({
    operation: "rank", dataSource: "datasetId", datasetId: "sample:saas_churn",
    entityColumn: "customer_id", outcomeColumn: "churned", subjectKind: "org",
    ack: false, topK: 20, outcomeIsDesirable: "unstated", reading: "{}", horizon: "", refitOf: "",
  });
  assert.ok(!("reading" in req.body));
});

test("inline rows rank synchronously and carry no reading", async () => {
  const req = await run({
    operation: "rank", dataSource: "rows", rows: '[{"id":"a","churned":1}]',
    entityColumn: "id", outcomeColumn: "churned", subjectKind: "org",
    ack: false, topK: 20, outcomeIsDesirable: "unstated", reading: "{}", horizon: "", refitOf: "",
  });
  assert.deepEqual(req.body.data, { rows: [{ id: "a", churned: 1 }] });
  assert.ok(!("reading" in req.body), "a reading needs an async source; the field is hidden there");
});

/* ── the thing this node must never do ────────────────────────────────────────────────────── */

test("an UNSTATED polarity is omitted, never defaulted", async () => {
  // The engine resolves polarity from the outcome name when the caller does not state it. A node
  // that sent `false` here would author a direction the user never gave, and every lever would
  // read the opposite way round.
  const req = await run({
    operation: "rank", dataSource: "datasetId", datasetId: "d", entityColumn: "e",
    outcomeColumn: "o", subjectKind: "org", ack: false, topK: 20,
    outcomeIsDesirable: "unstated", reading: "{}", horizon: "", refitOf: "",
  });
  assert.ok(!("outcome_is_desirable" in req.body));
});

test("empty optionals are omitted rather than sent as empty strings", async () => {
  const req = await run({
    operation: "rank", dataSource: "datasetId", datasetId: "d", entityColumn: "e",
    outcomeColumn: "o", subjectKind: "org", ack: false, topK: 20,
    outcomeIsDesirable: "unstated", reading: "{}", horizon: "", refitOf: "",
  });
  for (const k of ["horizon", "refit_of"]) assert.ok(!(k in req.body), `${k} was sent empty`);

  const provide = await run({ operation: "provide", provideFetchUrl: "", datasetName: "" });
  assert.deepEqual(provide.body, {}, "an empty Provide must ask for an upload_url, not send blanks");
});

test("report is idempotent on event_id and sends one outcome row", async () => {
  const req = await run({
    operation: "report", modelRef: "mr1_x", entityId: "a",
    outcome: true, observedAt: "2026-09-30", eventId: "crm-88213",
  });
  assert.deepEqual(req.body.outcomes, [
    { entity_id: "a", outcome: true, observed_at: "2026-09-30", event_id: "crm-88213" },
  ]);
});

test("describe takes no arguments at all", async () => {
  const req = await run({ operation: "describe" });
  assert.deepEqual(req.body, {});
});
