#!/usr/bin/env node
/**
 * hs-surface-parity — three-way parity gate for the Hunter-Seeker public surface.
 *
 *   node hs-surface-parity.mjs                              # spec vs node (no key needed)
 *   HS_KEY=hsk_test_… node hs-surface-parity.mjs            # + live MCP tools/list
 *   node hs-surface-parity.mjs path/to/HunterSeeker.node.js # + n8n node coverage
 *
 * Compares three descriptions of the same 15 operations:
 *   1. the OpenAPI spec        — the declared REST contract
 *   2. the live MCP server     — what tools/list actually serves   (needs HS_KEY)
 *   3. the n8n community node  — which ops an integrator can reach (needs a path)
 *
 * Exits non-zero on any disagreement, so it drops into CI unchanged. Legs 1 and 2
 * are the ones that must never drift; leg 3 is coverage, and is reported as a
 * warning unless --strict-node is passed.
 *
 * Zero dependencies. Node >= 18.
 */

import { readFileSync } from "node:fs";

const SPEC = process.env.HS_OPENAPI ?? "https://hunter-seeker.io/docs/openapi.json";
const BASE = process.env.HS_BASE ?? "https://hunter-seeker.io/api";
const KEY = process.env.HS_KEY;

const args = process.argv.slice(2);
const strictNode = args.includes("--strict-node");
const nodePath = args.find((a) => !a.startsWith("--"));

const strip = (n) => String(n).replace(/^hs_/, "");
const kebab = (id) => id.replace(/_/g, "-");

/* ------------------------------------------------- leg 1: the OpenAPI spec --- */

async function specOps() {
  const res = await fetch(SPEC, { headers: { accept: "application/json" } });
  if (!res.ok) throw new Error(`${SPEC} → HTTP ${res.status}`);
  const doc = await res.json();

  const ops = new Map(); // canonical id → path
  for (const [path, item] of Object.entries(doc.paths ?? {})) {
    for (const [method, op] of Object.entries(item)) {
      if (method.toLowerCase() !== "post") continue;
      const id = op?.operationId;
      if (id) ops.set(strip(id), path);
    }
  }
  if (!ops.size) throw new Error("spec declared no POST operations");

  // The naming rule is meant to be mechanical: hs_rank_topk ↔ /v1/rank-topk.
  const misnamed = [...ops].filter(([id, path]) => path !== `/v1/${kebab(id)}`);
  return { ops, misnamed, servers: (doc.servers ?? []).map((s) => s.url) };
}

/* ------------------------------------------------ leg 2: the live MCP server --- */

