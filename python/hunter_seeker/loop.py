"""The governed loop over agent runs: ledger → priors → gate → control arm → era-lock.

    from hunter_seeker import Client
    from hunter_seeker.loop import Ledger, gate, era_lock

    ledger = Ledger()                                   # one row per run; you own it
    ledger.extend(rows_with_known_outcomes)

    d = gate(hs, model_ref, ledger, new_run, subject_kind="event")
    if d.action == "intercept": ...                     # adverse outcome, band act: catch this run
    elif d.action == "proceed": ...                     # desirable outcome, band act: let it run
    else: ...                                           # your default policy (escalate/refuse/control)

    ledger.append({**new_run, "failed": None})          # record it; fill the outcome when observed
    hs.report_outcome(model_ref, [{"entity_id": new_run["run_id"], "outcome": 1, ...}])

WHY THIS MODULE EXISTS — three things the engine cannot do for you, each measured:

1.  **The reading does not run at score time.** `trace@1` derives six features during the fit —
    `agent_prior_n`, `agent_prior_outcome_rate`, and the same pair for `task` and `tool`. A later
    `hs_score_entity` reads them off the row you send and refuses when one is missing:

        422 row_not_scoreable: scorecard feature 'agent_prior_n' not found in frame columns [...]

    So the caller has to compute them, with the reading's exact definition: over runs of the same
    group value whose timestamp is STRICTLY earlier (a same-instant peer is not an earlier run),
    `_n` is the count and `_outcome_rate` the mean of the 0/1 outcome; a group with no earlier
    runs has `_n = 0` and rate NULL, not 0; a missing group value or an unparsable timestamp gives
    NULL for both. `Ledger.priors` is that definition, pinned to a fixture the engine generated.

2.  **Acting on the score destroys the data the score needs.** Once a band causes a reroute you
    stop observing what would have happened, and `hs_action_evidence` — which compares acted
    against not-acted WITHIN the same pattern — has nothing to compare. `Ledger.control` exempts a
    fixed slice of runs by a stable hash of the run id, so the slice is the same forever and the
    same on every machine.

3.  **A pattern can bound a monotone counter and never fire again.** Three of the six emits are
    counts that only grow, so `agent_prior_n > 97` is a date filter wearing a feature's name — the
    sample corpus selected exactly that. `era_lock` rebuilds each condition from `operator` and
    `missing_values` (never the direction word) and grades it in-fit, with no holdout needed.

What this module never does: choose a polarity (read off the Verdict), default a missing band to
permission (`safeguards` raises), or retrain anything (a refit is an explicit `rank_topk(refit_of)`).
"""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .safeguards import Autonomy, Band, band, ceiling, polarity_of

#: The group roles `trace@1` understands, in the engine's emission order.
GROUP_ROLES: Tuple[str, ...] = ("agent", "task", "tool")


def prior_feature_names(groups: Iterable[str] = GROUP_ROLES) -> List[str]:
    """The columns the scorecard may read: `<role>_prior_n`, `<role>_prior_outcome_rate`."""
    out: List[str] = []
    for g in groups:
        out += [f"{g}_prior_n", f"{g}_prior_outcome_rate"]
    return out


# ── timestamps ──────────────────────────────────────────────────────────────────────────────
#
# The engine parses through ONE format chain (duckdb_utils._TIMESTAMP_FORMATS) and compares at
# microsecond resolution with the session pinned to UTC: an aware value becomes the UTC instant
# with the offset dropped, a naive value passes through unchanged. This mirrors the ISO and
# epoch members of that chain and refuses the rest (US/EU/compact dates) rather than guessing —
# a ledger you write yourself can write ISO. `None` means "unparsable", which is what the engine
# emits for the run's priors in that case.

_ISO = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?)?"
    r"\s*(Z|[+-]\d{2}:?\d{2})?$"
)
_EPOCH_S = (10**8, 10**10)      # the engine's declared bands, not tuned thresholds
_EPOCH_MS = (10**11, 10**13)


