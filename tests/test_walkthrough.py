"""Guided demo and root-cause report.

Backends are replaced with deterministic fakes (mocked), so these tests check the demo's
own logic: per-stage status, verification, error isolation, stored-result labelling and
the report wording. The real backends are covered by the other test files.
"""
import uuid
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from analysis import cause_report
from simulation.experiments import latest_result
from tests.helpers import make_run
from walkthrough import flow

ROOT = Path(__file__).resolve().parent.parent
NS2_OK = {"available": True, "kind": "local", "detail": "/usr/bin/ns", "version": "2.35"}
NS2_MISSING = {"available": False, "kind": None, "detail": "NS2 was not found", "version": None}
NETLAB_OK = {"available": True, "backend": "docker", "reason": "test backend"}


# ------------------------------------------------------------------ fakes
def fake_diagnostics(target, **_kw):
    if target == "boom.example":
        raise RuntimeError("simulated crash in the diagnostic engine")
    rid = uuid.uuid4().hex[:12]
    if target == "nonexistent.invalid":
        return make_run(target, dns_ok=False, dns_kind="nxdomain", run_id=rid)
    if target == "garbled.example":
        return make_run(target, rtts=[], ping_parsed=False, run_id=rid)
    if target == "192.0.2.1":
        return make_run(target, ip_literal=True, resolved=target, rtts=[], run_id=rid,
                        tr_hops=[("192.168.1.1", [1, 1, 1]), ("10.0.0.1", [5, 5, 5]), (None, [None] * 3)])
    return make_run(target, ip_literal=True, resolved=target, run_id=rid,
                    tr_hops=[("192.168.1.1", [1, 1, 1]), (target, [9, 9, 9])])


def fake_sim(fail: set[str] = frozenset()):
    def _run(sc, *_a, **_k):
        if sc.id in fail:
            raise RuntimeError(f"ns crashed for {sc.id}")
        # a real stored result stands in for a fresh run; like a real run, it records this machine's path
        run_dir, res = flow._stored_run(sc.id)
        res["run"]["run_dir"] = str(run_dir)
        return res
    return _run


def fake_comparison(**_kw):
    return {"tcp": [{"ok": True, "integrity_ok": True}], "udp": [{"datagrams_sent": 391, "delivered_pct": 100.0}],
            "explanation": []}


class _TLS:
    def __init__(self):
        from communication.tcp_client import TLSInfo, TransferResult

        info = TLSInfo("TLSv1.3", "TLS_AES_256_GCM_SHA384", 256, "CN=localhost", "CN=RouteResQ Lab CA", "x", "ab")
        self.message = TransferResult(True, "message", "127.0.0.1", 1, tls=True, tls_info=info)
        self.file = TransferResult(True, "file", "127.0.0.1", 1, tls=True, payload_bytes=10, connect_ms=.1,
                                   server_ack={"sha256": "ab"}, integrity_ok=True, tls_info=info)


def fake_drills(**_kw):
    return {"timestamp": "t", "records": [
        {"failure_type": "Server unavailable", "condition_created": "No process listening on 127.0.0.1:9",
         "observed_error_kind": "refused", "observed_error": "ConnectionRefusedError", "impact": "rejected",
         "restoration": "started server", "resumed": True, "resume_detail": "ok", "injected": True, "details": {}}]}


def fake_upload_run(tmp_path):
    """A copy of the recorded upload run stands in for a fresh one (marked live, like a real run)."""
    import json
    import shutil

    from netlab import runner

    def _run(*_a, **_k):
        d = tmp_path / "netlab_live"
        if d.exists():
            shutil.rmtree(d)
        shutil.copytree(runner.RECORDED_DIR, d)
        meta = json.loads((d / "meta.json").read_text())
        meta["source"] = "live"
        (d / "meta.json").write_text(json.dumps(meta))
        return d
    return _run


@pytest.fixture()
def backends(monkeypatch, tmp_path):
    monkeypatch.setattr(flow, "HISTORY_ROOT", tmp_path / "diag")
    monkeypatch.setattr("diagnostics.engine.run_diagnostics", fake_diagnostics)
    monkeypatch.setattr("simulation.experiments.run_and_analyze", fake_sim())
    monkeypatch.setattr("communication.experiments.run_comparison", fake_comparison)
    monkeypatch.setattr("security.tls.run_secure_transfer", lambda **_k: _TLS())
    monkeypatch.setattr("communication.failures.run_all", fake_drills)
    monkeypatch.setattr("netlab.runner.run_sample", fake_upload_run(tmp_path))
    monkeypatch.setattr("netlab.runner.backend_status", lambda: NETLAB_OK)
    return monkeypatch


