# Changelog

## 2.0.0 — unreleased
- Python client for the full tool contract 2.0.0 (rank, score, verify, report, attest, evidence, drift, bundle).
- LangChain/LangGraph and CrewAI tool adapters; `hs` CLI with `init`, `rank`, `score`, `verify`, `sample`.
- n8n community node (unverified until published with provenance).
- Four Agent Skills.
- OpenAPI 3.1 contract pulled from the product; release is blocked by `scripts/check_spec.py` until placeholder schemas are replaced.
- `Client.verify` treats a missing or empty signature as `invalid_signature` (unsigned mode is dev-only on the server).
