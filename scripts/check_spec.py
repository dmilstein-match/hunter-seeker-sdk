#!/usr/bin/env python3
"""Refuse to publish an OpenAPI document that still carries placeholder schemas.

The master spec is generated in the PRODUCT repo (the tool definitions are private) and
published at https://hunter-seeker.io/api/docs/openapi.json. This repo PULLS it by tag
(scripts/pull_spec.sh). A placeholder reads `"description": "owned by packages/mcp"`, and a
generated SDK built from one would be a lie — so this check is required in CI and blocks release.

WHAT IS LEFT, AND WHY IT IS NOT A WIRING BUG. The eight existing tools' INPUT schemas are now
real: they are exported from the product's running MCP server by a genuine tools/list
(packages/mcp/scripts/export-tool-schemas.mts), so they are exactly what a client is told.
The remaining placeholders are OUTPUT schemas for seven tools that declare none upstream —
server.ts records that declaring them is queued for contract 2.0.0. They cannot be "wired in",
because there is nothing to wire: an output schema is a promise about what the server returns,
and inventing one to turn this gate green would be the worst possible way to pass it.
"""
import json, sys, pathlib
root = pathlib.Path(__file__).parents[1]
bad = 0
for name in ("openapi.json", "openapi-agent-actions.json"):
    doc = json.loads((root / "openapi" / name).read_text())
    for k, v in (doc.get("components", {}).get("schemas") or {}).items():
        if isinstance(v, dict) and v.get("description") == "owned by packages/mcp":
            why = ("no outputSchema declared upstream (server.ts: queued for 2.0.0)"
                   if k.endswith("_output") else "NOT EXPORTED — re-run export-tool-schemas.mts")
            print(f"{name}: placeholder {k} — {why}"); bad += 1
    if doc.get("openapi") != "3.1.0": print(f"{name}: not OpenAPI 3.1.0"); bad += 1
    if not doc.get("info", {}).get("version"): print(f"{name}: no info.version"); bad += 1
print("spec ok" if not bad else
      f"{bad} problem(s) — do not publish. Declaring the missing outputSchemas is a "
      f"contract decision, not a build fix.")
sys.exit(1 if bad else 0)