def run_everything(state, ns2=NS2_OK, targets=None, scenarios=None):
    flow.run_detect(state, targets)
    flow.run_impact(state, scenarios, ns2)
    flow.run_transport(state)
    flow.run_upload(state, NETLAB_OK)


# ------------------------------------------------------------------ flow logic
def test_new_state_is_not_started():
    st_ = flow.new_state()
    assert all(flow.step_status(st_, k) == flow.NOT_STARTED for k, _ in flow.STEPS)


def test_full_success_is_reported_as_fresh(backends):
    s = flow.new_state()
    run_everything(s)
    assert {k: flow.step_status(s, k) for k, _ in flow.STEPS} == {k: flow.SUCCESS for k, _ in flow.STEPS}
    md = flow.build_report(s)
    assert "Every stage completed with fresh, verified measurements" in md
    assert "## Root causes identified" in md and "Confirmed (injected)" in md
    assert "## Evidence chains" in md and "**Next check:**" in md


def test_detect_failure_is_isolated_and_successes_kept(backends):
    s = flow.new_state()
    flow.run_detect(s, ["8.8.8.8", "boom.example"])
    per = s["detect"]["per_target"]
    assert s["detect"]["status"] == flow.PARTIAL
    assert per["8.8.8.8"]["ok"] and per["boom.example"]["error"].startswith("RuntimeError")
    assert len(flow.detect_records(s)) == 1 and flow.step_status(s, "diagnose") == flow.SUCCESS
    assert "boom.example" in flow.build_report(s) and "Errors encountered" in flow.build_report(s)


def test_unparseable_measurement_is_not_verified(backends):
    s = flow.new_state()
    flow.run_detect(s, ["garbled.example"])
    v = s["detect"]["per_target"]["garbled.example"]
    assert not v["ok"] and "could not be parsed" in v["verified"]
    assert s["detect"]["status"] == flow.FAILED


def test_dns_failure_counts_as_a_valid_measurement(backends):
    s = flow.new_state()
    flow.run_detect(s, ["nonexistent.invalid"])
    assert s["detect"]["per_target"]["nonexistent.invalid"]["ok"]


def test_ns2_unavailable_uses_labelled_stored_runs(backends):
    s = flow.new_state()
    run_everything(s, ns2=NS2_MISSING)
    per = s["impact"]["per_scenario"]
    assert s["impact"]["status"] == flow.STORED and all(v["source"] == "stored" for v in per.values())
    assert all("stored run started" in v["verified"] for v in per.values())
    assert flow.step_status(s, "recovery") == flow.STORED
    md = flow.build_report(s)
    assert "Every stage completed with fresh" not in md
    assert "**stored runs**" in md and "(stored run)" in md


def test_fresh_failure_falls_back_to_stored_and_is_partial(backends):
    backends.setattr("simulation.experiments.run_and_analyze", fake_sim({"congestion"}))
    s = flow.new_state()
    flow.run_impact(s, None, NS2_OK)
    c = s["impact"]["per_scenario"]["congestion"]
    assert c["source"] == "stored" and "ns crashed" in c["error"]
    assert s["impact"]["status"] == flow.PARTIAL
    assert s["impact"]["per_scenario"]["healthy"]["source"] == "fresh"


def test_selected_scenarios_only(backends):
    s = flow.new_state()
    flow.run_impact(s, ["healthy", "link_failure_static"], NS2_OK)
    assert set(s["impact"]["per_scenario"]) == {"healthy", "link_failure_static"}
    assert set(flow.sim_results(s)) == {"healthy", "link_failure_static"}


def test_recovery_needs_a_failure_scenario(backends):
    s = flow.new_state()
    flow.run_impact(s, ["healthy"], NS2_OK)
    assert flow.step_status(s, "recovery") == flow.FAILED


def test_transport_part_failure_keeps_other_results(backends):
    def boom(**_k):
        raise OSError("TLS port in use")
    backends.setattr("security.tls.run_secure_transfer", boom)
    s = flow.new_state()
    flow.run_transport(s)
    parts = s["transport"]["parts"]
    assert s["transport"]["status"] == flow.PARTIAL
    assert parts["tcpudp"]["ok"] and parts["drills"]["ok"] and "TLS port in use" in parts["tls"]["error"]


