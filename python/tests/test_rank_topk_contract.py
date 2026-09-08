"""What rank_topk puts on the wire, and how long it is willing to wait.

The loop it replaces had no deadline and no attempt cap: it exited only when the server stopped
saying "pending", so a stalled task hung an unattended agent forever. It also rebound the response
wholesale on every iteration, discarding `stage` and `facts_so_far` — the staged-progress contract
the platform built on purpose — so from Python a 40-minute run and a hung process look identical.
"""
import itertools, json, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import pytest
from hunter_seeker import Client, HunterSeekerError

SEEN: list = []


def _server(script):
    """`script` yields one response per POST to /v1/rank-topk or /v1/poll-task."""
    it = iter(script)

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_POST(self):
            n = int(self.headers.get("content-length", 0))
            SEEN.append((self.path, json.loads(self.rfile.read(n) or b"{}")))
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(next(it)).encode())

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _client(srv):
    return Client(api_key="hsk_test_x", base_url=f"http://127.0.0.1:{srv.server_port}")


def setup_function(_):
    SEEN.clear()


def test_polarity_is_forwarded_when_stated_and_OMITTED_when_not():
    # Sending a default would author a polarity the caller never gave, and polarity decides which
    # way every lever reads. Unstated must mean absent, not False.
    srv = _server([{"ranking_ref": "r"}, {"ranking_ref": "r"}, {"ranking_ref": "r"}])
    hs = _client(srv)
    common = dict(rows=[{"a": 1}], entity_column="a", outcome_column="b", subject_kind="org")
    hs.rank_topk(**common)
    assert "outcome_is_desirable" not in SEEN[-1][1]
    hs.rank_topk(**common, outcome_is_desirable=False)
    assert SEEN[-1][1]["outcome_is_desirable"] is False
    hs.rank_topk(**common, outcome_is_desirable=True)
    assert SEEN[-1][1]["outcome_is_desirable"] is True
    srv.shutdown()


def test_page_carries_k_and_only_carries_offset_when_asked():
    srv = _server([{"ranking_ref": "r"}, {"ranking_ref": "r"}])
    hs = _client(srv)
    common = dict(rows=[{"a": 1}], entity_column="a", outcome_column="b", subject_kind="org")
    hs.rank_topk(**common, k=5)
    assert SEEN[-1][1]["page"] == {"k": 5}
    hs.rank_topk(**common, k=5, offset=20)
    assert SEEN[-1][1]["page"] == {"k": 5, "offset": 20}
    srv.shutdown()


def test_a_stalled_task_raises_instead_of_hanging_forever():
    pending = {"status": "pending", "task_id": "t1", "retry_after_ms": 0}
    # repeat, not a fixed list: a tight poll loop with no deadline would drain any finite script
    # and the test would pass for the wrong reason (a dead server, not a deadline).
    srv = _server(itertools.repeat(pending))
    hs = _client(srv)
    with pytest.raises(HunterSeekerError) as e:
        hs.rank_topk(rows=[{"a": 1}], entity_column="a", outcome_column="b", subject_kind="org",
                     poll_s=0.0, timeout_s=0.25)
    assert e.value.problem.code == "poll_timeout"
    # and it must not tell the caller to re-submit — that would cost a second run
    assert "do not re-submit" in e.value.problem.remedy
    srv.shutdown()


def test_progress_reaches_the_caller_instead_of_the_floor():
    stage = {"stage": "profiling", "frac": 0.05, "facts_so_far": {"row_count": 40}}
    srv = _server([{"status": "pending", "task_id": "t1", "retry_after_ms": 0, "stage": stage},
                   {"status": "pending", "task_id": "t1", "retry_after_ms": 0, "stage": stage},
                   {"ranking_ref": "r", "model_ref": None}])
    seen = []
    hs = _client(srv)
    out = hs.rank_topk(rows=[{"a": 1}], entity_column="a", outcome_column="b", subject_kind="org",
                       poll_s=0.0, on_progress=seen.append)
    assert out["ranking_ref"] == "r"
    assert len(seen) == 2, "every pending envelope must be offered, not just the first"
    assert seen[0]["stage"]["stage"] == "profiling"
    assert seen[0]["stage"]["frac"] == 0.05
    srv.shutdown()


def test_a_pending_envelope_with_no_task_id_is_a_problem_not_a_KeyError():
    srv = _server([{"status": "pending"}])
    hs = _client(srv)
    with pytest.raises(HunterSeekerError) as e:
        hs.rank_topk(rows=[{"a": 1}], entity_column="a", outcome_column="b", subject_kind="org")
    assert e.value.problem.code == "no_task_id"
    srv.shutdown()


def test_an_empty_table_is_a_local_error_not_a_confusing_server_422():
    hs = Client(api_key="hsk_test_x", base_url="http://127.0.0.1:1")
    for empty in ({"rows": []}, {"csv": ""}):
        with pytest.raises(ValueError):
            hs.rank_topk(**empty, entity_column="a", outcome_column="b", subject_kind="org")
