"""Datagoat unit 23 → Verify: every wrapper, against a fake `decide` / `ingest_events` client —
`route` comes back and is the only thing branched on; `arm` and `lever_id` travel from the receipt
to the attestation; an error or a slow answer is the named fallback with its reason; nothing ever
emits a `deny`; the grep-level rule (no wrapper reads `lane` for control flow); the Claude Code
hook end to end through `hs hook` against a local fake server with `CLAUDE_ENV_FILE` set."""
from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from hunter_seeker import HunterSeekerError, ProblemDetails
from hunter_seeker.runtime import (RouteDecision, attest, attestation_event, authorizer_response, close_case,
                                   decide_case, env_lines, from_receipt)

ROOT = Path(__file__).resolve().parents[2]
RECEIPT = {"verdict_id": "01V", "case_id": "c1", "case_ref": "c1", "agent_id": "ag_1", "kind": "decision",
           "mode": "live", "applied": True, "route": "act", "lane": "act", "band": "act", "max_autonomy": "L2",
           "likelihood_direction": "lower", "control": False, "lever_id": "lv_9", "lever_arm": "treat",
           "rule_reason": "the same action is cheapest across the whole interval", "signature": None}


class FakeDoor:
    """Records the calls; answers with a receipt, or fails, or sleeps."""

    def __init__(self, receipt=None, *, fail=None, delay=0.0):
        self.receipt = dict(RECEIPT if receipt is None else receipt)
        self.fail, self.delay = fail, delay
        self.decides, self.events, self.timeouts = [], [], []

    def decide(self, agent_id, case, *, mode=None, timeout=None, open_levers=None, **kw):
        self.decides.append({"agent_id": agent_id, "case": dict(case), "mode": mode, "open_levers": open_levers})
        self.timeouts.append(timeout)
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise self.fail
        return dict(self.receipt)

    def ingest_events(self, events, *, timeout=None):
        self.events.extend(dict(e) for e in events)
        self.timeouts.append(timeout)
        if self.fail:
            raise self.fail
        return {"accepted": len(events), "duplicates": 0, "held": 0, "events": []}


CASE = {"case_id": "c1", "kind": {"task": "refunds"}, "actor": {"kind": "agent", "name": "bot"}, "opened_at": "2026-09-14T10:00:00Z"}


# -- the core ------------------------------------------------------------------------------------
def test_decide_case_returns_the_route_and_carries_arm_and_lever_id():
    hs = FakeDoor()
    d = decide_case(hs, "ag_1", CASE, fallback="human")
    assert (d.route, d.lane, d.arm, d.lever_id, d.fallback) == ("act", "act", "treat", "lv_9", False)
    assert d.case_ref == "c1" and d.verdict_id == "01V" and d.receipt["route"] == "act"
    assert hs.timeouts == [2.0]
    assert hs.decides[0]["case"] == CASE


def test_any_error_or_a_slow_answer_is_the_named_fallback_with_its_reason_never_a_raise():
    err = HunterSeekerError(ProblemDetails(code="engine_unreachable", detail="down", remedy="wait", status=503,
                                           field=None, request_id="req_1"))
    d = decide_case(FakeDoor(fail=err), "ag_1", CASE, fallback="review")
    assert d.route == "review" and d.fallback and d.reason.startswith("fallback:") and "down" in d.reason
    d2 = decide_case(FakeDoor(fail=TimeoutError("timed out")), "ag_1", CASE)
    assert d2.route == "none" and d2.fallback
    slow = decide_case(FakeDoor(delay=0.05), "ag_1", CASE, fallback="act", timeout=0.01)
    assert slow.route == "act" and slow.fallback and "longer than" in slow.reason
    # an unknown fallback name is `none`; an unknown route on a receipt is `none`
    assert decide_case(FakeDoor(fail=RuntimeError("x")), "ag_1", CASE, fallback="deny").route == "none"
    assert from_receipt({**RECEIPT, "route": "block"}).route == "none"


def test_attestation_carries_the_tool_name_only_and_the_receipt_arm_and_lever():
    hs = FakeDoor()
    assert attest(hs, "urn:rt", "c1", "send_email", arm="treat", lever_id="lv_9") is True
    ev = hs.events[0]
    assert ev["type"] == "action.attested" and ev["subject"] == "c1" and ev["source"] == "urn:rt"
    assert ev["data"] == {"tool": "send_email", "arm": "treat", "lever_id": "lv_9"}
    assert set(ev) == {"specversion", "id", "source", "type", "subject", "time", "datacontenttype", "data"}
    assert attest(FakeDoor(fail=RuntimeError("x")), "urn:rt", "c1", "t") is False
    assert close_case(hs, "urn:rt", "c1") is True and hs.events[-1]["type"] == "case.closed"
    e = attestation_event("urn:rt", "c1", "t", event_id="fixed")
    assert e["id"] == "fixed" and e["data"] == {"tool": "t"}


