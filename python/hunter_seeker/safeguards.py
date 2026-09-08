"""The safeguards the skills describe in prose, as code.

Every ranked row carries `band`, `band_reason` and `max_autonomy`, and every lever carries
`likelihood_direction`. The client returns them as raw dicts, so acting on them correctly has been
left to each caller's own `if` statements — and both cleared sample runs mixed `act`/L3 and
`escalate`/L1 INSIDE THE SAME top-k, so "the top k are the ones to act on" is wrong on real data.

The one rule worth stating twice: **polarity is never guessed here.** `likelihood_direction` says
which way a lever moves the predicted likelihood OF THE OUTCOME. Whether that is good news depends
entirely on whether the outcome is one you want, and Hunter-Seeker does not infer that. A lever
reading "lower" is good news on churn and bad news on conversion. So `lever_helps` REFUSES rather
than defaults when it cannot see the polarity — the failure mode it exists to prevent is an
integrator hardcoding a direction and silently inverting every recommendation the day someone runs
the other kind of model.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Mapping, Optional


class Band(str, Enum):
    """The engine's verdict on one entity. A FACT about likelihood, never advice."""

    ACT = "act"            # certified likely
    ESCALATE = "escalate"  # uncertain — ask a human
    REFUSE = "refuse"      # the engine will not vouch, and says why


class Autonomy(str, Enum):
    """How much rope THIS decision earns. Ordered: L0 < L1 < L2 < L3 < L4."""

    L0 = "L0"  # observe and record
    L1 = "L1"  # recommend to a human
    L2 = "L2"  # act with a human gate
    L3 = "L3"  # act and log
    L4 = "L4"  # defined but never issued in v1 — treat as unreachable, not as "maximum"

    @property
    def rank(self) -> int:
        return int(self.value[1:])

    def permits(self, needed: "Autonomy") -> bool:
        """True when this ceiling allows an action needing `needed`. Never compare the STRINGS:
        "L10" would sort below "L2" and every ladder check would silently invert."""
        return self.rank >= needed.rank


# ── run-level usability ──────────────────────────────────────────────────────────────────────
#
# The three values Hunter-Seeker puts on `usability`, and the ONE degradation rule around them.
#
# Every ranked surface — the hs_rank_topk envelope, the hs_poll_task envelope, and hs_context_brief
# in both formats — carries `usability`. It is the run-level answer to the question the per-entity
# band answers per row: may I act on this at all?
#
# Measured on the live surface, 2026-09-08: a partitioned run below the row floor returned
# gate_verdicts ["cleared: ..."] beside clearance_frequency {cleared: 0, of: 2, judgeable: 0}, a
# null model_ref and a null verdict. Both statements were true of different questions, and an agent
# reading the first acted on a run the engine had never been able to judge.
ACTIONABLE = "actionable"   # the engine judged this run and vouches for it
UNJUDGED = "unjudged"       # the engine could not APPLY its bar - an unanswered question
REFUSED = "refused"         # the bar was applied and nothing cleared

_USABILITY_VALUES = frozenset((ACTIONABLE, UNJUDGED, REFUSED))


def usability_of(envelope: Mapping[str, Any]) -> str:
    """This run's usability, read off any surface that carries it.

    DEGRADES TO ``unjudged``, never to ``actionable``. An envelope from before the field shipped,
    a cached analysis rehydrated by an older build, or a value this client does not recognise all
    resolve to ``unjudged`` - the same asymmetry the per-entity helpers use, and for the same
    reason: a missing stop signal must never become permission.

    It does NOT re-derive the label from model_ref/verdict/clearance_frequency. The server owns
    that derivation, and a second one here would be free to disagree with the envelope it is
    reading - which is the exact class of bug `usability` exists to close.
    """
    if not isinstance(envelope, Mapping):
        return UNJUDGED
    value = envelope.get("usability")
    return value if value in _USABILITY_VALUES else UNJUDGED


def run_is_actionable(envelope: Mapping[str, Any]) -> bool:
    """True only when the run itself is actionable. Says nothing about any single entity."""
    return usability_of(envelope) == ACTIONABLE


def _judgeable_note(envelope: Mapping[str, Any]) -> str:
    """The clearance counts, quoted back verbatim when the envelope carries them.

    Read from both shapes without normalising them: the rank/poll envelope nests the block under
    `partitions`, the brief carries it under `trust`. Absent on an undivided run, and absent is not
    zero - so the sentence is only added when the numbers are actually there.
    """
    for holder in (envelope.get("partitions"), envelope.get("trust")):
        if isinstance(holder, Mapping):
            cf = holder.get("clearance_frequency")
            if isinstance(cf, Mapping) and cf.get("judgeable") is not None:
                return (
                    " This run reports clearance_frequency judgeable: %s of %s draws - the bar "
                    "could not be applied to %s of them, so no draw-level clearance exists."
                    % (cf.get("judgeable"), cf.get("of"), cf.get("of"))
                )
    return ""


class MissingSafeguard(ValueError):
    """A safeguard field the engine ships was absent, so no safe answer exists.

    Raised rather than defaulted. Every one of these fields exists to stop an action; a default
    would turn a missing stop signal into permission, which is the one direction the error must
    never fail in.
    """


