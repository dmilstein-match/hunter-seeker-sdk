from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional, Sequence

from ._version import __version__

DEFAULT_BASE = "https://hunter-seeker.io/api"


def _json_default(o: Any) -> Any:
    """Dates go out as ISO-8601; nothing else is guessed at.

    The Ledger accepts a `datetime` ts (parse_ts does), and gate() sends the row as-is, so without
    this every scored, batched or uploaded row carrying one died in json.dumps. Anything else still
    raises TypeError rather than being str()-ed into a value the engine would misread."""
    import datetime as _dt
    if isinstance(o, _dt.date):          # covers datetime, a date subclass
        return o.isoformat()
    raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")


@dataclass(frozen=True)
class ProblemDetails:
    status: int
    code: str
    detail: str
    remedy: str
    field: Optional[str]
    request_id: Optional[str]


class HunterSeekerError(Exception):
    def __init__(self, p: ProblemDetails) -> None:
        super().__init__(f"{p.code}: {p.detail} — {p.remedy}")
        self.problem = p

    @property
    def retryable(self) -> bool:
        return self.problem.status in (429, 503)


class Client:
    def __init__(self, api_key: Optional[str] = None, *, oauth_token: Optional[str] = None,
                 base_url: str = DEFAULT_BASE, timeout: float = 60.0) -> None:
        if not (api_key or oauth_token):
            raise ValueError("provide api_key (hsk_...) or oauth_token")
        self._auth = f"Bearer {oauth_token or api_key}"
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.test_mode = bool(api_key and api_key.startswith("hsk_test_"))

    # -- transport ---------------------------------------------------------- #
    def _call(self, path: str, body: Optional[Mapping[str, Any]] = None, *, method: str = "POST",
              idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        data = json.dumps(body or {}, default=_json_default).encode() if method == "POST" else None
        req = urllib.request.Request(self.base + path, data=data, method=method, headers={
            "authorization": self._auth, "content-type": "application/json",
            "user-agent": f"hunter-seeker-python/{__version__}",
            **({"idempotency-key": idempotency_key} if idempotency_key else {}),
        })
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:  # noqa: S310
                return json.load(r)
        except urllib.error.HTTPError as e:
            try:
                prob = json.load(e)
                hs = prob.get("hs") or (prob.get("detail") or {}).get("hs") or {}
                det = prob.get("detail") if isinstance(prob.get("detail"), str) else (prob.get("detail") or {}).get("detail", "")
            except Exception:  # noqa: BLE001
                hs, det = {}, e.reason
            raise HunterSeekerError(ProblemDetails(e.code, hs.get("code", "http_error"), det or str(e.reason),
                                                   hs.get("remedy", "see docs"), hs.get("field"),
                                                   e.headers.get("x-request-id"))) from None

    # -- existing surface --------------------------------------------------- #
    def describe_capabilities(self) -> Dict[str, Any]:
        return self._call("/v1/describe-capabilities")

    def provide_dataset(self, *, fetch_url: Optional[str] = None, name: Optional[str] = None) -> Dict[str, Any]:
        return self._call("/v1/provide-dataset", {k: v for k, v in {"fetch_url": fetch_url, "name": name}.items() if v})

    def append_rows(self, rows: Sequence[Mapping[str, Any]], *, dataset_id: Optional[str] = None,
                    chunk_index: int = 0, name: Optional[str] = None) -> Dict[str, Any]:
        """Send ONE chunk. Most callers want `upload_rows` below, which does the loop."""
        body: Dict[str, Any] = {"rows": list(rows), "chunk_index": chunk_index}
        if dataset_id: body["dataset_id"] = dataset_id
        if name and chunk_index == 0: body["name"] = name
        return self._call("/v1/append-rows", body)

    def upload_rows(self, rows: Sequence[Mapping[str, Any]], *, chunk_size: int = 1500,
                    name: Optional[str] = None) -> str:
        """Send a large table one chunk at a time and return the dataset_id to rank with.

        THE DOOR THAT ALWAYS WORKS. The other large-data paths need the open internet from YOUR
        side — a presigned upload_url points at s3.amazonaws.com, and fetch_url means hosting a
        public URL of your own — so behind an egress proxy, or in a sandbox, neither is reachable.
        This travels the connection you are already using. It is slower than a single PUT, which is
        the right trade: minutes rather than impossible. If you CAN reach S3, prefer
        `provide_dataset()` and PUT the file.

        Chunking cannot change the result. Every chunk is sent with the SAME column order as the
        first (taken from the first row), and chunks are assembled in index order — row order is
        load-bearing, because the engine splits train/gate/test by position. The assembled bytes are
        the bytes a single upload would have produced.

        Retries are safe: re-sending a chunk_index that already landed is a no-op, so a dropped
        connection costs one chunk and not the upload.
        """
        rows = list(rows)
        if not rows:
            raise ValueError("upload_rows needs at least one row")
        if chunk_size < 1:
            raise ValueError("chunk_size must be >= 1")
        # Column order is fixed HERE, once, from the first row. Passing each chunk's own dict order
        # would let a differently-ordered dict get the chunk refused mid-upload.
        columns = list(rows[0].keys())
        dataset_id: Optional[str] = None
        for index, start in enumerate(range(0, len(rows), chunk_size)):
            chunk = [{c: r.get(c) for c in columns} for r in rows[start:start + chunk_size]]
            out = self.append_rows(chunk, dataset_id=dataset_id, chunk_index=index, name=name)
            dataset_id = out.get("dataset_id") or dataset_id
            if not dataset_id:
                raise HunterSeekerError(ProblemDetails(502, "no_dataset_id",
                                                       "the server returned no dataset_id for chunk 0",
                                                       "retry the upload", None, None))
        return dataset_id  # type: ignore[return-value]

    #: The engine's own published run ceiling — hs_describe_capabilities reports
    #: limits.completion.run_timeout_seconds = 3600. A run cannot outlive it, so a client that waits
    #: longer than this is not being patient, it is hung.
    RUN_TIMEOUT_S = 3600.0

    def rank_topk(self, *, entity_column: str, outcome_column: str, subject_kind: str,
                  dataset_id: Optional[str] = None, rows: Optional[list] = None, csv: Optional[str] = None,
                  fetch_url: Optional[str] = None, k: int = 20, offset: int = 0,
                  outcome_is_desirable: Optional[bool] = None,
                  horizon: Optional[str] = None,
                  acknowledge_decision_support: bool = False, reading: Optional[Mapping[str, Any]] = None,
                  refit_of: Optional[str] = None, idempotency_key: Optional[str] = None,
                  wait: bool = True, poll_s: float = 2.0,
                  timeout_s: Optional[float] = None,
                  on_progress: Optional[Callable[[Dict[str, Any]], None]] = None) -> Dict[str, Any]:
        """Rank a table. The only call that costs a run.

        `outcome_is_desirable` — TRUE for an outcome you WANT (converted, renewed, paid_in_full),
        FALSE for one you want to avoid (churned, defaulted, failed). Forwarded ONLY when you state
        it: passing a default here would author a polarity you never gave, and polarity is what
        decides which way every lever reads. Left unstated, the engine resolves it from the outcome
        column NAME, which it says plainly is unreliable for arbitrary names.

        `timeout_s` bounds the whole wait, not one HTTP request (that is `Client.timeout`). Defaults
        to the engine's own 3,600s run ceiling: past that the run cannot still be alive, so waiting
        longer only hangs an unattended agent.

        `on_progress` is called with each pending envelope, which is the only way to see `stage`
        and `facts_so_far` — a million-row run is a ~40-minute job, and without this it is
        indistinguishable from a hung process. Those facts are leak-firewalled PROGRESS, never a
        partial ranking: report them, never quote them as a result.
        """
        # Membership, not truthiness. `csv=""` and `rows=[]` are caller mistakes worth a clear local
        # error; silently dropping them sent an empty `data` and produced a confusing server 422.
        data = {k_: v for k_, v in {"dataset_id": dataset_id, "rows": rows, "csv": csv,
                                    "fetch_url": fetch_url}.items() if v is not None}
        if not data:
            raise ValueError("pass exactly one of dataset_id / rows / csv / fetch_url")
        empty = [k_ for k_, v in data.items() if not v]
        if empty:
            raise ValueError(f"{empty[0]} is empty - there is nothing to rank. "
                             f"The old truthiness filter dropped it from the request instead, "
                             f"which sent an empty `data` and produced a confusing server 422.")
        body: Dict[str, Any] = {"data": data, "entity_column": entity_column, "outcome_column": outcome_column,
                                "subject_kind": subject_kind,
                                "page": {"k": k, **({"offset": offset} if offset else {})},
                                "acknowledge_decision_support": acknowledge_decision_support}
        # Forwarded ONLY when stated — see the docstring. The n8n node has the same three-state rule.
        if outcome_is_desirable is not None: body["outcome_is_desirable"] = bool(outcome_is_desirable)
        if horizon: body["horizon"] = horizon
        if reading: body["reading"] = dict(reading)
        if refit_of: body["refit_of"] = refit_of
        key = idempotency_key or str(uuid.uuid4())
        body["idempotency_key"] = key
        out = self._call("/v1/rank-topk", body, idempotency_key=key)
        deadline = time.monotonic() + (self.RUN_TIMEOUT_S if timeout_s is None else timeout_s)
        while wait and out.get("status") == "pending":
            if on_progress is not None:
                on_progress(out)          # `stage` + `facts_so_far` live here and nowhere else
            task_id = out.get("task_id")
            if not task_id:
                raise HunterSeekerError(ProblemDetails(502, "no_task_id",
                                                       "a pending response carried no task_id",
                                                       "retry the submit", None, None))
            if time.monotonic() >= deadline:
                raise HunterSeekerError(ProblemDetails(
                    504, "poll_timeout",
                    f"still pending after {(self.RUN_TIMEOUT_S if timeout_s is None else timeout_s):.0f}s",
                    f"the run may still finish - poll_task({task_id!r}) to check, and do not re-submit "
                    f"(that would cost a second run)", None, None))
            time.sleep(max(poll_s, out.get("retry_after_ms", 0) / 1000))
            out = self.poll_task(task_id)
        return out

    def poll_task(self, task_id: str) -> Dict[str, Any]:
        return self._call("/v1/poll-task", {"task_id": task_id})

    def model_quality(self, ranking_ref: str) -> Dict[str, Any]:
        return self._call("/v1/model-quality", {"ranking_ref": ranking_ref})

    def explain_drivers(self, ranking_ref: str) -> Dict[str, Any]:
        return self._call("/v1/explain-drivers", {"ranking_ref": ranking_ref})

    def explain_levers(self, ranking_ref: str, entity_ids: list[str]) -> Dict[str, Any]:
        return self._call("/v1/explain-levers", {"ranking_ref": ranking_ref, "entity_ids": entity_ids})

    def context_brief(self, ranking_ref: str, fmt: str = "json") -> Dict[str, Any]:
        return self._call("/v1/context-brief", {"ranking_ref": ranking_ref, "format": fmt})

    # -- verdict layer ------------------------------------------------------- #
    def score_entity(self, model_ref: str, row: Mapping[str, Any], *, subject_kind: str,
                     entity_id: Optional[str] = None, acknowledge_decision_support: bool = False,
                     on_behalf_of: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
        body = {"model_ref": model_ref, "row": dict(row), "subject_kind": subject_kind,
                "acknowledge_decision_support": acknowledge_decision_support}
        if entity_id: body["entity_id"] = entity_id
        if on_behalf_of: body["on_behalf_of"] = dict(on_behalf_of)
        return self._call("/v1/score-entity", body)

    def score_batch(self, model_ref: str, rows: list, *, subject_kind: str, entity_column: Optional[str] = None,
                    acknowledge_decision_support: bool = False, as_of: Optional[str] = None) -> Dict[str, Any]:
        body = {"model_ref": model_ref, "rows": rows, "subject_kind": subject_kind,
                "acknowledge_decision_support": acknowledge_decision_support}
        if entity_column: body["entity_column"] = entity_column
        if as_of: body["as_of"] = as_of
        return self._call("/v1/score-batch", body)

    def verify(self, verdict: Mapping[str, Any], signature: Optional[Mapping[str, str]], *,
               offline: bool = True, jwks: Optional[Mapping[str, Any]] = None) -> str:
        """Offline by default via hs-verify. Pass ``jwks`` to avoid the network entirely.

        A Verdict with no signature is UNVERIFIABLE and is reported as "invalid_signature":
        production deployments always sign, so a missing signature means a misconfigured or
        non-production server, never a valid decision.
        """
        if not signature or not signature.get("protected") or not signature.get("signature"):
            return "invalid_signature"
        if offline:
            try:
                from hs_verify import verify as _v  # type: ignore
            except ImportError:
                pass
            else:
                # `jwks` makes this genuinely offline. Without it hs_verify fetches the
                # published keys, and an unreachable JWKS RAISES rather than reporting the
                # Verdict as invalid — a network failure is not a forgery.
                return _v(verdict, signature, jwks=jwks) if jwks is not None else _v(verdict, signature)
        return self._call("/v1/verify-verdict", {"verdict": dict(verdict), "signature": dict(signature)})["status"]

    def report_outcome(self, model_ref: str, outcomes: list[Mapping[str, Any]]) -> Dict[str, Any]:
        return self._call("/v1/report-outcome", {"model_ref": model_ref, "outcomes": [dict(o) for o in outcomes]})

    def attest_action(self, *, model_ref: str, entity_id: str, lever_token: str, post_value: Any,
                      acted_at: str, event_id: Optional[str] = None) -> Dict[str, Any]:
        body = {"model_ref": model_ref, "entity_id": entity_id, "lever_token": lever_token,
                "post_value": post_value, "acted_at": acted_at}
        if event_id: body["event_id"] = event_id
        return self._call("/v1/attest-action", body)

    def action_evidence(self, model_ref: str) -> Dict[str, Any]:
        return self._call("/v1/action-evidence", {"model_ref": model_ref})

    def drift_status(self, model_ref: str) -> Dict[str, Any]:
        return self._call("/v1/drift-status", {"model_ref": model_ref})

    def export_bundle(self, verdict_id: str, entity_id: Optional[str] = None) -> Dict[str, Any]:
        body = {"verdict_id": verdict_id}
        if entity_id: body["entity_id"] = entity_id
        return self._call("/v1/export-bundle", body)
