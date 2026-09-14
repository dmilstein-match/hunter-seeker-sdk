"""The one core every runtime wrapper shares (Datagoat unit 23): `decide` reached from a
harness with a two-second budget, the customer's named fallback on any error, mechanical
attestation with the tool NAME only, and the shapes a router or a gateway reads.

    from hunter_seeker import Client
    from hunter_seeker.runtime import decide_case, attest, authorizer_response

    d = decide_case(hs, "ag_...", {"case_id": run_id, "kind": {...}, "actor": {...}, "opened_at": ts},
                    fallback="none")
    if d.route == "act": ...            # branch on ROUTE, never on lane
    attest(hs, "urn:my-runtime", run_id, tool="send_email", arm=d.arm, lever_id=d.lever_id)

Three rules every wrapper here keeps (D-58, D-59): a wrapper branches on `route` and only on
`route` (`lane` is the record's answer, not the instruction); `arm` and `lever_id` travel from the
receipt to the attestation unchanged; and nothing here ever denies — an error or a timeout is
the fallback branch with its `reason`, and what the harness does with a route is its policy.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional, Sequence

ROUTES = ("act", "review", "human", "none")
DEFAULT_TIMEOUT_S = 2.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class RouteDecision:
    """What a runtime does with one case. `route` is the only field a wrapper branches on."""
    route: str                          # act | review | human | none
    reason: str
    fallback: bool = False              # True when the route is the customer's fallback, not the receipt's
    lane: Optional[str] = None
    band: Optional[str] = None
    max_autonomy: Optional[str] = None
    likelihood_direction: Optional[str] = None
    arm: Optional[str] = None           # the receipt's lever_arm: treat | control
    lever_id: Optional[str] = None
    case_ref: Optional[str] = None
    verdict_id: Optional[str] = None
    receipt: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def route_of(receipt: Mapping[str, Any]) -> str:
    """The receipt's route, `none` when it is missing or not one of the four."""
    r = receipt.get("route")
    return r if r in ROUTES else "none"


def from_receipt(receipt: Mapping[str, Any]) -> RouteDecision:
    route = route_of(receipt)
    return RouteDecision(
        route=route,
        reason=str(receipt.get("reason") or receipt.get("rule_reason") or f"route {route}"),
        fallback=False,
        lane=receipt.get("lane"),
        band=receipt.get("band"),
        max_autonomy=receipt.get("max_autonomy"),
        likelihood_direction=receipt.get("likelihood_direction"),
        arm=receipt.get("lever_arm"),
        lever_id=receipt.get("lever_id"),
        case_ref=receipt.get("case_ref"),
        verdict_id=receipt.get("verdict_id"),
        receipt=dict(receipt),
    )


def fallback_decision(fallback: str, error: BaseException | str, case_ref: Optional[str] = None) -> RouteDecision:
    route = fallback if fallback in ROUTES else "none"
    detail = str(error)[:200] or error.__class__.__name__ if isinstance(error, BaseException) else str(error)[:200]
    return RouteDecision(route=route, reason=f"fallback: {detail}", fallback=True, case_ref=case_ref, error=detail)


def decide_case(hs: Any, agent_id: str, case: Mapping[str, Any], *, fallback: str = "none",
                timeout: float = DEFAULT_TIMEOUT_S, mode: Optional[str] = None,
                open_levers: Optional[Sequence[Mapping[str, Any]]] = None) -> RouteDecision:
    """One decision inside a `timeout` budget; any error or timeout is the fallback branch.

    `hs` is a `hunter_seeker.Client` (or anything with the same `decide` method). The call is
    never retried here — a runtime that waited longer than two seconds has already lost the
    decision point; the fallback is what the business does anyway.
    """
    started = time.monotonic()
    try:
        kwargs: Dict[str, Any] = {"mode": mode, "timeout": timeout}
        if open_levers:
            kwargs["open_levers"] = [dict(x) for x in open_levers]
        receipt = hs.decide(agent_id, case, **kwargs)
        if not isinstance(receipt, Mapping):
            return fallback_decision(fallback, "the door answered no receipt", str(case.get("case_id") or ""))
        d = from_receipt(receipt)
        if time.monotonic() - started > timeout:
            # the answer came back, but after the budget: the runtime must not have waited
            return fallback_decision(fallback, f"decide took longer than {timeout:g}s", d.case_ref)
        return d
    except Exception as e:  # noqa: BLE001 — the whole point: never raise into a runtime
        return fallback_decision(fallback, e, str(case.get("case_id") or ""))


