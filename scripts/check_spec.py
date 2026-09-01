#!/usr/bin/env python3
"""Refuse to publish an OpenAPI document that still carries placeholder schemas.

The master spec is generated in the PRODUCT repo (the tool definitions are private) and
published at https://hunter-seeker.net/api/docs/openapi.json. This repo PULLS it by tag
(scripts/pull_spec.sh). Until the product's build replaces the eight existing tools'
placeholder schemas, the file here says `"description": "owned by packages/mcp"` — and a
generated SDK from that would be a lie. So this check is required in CI and blocks release.
"""
import json, sys, pathlib
root = pathlib.Path(__file__).parents[1]
bad = 0
for name in ("openapi.json", "openapi-agent-actions.json"):
    doc = json.loads((root / "openapi" / name).read_text())
    for k, v in (doc.get("components", {}).get("schemas") or {}).items():
        if isinstance(v, dict) and v.get("description") == "owned by packages/mcp":
            print(f"{name}: placeholder schema {k}"); bad += 1
    if doc.get("openapi") != "3.1.0": print(f"{name}: not OpenAPI 3.1.0"); bad += 1
    if not doc.get("info", {}).get("version"): print(f"{name}: no info.version"); bad += 1
print("spec ok" if not bad else f"{bad} problem(s) — do not publish")
sys.exit(1 if bad else 0)