def test_rerun_replaces_stage_result(backends):
    s = flow.new_state()
    flow.run_detect(s, ["boom.example"])
    assert s["detect"]["status"] == flow.FAILED
    flow.run_detect(s, ["8.8.8.8"])                       # retry after the problem is fixed
    assert s["detect"]["status"] == flow.SUCCESS and list(s["detect"]["per_target"]) == ["8.8.8.8"]


def test_evidence_chain_for_unreachable_destination(backends):
    s = flow.new_state()
    flow.run_detect(s, ["192.0.2.1"])
    ch = flow.evidence_chain(flow.detect_records(s)[0])
    assert ch["status"] == cause_report.NOT_CONFIRMED and len(ch["alternatives"]) >= 2
    assert any("did not answer any ping" in x for x in ch["symptoms"])
    assert ch["next_checks"] and any("not confirmed" in x for x in ch["limitations"])


# ------------------------------------------------------------------ root-cause report
def test_live_cause_likely_for_nxdomain():
    from failure_analysis.rules import Thresholds, analyze_run

    run = make_run("bad.example", dns_ok=False, dns_kind="nxdomain")
    c = cause_report.live_cause(run.to_dict(), analyze_run(run, th=Thresholds()).to_dict())
    assert c["status"] == cause_report.LIKELY and "does not exist" in c["cause"]


def test_sim_cause_is_confirmed_and_has_mechanism():
    c = cause_report.sim_cause(latest_result("link_failure_static"))
    assert c["status"] == cause_report.CONFIRMED and "rtmodel-at" in c["cause"] and "static routing" in c["mechanism"]
    assert cause_report.sim_cause(latest_result("healthy"))["status"] == cause_report.NO_FAILURE


def test_register_reanalyses_stale_stored_analysis():
    """A stored analysis written by an older rule set is replaced by today's rules."""
    run = make_run("8.8.8.8", ip_literal=True, resolved="8.8.8.8", run_id="x1")
    stale = {"classifications": ["Healthy / Reachable", "Possible Routing Issue"], "findings": [],
             "explanations": [], "observations": [], "contradictions": [], "conclusion": "old"}
    rows = cause_report.collect([{"run": run.to_dict(), "analysis": stale}], {}, None)
    assert rows[0]["status"] == cause_report.NO_FAILURE
    old = cause_report.collect([{"run": run.to_dict(), "analysis": stale}], {}, None, reanalyze=False)
    assert old[0]["status"] == cause_report.NOT_CONFIRMED


def test_cause_report_markdown_sections():
    rows = cause_report.collect([], {"link_failure_dv": latest_result("link_failure_dv")}, fake_drills())
    md = cause_report.cause_report_markdown(rows)
    assert "## Summary" in md and "## Details" in md and "How it caused the failure" in md
    assert [r["source"] for r in rows] == ["NS2 simulation", "Transport drill"]


# ------------------------------------------------------------------ UI (AppTest, same fakes)
@pytest.mark.ui
def test_full_demo_through_ui_reports_verified_stages(backends):
    backends.setattr("ui.data.ns2_status", lambda: NS2_OK)
    backends.setattr("ui.data.netlab_status", lambda: NETLAB_OK)
    at = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=180).run()
    at.switch_page("app_pages/demo_page.py").run()
    next(b for b in at.button if b.label == "Run the full demo").click().run()
    assert not at.exception, [x.message for x in at.exception]
    w = at.session_state["wt"]
    assert w["step"] == len(flow.STEPS) - 1 and all(flow.step_status(w, k) == flow.SUCCESS for k, _ in flow.STEPS)
    assert "Every stage completed with fresh, verified measurements" in flow.build_report(w)
    n = len(flow.STEPS)
    assert any(d.value["status"].tolist() == ["verified"] * n for d in at.dataframe if "status" in d.value)
    for i in range(n):                       # every completed step is directly reachable
        at.button(key=f"wt_btn_{i}").click().run()
        assert not at.exception and at.session_state["wt"]["step"] == i
    next(b for b in at.button if b.label == "Reset").click().run()
    assert at.session_state["wt"]["detect"] is None


@pytest.mark.ui
def test_demo_without_ns2_labels_stored_data(backends):
    backends.setattr("ui.data.ns2_status", lambda: NS2_MISSING)
    at = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=180).run()
    at.switch_page("app_pages/demo_page.py").run()
    next(b for b in at.button if b.label == "Run the full demo").click().run()
    assert not at.exception
    w = at.session_state["wt"]
    assert flow.step_status(w, "impact") == flow.STORED
    assert "stored runs" in flow.build_report(w)