def attestation_event(source: str, case_ref: str, tool: str, *, arm: Optional[str] = None,
                      lever_id: Optional[str] = None, at: Optional[str] = None,
                      event_id: Optional[str] = None) -> Dict[str, Any]:
    """The CloudEvent a mechanical attestation is: the tool NAME only, the arm and lever id the
    receipt carried, the case key as `subject`; never a prompt, a completion or an argument."""
    data: Dict[str, Any] = {"tool": str(tool)}
    if arm:
        data["arm"] = arm
    if lever_id:
        data["lever_id"] = lever_id
    return {
        "specversion": "1.0",
        "id": event_id or f"{case_ref}:attest:{tool}:{uuid.uuid4().hex[:8]}",
        "source": source,
        "type": "action.attested",
        "subject": case_ref,
        "time": at or _now_iso(),
        "datacontenttype": "application/json",
        "data": data,
    }


def attest(hs: Any, source: str, case_ref: str, tool: str, *, arm: Optional[str] = None,
           lever_id: Optional[str] = None, timeout: float = DEFAULT_TIMEOUT_S) -> bool:
    """Send one `action.attested` for the case; False (never an exception) when it did not land."""
    try:
        hs.ingest_events([attestation_event(source, case_ref, tool, arm=arm, lever_id=lever_id)], timeout=timeout)
        return True
    except Exception:  # noqa: BLE001
        return False


def close_case(hs: Any, source: str, case_ref: str, *, timeout: float = DEFAULT_TIMEOUT_S) -> bool:
    """Send `case.closed` for the case; False when it did not land."""
    try:
        hs.ingest_events([{
            "specversion": "1.0", "id": f"{case_ref}:closed", "source": source, "type": "case.closed",
            "subject": case_ref, "time": _now_iso(), "datacontenttype": "application/json", "data": {},
        }], timeout=timeout)
        return True
    except Exception:  # noqa: BLE001
        return False


def authorizer_response(d: RouteDecision) -> Dict[str, Any]:
    """The gateway authorizer's shape: facts and the route, never `allow` — the gateway's own rule
    maps band / route to allow or deny (Datagoat spec 23)."""
    out: Dict[str, Any] = {
        "allow": None,
        "band": d.band,
        "max_autonomy": d.max_autonomy,
        "likelihood_direction": d.likelihood_direction,
        "lane": d.lane,
        "route": d.route,
        "receipt": dict(d.receipt),
        "reason": d.reason,
        "fallback": d.fallback,
    }
    if d.arm:
        out["arm"] = d.arm
    if d.lever_id:
        out["lever_id"] = d.lever_id
    return out


def env_lines(d: RouteDecision) -> str:
    """`export` lines a shell hook writes for the session (Claude Code's `$CLAUDE_ENV_FILE`)."""
    pairs = [("HS_ROUTE", d.route), ("HS_LANE", d.lane or ""), ("HS_ARM", d.arm or ""),
             ("HS_LEVER_ID", d.lever_id or ""), ("HS_CASE_REF", d.case_ref or ""),
             ("HS_VERDICT_ID", d.verdict_id or ""), ("HS_FALLBACK_APPLIED", "1" if d.fallback else "0")]
    return "".join(f"export {k}={_sh(v)}\n" for k, v in pairs)


def _sh(v: str) -> str:
    return "'" + str(v).replace("'", "'\\''") + "'"


__all__ = ["ROUTES", "DEFAULT_TIMEOUT_S", "RouteDecision", "route_of", "from_receipt", "fallback_decision",
           "decide_case", "attestation_event", "attest", "close_case", "authorizer_response", "env_lines"]