async function readRpc(res) {
  const text = await res.text();
  if ((res.headers.get("content-type") ?? "").includes("text/event-stream")) {
    for (const line of text.split(/\r?\n/)) {
      if (line.startsWith("data:")) {
        try {
          return JSON.parse(line.slice(5).trim());
        } catch {}
      }
    }
    return null;
  }
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

async function mcpOps() {
  const url = `${BASE}/mcp`;
  const headers = {
    Authorization: `Bearer ${KEY}`,
    "content-type": "application/json",
    accept: "application/json, text/event-stream",
  };

  const init = await fetch(url, {
    method: "POST",
    headers,
    body: JSON.stringify({
      jsonrpc: "2.0",
      id: 1,
      method: "initialize",
      params: {
        protocolVersion: "2025-06-18",
        capabilities: {},
        clientInfo: { name: "hs-surface-parity", version: "2.0.0" },
      },
    }),
  });
  if (!init.ok) throw new Error(`initialize → HTTP ${init.status}`);
  await readRpc(init);

  const session = init.headers.get("mcp-session-id");
  if (session) headers["mcp-session-id"] = session;

  await fetch(url, {
    method: "POST",
    headers,
    body: JSON.stringify({ jsonrpc: "2.0", method: "notifications/initialized" }),
  }).catch(() => {});

  const list = await fetch(url, {
    method: "POST",
    headers,
    body: JSON.stringify({ jsonrpc: "2.0", id: 2, method: "tools/list" }),
  });
  if (!list.ok) throw new Error(`tools/list → HTTP ${list.status}`);

  const tools = (await readRpc(list))?.result?.tools;
  if (!Array.isArray(tools)) throw new Error("tools/list returned no tools array");
  return new Set(tools.map((t) => strip(t.name)));
}

/* ------------------------------------------------------ leg 3: the n8n node --- */

function nodeOps(path) {
  const src = readFileSync(path, "utf8");
  const found = [...src.matchAll(/["'`]\/v1\/([a-z0-9-]+)["'`]/g)].map((m) =>
    m[1].replace(/-/g, "_")
  );
  return new Set(found);
}

/* -------------------------------------------------------------------- main --- */

const pad = (s, n) => String(s).padEnd(n);
const problems = [];

let spec;
try {
  spec = await specOps();
} catch (err) {
  console.error(`FATAL: could not read the OpenAPI spec — ${err.message}`);
  process.exit(2);
}

let mcp = null;
if (KEY) {
  try {
    mcp = await mcpOps();
  } catch (err) {
    console.error(`WARN: live MCP leg skipped — ${err.message}\n`);
  }
} else {
  console.error("note: HS_KEY unset, skipping the live MCP leg.\n");
}

let node = null;
if (nodePath) {
  try {
    node = nodeOps(nodePath);
  } catch (err) {
    console.error(`WARN: n8n node leg skipped — ${err.message}\n`);
  }
}

const ids = [...new Set([...spec.ops.keys(), ...(mcp ?? []), ...(node ?? [])])].sort();

console.log(`spec    ${SPEC}`);
console.log(`servers ${spec.servers.join(", ") || "(none declared)"}\n`);
console.log(`${pad("operation", 24)}${pad("REST", 7)}${pad("MCP", 6)}n8n`);
console.log("-".repeat(48));
for (const id of ids) {
  const inSpec = spec.ops.has(id);
  const inMcp = mcp ? mcp.has(id) : null;
  const inNode = node ? node.has(id) : null;
  const mark = (v) => (v === null ? "–" : v ? "yes" : "NO");
  console.log(`${pad(id, 24)}${pad(mark(inSpec), 7)}${pad(mark(inMcp), 6)}${mark(inNode)}`);

  if (mcp && inSpec && !inMcp) problems.push(`${id}: in the spec, not served by MCP`);
  if (mcp && !inSpec && inMcp) problems.push(`${id}: served by MCP, absent from the spec`);
  if (node && !inSpec && inNode) problems.push(`${id}: called by the n8n node, absent from the spec`);
}

for (const [id, path] of spec.misnamed) {
  problems.push(`${id}: path "${path}" breaks the /v1/<kebab> naming rule`);
}

const nodeGaps = node ? [...spec.ops.keys()].filter((id) => !node.has(id)) : [];

console.log(`\nspec declares    ${spec.ops.size}`);
if (mcp) console.log(`MCP serves       ${mcp.size}`);
if (node) console.log(`n8n node covers  ${node.size}  (missing: ${nodeGaps.join(", ") || "none"})`);

if (problems.length) {
  console.log("\nPARITY FAILED");
  for (const p of problems) console.log(`  · ${p}`);
} else {
  console.log("\nPARITY OK — spec and server agree.");
}
if (nodeGaps.length) {
  console.log(
    `\n${strictNode ? "FAIL" : "warn"}: the n8n node reaches ${node.size}/${spec.ops.size} operations.` +
      (nodeGaps.includes("attest_action")
        ? "\n  attest_action is missing — an integrator cannot close the attest → report → evidence loop."
        : "")
  );
}
console.log();

process.exit(problems.length || (strictNode && nodeGaps.length) ? 1 : 0);