def test_the_gateway_shape_never_carries_allow_and_the_env_lines_name_the_route():
    d = decide_case(FakeDoor(), "ag_1", CASE)
    out = authorizer_response(d)
    assert out["allow"] is None
    assert {k: out[k] for k in ("band", "max_autonomy", "likelihood_direction", "lane", "route", "arm", "lever_id")} == {
        "band": "act", "max_autonomy": "L2", "likelihood_direction": "lower", "lane": "act", "route": "act",
        "arm": "treat", "lever_id": "lv_9"}
    assert out["receipt"] == d.receipt
    lines = env_lines(d)
    assert "export HS_ROUTE='act'\n" in lines and "export HS_ARM='treat'\n" in lines and "export HS_LEVER_ID='lv_9'\n" in lines
    assert "export HS_FALLBACK_APPLIED='0'\n" in lines


# -- Google ADK ----------------------------------------------------------------------------------
class _Ctx:
    def __init__(self):
        self.state = {}


def test_adk_before_agent_branches_on_route_and_after_tool_attests():
    from hunter_seeker.adk import attest_after_tool, decide_before_agent, route_of_state
    hs = FakeDoor()
    before = decide_before_agent(hs, "ag_1", case_from_context=lambda c: CASE)
    ctx = _Ctx()
    assert before(ctx) is None                       # act: the agent runs
    assert ctx.state["hs_route"] == "act" and ctx.state["hs_arm"] == "treat" and ctx.state["hs_lever_id"] == "lv_9"
    assert route_of_state(ctx.state).route == "act"
    after = attest_after_tool(hs, "urn:rt")
    class Tool:
        name = "refund"
    assert after(Tool(), {"amount": 9}, ctx, {"ok": True}) is None
    assert hs.events[-1]["data"] == {"tool": "refund", "arm": "treat", "lever_id": "lv_9"}
    assert "amount" not in json.dumps(hs.events[-1])   # the tool's arguments never leave
    # human: the run ends with a Content; the decision is on the state
    hs2 = FakeDoor({**RECEIPT, "route": "human", "lane": "human"})
    ctx2 = _Ctx()
    content = decide_before_agent(hs2, "ag_1", case_from_context=lambda c: CASE)(ctx2)
    assert content is not None and "human" in json.dumps(content, default=str)
    assert ctx2.state["hs_route"] == "human"
    # an error: the fallback route, the agent still runs (none) — no exception
    ctx3 = _Ctx()
    assert decide_before_agent(FakeDoor(fail=RuntimeError("x")), "ag_1", case_from_context=lambda c: CASE)(ctx3) is None
    assert ctx3.state["hs_decision"]["fallback"] is True


# -- OpenAI Agents SDK ---------------------------------------------------------------------------
class _RunCtx:
    def __init__(self, inner):
        self.context = inner


def test_openai_guardrail_trips_on_human_only_and_hooks_attest_with_the_decision():
    from hunter_seeker.openai_agents import AttestHooks, decide_input_guardrail, is_coroutine_guardrail
    hs = FakeDoor()
    decisions = {}
    g = decide_input_guardrail(hs, "ag_1", case_from_input=lambda ctx, agent, inp: CASE, remember=decisions)
    assert is_coroutine_guardrail(g)
    fn = getattr(g, "guardrail_function", g)
    rc = _RunCtx({"hs_case_ref": "c1"})
    out = asyncio.run(fn(rc, None, "refund order 41"))
    info = out["output_info"] if isinstance(out, dict) else out.output_info
    tripped = out["tripwire_triggered"] if isinstance(out, dict) else out.tripwire_triggered
    assert info["route"] == "act" and tripped is False and rc.context["hs_route"] == "act"
    assert decisions["c1"].arm == "treat"
    hooks = AttestHooks(hs, "urn:rt", decisions=decisions)
    class Tool:
        name = "refund"
    asyncio.run(hooks.on_tool_end(rc, None, Tool(), "done"))
    assert hs.events[-1]["data"] == {"tool": "refund", "arm": "treat", "lever_id": "lv_9"}
    assert hooks.attested == [{"case_ref": "c1", "tool": "refund", "sent": True}]
    # human trips; review does not by default; an error is the fallback and does not trip
    hs_h = FakeDoor({**RECEIPT, "route": "human"})
    out_h = asyncio.run(getattr(g2 := decide_input_guardrail(hs_h, "ag_1", case_from_input=lambda *a: CASE), "guardrail_function", g2)(_RunCtx({}), None, "x"))
    assert (out_h["tripwire_triggered"] if isinstance(out_h, dict) else out_h.tripwire_triggered) is True
    hs_r = FakeDoor({**RECEIPT, "route": "review"})
    out_r = asyncio.run(getattr(g3 := decide_input_guardrail(hs_r, "ag_1", case_from_input=lambda *a: CASE), "guardrail_function", g3)(_RunCtx({}), None, "x"))
    assert (out_r["tripwire_triggered"] if isinstance(out_r, dict) else out_r.tripwire_triggered) is False
    hs_e = FakeDoor(fail=RuntimeError("x"))
    out_e = asyncio.run(getattr(g4 := decide_input_guardrail(hs_e, "ag_1", case_from_input=lambda *a: CASE, fallback="human"), "guardrail_function", g4)(_RunCtx({}), None, "x"))
    info_e = out_e["output_info"] if isinstance(out_e, dict) else out_e.output_info
    assert info_e["fallback"] is True and info_e["route"] == "human"


