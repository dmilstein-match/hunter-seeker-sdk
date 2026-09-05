#!/usr/bin/env bash
# Pull the published spec by tool-contract version and fail if it differs from what is committed.
# Usage: scripts/pull_spec.sh 2.0.0
set -euo pipefail
VER="${1:?tool contract version, e.g. 2.0.0}"
BASE="${HS_SPEC_BASE:-https://hunter-seeker.io/api/docs}"
tmp=$(mktemp -d)
curl -fsSL "$BASE/openapi.json?version=$VER" -o "$tmp/openapi.json"
curl -fsSL "$BASE/openapi-agent-actions.json?version=$VER" -o "$tmp/openapi-agent-actions.json"
for f in openapi.json openapi-agent-actions.json; do
  if ! cmp -s "$tmp/$f" "openapi/$f"; then
    echo "openapi/$f differs from the published $VER spec:"; diff <(python3 -m json.tool "openapi/$f") <(python3 -m json.tool "$tmp/$f") | head -40 || true
    echo "run: cp $tmp/$f openapi/$f && commit"; exit 1
  fi
done
echo "spec matches published $VER"
