import json, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from hunter_seeker import Client, HunterSeekerError

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        n = int(self.headers.get("content-length", 0)); body = json.loads(self.rfile.read(n) or b"{}")
        if self.path == "/v1/score-entity":
            out = {"entity": {"entity_id": "a", "score": 0.9, "band": "act", "max_autonomy": "L3", "principal_reasons": []}, "verdict": {"expires_at": "2099-01-01T00:00:00Z"}, "signature": {"protected": "x", "signature": "y"}, "billable_decisions": 1}
            self.send_response(200)
        else:
            out = {"type": "https://hunter-seeker.io/problems/model_ref_expired", "title": "expired", "status": 404, "detail": "gone", "hs": {"code": "model_ref_expired", "remedy": "re-run", "field": "model_ref"}}
            self.send_response(404)
        self.send_header("content-type", "application/json"); self.end_headers(); self.wfile.write(json.dumps(out).encode())

def test_client_roundtrip_and_problem_mapping():
    srv = HTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
    hs = Client(api_key="hsk_test_abc", base_url=f"http://127.0.0.1:{srv.server_port}")
    assert hs.test_mode
    r = hs.score_entity("mr1_x", {"tenure": 1}, subject_kind="org")
    assert r["entity"]["band"] == "act"
    try:
        hs.drift_status("mr1_gone"); assert False
    except HunterSeekerError as e:
        assert e.problem.code == "model_ref_expired" and e.problem.remedy == "re-run" and not e.retryable
    srv.shutdown()

def test_init_proposes_and_never_guesses(tmp_path, monkeypatch):
    from hunter_seeker.cli import main
    (tmp_path / "leads.csv").write_text("id,churned,other,tenure\n1,1,1,5\n2,0,0,5\n3,1,1,2\n")
    monkeypatch.chdir(tmp_path)
    assert main(["init", "leads.csv"]) == 0
    spec = (tmp_path / "hs.yaml").read_text()
    assert 'entity_column: "id"' in spec and 'outcome_column: null' in spec  # two outcome candidates → a choice, not a guess


def test_missing_signature_is_unverifiable_not_valid():
    hs = Client(api_key="hsk_test_abc", base_url="http://127.0.0.1:1")
    assert hs.verify({"expires_at": "2099-01-01T00:00:00Z"}, None) == "invalid_signature"
    assert hs.verify({"expires_at": "2099-01-01T00:00:00Z"}, {}) == "invalid_signature"
