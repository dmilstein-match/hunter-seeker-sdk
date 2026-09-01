from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

DEFAULT_BASE = "https://hunter-seeker.net/api"


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
        data = json.dumps(body or {}).encode() if method == "POST" else None
        req = urllib.request.Request(self.base + path, data=data, method=method, headers={
            "authorization": self._auth, "content-type": "application/json",
            "user-agent": "hunter-seeker-python/2.0.0",
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

    def rank_topk(self, *, entity_column: str, outcome_column: str, subject_kind: str,
                  dataset_id: Optional[str] = None, rows: Optional[list] = None, csv: Optional[str] = None,
                  fetch_url: Optional[str] = None, k: int = 20, horizon: Optional[str] = None,
                  acknowledge_decision_support: bool = False, reading: Optional[Mapping[str, Any]] = None,
                  refit_of: Optional[str] = None, idempotency_key: Optional[str] = None,
                  wait: bool = True, poll_s: float = 2.0) -> Dict[str, Any]:
        data = {k_: v for k_, v in {"dataset_id": dataset_id, "rows": rows, "csv": csv, "fetch_url": fetch_url}.items() if v}
        body: Dict[str, Any] = {"data": data, "entity_column": entity_column, "outcome_column": outcome_column,
                                "subject_kind": subject_kind, "page": {"k": k},
                                "acknowledge_decision_support": acknowledge_decision_support}
        if horizon: body["horizon"] = horizon
        if reading: body["reading"] = dict(reading)
        if refit_of: body["refit_of"] = refit_of
        key = idempotency_key or str(uuid.uuid4())
        body["idempotency_key"] = key
        out = self._call("/v1/rank-topk", body, idempotency_key=key)
        while wait and out.get("status") == "pending":
            time.sleep(max(poll_s, out.get("retry_after_ms", 0) / 1000))
            out = self.poll_task(out["task_id"])
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

    def verify(self, verdict: Mapping[str, Any], signature: Optional[Mapping[str, str]], *, offline: bool = True) -> str:
        """Offline by default via hs-verify (no network beyond JWKS). Falls back to the API.

        A Verdict with no signature is UNVERIFIABLE and is reported as "invalid_signature":
        production deployments always sign, so a missing signature means a misconfigured or
        non-production server, never a valid decision.
        """
        if not signature or not signature.get("protected") or not signature.get("signature"):
            return "invalid_signature"
        if offline:
            try:
                from hs_verify import verify as _v  # type: ignore
                return _v(verdict, signature)
            except ImportError:
                pass
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
