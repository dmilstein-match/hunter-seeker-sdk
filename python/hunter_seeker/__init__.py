"""hunter-seeker — Python client for the Hunter-Seeker Verdict layer.

    from hunter_seeker import Client
    hs = Client(api_key="hsk_test_...")             # or oauth token
    caps = hs.describe_capabilities()
    run  = hs.rank_topk(dataset_id="sample:saas_churn", entity_column="customer_id",
                        outcome_column="churned", subject_kind="org")
    v    = hs.score_entity(run["model_ref"], {"tenure": 14, "seats": 3}, subject_kind="org")
    hs.verify(v["verdict"], v["signature"])          # -> "valid"

Acting on a result safely (band / autonomy ladder / lever direction):

    from hunter_seeker import should_act, lever_helps
    top = run["entities"][0]
    if should_act(top):                     # band is act AND the ceiling allows L3
        ...
    # lever_helps needs the Verdict: which direction is GOOD depends on the outcome polarity,
    # and it raises rather than guessing when it cannot see one.
    lever_helps(levers[0], run["verdict"])

The governed loop over AGENT RUNS (ledger → priors → gate → control arm → era-lock):

    from hunter_seeker import Ledger, gate, era_lock
    ledger = Ledger(); ledger.extend(rows_with_known_outcomes)
    d = gate(hs, model_ref, ledger, new_run)        # attaches the trace@1 priors, draws the
    d.action                                        # control arm, reads the band WITH its polarity
                                                    # → "intercept" | "proceed" | "default"
    era_lock(hs.explain_drivers(ranking_ref)["pattern"]["conditions"], ledger.rows)["era_locked"]

Harness adapters for that loop: hunter_seeker.claude_agent (hooks), hunter_seeker.langchain_middleware.
Framework adapters that give an AGENT the engine as tools: hunter_seeker.langchain, hunter_seeker.crewai.
CLI: `hs`.
"""
from .client import Client, HunterSeekerError, ProblemDetails
from .loop import Decision, Ledger, control_arm, decide, era_lock, gate
from .safeguards import (ACTIONABLE, REFUSED, UNJUDGED, Autonomy, Band, MissingSafeguard,
                         attestable, band, ceiling, lever_helps, polarity_of, run_is_actionable,
                         should_act, usability_of)

__all__ = ["Client", "HunterSeekerError", "ProblemDetails",
           "Band", "Autonomy", "MissingSafeguard",
           "should_act", "ceiling", "band", "lever_helps", "polarity_of", "attestable",
           "usability_of", "run_is_actionable", "ACTIONABLE", "UNJUDGED", "REFUSED",
           "Ledger", "gate", "decide", "Decision", "control_arm", "era_lock"]
# Kept in step with pyproject.toml by the versions-agree CI job. This read 2.0.0 through four
# releases while pyproject.toml and the User-Agent string both said 2.1.1.
__version__ = "2.2.1"
