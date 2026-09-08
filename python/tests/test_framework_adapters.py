"""The framework adapters must reach every operation, and actually call the client.

Both adapters shipped a fraction of the surface and had ZERO tests, so the gap was invisible:
langchain exposed 5 of 16 and crewai exposed 1. Neither included `rank_topk`, so an agent built
from either could never obtain the `model_ref` its own `score_entity` tool requires, nor the
`lever_token` `attest_action` requires — the two steps the skills teach as mandatory.

This is the same failure the repo already fixed for the n8n node and gated in CI. `ci.yml` there
records it: "It shipped covering five of fifteen operations, and the five did not include
attest_action or explain_levers ... The governance loop the product exists to provide was
unreachable from its own integration, and nothing failed."

The frameworks themselves are not installed here, so both are stubbed. That is on purpose: what
must not drift is the SET OF OPERATIONS and the client method behind each, and neither needs a
real LangChain to check.
"""
import sys
import types
import pytest

from hunter_seeker.client import Client

# Every operation the REST surface exposes. Kept here as a literal so a client method that quietly
# disappears from an adapter fails loudly rather than shrinking the expected set with it.
ALL_OPS = {
    "hs_describe_capabilities", "hs_provide_dataset", "hs_append_rows", "hs_rank_topk",
    "hs_poll_task", "hs_model_quality", "hs_explain_drivers", "hs_explain_levers",
    "hs_context_brief", "hs_score_entity", "hs_score_batch", "hs_verify_verdict",
    "hs_attest_action", "hs_report_outcome", "hs_action_evidence", "hs_drift_status",
}

# The three whose absence made the loop unrunnable, called out so a regression names itself.
LOOP_CRITICAL = {"hs_rank_topk", "hs_explain_levers", "hs_attest_action"}


class RecordingClient(Client):
    """A Client that records the method name instead of making a request."""

    def __init__(self):
        super().__init__(api_key="hsk_test_x")
        self.calls = []

    def __getattribute__(self, name):
        if name.startswith("_") or name in ("calls", "base", "timeout", "test_mode"):
            return object.__getattribute__(self, name)
        attr = object.__getattribute__(self, name)
        if callable(attr) and not isinstance(attr, type):
            def rec(*a, **k):
                object.__getattribute__(self, "calls").append(name)
                return {"ok": name}
            return rec
        return attr


@pytest.fixture
def fake_langchain(monkeypatch):
    mod = types.ModuleType("langchain_core.tools")

    def tool(fn):
        fn.name = fn.__name__
        return fn

    mod.tool = tool
    pkg = types.ModuleType("langchain_core")
    pkg.tools = mod
    monkeypatch.setitem(sys.modules, "langchain_core", pkg)
    monkeypatch.setitem(sys.modules, "langchain_core.tools", mod)


@pytest.fixture
def fake_crewai(monkeypatch):
    # crewai brings pydantic; without it there is nothing to build a BaseTool from. Skip rather
    # than error so a bare env degrades cleanly — but CI installs pydantic, because a test that
    # only ever skips is the same as no test, which is what this file exists to correct.
    BaseModel = pytest.importorskip("pydantic", reason="pydantic is required for the crewai adapter").BaseModel

    class BaseTool(BaseModel):
        model_config = {"arbitrary_types_allowed": True}

    mod = types.ModuleType("crewai.tools")
    mod.BaseTool = BaseTool
    pkg = types.ModuleType("crewai")
    pkg.tools = mod
    monkeypatch.setitem(sys.modules, "crewai", pkg)
    monkeypatch.setitem(sys.modules, "crewai.tools", mod)


def test_langchain_reaches_every_operation(fake_langchain):
    from hunter_seeker.langchain import verdict_tools
    names = {t.name for t in verdict_tools(RecordingClient())}
    assert names == ALL_OPS, f"missing: {sorted(ALL_OPS - names)}; unexpected: {sorted(names - ALL_OPS)}"
    assert LOOP_CRITICAL <= names, "the ranking -> lever -> attest chain is unreachable again"


def test_crewai_reaches_every_operation(fake_crewai):
    from hunter_seeker.crewai import verdict_tools
    names = {t.name for t in verdict_tools(RecordingClient())}
    assert names == ALL_OPS, f"missing: {sorted(ALL_OPS - names)}; unexpected: {sorted(names - ALL_OPS)}"
    assert LOOP_CRITICAL <= names


def test_langchain_tools_call_the_client_rather_than_pretending(fake_langchain):
    # A tool that returns a plausible dict without calling the client is worse than a missing one.
    from hunter_seeker.langchain import verdict_tools
    hs = RecordingClient()
    by_name = {t.name: t for t in verdict_tools(hs)}
    assert by_name["hs_rank_topk"](entity_column="a", outcome_column="b", subject_kind="org",
                                   rows=[{"a": 1}]) == {"ok": "rank_topk"}
    assert by_name["hs_explain_levers"](ranking_ref="r", entity_ids=["e"]) == {"ok": "explain_levers"}
    assert by_name["hs_attest_action"](model_ref="m", entity_id="e", lever_token="t",
                                       post_value=3, acted_at="2026-09-08T00:00:00Z") == {"ok": "attest_action"}
    assert hs.calls == ["rank_topk", "explain_levers", "attest_action"]


def test_crewai_tools_call_the_client_rather_than_pretending(fake_crewai):
    from hunter_seeker.crewai import verdict_tools
    hs = RecordingClient()
    by_name = {t.name: t for t in verdict_tools(hs)}
    assert by_name["hs_rank_topk"]._run(entity_column="a", outcome_column="b", subject_kind="org",
                                        rows=[{"a": 1}]) == {"ok": "rank_topk"}
    assert by_name["hs_drift_status"]._run(model_ref="m") == {"ok": "drift_status"}
    assert hs.calls == ["rank_topk", "drift_status"]


def test_the_original_crewai_single_tool_factory_still_works(fake_crewai):
    # Existing code imports score_entity_tool by name; completing the adapter must not break it.
    from hunter_seeker.crewai import score_entity_tool
    assert score_entity_tool(RecordingClient()).name == "hs_score_entity"
