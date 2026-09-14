/**
 * The Hunter-Seeker Trigger (Datagoat unit 23): a signed delivery starts the workflow with the
 * event's body; an unsigned, tampered or stale one is answered 401 and starts nothing; an event
 * the workflow did not subscribe to is acknowledged and ignored. The signature is computed here
 * the way the sender computes it (HMAC-SHA256 over id.timestamp.body under the decoded secret).
 */
import test from "node:test";
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { readFileSync } from "node:fs";

import { HunterSeekerTrigger, verifySignature, WEBHOOK_EVENTS } from "../dist/nodes/HunterSeekerTrigger/HunterSeekerTrigger.node.js";

const SECRET = "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw";
const now = Math.floor(Date.now() / 1000);

function sign(id, ts, body, secret = SECRET) {
  const mac = createHmac("sha256", Buffer.from(secret.slice("whsec_".length), "base64")).update(`${id}.${ts}.${body}`).digest("base64");
  return `v1,${mac}`;
}

function ctx(headers, body, events = ["verdict.drift", "escalate"]) {
  const raw = JSON.stringify(body);
  const self = {
    getCredentials: async () => ({ secret: SECRET }),
    getRequestObject: () => ({ rawBody: Buffer.from(raw), body }),
    getHeaderData: () => headers,
    getBodyData: () => body,
    getNodeParameter: (name, fallback) => (name === "events" ? events : fallback),
    helpers: { returnJsonArray: (items) => items.map((json) => ({ json })) },
  };
  return self;
}

const EVENT = { id: "evt_412", type: "verdict.drift", ledger_kind: "verdict.drift", ref: "ag_1", at: "2026-09-14T04:00:00.000Z", workspace_id: "org_1", version: "dg.webhook.v1" };

test("a signed delivery of a subscribed event starts the workflow with the body", async () => {
  const body = EVENT;
  const raw = JSON.stringify(body);
  const headers = { "webhook-id": "evt_412", "webhook-timestamp": String(now), "webhook-signature": sign("evt_412", now, raw) };
  const out = await new HunterSeekerTrigger().webhook.call(ctx(headers, body));
  assert.equal(out.webhookResponse.status, 200);
  assert.deepEqual(out.workflowData, [[{ json: body }]]);
});

test("an unsigned, tampered or stale delivery is 401 and starts nothing", async () => {
  const raw = JSON.stringify(EVENT);
  const good = { "webhook-id": "evt_412", "webhook-timestamp": String(now), "webhook-signature": sign("evt_412", now, raw) };
  for (const [name, headers, body] of [
    ["missing", {}, EVENT],
    ["tampered", good, { ...EVENT, ref: "ag_2" }],
    ["wrong secret", { ...good, "webhook-signature": sign("evt_412", now, raw, "whsec_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA") }, EVENT],
    ["stale", { ...good, "webhook-timestamp": String(now - 3600), "webhook-signature": sign("evt_412", now - 3600, raw) }, EVENT],
  ]) {
    const out = await new HunterSeekerTrigger().webhook.call(ctx(headers, body));
    assert.equal(out.webhookResponse.status, 401, name);
    assert.equal(out.workflowData, undefined, name);
    assert.match(out.webhookResponse.body.code, /^signature_/);
  }
});

test("an event the workflow did not subscribe to is acknowledged and ignored", async () => {
  const body = { ...EVENT, type: "source.stale" };
  const raw = JSON.stringify(body);
  const headers = { "webhook-id": "evt_412", "webhook-timestamp": String(now), "webhook-signature": sign("evt_412", now, raw) };
  const out = await new HunterSeekerTrigger().webhook.call(ctx(headers, body));
  assert.equal(out.webhookResponse.status, 200);
  assert.equal(out.webhookResponse.body.ignored, true);
  assert.equal(out.workflowData, undefined);
});

test("verifySignature accepts any v1 value in a rotation window and names every refusal", () => {
  const raw = JSON.stringify(EVENT);
  const h = { "webhook-id": "evt_412", "webhook-timestamp": String(now), "webhook-signature": `v1,AAAA ${sign("evt_412", now, raw)}` };
  assert.deepEqual(verifySignature(SECRET, h, raw, now), { ok: true, id: "evt_412" });
  assert.deepEqual(verifySignature(SECRET, { ...h, "webhook-timestamp": "soon" }, raw, now), { ok: false, reason: "bad_timestamp" });
  assert.equal(WEBHOOK_EVENTS.length, 12);
});

test("the action node branches on route (never lane) and the trigger declares its webhook", () => {
  const node = readFileSync(new URL("../nodes/HunterSeeker/HunterSeeker.node.ts", import.meta.url), "utf8");
  assert.match(node, /PORTS_FIELD = "route"/);
  assert.doesNotMatch(node, /\?\.lane\b|\.lane\s*\?\?|\["lane"\]/);
  const trig = readFileSync(new URL("../nodes/HunterSeekerTrigger/HunterSeekerTrigger.node.ts", import.meta.url), "utf8");
  assert.match(trig, /webhooks: \[\{ name: "default", httpMethod: "POST"/);
  assert.doesNotMatch(trig, /permissionDecision/);
});
