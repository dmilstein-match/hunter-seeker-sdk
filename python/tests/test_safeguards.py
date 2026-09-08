"""The safeguards, driven by response shapes captured from production (engine 0.3.6).

Every entity/lever/verdict literal below was returned by a real run against the live MCP surface,
not invented — including the fact that ONE cleared top-k contained both `act`/L3 and `escalate`/L1
rows, which is the case a caller who trusts "the top k are the ones to act on" gets wrong.
"""
import pytest
from hunter_seeker import (ACTIONABLE, REFUSED, UNJUDGED, Autonomy, Band, MissingSafeguard,
                           attestable, band, ceiling, lever_helps, polarity_of,
                           run_is_actionable, should_act, usability_of)

# sample:saas_churn — rank 1 and rank 58 of ONE ranking (lift 4.44)
ACT_ROW = {"entity_id": "cust_0563", "score": 0.7759820514189896, "tier": "high",
           "band": "act", "band_reason": "certified", "max_autonomy": "L3"}
ESCALATE_ROW = {"entity_id": "cust_0730", "score": 0.5777643278261534, "tier": "high",
                "band": "escalate", "band_reason": "uncertain", "max_autonomy": "L1"}
# a person-level decision is capped at L2 however strong the row
PERSON_ROW = {"entity_id": "p_1", "band": "act", "band_reason": "certified", "max_autonomy": "L2"}

ADVERSE = {"outcome": {"column": "churned", "polarity": "adverse"}}
DESIRABLE = {"outcome": {"column": "converted", "polarity": "desirable"}}

# sample:agent_traces reduced through trace@1 — a real lever, verbatim
LEVER_LOWER = {"entity_id": "run_0287",
               "changes": [{"feature": "tool", "direction": "change"},
                           {"feature": "agent_prior_n", "direction": "decrease"}],
               "magnitude": "substantial", "likelihood_direction": "lower",
               "association_not_causal": True}
LEVER_HIGHER = {**LEVER_LOWER, "likelihood_direction": "higher"}
LEVER_UNCHANGED = {**LEVER_LOWER, "likelihood_direction": "unchanged"}


def test_one_top_k_really_does_mix_act_and_escalate():
    # The premise. If this ever stops being true the helpers are less necessary, not more correct.
    assert should_act(ACT_ROW) is True
    assert should_act(ESCALATE_ROW) is False
    assert band(ESCALATE_ROW) is Band.ESCALATE


def test_a_certified_row_can_still_be_capped_below_the_action_you_want():
    # band act + L2 means "act with a human gate", not "act". Reading band alone misses this.
    assert band(PERSON_ROW) is Band.ACT
    assert should_act(PERSON_ROW) is False, "L2 must not satisfy an unattended L3 action"
    assert should_act(PERSON_ROW, needs=Autonomy.L2) is True
    assert ceiling(PERSON_ROW) is Autonomy.L2


def test_the_ladder_is_ordered_numerically_not_lexicographically():
    assert Autonomy.L3.permits(Autonomy.L2)
    assert not Autonomy.L1.permits(Autonomy.L3)
    assert Autonomy.L0.rank == 0 and Autonomy.L4.rank == 4


def test_the_same_lever_helps_on_one_polarity_and_hurts_on_the_other():
    # THE failure this module exists to prevent: "lower" is good news on churn and bad news on
    # conversion. An integrator who hardcodes one inverts every recommendation on the other.
    assert lever_helps(LEVER_LOWER, ADVERSE) is True
    assert lever_helps(LEVER_LOWER, DESIRABLE) is False
    assert lever_helps(LEVER_HIGHER, DESIRABLE) is True
    assert lever_helps(LEVER_HIGHER, ADVERSE) is False
    assert lever_helps(LEVER_UNCHANGED, ADVERSE) is False


def test_an_absent_polarity_raises_rather_than_defaulting():
    # The whole contract. A default here would silently pick a direction the caller never gave.
    for bad in ({}, {"outcome": {}}, {"outcome": {"column": "churned"}}, None):
        with pytest.raises(MissingSafeguard):
            lever_helps(LEVER_LOWER, bad)
    with pytest.raises(MissingSafeguard):
        polarity_of({"outcome": {"polarity": "unknown"}})


def test_an_absent_band_or_ceiling_raises_rather_than_defaulting():
    # An UNBANDED entity carries no band key at all — not null, not a default.
    with pytest.raises(MissingSafeguard):
        should_act({"entity_id": "e", "score": 0.9})
    with pytest.raises(MissingSafeguard):
        ceiling({"entity_id": "e", "band": "act"})


def test_a_lever_without_a_token_cannot_be_attested():
    # The field is ABSENT rather than null when the engine minted none, so membership is the test.
    assert attestable(LEVER_LOWER) is False
    assert attestable({**LEVER_LOWER, "lever_token": "ct1.abc.def"}) is True
    assert attestable({**LEVER_LOWER, "lever_token": ""}) is False


