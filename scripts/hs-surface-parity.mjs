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
const strictPython = args.includes("--strict-python");
const nodePath = args.find((a) => !a.startsWith("--"));
// Leg 4 reads the adapter SOURCE rather than importing it, exactly as the node leg does — no
// Python runtime, no langchain/crewai install, and it still cannot be fooled by a tool that is
// declared and never returned, because it reads the returned list.
const pythonDir = process.env.HS_PYTHON_DIR ?? "python/hunter_seeker";

const strip = (n) => String(n).replace(/^hs_/, "");
const kebab = (id) => id.replace(/_/g, "-");

// The rules an operation may be exempted from, via `x-hs-surface-exempt` ON THE OPERATION in the
// spec. Deliberately not a list of exempt operations kept here: an exception belongs with the thing
// it excuses, where the next person to read that operation cannot miss it, and where it has to be
// justified in the same commit that takes it. An exemption naming a rule outside this set is an
// error, not a no-op, so a typo cannot silently excuse nothing (or everything).
const RULES = new Set(["naming", "mcp", "n8n", "python-adapters"]);

/* ------------------------------------------------- leg 1: the OpenAPI spec --- */

async function specOps() {
  const res = await fetch(SPEC, { headers: { accept: "application/json" } });
  if (!res.ok) throw new Error(`${SPEC} → HTTP ${res.status}`);
  const doc = await res.json();

  const ops = new Map(); // canonical id → path
  const exempt = new Map(); // canonical id → { rules:Set, reason }
  const badExemptions = [];
  for (const [path, item] of Object.entries(doc.paths ?? {})) {
    for (const [method, op] of Object.entries(item)) {
      if (method.toLowerCase() !== "post") continue;
      const id = op?.operationId;
      if (!id) continue;
      ops.set(strip(id), path);

      const ex = op["x-hs-surface-exempt"];
      if (ex === undefined) continue;
      // An exemption must NAME what it excuses and defend itself in writing. A bare `true`, an
      // empty reason or an unknown rule is reported as a failure rather than quietly honoured —
      // an exemption nobody had to justify is how a gate starts rotting, and this gate exists
      // because a surface once shipped covering 5 of 15 operations with nothing going red.
      const rules = Array.isArray(ex?.rules) ? ex.rules : [];
      const reason = typeof ex?.reason === "string" ? ex.reason.trim() : "";
      const unknown = rules.filter((r) => !RULES.has(r));
      if (!rules.length || !reason || unknown.length) {
        badExemptions.push(
          `${strip(id)}: invalid x-hs-surface-exempt — ` +
            (!rules.length
              ? "it names no rules"
              : unknown.length
                ? `unknown rule(s): ${unknown.join(", ")}`
                : "its reason is empty")
        );
        continue;
      }
      exempt.set(strip(id), { rules: new Set(rules), reason });
    }
  }
  if (!ops.size) throw new Error("spec declared no POST operations");

  // The naming rule is meant to be mechanical: hs_rank_topk ↔ /v1/rank-topk.
  const misnamed = [...ops].filter(
    ([id, path]) => path !== `/v1/${kebab(id)}` && !exempt.get(id)?.rules.has("naming")
  );
  return { ops, misnamed, exempt, badExemptions, servers: (doc.servers ?? []).map((s) => s.url) };
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

/* ------------------------------------------ leg 4: the Python framework adapters --- */

// Both adapters shipped a FRACTION of the surface with zero tests: langchain returned 5 of 16 and
// crewai 1, and neither included rank_topk — so an agent built from either could never obtain the
// model_ref its own score_entity tool requires. That is the same gap this script already fails the
// n8n node for; it simply had no leg that could see Python.
function pythonOps(dir) {
  const out = new Set();
  for (const file of ["langchain.py", "crewai.py"]) {
    let src;
    try {
      src = readFileSync(`${dir}/${file}`, "utf8");
    } catch {
      continue;
    }
    // Only names in the RETURNED list count. A tool defined above and left out of the return is
    // exactly the shape of the bug, so declaration alone must not satisfy this.
    for (const block of src.matchAll(/return \[([\s\S]*?)\]/g)) {
      for (const m of block[1].matchAll(/hs_([a-z0-9_]+)/g)) out.add(m[1]);
    }
    // crewai builds its tools from a table of ("hs_<op>", ...) spec tuples.
    for (const m of src.matchAll(/\(\s*"hs_([a-z0-9_]+)"\s*,/g)) out.add(m[1]);
  }
  return out;
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

let python = null;
try {
  python = pythonOps(pythonDir);
} catch (err) {
  console.error(`WARN: python adapter leg skipped — ${err.message}
`);
}

let node = null;
if (nodePath) {
  try {
    node = nodeOps(nodePath);
  } catch (err) {
    console.error(`WARN: n8n node leg skipped — ${err.message}\n`);
  }
}

const ids = [...new Set([...spec.ops.keys(), ...(mcp ?? []), ...(node ?? []), ...(python ?? [])])].sort();

console.log(`spec    ${SPEC}`);
console.log(`servers ${spec.servers.join(", ") || "(none declared)"}\n`);
const exemptFrom = (id, rule) => spec.exempt.get(id)?.rules.has(rule) ?? false;

console.log(`${pad("operation", 24)}${pad("REST", 7)}${pad("MCP", 8)}${pad("n8n", 8)}py`);
console.log("-".repeat(54));
for (const id of ids) {
  const inSpec = spec.ops.has(id);
  const inMcp = mcp ? mcp.has(id) : null;
  const inNode = node ? node.has(id) : null;
  const inPy = python ? python.has(id) : null;
  // An exempt surface reads "exempt", never "yes": the table must not claim coverage that does
  // not exist, only record that its absence was argued for.
  const mark = (v, rule) => (v === null ? "–" : v ? "yes" : rule && exemptFrom(id, rule) ? "exempt" : "NO");
  console.log(
    `${pad(id, 24)}${pad(mark(inSpec), 7)}${pad(mark(inMcp, "mcp"), 8)}${pad(mark(inNode, "n8n"), 8)}${mark(inPy, "python-adapters")}`
  );

  if (mcp && inSpec && !inMcp && !exemptFrom(id, "mcp")) problems.push(`${id}: in the spec, not served by MCP`);
  if (mcp && !inSpec && inMcp) problems.push(`${id}: served by MCP, absent from the spec`);
  if (node && !inSpec && inNode) problems.push(`${id}: called by the n8n node, absent from the spec`);
  if (python && !inSpec && inPy) problems.push(`${id}: exposed by a Python adapter, absent from the spec`);
}

for (const [id, path] of spec.misnamed) {
  problems.push(`${id}: path "${path}" breaks the /v1/<kebab> naming rule`);
}

const nodeGaps = node ? [...spec.ops.keys()].filter((id) => !node.has(id) && !exemptFrom(id, "n8n")) : [];
const pyGaps = python
  ? [...spec.ops.keys()].filter((id) => !python.has(id) && !exemptFrom(id, "python-adapters"))
  : [];
const exemptCount = (rule) => [...spec.exempt.values()].filter((e) => e.rules.has(rule)).length;

console.log(`\nspec declares    ${spec.ops.size}`);
if (mcp) console.log(`MCP serves       ${mcp.size}`);
if (node)
  console.log(
    `n8n node covers  ${node.size}  (missing: ${nodeGaps.join(", ") || "none"}${exemptCount("n8n") ? `, exempt: ${exemptCount("n8n")}` : ""})`
  );
if (python)
  console.log(
    `py adapters cover ${python.size}  (missing: ${pyGaps.join(", ") || "none"}${exemptCount("python-adapters") ? `, exempt: ${exemptCount("python-adapters")}` : ""})`
  );

// An exemption that nobody ever reads is the same as no gate at all, so every one of them is
// printed on every run, with its reason, pass or fail.
if (spec.exempt.size) {
  console.log(`\nexemptions (${spec.exempt.size}) — declared on the operation in the spec:`);
  for (const [id, { rules, reason }] of spec.exempt) {
    console.log(`  · ${id} — exempt from ${[...rules].join(", ")}`);
    for (const line of reason.match(/.{1,92}(\s|$)/g) ?? [reason]) console.log(`      ${line.trim()}`);
  }
}

problems.push(...spec.badExemptions);

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

if (pyGaps.length) {
  console.log(
    `\n${strictPython ? "FAIL" : "warn"}: the Python adapters reach ${python.size}/${spec.ops.size} operations.` +
      (pyGaps.includes("rank_topk")
        ? "\n  rank_topk is missing - an agent built from these cannot obtain the model_ref its own score_entity tool requires."
        : "") +
      (pyGaps.includes("attest_action")
        ? "\n  attest_action is missing - an integrator cannot close the attest -> report -> evidence loop."
        : "")
  );
}

// process.exitCode, not process.exit(): exiting while a keep-alive fetch socket is still open
// aborts Node on Windows (a libuv assertion in src/win/async.c), so every local run reported
// 127 - pass and fail alike - which made this gate unreadable anywhere but Linux CI.
process.exitCode = problems.length || (strictNode && nodeGaps.length) || (strictPython && pyGaps.length) ? 1 : 0;
