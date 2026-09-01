"""`hs` — the command line.

  hs init leads.csv           propose entity/outcome columns (propose-and-gate), write hs.yaml
  hs rank                     run hs.yaml (one billed run) and print model_ref + verdict id
  hs score '{"tenure":14}'    score one row against the model_ref in hs.yaml
  hs verify v.json s.json     keyless verification
  hs sample                   rank a hosted sample dataset (free) — the five-minute test
"""
from __future__ import annotations

import csv
import json
import os
import sys
from pathlib import Path

from .client import Client, HunterSeekerError


def _client() -> Client:
    key = os.environ.get("HS_API_KEY")
    if not key:
        sys.exit("set HS_API_KEY (hsk_test_... reaches the free sample datasets)")
    return Client(api_key=key, base_url=os.environ.get("HS_BASE_URL", "https://hunter-seeker.net/api"))


def _propose(path: Path) -> dict:
    """Local first pass: enumerate binary-looking and id-looking columns. The server-side
    /resolve-spec gate is authoritative; this only writes candidates for the human to confirm."""
    with path.open(newline="") as f:
        rows = list(csv.DictReader(f))
    cols = rows[0].keys() if rows else []
    n = len(rows)
    ids, outs = [], []
    for c in cols:
        vals = [r[c] for r in rows if r.get(c) not in (None, "")]
        distinct = set(vals)
        if n and len(distinct) == n:
            ids.append(c)
        low = {v.strip().lower() for v in distinct}
        if low and low <= {"0", "1", "true", "false", "yes", "no", "y", "n"}:
            outs.append(c)
    return {"rows": n, "entity_candidates": ids, "outcome_candidates": outs}


def main(argv=None) -> int:
    a = list(argv or sys.argv[1:])
    if not a or a[0] in ("-h", "--help"):
        print(__doc__); return 0
    cmd, rest = a[0], a[1:]
    try:
        if cmd == "init":
            p = Path(rest[0]); prop = _propose(p)
            def pick(kind, cands):
                if len(cands) == 1: return cands[0]
                if not cands: return None
                print(f"{kind}: choose one of {cands}"); return None  # ≥2 → surface a choice, never guess
            spec = {"dataset": str(p), "entity_column": pick("entity", prop["entity_candidates"]),
                    "outcome_column": pick("outcome", prop["outcome_candidates"]), "subject_kind": "org", "k": 20}
            Path("hs.yaml").write_text("".join(f"{k}: {json.dumps(v)}\n" for k, v in spec.items()))
            print(json.dumps({"proposed": prop, "wrote": "hs.yaml"}, indent=2)); return 0
        hs = _client()
        if cmd == "sample":
            out = hs.rank_topk(dataset_id="sample:saas_churn", entity_column="customer_id", outcome_column="churned", subject_kind="org")
            print(json.dumps({k: out.get(k) for k in ("ranking_ref", "model_ref", "honest_empty")}, indent=2))
            if out.get("verdict"):
                print("verify:", hs.verify(out["verdict"], out["signature"]))
            return 0
        spec = {l.split(":")[0]: json.loads(l.split(":", 1)[1]) for l in Path("hs.yaml").read_text().splitlines() if l.strip()}
        if cmd == "rank":
            csv_text = Path(spec["dataset"]).read_text()
            out = hs.rank_topk(csv=csv_text, entity_column=spec["entity_column"], outcome_column=spec["outcome_column"],
                               subject_kind=spec["subject_kind"], k=spec.get("k", 20))
            spec["model_ref"] = out.get("model_ref")
            Path("hs.yaml").write_text("".join(f"{k}: {json.dumps(v)}\n" for k, v in spec.items()))
            print(json.dumps({k: out.get(k) for k in ("ranking_ref", "model_ref", "honest_empty")}, indent=2)); return 0
        if cmd == "score":
            out = hs.score_entity(spec["model_ref"], json.loads(rest[0]), subject_kind=spec["subject_kind"])
            print(json.dumps(out["entity"], indent=2))
            st = hs.verify(out["verdict"], out.get("signature"))
            print("verify:", st + ("" if st == "valid" else "  (do not act on an unverified Verdict)")); return 0
        if cmd == "verify":
            v, s = json.load(open(rest[0])), json.load(open(rest[1])); print(hs.verify(v, s)); return 0
        print(__doc__); return 2
    except HunterSeekerError as e:
        print(json.dumps({"error": e.problem.code, "detail": e.problem.detail, "remedy": e.problem.remedy}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
