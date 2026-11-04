"""Real NS2 runs (marked ``ns2``; skipped automatically when NS2 is not installed).

These tests execute the actual simulator and check the behaviour RouteResQ reports
against the trace - nothing here is mocked.
"""
import subprocess

import pytest

from analysis.comparison import compare
from analysis.report import comparison_report, experiment_report
from common.paths import TCL_SCRIPT
from simulation.experiments import run_and_analyze
from simulation.runner import DOCKER_IMAGE, NS2UnavailableError, detect_backend
from simulation.scenario import load_all_scenarios

pytestmark = pytest.mark.ns2


@pytest.fixture(scope="module")
def backend():
    try:
        return detect_backend()
    except NS2UnavailableError as exc:
        pytest.skip(f"NS2 not available: {exc}")


@pytest.fixture(scope="module")
def results(backend, tmp_path_factory):
    out = tmp_path_factory.mktemp("ns2")
    return {sid: run_and_analyze(sc, backend, out_root=out) for sid, sc in load_all_scenarios().items()}


def test_ns2_script_execution_and_outputs(results):
    for sid, r in results.items():
        assert r["trace_quality"]["malformed_lines"] == 0, sid
        assert r["trace_quality"]["packet_events"] > 1000
        assert r["run"]["returncode"] == 0


def test_unknown_parameter_is_rejected_by_tcl(backend, tmp_path):
    if backend.kind == "local":
        cmd = [backend.detail, str(TCL_SCRIPT), "bogus=1"]
    else:
        cmd = ["docker", "run", "--rm", "-v", f"{TCL_SCRIPT.parent}:/s:ro", DOCKER_IMAGE, "/s/routeresq.tcl", "bogus=1"]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert res.returncode == 2 and "Unknown parameter" in res.stderr


def test_healthy_baseline(results):
    r = results["healthy"]
    s = r["flows"]["1"]["summary"]
    # 1 Mb/s, 1000-byte packets from 1.0 s to 9.0 s inclusive -> 1001 packets
    assert s["sent"] == 1001 and s["delivered"] == 1001 and s["loss_pct"] == 0
    assert r["route_changes"] == [] and r["delivery_gaps"] == []
    # propagation 2+10+10+2 ms + transmission 0.8+4+4+0.8 ms = 33.6 ms
    assert s["avg_delay_ms"] == pytest.approx(33.6, abs=0.01)
    assert r["findings"]["recovery"]["outcome"] == "not applicable"


def test_link_failure_dv_reroutes(results):
    r = results["link_failure_dv"]
    f = r["findings"]
    assert {(e["state"], e["time"]) for e in r["trace_quality"]["link_events"]} >= {("down", 3.0), ("up", 6.0)}
    ch = r["route_changes"]
    assert ch[0]["from_path"] == "0-1-2-4-5" and ch[0]["to_path"] == "0-1-3-4-5"
    assert 3.0 <= ch[0]["time"] < 3.1
    assert any(c["to_path"] == "0-1-2-4-5" and c["time"] >= 6.0 for c in ch[1:])  # back after restore
    assert f["recovery"]["outcome"].startswith("rerouted")
    assert f["destination_reachable_during_failure"] and not f["communication_stopped"]
    assert 0 < f["packets_lost_due_to_failure"] <= 10
    # alternative path: 2+15+15+2 ms + transmission 9.6 ms = 43.6 ms
    assert r["phases"]["1"]["during"]["avg_delay_ms"] == pytest.approx(43.6, abs=0.01)
    assert r["routing_control"]["total_messages"] > 0


def test_link_failure_static_interrupts_until_restore(results):
    r = results["link_failure_static"]
    f = r["findings"]
    assert f["recovery"]["outcome"].startswith("interrupted")
    assert r["route_changes"] == [] and r["routing_control"]["total_messages"] == 0
    gap = max(r["delivery_gaps"], key=lambda g: g["duration_s"])
    assert gap["start"] < 3.05 and 6.0 <= gap["end"] < 6.1
    during = r["phases"]["1"]["during"]
    assert during["delivered"] == 0 and during["loss_pct"] == 100
    assert during["fates"]["lost_at_node"] == during["sent"]  # untraced drops located at node 1
    assert r["phases"]["1"]["after"]["loss_pct"] == 0


def test_congestion_queue_drops_and_recovery(results):
    r = results["congestion"]
    f = r["findings"]
    assert r["bottleneck_link"] == "1->2"
    assert r["queue_stats"]["1->2"]["max_queue_pkts"] == 20  # = configured queue limit
    assert f["queue_drops"] > 0 and f["queue_drops_monitored_flow"] > 0
    before, during = r["phases"]["1"]["before"], r["phases"]["1"]["during"]
    assert during["avg_delay_ms"] > before["avg_delay_ms"] and during["throughput_kbps"] < before["throughput_kbps"]
    assert all(lp["fate"] == "dropped_queue" for lp in r["lost_packets"])
    assert f["recovery"]["outcome"].startswith("recovered")
    assert r["route_changes"] == []


def test_timeline_has_configured_and_observed_events(results):
    tl = results["link_failure_dv"]["timeline"]
    kinds = {(e["source"], e["event"]) for e in tl}
    assert ("configured", "LINK_DOWN") in kinds and ("trace", "LINK_DOWN_TRACED") in kinds
    assert ("trace", "ROUTE_CHANGE") in kinds
    assert [e["time"] for e in tl] == sorted(e["time"] for e in tl)
    tl_c = results["congestion"]["timeline"]
    assert any(e["event"] == "QUEUE_FULL" for e in tl_c) and any(e["event"] == "QUEUE_DRAINED" for e in tl_c)


def test_comparison_and_reports(results):
    rows = compare(list(results.values()))
    by = {r["scenario"]: r for r in rows}
    assert by["healthy"]["throughput_vs_baseline_pct"] == 0
    assert by["link_failure_static"]["loss_pct"] > by["link_failure_dv"]["loss_pct"] > 0
    assert by["congestion"]["max_queue_pkts"] == 20
    md = comparison_report(rows)
    assert "| B2 |" in md
    rep = experiment_report(results["link_failure_dv"])
    assert "## What failed?" in rep and "## Was recovery observed?" in rep
