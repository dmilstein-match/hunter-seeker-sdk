"""hunter-seeker — Python client for the Hunter-Seeker Verdict layer.

    from hunter_seeker import Client
    hs = Client(api_key="hsk_test_...")             # or oauth token
    caps = hs.describe_capabilities()
    run  = hs.rank_topk(dataset_id="sample:saas_churn", entity_column="customer_id",
                        outcome_column="churned", subject_kind="org")
    v    = hs.score_entity(run["model_ref"], {"tenure": 14, "seats": 3}, subject_kind="org")
    hs.verify(v["verdict"], v["signature"])          # -> "valid"

Framework adapters: hunter_seeker.langchain, hunter_seeker.crewai. CLI: `hs`.
"""
from .client import Client, HunterSeekerError, ProblemDetails

__all__ = ["Client", "HunterSeekerError", "ProblemDetails"]
__version__ = "2.0.0"