def parse_ts(value: Any) -> Optional[datetime]:
    """A naive-UTC datetime at microsecond resolution, or None when the engine would not parse it."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        v = float(value)
        if _EPOCH_S[0] <= v < _EPOCH_S[1]:
            dt = datetime.fromtimestamp(v, tz=timezone.utc)
        elif _EPOCH_MS[0] <= v < _EPOCH_MS[1]:
            dt = datetime.fromtimestamp(v / 1000.0, tz=timezone.utc)
        else:
            return None
    else:
        s = str(value).strip()
        if s.isdigit():
            return parse_ts(int(s))
        m = _ISO.match(s)
        if not m:
            return None
        y, mo, d, hh, mm, ss, frac, tz = m.groups()
        try:
            dt = datetime(int(y), int(mo), int(d), int(hh or 0), int(mm or 0), int(ss or 0),
                          int((frac or "0")[:6].ljust(6, "0")))
        except ValueError:
            return None
        if tz == "Z":
            dt = dt.replace(tzinfo=timezone.utc)
        elif tz:
            sign = 1 if tz[0] == "+" else -1
            digits = tz[1:].replace(":", "")
            off = sign * (int(digits[:2]) * 60 + int(digits[2:]))
            dt = dt.replace(tzinfo=timezone(timedelta(minutes=off)))
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt  # datetime carries microseconds and nothing finer, like the engine


# ── the ledger ──────────────────────────────────────────────────────────────────────────────

def _binary_or_none(value: Any, where: str) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)) and value in (0, 1):
        return int(value)
    if isinstance(value, str) and value.strip() in ("0", "1"):
        return int(value.strip())
    raise ValueError(f"{where}: outcome must be 0/1/true/false or None (unknown yet), got {value!r}. "
                     "The engine refuses anything else, and so does the ledger: a self-reported "
                     "'done' is not an observed outcome.")


class Ledger:
    """One row per agent run. The only state the loop needs you to own.

    Rows are plain dicts. The outcome column may be None while the run is in flight; only rows
    with a KNOWN outcome contribute to another run's priors, because that is what the fit saw —
    the engine fits on a fully labelled table, and the decision-time equivalent is "the earlier
    runs whose outcome I know".
    """

    def __init__(self, *, identifier: str = "run_id", time_axis: str = "ts",
                 outcome: str = "failed",
                 groups: Optional[Mapping[str, str]] = None) -> None:
        self.identifier = identifier
        self.time_axis = time_axis
        self.outcome = outcome
        #: role -> column. Default binds every role to a column of the same name.
        self.groups: Dict[str, str] = dict(groups) if groups is not None else {g: g for g in GROUP_ROLES}
        unknown = set(self.groups) - set(GROUP_ROLES)
        if unknown:
            raise ValueError(f"unknown group role(s) {sorted(unknown)}; trace@1 knows {GROUP_ROLES}")
        if not self.groups:
            raise ValueError("bind at least one group role (agent, task, tool): a prior rate is a rate OVER something")
        self.rows: List[Dict[str, Any]] = []

    # -- writing -------------------------------------------------------------------------------
    def append(self, row: Mapping[str, Any]) -> None:
        for col in (self.identifier, self.time_axis):
            if col not in row:
                raise ValueError(f"row is missing the {col!r} column")
        r = dict(row)
        r[self.outcome] = _binary_or_none(r.get(self.outcome), f"run {r[self.identifier]!r}")
        self.rows.append(r)

    def extend(self, rows: Iterable[Mapping[str, Any]]) -> None:
        for r in rows:
            self.append(r)

    def observe(self, run_id: str, outcome: Any) -> None:
        """Fill in the observed outcome for a run already in the ledger."""
        for r in self.rows:
            if str(r[self.identifier]) == str(run_id):
                r[self.outcome] = _binary_or_none(outcome, f"run {run_id!r}")
                return
        raise KeyError(f"run {run_id!r} is not in the ledger")

    # -- priors --------------------------------------------------------------------------------
    def priors(self, row: Mapping[str, Any]) -> Dict[str, Optional[float]]:
        """The six `trace@1` features for `row`, computed over this ledger's labelled rows.

        `row` need not be in the ledger. Its own timestamp and group values decide the windows;
        rows of the ledger that share its identifier are excluded so scoring a run already
        recorded does not let it see its own label.
        """
        t = parse_ts(row.get(self.time_axis))
        out: Dict[str, Optional[float]] = {}
        own_id = str(row.get(self.identifier))
        for role, col in self.groups.items():
            n_name, rate_name = f"{role}_prior_n", f"{role}_prior_outcome_rate"
            value = row.get(col)
            if t is None or value is None:
                out[n_name] = None
                out[rate_name] = None
                continue
            key = str(value)
            n, total = 0, 0
            for r in self.rows:
                if r.get(self.outcome) is None or r.get(col) is None:
                    continue
                if str(r.get(self.identifier)) == own_id:
                    continue
                if str(r[col]) != key:
                    continue
                rt = parse_ts(r.get(self.time_axis))
                if rt is None or not (rt < t):          # strictly earlier; a tie is not earlier
                    continue
                n += 1
                total += int(r[self.outcome])
            out[n_name] = float(n)
            out[rate_name] = (total / n) if n else None
        return out

    def with_priors(self, row: Mapping[str, Any]) -> Dict[str, Any]:
        return {**row, **self.priors(row)}

    # -- the control arm -----------------------------------------------------------------------
    def control(self, run_id: Any, *, fraction: float = 0.15, salt: str = "") -> bool:
        return control_arm(run_id, fraction=fraction, salt=salt)


def control_arm(run_id: Any, *, fraction: float = 0.15, salt: str = "") -> bool:
    """True for a fixed `fraction` of run ids, by stable hash. Same answer forever, everywhere.

    Not `random()`: a control arm that is re-drawn each call is not a control arm, and one drawn
    from a process-local RNG differs between the machine that scored and the machine that reports.
    `salt` lets two loops over the same ids hold out different slices.
    """
    if not (0.0 <= fraction <= 1.0):
        raise ValueError("fraction must be in [0, 1]")
    h = hashlib.sha256(f"{salt}\x1f{run_id}".encode("utf-8")).digest()
    bucket = int.from_bytes(h[:4], "big") % 10_000
    return bucket < int(round(fraction * 10_000))


# ── the gate ─────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Decision:
    """What the loop decided about one run, and why. `action` is the only field a router reads."""
    run_id: str
    action: str                    # "intercept" | "proceed" | "default"
    reason: str
    band: Optional[str]
    autonomy: Optional[str]
    polarity: Optional[str]
    control: bool
    entity: Dict[str, Any] = field(default_factory=dict)
    verdict: Dict[str, Any] = field(default_factory=dict)
    signature: Dict[str, Any] = field(default_factory=dict)
    row_scored: Dict[str, Any] = field(default_factory=dict)


def decide(entity: Mapping[str, Any], verdict: Mapping[str, Any], *, run_id: Any,
           control: bool = False, needs: Autonomy = Autonomy.L3) -> Decision:
    """Turn a scored entity + its Verdict into an action, reading the polarity off the Verdict.

    On an ADVERSE outcome (fitted on `failed`) a certified row is a run to CATCH → "intercept".
    On a DESIRABLE outcome (fitted on `succeeded`) it is a run to let through → "proceed".
    Everything else — escalate, refuse, a ceiling below `needs`, or the control arm — is
    "default": your baseline policy, never attributed to the engine. Raises `MissingSafeguard`
    rather than defaulting when band, ceiling or polarity is absent.
    """
    b = band(entity)
    c = ceiling(entity)
    pol = polarity_of(verdict)
    base = dict(run_id=str(run_id), band=b.value, autonomy=c.value, polarity=pol, control=control,
                entity=dict(entity), verdict=dict(verdict))
    if control:
        return Decision(action="default", reason="control arm: recorded, not acted on", **base)
    if b is not Band.ACT:
        return Decision(action="default", reason=f"band {b.value}", **base)
    if not c.permits(needs):
        return Decision(action="default", reason=f"ceiling {c.value} below {needs.value}", **base)
    if pol == "adverse":
        return Decision(action="intercept", reason="certified likely to hit an adverse outcome", **base)
    return Decision(action="proceed", reason="certified likely to hit a desirable outcome", **base)


def gate(hs: Any, model_ref: str, ledger: Ledger, row: Mapping[str, Any], *,
         subject_kind: str = "event", needs: Autonomy = Autonomy.L3,
         control_fraction: float = 0.15, salt: str = "",
         acknowledge_decision_support: bool = False) -> Decision:
    """Score one run through `hs.score_entity` with its priors attached, and decide.

    Costs one decision from quota unless the engine refuses. The control-arm draw happens BEFORE
    the call, so a control run is still scored and recorded — that is the point: the comparison
    needs its band — but its action is always "default".
    """
    run_id = row.get(ledger.identifier)
    scored_row = ledger.with_priors(row)
    is_control = ledger.control(run_id, fraction=control_fraction, salt=salt)
    resp = hs.score_entity(model_ref, scored_row, subject_kind=subject_kind, entity_id=str(run_id),
                           acknowledge_decision_support=acknowledge_decision_support)
    entity = resp.get("entity") or {}
    verdict = resp.get("verdict") or {}
    d = decide(entity, verdict, run_id=run_id, control=is_control, needs=needs)
    return Decision(**{**d.__dict__, "signature": dict(resp.get("signature") or {}),
                       "row_scored": scored_row})


# ── era-lock ─────────────────────────────────────────────────────────────────────────────────
#
# Rebuild each condition from `operator` and `missing_values` — never from the direction word.
# "lower" is `<=` with missing INCLUDED; "higher" is `>` with missing EXCLUDED; reading the
# English instead of the predicate silently selects a different cohort.

FORWARD_COLLAPSE = 0.10   # holdout firing < 10% of fit firing → COLLAPSING
NEAR_ZERO = 0.001         # holdout firing below this → DEAD
CLOCK_RHO = 0.7           # |rank correlation with time| above this → CLOCK-LIKE


def _fires(cond: Mapping[str, Any], row: Mapping[str, Any]) -> bool:
    v = row.get(cond["feature"])
    if cond.get("categories") is not None:
        inside = v is not None and str(v) in {str(c) for c in cond["categories"]}
        return inside if cond.get("category_match", "is_one_of") == "is_one_of" else not inside
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return cond.get("missing_values") == "included"
    op, t = cond["operator"], float(cond["threshold"])
    x = float(v)
    return {"<=": x <= t, "<": x < t, ">": x > t, ">=": x >= t}[op]


def _rank(values: Sequence[float]) -> List[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        r = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = r
        i = j + 1
    return ranks


def _spearman(x: Sequence[float], y: Sequence[float]) -> Optional[float]:
    if len(x) < 50:
        return None
    rx, ry = _rank(x), _rank(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    if sxx == 0 or syy == 0:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(rx, ry)) / math.sqrt(sxx * syy)


def era_lock(conditions: Sequence[Mapping[str, Any]], rows: Sequence[Mapping[str, Any]], *,
             time_axis: str = "ts", cutoff: Any = None, bins: int = 6) -> Dict[str, Any]:
    """Does this pattern describe the problem, or the calendar?

    `conditions` is `explain_drivers()["pattern"]["conditions"]`, verbatim. `rows` is the frame
    you sent the engine (with the prior features attached — `Ledger.with_priors` on each row
    reproduces them). Returns per-condition verdicts and `era_locked`.

    Two tests. FORWARD (needs `cutoff`): firing rate on rows before the cutoff vs after — a
    condition that fires on the fit era and never after is DEAD. IN-FIT (no cutoff needed):
    firing rate across time bins inside the window, and the rank correlation of the raw feature
    against time — a feature that IS a clock is CLOCK-LIKE whatever it is called.
    """
    timed = [(parse_ts(r.get(time_axis)), r) for r in rows]
    timed = [(t, r) for t, r in timed if t is not None]
    timed.sort(key=lambda tr: tr[0])
    cut = parse_ts(cutoff) if cutoff is not None else None
    fit = [r for t, r in timed if cut is None or t < cut]
    hold = [r for t, r in timed if cut is not None and t >= cut]
    fit_t = [t for t, r in timed if cut is None or t < cut]

    results, verdicts = [], []
    for c in conditions:
        m_fit = [_fires(c, r) for r in fit]
        rate_fit = (sum(m_fit) / len(m_fit)) if m_fit else 0.0
        rate_hold = (sum(_fires(c, r) for r in hold) / len(hold)) if hold else None

        nb = max(1, min(bins, len(fit)))
        per_bin: List[float] = []
        for b in range(nb):
            lo, hi = (b * len(fit)) // nb, ((b + 1) * len(fit)) // nb
            chunk = m_fit[lo:hi]
            per_bin.append((sum(chunk) / len(chunk)) if chunk else 0.0)
        declining = len(per_bin) >= 3 and per_bin[0] > 0 and per_bin[-1] <= FORWARD_COLLAPSE * per_bin[0]

        rho = None
        if c.get("categories") is None:
            xs, ys = [], []
            for t, r in zip(fit_t, fit):
                v = r.get(c["feature"])
                if v is None or (isinstance(v, float) and math.isnan(v)):
                    continue
                xs.append(t.timestamp())
                ys.append(float(v))
            rho = _spearman(xs, ys)

        if rate_hold is not None and rate_hold < NEAR_ZERO:
            v = "DEAD"
        elif rate_hold is not None and rate_fit > 0 and rate_hold < FORWARD_COLLAPSE * rate_fit:
            v = "COLLAPSING"
        elif declining:
            v = "DECLINING (in-fit)"
        elif rho is not None and abs(rho) > CLOCK_RHO:
            v = "CLOCK-LIKE"
        else:
            v = "ok"
        verdicts.append(v)
        results.append({
            "feature": c["feature"],
            "predicate": (f"in {list(c['categories'])}" if c.get("categories") is not None
                          else f"{c['operator']} {c['threshold']}"),
            "fires_fit": round(rate_fit, 4),
            "fires_holdout": None if rate_hold is None else round(rate_hold, 4),
            "per_bin": [round(x, 4) for x in per_bin],
            "rho_vs_time": None if rho is None else round(rho, 3),
            "verdict": v,
        })

    joint_fit = (sum(all(_fires(c, r) for c in conditions) for r in fit) / len(fit)) if fit else 0.0
    joint_hold = (sum(all(_fires(c, r) for c in conditions) for r in hold) / len(hold)) if hold else None
    return {
        "conditions": results,
        "joint_coverage_fit": round(joint_fit, 5),
        "joint_coverage_holdout": None if joint_hold is None else round(joint_hold, 5),
        "era_locked": any(v in ("DEAD", "COLLAPSING", "DECLINING (in-fit)") for v in verdicts),
        "clock_like": any(v == "CLOCK-LIKE" for v in verdicts),
    }


__all__ = ["GROUP_ROLES", "prior_feature_names", "parse_ts", "Ledger", "control_arm",
           "Decision", "decide", "gate", "era_lock"]
