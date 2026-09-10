/**
 * hs-surface-parity — the exemption mechanism, and proof that it still bites.
 *
 * `x-hs-surface-exempt` exists so ONE operation can be excused from rules that cannot sensibly
 * apply to it: `register_agent` is the call you make before you have a credential, so it cannot be
 * a gap in a credentialed workflow, and its live path cannot move. That is a real exception.
 *
 * An exemption mechanism is also how a gate rots. So the cases below are mostly deliberate
 * violations: the same spec with the exemption removed must go red, an unexempted gap on a
 * DIFFERENT operation must go red, and an exemption that names no rules, names an unknown rule or
 * carries no written reason must go red rather than being quietly honoured.
 *
 * Run: node --test scripts/
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const execFileAsync = promisify(execFile);
const SCRIPT = fileURLToPath(new URL("./hs-surface-parity.mjs", import.meta.url));

const REASON = "Not a tool, and the one unauthenticated operation: you call it BEFORE you hold a key.";

/** A minimal three-operation spec. `exempt` undefined means the annotation is absent entirely. */
function spec({ exempt } = {}) {
  const post = (operationId, extra = {}) => ({ post: { operationId, ...extra } });
  return {
    openapi: "3.1.0",
    servers: [{ url: "https://example.test/api" }],
    paths: {
      "/v1/rank-topk": post("hs_rank_topk"),
      "/v1/score-entity": post("hs_score_entity"),
      // Misnamed on purpose: the kebab rule would demand /v1/register-agent.
      "/v1/agents/register": post("register_agent", exempt === undefined ? {} : { "x-hs-surface-exempt": exempt }),
    },
  };
}

/**
 * Serve `doc`, run the real gate against it, return its exit code and output.
 *
 * execFile rather than spawnSync: spawnSync blocks this process's event loop, so the in-process
 * HTTP server could never answer the child and every run would hang.
 */
async function runGate(doc, { nodeOps = ["rank-topk", "score-entity"], pyOps = ["rank_topk", "score_entity"] } = {}) {
  const server = createServer((_req, res) => {
    res.setHeader("content-type", "application/json");
    res.end(JSON.stringify(doc));
  });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  const { port } = server.address();

  const dir = mkdtempSync(join(tmpdir(), "hs-parity-"));
  // Leg 3 scans the node's SOURCE for "/v1/<op>" literals; leg 4 scans the adapter's returned list.
  writeFileSync(join(dir, "node.js"), nodeOps.map((p) => `const _ = "/v1/${p}";`).join("\n"));
  writeFileSync(join(dir, "langchain.py"), `def verdict_tools(hs):\n    return [${pyOps.map((o) => "hs_" + o).join(", ")}]\n`);

  let code = 0;
  let out = "";
  try {
    const r = await execFileAsync(
      process.execPath,
      [SCRIPT, join(dir, "node.js"), "--strict-node", "--strict-python"],
      { env: { ...process.env, HS_OPENAPI: `http://127.0.0.1:${port}/openapi.json`, HS_PYTHON_DIR: dir, HS_KEY: "" } }
    );
    out = r.stdout + r.stderr;
  } catch (e) {
    code = e.code ?? 1;
    out = (e.stdout ?? "") + (e.stderr ?? "");
  } finally {
    await new Promise((r) => server.close(r));
  }
  return { code, out };
}

const VALID = { rules: ["naming", "mcp", "n8n", "python-adapters"], reason: REASON };

test("a properly declared exemption lets the gate pass", async () => {
  const { code, out } = await runGate(spec({ exempt: VALID }));
  assert.equal(code, 0, `expected green, got:\n${out}`);
  assert.match(out, /exemptions \(1\)/, "the exemption is reported on every run, not hidden");
  assert.ok(out.includes(REASON.slice(0, 40)), "its written reason is printed");
  assert.match(out, /register_agent.*exempt/, "the table records absence as exempt, never as covered");
});

test("DELIBERATE VIOLATION: remove the exemption and the same spec goes red", async () => {
  const { code, out } = await runGate(spec());
  assert.equal(code, 1, "an unexcused gap must still fail");
  assert.match(out, /breaks the \/v1\/<kebab> naming rule/);
  assert.match(out, /n8n node reaches 2\/3/);
  assert.match(out, /Python adapters reach 2\/3/);
});

test("DELIBERATE VIOLATION: an exemption does not cover a different operation's gap", async () => {
  // register_agent is properly exempt; score_entity is simply missing from both surfaces.
  const { code, out } = await runGate(spec({ exempt: VALID }), {
    nodeOps: ["rank-topk"],
    pyOps: ["rank_topk"],
  });
  assert.equal(code, 1, "one operation's exemption must not excuse another's gap");
  assert.match(out, /missing: score_entity/);
});

test("DELIBERATE VIOLATION: an exemption naming no rules is rejected, not honoured", async () => {
  const { code, out } = await runGate(spec({ exempt: true }));
  assert.equal(code, 1);
  assert.match(out, /invalid x-hs-surface-exempt — it names no rules/);
});

test("DELIBERATE VIOLATION: an exemption with no written reason is rejected", async () => {
  const { code, out } = await runGate(spec({ exempt: { rules: ["naming", "n8n", "python-adapters"], reason: "   " } }));
  assert.equal(code, 1);
  assert.match(out, /invalid x-hs-surface-exempt — its reason is empty/);
});

test("DELIBERATE VIOLATION: an unknown rule name is an error, not a silent no-op", async () => {
  // A typo must not quietly excuse nothing (or, worse, read as excusing everything).
  const { code, out } = await runGate(spec({ exempt: { rules: ["naming", "n8n-node"], reason: REASON } }));
  assert.equal(code, 1);
  assert.match(out, /unknown rule\(s\): n8n-node/);
});

test("an exemption is scoped to the rules it names", async () => {
  // Exempt from naming only: the surface gaps must still fail.
  const { code, out } = await runGate(spec({ exempt: { rules: ["naming"], reason: REASON } }));
  assert.equal(code, 1, "naming was excused; the coverage gaps were not");
  assert.doesNotMatch(out, /breaks the \/v1\/<kebab> naming rule/);
  assert.match(out, /missing: register_agent/);
});