def _need(entity: Mapping[str, Any], field: str) -> Any:
    if not isinstance(entity, Mapping) or entity.get(field) is None:
        raise MissingSafeguard(
            f"no {field!r} on this entity. An UNBANDED entity carries no band key at all - not "
            f"null, not a default - so treat it as 'the engine did not vouch for this row' and "
            f"escalate to a human. Do not act."
        )
    return entity[field]


def band(entity: Mapping[str, Any]) -> Band:
    """This entity's band, as an enum. Raises MissingSafeguard when absent."""
    return Band(_need(entity, "band"))


def ceiling(entity: Mapping[str, Any]) -> Autonomy:
    """This entity's autonomy ceiling. Raises MissingSafeguard when absent.

    Note it is per-DECISION, not per-run: a person-level decision caps at L2 (L0 without a human
    principal) however strong the ranking, and a single top-k routinely mixes L3 and L1 rows.
    """
    return Autonomy(_need(entity, "max_autonomy"))


def should_act(
    entity: Mapping[str, Any],
    *,
    needs: Autonomy = Autonomy.L3,
    run: Optional[Mapping[str, Any]] = None,
) -> bool:
    """True only when the engine both certified this row AND left enough rope for `needs`.

    Both halves matter. A row can be band `act` and still be capped at L2, which means "act with a
    human gate" - not "act". Defaults to L3 (act and log) because that is what an unattended agent
    is actually asking about when it asks whether it may act.

    THREE halves, since 2.2.0. Pass ``run`` - the envelope the entity came out of - and the RUN is
    checked before the row. A run the engine could not judge produces entities that look ordinary:
    on the measured live case they carried a score and a tier and no band at all, so the existing
    per-entity check happened to refuse. It refused for the wrong reason, and it would have passed
    the moment the engine started banding an unjudged run's rows. The run-level check is the one
    that is actually load-bearing, so it goes first and it raises rather than returning False:
    "there is no answer here" is a different outcome from "the answer is no", and an integrator
    that cannot tell them apart will retry the first as if it were the second.

    ``run`` is OPTIONAL for compatibility with callers written before this existed, and omitting it
    reproduces the previous behaviour exactly. Pass it. Every rank, poll and brief response is a
    valid argument.
    """
    if run is not None:
        state = usability_of(run)
        if state != ACTIONABLE:
            raise MissingSafeguard(
                "this RUN is not actionable (usability: %r), so no entity in it may be acted on, "
                "whatever its band says.%s %s Do not retry the identical call - re-run with more "
                "rows per entity-draw, or without partitions."
                % (
                    state,
                    _judgeable_note(run),
                    "An unjudged run is an unanswered question, not a negative answer: the engine "
                    "could not apply its bar to it."
                    if state == UNJUDGED
                    else "A refused run is a real answer: the bar was applied and nothing cleared.",
                )
            )
    return band(entity) is Band.ACT and ceiling(entity).permits(needs)


def polarity_of(verdict: Mapping[str, Any]) -> str:
    """`"adverse"` or `"desirable"`, read off a signed Verdict. Raises when absent.

    Absence is not a shrug: `outcome.polarity` is REQUIRED on a Verdict, so a missing one means you
    are not holding a Verdict - or you are holding a rank envelope, where it lives under
    `verdict.outcome.polarity` rather than at the top level.
    """
    outcome = (verdict or {}).get("outcome") if isinstance(verdict, Mapping) else None
    pol = (outcome or {}).get("polarity") if isinstance(outcome, Mapping) else None
    if pol not in ("adverse", "desirable"):
        raise MissingSafeguard(
            "no outcome.polarity on this verdict, so which way a lever should point is unknowable. "
            "Read it from the Verdict a cleared hs_rank_topk returned (verdict.outcome.polarity), "
            "or ask the user whether this outcome is one they want. Never assume 'lower is better' "
            "- that is true of churn and false of conversion, and the two are the same shape here."
        )
    return str(pol)


def lever_helps(lever: Mapping[str, Any], verdict: Mapping[str, Any]) -> bool:
    """True when pulling this lever moves likelihood in the direction the caller wants.

    Adverse outcome (churn, default, failure) -> you want likelihood LOWER.
    Desirable outcome (converted, renewed, closed) -> you want it HIGHER.
    `unchanged` helps neither way.

    RAISES when the polarity is missing rather than picking one. That refusal is the whole point of
    this function: assuming a direction is how every recommendation gets inverted at once.
    """
    want = "lower" if polarity_of(verdict) == "adverse" else "higher"
    direction = (lever or {}).get("likelihood_direction") if isinstance(lever, Mapping) else None
    if direction is None:
        raise MissingSafeguard(
            "no likelihood_direction on this lever. It is returned per LEVER and is not fixed - "
            "read it per lever rather than assuming the run's usual direction."
        )
    return direction == want


def attestable(lever: Mapping[str, Any]) -> bool:
    """True when this lever carries the `lever_token` hs_attest_action requires.

    The token is present ONLY when the engine minted one, and the field is absent rather than null
    when it did not - so membership, not truthiness, is the honest test. A lever without one cannot
    be attested, which means the acted-vs-not evidence loop is closed for it.
    """
    return isinstance(lever, Mapping) and isinstance(lever.get("lever_token"), str) and bool(lever["lever_token"])
