"""Shared fixtures for the governed-loop tests: one fake scoring client, the canned responses."""
from __future__ import annotations

MODEL_REF = "mr1_" + "0" * 32

ACT_L3 = {"entity_id": "r1", "score": 0.53, "band": "act", "band_reason": "certified", "max_autonomy": "L3"}
ACT_L2 = {**ACT_L3, "max_autonomy": "L2"}
ESCALATE = {"entity_id": "r1", "score": 0.51, "band": "escalate", "band_reason": "uncertain", "max_autonomy": "L1"}
REFUSE = {"entity_id": "r1", "score": 0.2, "band": "refuse", "band_reason": "no_vouch", "max_autonomy": "L0"}
ADVERSE = {"outcome": {"column": "failed", "polarity": "adverse"}}
DESIRABLE = {"outcome": {"column": "succeeded", "polarity": "desirable"}}


class FakeScoringClient:
    """Records every row it is asked to score (`calls`) and the arguments that went with it
    (`kwargs`), and answers with a canned entity + verdict, in the shape `/v1/score-entity` returns."""

    def __init__(self, entity=ACT_L3, verdict=ADVERSE):
        self.entity, self.verdict, self.calls, self.kwargs = entity, verdict, [], []

    def score_entity(self, model_ref, row, *, subject_kind, entity_id=None, acknowledge_decision_support=False):
        self.calls.append(dict(row))
        self.kwargs.append({"model_ref": model_ref, "entity_id": entity_id, "subject_kind": subject_kind,
                            "acknowledge_decision_support": acknowledge_decision_support})
        return {"entity": dict(self.entity), "verdict": dict(self.verdict),
                "signature": {"kid": "test", "protected": "x", "signature": "y"}, "billable_decisions": 1}
