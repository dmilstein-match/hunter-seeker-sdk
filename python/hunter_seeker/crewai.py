"""CrewAI tools. `pip install hunter-seeker[crewai]`. Or point CrewAI at the MCP server:
    Agent(..., mcps=["https://hunter-seeker.io/api/mcp#hs_score_entity"])
"""
from __future__ import annotations

from typing import Any, Dict, Type

from .client import Client


def score_entity_tool(hs: Client):
    from crewai.tools import BaseTool  # type: ignore
    from pydantic import BaseModel, Field

    class Args(BaseModel):
        model_ref: str = Field(description="model_ref from a cleared hs_rank_topk")
        row: Dict[str, Any] = Field(description="one entity's feature values")
        subject_kind: str = Field(description="person | org | object | event | other")
        acknowledge_decision_support: bool = False

    class HSScoreEntity(BaseTool):
        name: str = "hs_score_entity"
        description: str = ("Score one row against a fitted scorecard; costs one decision. Returns score, band "
                            "(act|escalate|refuse), max_autonomy, principal_reasons, and a signed Verdict. Read band; "
                            "never reconstruct thresholds. Person-level requires acknowledge_decision_support=True.")
        args_schema: Type[BaseModel] = Args

        def _run(self, model_ref: str, row: Dict[str, Any], subject_kind: str,
                 acknowledge_decision_support: bool = False) -> Dict[str, Any]:
            return hs.score_entity(model_ref, row, subject_kind=subject_kind,
                                   acknowledge_decision_support=acknowledge_decision_support)

    return HSScoreEntity()