# -- LangChain -----------------------------------------------------------------------------------
def test_langchain_decide_middleware_gates_on_route_and_attests_the_tools_called():
    pytest.importorskip("langchain.agents.middleware")
    from langchain.agents import create_agent
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain_core.messages import AIMessage
    from hunter_seeker.langchain_middleware import DecideMiddleware

    def run(hs):
        mw = DecideMiddleware(hs, "ag_1", case_from_state=lambda s, r: CASE, source="urn:rt")
        model = GenericFakeChatModel(messages=iter([AIMessage(content="MODEL_RAN")] * 3))
        agent = create_agent(model=model, tools=[], middleware=[mw])
        return mw, agent.invoke({"messages": [("user", "go")]})

    mw, out = run(FakeDoor())
    assert out["hs_route"] == "act" and any(getattr(m, "content", "") == "MODEL_RAN" for m in out["messages"])
    mw_h, out_h = run(FakeDoor({**RECEIPT, "route": "human"}))
    assert out_h["hs_route"] == "human" and not any(getattr(m, "content", "") == "MODEL_RAN" for m in out_h["messages"])
    assert out_h["hs_decision"].receipt["route"] == "human"
    mw_e, out_e = run(FakeDoor(fail=RuntimeError("x")))
    assert out_e["hs_route"] == "none" and out_e["hs_decision"].fallback


# -- the grep-level rule -------------------------------------------------------------------------
def test_no_wrapper_reads_lane_for_control_flow_and_nothing_denies():
    src = ROOT / "python" / "hunter_seeker"
    lane_use = re.compile(r"""(?:\.lane\b|\["lane"\]|\.get\("lane"\))""")
    for name in ("runtime.py", "adk.py", "openai_agents.py", "langchain_middleware.py"):
        text = (src / name).read_text(encoding="utf-8")
        code = "\n".join(l for l in text.splitlines() if not l.strip().startswith("#"))
        # `lane` is READ only into RouteDecision.lane (a passthrough); never compared or branched on
        for m in lane_use.finditer(code):
            line = code[code.rfind("\n", 0, m.start()) + 1: code.find("\n", m.end())]
            assert "==" not in line and " in " not in line and "if " not in line, f"{name}: {line.strip()}"
        assert "permissionDecision" not in text and '"deny"' not in text
    for rel in ("hooks/claude-code/hooks.json", "hooks/claude-code/hs-hook.sh"):
        assert "permissionDecision" not in (ROOT / rel).read_text(encoding="utf-8")
    node = (ROOT / "n8n" / "nodes" / "HunterSeeker" / "HunterSeeker.node.ts").read_text(encoding="utf-8")
    assert 'PORTS_FIELD = "route"' in node


# -- the Claude Code hook, end to end ------------------------------------------------------------
class _Door(BaseHTTPRequestHandler):
    calls: list = []

    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("content-length", "0"))
        body = json.loads(self.rfile.read(n) or b"{}")
        _Door.calls.append((self.path, body, self.headers.get("authorization")))
        if self.path.endswith("/decide"):
            case_id = str((body.get("case") or {}).get("case_id") or "c1")
            out = {**RECEIPT, "case_id": case_id, "case_ref": case_id}
        else:
            out = {"accepted": 1, "duplicates": 0, "held": 0, "events": []}
        data = json.dumps(out).encode()
        self.send_response(200); self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def log_message(self, *a):  # quiet
        return


