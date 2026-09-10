"""`hs` — the command line.

  hs signup                   mint a samples-only key with no account, and write it to hs.yaml
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
import re
import sys
from pathlib import Path

from .client import Client, HunterSeekerError


def _base_url() -> str:
    return os.environ.get("HS_BASE_URL", "https://hunter-seeker.io/api")


SPEC_PATH = Path("hs.yaml")

# A key is `hsk_live_`/`hsk_test_` followed by 24 random bytes as hex - 57 characters, always.
# The minting side is `generateKey` in db/partner-keys.ts (KEY_BYTES = 24).
KEY_RE = re.compile(r"^hsk_(?:live|test)_[0-9a-f]{48}$")

# What the docs and examples put where a key goes. A credential that is present but fake
# otherwise reaches the server and comes back a bare 401, which an agent reads as "my
# credentials were rejected" - and retries - rather than "I sent the example from the README".
_PLACEHOLDER_MARKS = ("...", "\u2026", "<", ">", "your", "example", "xxx", "here")


def _read_spec(path: Path = SPEC_PATH) -> dict:
    """Parse hs.yaml. Deliberately tolerant: `hs init` proposes and a human edits.

    Comments, blank lines and unquoted YAML scalars used to raise out of three separate
    ad-hoc copies of this parse - including one that ran AFTER `hs signup` had minted a
    key, so the crash lost a credential the server shows exactly once.
    """
    try:
        text = path.read_text()
    except OSError:
        return {}
    spec: dict = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, _, raw = line.partition(":")
        try:
            spec[key.strip()] = json.loads(raw)
        except ValueError:
            spec[key.strip()] = raw.strip()   # a bare scalar, e.g. `subject_kind: org`
    return spec


def _write_spec(spec: dict, path: Path = SPEC_PATH) -> None:
    """Write the spec atomically, keeping the file's comments and their order.

    Atomic because `hs signup` persists a key shown EXACTLY ONCE: a half-written hs.yaml
    strands the tenant it belongs to. Keys absent from `spec` are dropped, so a re-`hs init`
    cannot leave a stale model_ref behind pointing at a model fitted on another dataset.
    """
    kept: list[str] = []
    seen: set[str] = set()
    try:
        existing = path.read_text().splitlines()
    except OSError:
        existing = []
    for line in existing:
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            kept.append(line)                                   # comment / blank / not ours
            continue
        key = line.partition(":")[0].strip()
        if key in spec and key not in seen:
            kept.append(f"{key}: {json.dumps(spec[key])}")
            seen.add(key)
    kept += [f"{k}: {json.dumps(v)}" for k, v in spec.items() if k not in seen]
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("\n".join(kept) + "\n")
    os.replace(tmp, path)


def _stored_key() -> str | None:
    """The key `hs signup` wrote, if there is one. HS_API_KEY still wins."""
    key = _read_spec().get("api_key")
    return key if isinstance(key, str) else None


def _key_problem(key: str, source: str) -> str | None:
    """Why this cannot be a Hunter-Seeker key - or None if it is shaped like one.

    Decided locally so the answer names the cause. A malformed key sent to the server
    returns 401, which is indistinguishable from a revoked one and invites a retry loop.
    """
    if KEY_RE.match(key):
        return None
    shown = key[:13] + "..." if len(key) > 13 else key          # never echo a whole key
    if any(m in key.lower() for m in _PLACEHOLDER_MARKS):
        return (f"{source} holds {shown!r} - that is the placeholder from the documentation, "
                "not a key. `hs signup` mints a real one: no account, no email, no card.")
    if not key.startswith(("hsk_live_", "hsk_test_")):
        return (f"{source} holds {shown!r}, which is not a Hunter-Seeker key. One begins "
                "`hsk_live_` or `hsk_test_`.")
    if len(key) != 57:
        return (f"{source} holds {shown!r}, which is {len(key)} characters. A Hunter-Seeker key "
                "is always 57: the prefix plus 48 hex characters.")
    return (f"{source} holds {shown!r}: the right length, but the 48 characters after the prefix "
            "must be hex (0-9, a-f).")


def _fail(error: str, detail: str, remedy: str) -> None:
    """Every failure leaves by the same door, in the shape the rest of the CLI already uses,
    because the caller is usually an agent parsing stderr rather than a person reading it."""
    print(json.dumps({"error": error, "detail": detail, "remedy": remedy}, indent=2), file=sys.stderr)
    raise SystemExit(1)


def _client() -> Client:
    raw, source = os.environ.get("HS_API_KEY"), "HS_API_KEY"
    if not raw:
        raw, source = _stored_key(), "hs.yaml"
    if not raw:
        _fail("no_credential",
              "No HS_API_KEY in the environment and no api_key in hs.yaml.",
              "Run `hs signup` for a samples-only key (no account, no email, no card), "
              "or set HS_API_KEY.")
    key = raw.strip()          # a key pasted into CI or a .env arrives carrying a newline
    problem = _key_problem(key, source)
    if problem:
        _fail("malformed_key", problem,
              "Run `hs signup` to mint a samples-only key, or set HS_API_KEY to a real one. "
              "The key was not sent: this was decided locally from its shape.")
    return Client(api_key=key, base_url=_base_url())


def _signup(agent_caller: str, force: bool) -> int:
    """B12 — the one unauthenticated call, from the command line.

    It writes the key to `hs.yaml` beside the rest of the project's settings rather than to a
    dotfile in $HOME: the key is scoped to THIS project's tenant, and a global one would be the
    wrong thing the moment somebody has two.

    IT REFUSES TO OVERWRITE. A second `hs signup` in a directory that already holds a key would
    silently strand the first one — its tenant, its model_refs and its reported outcomes still
    exist and are now unreachable, because the raw key was shown once and never stored anywhere
    else. `--force` is the way to say you meant it.
    """
    import urllib.error
    import urllib.request

    existing = _stored_key()
    if existing and not force:
        print(
            json.dumps({
                "error": "key_exists",
                "detail": f"hs.yaml already holds {existing[:14]}... Registering again would strand it: "
                          "its tenant, model_refs and reported outcomes stay alive but the key was shown "
                          "once and is not recoverable.",
                "remedy": "Use the key you have, or pass --force if you really want a new tenant.",
            }, indent=2),
            file=sys.stderr,
        )
        return 1

    req = urllib.request.Request(
        f"{_base_url()}/v1/agents/register",
        data=json.dumps({"agent_caller": agent_caller}).encode(),
        headers={"content-type": "application/json", "user-agent": "hunter-seeker-cli"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            out = json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            p = json.loads(body)
            detail, remedy = p.get("detail", body), (p.get("hs") or {}).get("remedy", "")
        except ValueError:
            detail, remedy = body, ""
        print(json.dumps({"error": f"http_{e.code}", "detail": detail, "remedy": remedy}, indent=2), file=sys.stderr)
        # 429 carries Retry-After; surfacing it beats making the caller parse a header.
        if e.code == 429 and e.headers.get("Retry-After"):
            print(f"retry after {e.headers['Retry-After']}s", file=sys.stderr)
        return 1
    except urllib.error.URLError as e:
        print(json.dumps({"error": "unreachable", "detail": str(e.reason)}, indent=2), file=sys.stderr)
        return 1

    key = out.get("api_key")
    if not isinstance(key, str) or not key:
        _fail("no_key_in_response",
              "register returned no api_key. Nothing was written.",
              "Retry `hs signup`. If it repeats, the registration endpoint is the problem.")

    # PRINT BEFORE PERSISTING. The server shows this key exactly once, so anything that can
    # fail must happen after it is on the caller's terminal - a write error here used to
    # leave a minted tenant unreachable forever.
    print(f"\nexport HS_API_KEY={key}", file=sys.stderr)

    spec = _read_spec()
    spec["api_key"] = key
    spec["agent_id"] = out.get("agent_id")
    try:
        _write_spec(spec)
        wrote = "hs.yaml"
    except OSError as e:
        print(json.dumps({
            "error": "key_not_persisted",
            "detail": f"the key printed above was minted, but hs.yaml could not be written: {e}",
            "remedy": "Save that export line now. The key is not recoverable from the server.",
        }, indent=2), file=sys.stderr)
        wrote = None

    print(json.dumps({
        "wrote": wrote,
        "mode": out.get("mode"),
        "agent_id": out.get("agent_id"),
        "claim_url": out.get("claim_url"),
        "next": "hs sample",
    }, indent=2))
    return 0 if wrote else 1


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


def _report(out: dict) -> None:
    """Print a rank result the way the response is actually shaped.

    There is no top-level `honest_empty` field - never has been. A refusal is
    {result: "none", reasons, retry, guidance}; `honest_empty` lives inside a Verdict and in
    hs_context_brief. Reading ranking_ref/model_ref/honest_empty therefore printed three nulls
    and swallowed every reason, so the product's headline guarantee looked like a broken call on
    the first command a new user runs.

    The n8n node already gets this right - `result === "none"` leaves by its own door, pinned by
    a named test. This is that discipline in Python.
    """
    if out.get("result") == "none":
        print(json.dumps({k: out[k] for k in ("result", "reasons", "retry", "guidance") if k in out}, indent=2))
        return
    shown = {k: out[k] for k in ("ranking_ref", "model_ref", "top_decile_lift") if k in out}
    # A run can CLEAR the bar and still carry model_ref: null - below the holdout floor the engine
    # caches no scorecard, so the ranking is real while the decision tools are unavailable for it.
    # Say that, rather than letting a null read as a failure.
    if out.get("model_ref") is None:
        shown["note"] = "no model_ref for this run - the ranking stands, but hs score is unavailable for it"
    print(json.dumps(shown, indent=2))


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
            # Carry the credential across a re-init - overwriting hs.yaml used to delete the key
            # `hs signup` had just written. model_ref is deliberately NOT carried: it belonged to
            # whatever dataset was configured before this call.
            prior = _read_spec()
            spec.update({k: prior[k] for k in ("api_key", "agent_id") if k in prior})
            _write_spec(spec)
            print(json.dumps({"proposed": prop, "wrote": "hs.yaml"}, indent=2)); return 0
        if cmd == "signup":
            caller = "hs-cli"
            if "--agent-caller" in rest:
                i = rest.index("--agent-caller")
                if i + 1 < len(rest):
                    caller = rest[i + 1]
            return _signup(caller, force="--force" in rest)
        hs = _client()
        if cmd == "sample":
            out = hs.rank_topk(dataset_id="sample:saas_churn", entity_column="customer_id", outcome_column="churned", subject_kind="org")
            _report(out)
            if out.get("verdict"):
                print("verify:", hs.verify(out["verdict"], out["signature"]))
            return 0
        spec = _read_spec()
        if cmd == "rank":
            csv_text = Path(spec["dataset"]).read_text()
            out = hs.rank_topk(csv=csv_text, entity_column=spec["entity_column"], outcome_column=spec["outcome_column"],
                               subject_kind=spec["subject_kind"], k=spec.get("k", 20))
            # Persist ONLY a real model_ref. Writing out.get("model_ref") unconditionally put
            # model_ref: null into hs.yaml on every refusal AND on every cleared-but-uncached
            # run, clobbering a previously good ref and firing the next `hs score` at a null.
            if out.get("model_ref"):
                spec["model_ref"] = out["model_ref"]
                _write_spec(spec)
            _report(out)
            return 0 if out.get("result") != "none" else 1
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
