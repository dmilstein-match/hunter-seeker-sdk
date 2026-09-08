"""The safeguards, driven by response shapes captured from production (engine 0.3.6).

Every entity/lever/verdict literal below was returned by a real run against the live MCP surface,
not invented — including the fact that ONE cleared top-k contained both `act`/L3 and `escalate`/L1
rows, which is the case a caller who trusts "the top k are the ones to act on" gets wrong.
"""
import pytest
from hunter_seeker import (Autonomy, Band, MissingSafeguard, attestable, band, ceiling,
                           lever_helps, polarity_of, should_act)

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