@pytest.fixture
def door():
    _Door.calls = []
    srv = HTTPServer(("127.0.0.1", 0), _Door)
    t = threading.Thread(target=srv.serve_forever, daemon=True); t.start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def _run_hook(event, stdin, env, tmp_path, door_url):
    envfile = tmp_path / "env.sh"
    full = {**os.environ, "HS_API_KEY": "hsk_live_" + "a" * 32, "HS_AGENT_ID": "ag_1", "HS_SOURCE": "urn:rt",
            "HS_BASE_URL": door_url, "CLAUDE_ENV_FILE": str(envfile), **env}
    r = subprocess.run([sys.executable, "-m", "hunter_seeker.cli", "hook", event], input=json.dumps(stdin),
                       capture_output=True, text=True, env=full, cwd=str(ROOT / "python"), timeout=30)
    return r, envfile


def test_hs_hook_end_to_end_writes_the_route_attests_and_closes(tmp_path, door):
    r, envfile = _run_hook("session-start", {"session_id": "sess_1", "hook_event_name": "SessionStart"}, {}, tmp_path, door)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    text = envfile.read_text(encoding="utf-8")
    assert "export HS_ROUTE='act'" in text and "export HS_ARM='treat'" in text and "export HS_LEVER_ID='lv_9'" in text
    assert "export HS_CASE_REF='sess_1'" in text and "permissionDecision" not in r.stdout
    assert _Door.calls[-1][0].endswith("/v1/decide") and _Door.calls[-1][1]["case"]["case_id"] == "sess_1"
    r2, _ = _run_hook("post-tool", {"session_id": "sess_1", "tool_name": "Edit", "tool_input": {"path": "x"}},
                      {"HS_ARM": "treat", "HS_LEVER_ID": "lv_9"}, tmp_path, door)
    assert r2.returncode == 0
    ev = _Door.calls[-1][1]["events"][0]
    assert ev["type"] == "action.attested" and ev["subject"] == "sess_1" and ev["data"] == {"tool": "Edit", "arm": "treat", "lever_id": "lv_9"}
    r3, _ = _run_hook("stop", {"session_id": "sess_1"}, {}, tmp_path, door)
    assert r3.returncode == 0 and _Door.calls[-1][1]["events"][0]["type"] == "case.closed"


def test_hs_hook_without_a_door_is_the_fallback_and_still_exits_zero(tmp_path):
    r, envfile = _run_hook("session-start", {"session_id": "sess_2"}, {"HS_FALLBACK": "review"}, tmp_path, "http://127.0.0.1:9")
    assert r.returncode == 0
    text = envfile.read_text(encoding="utf-8")
    assert "export HS_ROUTE='review'" in text and "export HS_FALLBACK_APPLIED='1'" in text


@pytest.mark.skipif(not (Path("/usr/bin/bash").exists() or Path("C:/Program Files/Git/bin/bash.exe").exists()), reason="bash")
def test_the_curl_hook_script_writes_the_route_without_python(tmp_path, door):
    bash = "/usr/bin/bash" if Path("/usr/bin/bash").exists() else "C:/Program Files/Git/bin/bash.exe"
    envfile = tmp_path / "env.sh"
    env = {**os.environ, "HS_API_KEY": "hsk_live_" + "a" * 32, "HS_AGENT_ID": "ag_1", "HS_SOURCE": "urn:rt",
           "HS_BASE_URL": door, "CLAUDE_ENV_FILE": str(envfile)}
    script = str(ROOT / "hooks" / "claude-code" / "hs-hook.sh")
    r = subprocess.run([bash, script, "session-start"], input=json.dumps({"session_id": "sess_3"}),
                       capture_output=True, text=True, env=env, timeout=30)
    assert r.returncode == 0, r.stderr
    text = envfile.read_text(encoding="utf-8")
    assert "export HS_ROUTE=act" in text and "export HS_ARM=treat" in text and "export HS_CASE_REF=sess_3" in text
    assert "hookSpecificOutput" in r.stdout and "permissionDecision" not in r.stdout
    r2 = subprocess.run([bash, script, "post-tool"], input=json.dumps({"session_id": "sess_3", "tool_name": "Bash"}),
                        capture_output=True, text=True, env={**env, "HS_ARM": "treat", "HS_LEVER_ID": "lv_9"}, timeout=30)
    assert r2.returncode == 0
    ev = _Door.calls[-1][1]["events"][0]
    assert ev["type"] == "action.attested" and ev["data"] == {"tool": "Bash", "arm": "treat", "lever_id": "lv_9"}