# ─────────────────────────────────────────────────────────────────────────────────────────────
# Unit 102 / B11 — the SDK refuses the RUN, not just the row.
#
# Measured on the live surface 2026-09-08: sample:saas_churn with partitions:2 below the row floor
# returned gate_verdicts ["cleared: ..."] beside clearance_frequency {cleared:0, of:2, judgeable:0},
# a null model_ref and a null verdict. An agent that read the first acted on a run the engine had
# never been able to judge.
# ─────────────────────────────────────────────────────────────────────────────────────────────

UNJUDGED_RUN = {
    "usability": "unjudged",
    "model_ref": None,
    "verdict": None,
    "partitions": {"clearance_frequency": {"cleared": 0, "of": 2, "judgeable": 0}},
}
ACTIONABLE_RUN = {"usability": "actionable", "model_ref": "mr1_x", "verdict": {"kind": "ranking"}}
REFUSED_RUN = {"result": "none", "usability": "refused"}
BANDED_ENTITY = {"entity_id": "e", "score": 0.9, "band": "act", "max_autonomy": "L3"}


def test_usability_is_read_not_re_derived():
    assert usability_of(ACTIONABLE_RUN) == ACTIONABLE
    assert usability_of(UNJUDGED_RUN) == UNJUDGED
    assert usability_of(REFUSED_RUN) == REFUSED
    assert run_is_actionable(ACTIONABLE_RUN) is True
    assert run_is_actionable(UNJUDGED_RUN) is False


def test_an_envelope_from_before_the_field_shipped_degrades_to_unjudged():
    # B12. Never to actionable — a missing stop signal must not become permission. This is the one
    # rule that makes it safe to ship the field without a client-version handshake.
    legacy = {k: v for k, v in ACTIONABLE_RUN.items() if k != "usability"}
    assert usability_of(legacy) == UNJUDGED
    assert usability_of({}) == UNJUDGED
    assert usability_of({"usability": "probably_fine"}) == UNJUDGED
    assert usability_of(None) == UNJUDGED
    with pytest.raises(MissingSafeguard):
        should_act(BANDED_ENTITY, run=legacy)


def test_should_act_refuses_the_whole_run_and_names_the_evidence():
    # It RAISES rather than returning False: "there is no answer here" is a different outcome from
    # "the answer is no", and an integrator that cannot tell them apart retries the first.
    with pytest.raises(MissingSafeguard) as e:
        should_act(BANDED_ENTITY, run=UNJUDGED_RUN)
    msg = str(e.value)
    assert "usability: 'unjudged'" in msg
    assert "judgeable: 0 of 2" in msg, "the refusal must quote the engine's own counts"
    assert "unanswered question, not a negative answer" in msg
    # A refused run refuses too, and says something different — it IS an answer.
    with pytest.raises(MissingSafeguard) as e2:
        should_act(BANDED_ENTITY, run=REFUSED_RUN)
    assert "the bar was applied and nothing cleared" in str(e2.value)


def test_the_run_check_fires_BEFORE_the_row_check():
    # Load-bearing ordering. On the measured run the entities carried no band at all, so the
    # per-entity check happened to refuse — for the wrong reason, and it would pass the moment the
    # engine started banding an unjudged run's rows. Prove the run gate is what refuses here.
    with pytest.raises(MissingSafeguard) as e:
        should_act(BANDED_ENTITY, run=UNJUDGED_RUN)
    assert "this RUN is not actionable" in str(e.value)
    assert "no 'band'" not in str(e.value)


def test_the_brief_shape_is_accepted_too():
    # hs_context_brief nests the same counts under `trust` rather than `partitions`. One helper,
    # both shapes — an agent should not have to normalise a surface before it can be safe.
    brief = {
        "usability": "unjudged",
        "trust": {"clearance_frequency": {"cleared": 0, "of": 2, "judgeable": 0}},
    }
    with pytest.raises(MissingSafeguard) as e:
        should_act(BANDED_ENTITY, run=brief)
    assert "judgeable: 0 of 2" in str(e.value)


def test_existing_per_entity_behaviour_is_unchanged_when_run_is_omitted():
    # B11's "existing per-entity behaviour unchanged". Omitting `run` reproduces the old contract
    # exactly, so no caller written before this breaks.
    assert should_act(BANDED_ENTITY) is True
    assert should_act(BANDED_ENTITY, run=ACTIONABLE_RUN) is True
    assert should_act({**BANDED_ENTITY, "band": "escalate"}, run=ACTIONABLE_RUN) is False
    assert should_act({**BANDED_ENTITY, "max_autonomy": "L2"}, run=ACTIONABLE_RUN) is False
    with pytest.raises(MissingSafeguard):
        should_act({"entity_id": "e", "score": 0.9}, run=ACTIONABLE_RUN)
