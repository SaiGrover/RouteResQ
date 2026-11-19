"""File upload under link failure (netlab).

* pure analysis: stall measurement, counter windows, first backup traffic, classification;
* settings bounds and the bundled sample;
* the recorded run: the fault happened during the transfer, and the saved progress, events and
  outcomes agree with each other;
* the recorded-run fallback (hosted deployment / no backend) and the root-cause register rows;
* one real end-to-end run in the isolated test network (marker ``netlab``, skipped without a backend).
"""
from __future__ import annotations

import json

import pytest

from analysis import cause_report
from netlab import analysis
from netlab.config import (MAX_FILE_BYTES, MIN_FILE_BYTES, RUN_MODES, SAMPLE_BYTES, ConfigError, LabConfig,
                           check_file_size, sample_bytes)
from netlab import runner
from netlab.report import rows, write_report


# ---------------------------------------------------------------------------- analysis
def prog(points, conn=1):
    return [(t, b, conn) for t, b in points]


def test_stall_is_the_pause_caused_by_the_fault_not_an_earlier_one():
    p = prog([(0.0, 0), (0.1, 10), (0.6, 20), (0.7, 30), (0.8, 40), (3.9, 50), (4.0, 60)])
    # a 0.5 s pause happens before the fault at 0.75 s; only the 3.1 s pause after it counts
    s = analysis.stall(p, 1, t_fault=0.75)
    assert s == {"stall_s": 3.1, "start": 0.8, "end": 3.9, "resumed": True}
    # without a fault (baseline) the longest pause anywhere counts
    assert analysis.stall(p, 1)["stall_s"] == 3.1
    assert analysis.stall(prog([(0, 0), (0.1, 5), (0.6, 9), (0.7, 12)]), 1)["stall_s"] == 0.5


def test_stall_that_never_resumes_runs_until_the_connection_was_given_up():
    p = prog([(0.0, 0), (0.1, 10), (0.2, 20)])
    s = analysis.stall(p, 1, t_fault=0.15, t_gave_up=10.2)
    assert s["resumed"] is False and s["end"] is None and s["stall_s"] == 10.0


def test_progress_of_other_connections_is_ignored():
    p = prog([(0, 0), (0.1, 10), (5.0, 20)], conn=1) + prog([(6.0, 5), (6.1, 99)], conn=2)
    assert analysis.increments(p, 2) == [(6.0, 5), (6.1, 99)]
    assert analysis.stall(p, 1, t_fault=0.05)["stall_s"] == 4.9


def test_counter_window_excludes_bytes_counted_before_it():
    c = [(0.0, {"c_backup_tx": 100}), (1.0, {"c_backup_tx": 5_000}), (1.05, {"c_primary_tx": 1}),
         (1.1, {"c_backup_tx": 5_100}), (1.2, {"c_backup_tx": 60_000}), (2.0, {"c_backup_tx": 900_000})]
    # window starts at 1.02: the first backup sample at/after it is 5_100, so earlier bytes never leak in
    assert analysis.delta(c, "c_backup_tx", 1.02, 2.0) == 894_900
    assert analysis.first_traffic(c, "c_backup_tx", 1.02) == 1.2      # first growth >= 16 KiB
    assert analysis.first_traffic(c, "c_backup_tx", 2.0) is None
    assert analysis.value_at(c, "c_backup_tx", 1.15) == 5_100
    assert analysis.delta(c, "missing", 0, 2) is None


@pytest.mark.parametrize("args, code", [
    ((False, True, True, 1, False, None), "completed"),
    ((True, True, True, 1, True, True), "continued_on_backup"),
    ((True, True, True, 1, False, False), "stalled_then_resumed"),
    ((True, True, True, 2, False, False), "completed_after_retry"),
    ((True, True, False, 2, False, False), "failed"),
    ((True, False, True, 1, False, None), "fault_not_during_transfer"),
])
def test_classification(args, code):
    assert analysis.classify(*args)[0] == code


def test_a_retry_is_never_reported_as_the_same_connection_resuming():
    code, label = analysis.classify(True, True, True, 2, True, True)
    assert code == "completed_after_retry" and "new TCP connection" in label


# ---------------------------------------------------------------------------- settings
def test_settings_are_bounded():
    LabConfig().validate()
    for bad in ({"fault_at_pct": 95}, {"outage_s": 0.1}, {"rate_kib_s": 10_000}, {"timeout_s": 60},
                {"retries": 9}, {"runs": ["baseline", "nope"]}, {"max_run_s": 600}):
        with pytest.raises(ConfigError):
            LabConfig(**bad).validate()
    with pytest.raises(ConfigError):
        check_file_size(MIN_FILE_BYTES - 1)
    with pytest.raises(ConfigError):
        check_file_size(MAX_FILE_BYTES + 1)
    check_file_size(SAMPLE_BYTES)


def test_bundled_sample_is_deterministic():
    assert sample_bytes(4096) == sample_bytes(4096) and len(sample_bytes()) == SAMPLE_BYTES


# ---------------------------------------------------------------------------- the recorded run
@pytest.fixture(scope="module")
def recorded():
    run = runner.recorded_run()
    assert run, "results/netlab/recorded is missing"
    return run


def test_recorded_run_has_three_runs_with_identical_settings(recorded):
    assert set(recorded["runs"]) == set(RUN_MODES)
    assert recorded["meta"]["source"] == "recorded"
    cfgs = {json.dumps(r["config"], sort_keys=True) for r in recorded["runs"].values()}
    files = {(r["file"]["size"], r["file"]["sha256"]) for r in recorded["runs"].values()}
    assert len(cfgs) == 1 and len(files) == 1


def test_fault_hit_the_upload_in_progress_at_the_configured_point(recorded):
    for mode in ("failover", "static"):
        r = recorded["runs"][mode]
        o, ev = r["outcome"], {e["kind"]: e for e in r["events"]}
        size, pct = r["file"]["size"], r["config"]["fault_at_pct"]
        assert o["fault_during_transfer"]
        assert ev["transfer_start"]["t"] < ev["link_down"]["t"] < ev["server_complete"]["t"]
        # the server had received at least the configured share when the link went down, and not all of it
        at = max(b for t, b, c in r["progress"] if c == 1 and t <= ev["link_down"]["t"])
        assert size * pct / 100 <= at < size
        assert ev["link_up"]["t"] - ev["link_down"]["t"] == pytest.approx(r["config"]["outage_s"], abs=0.05)


def test_saved_progress_events_and_outcomes_agree(recorded):
    for mode, r in recorded["runs"].items():
        o = r["outcome"]
        # receiver progress only ever grows on a connection, and ends at the file size on success
        for cid in {c for _, _, c in r["progress"]}:
            bs = [b for _, b, c in r["progress"] if c == cid]
            assert bs == sorted(bs)
        assert max(b for _, b, _ in r["progress"]) == r["file"]["size"]
        # the stored stall is what the analysis computes from the stored progress
        again = analysis.stall(r["progress"], 1, t_fault=o["link_down_t"])
        assert again["stall_s"] == o["stall_s"]
        assert o["sha256_match"] and r["server_sha256"] == r["file"]["sha256"]
        assert o["connections"] == len(r["attempts"]) == len(r["server_connections"])


def test_recorded_outcomes_answer_the_question(recorded):
    o = {m: r["outcome"] for m, r in recorded["runs"].items()}
    assert o["baseline"]["code"] == "completed"
    assert o["failover"]["code"] == "continued_on_backup" and o["failover"]["backup_used"]
    assert o["failover"]["first_backup_traffic_t"] < o["failover"]["link_up_t"]
    assert o["static"]["code"] == "stalled_then_resumed" and not o["static"]["backup_used"]
    assert o["static"]["stall_s"] > o["failover"]["stall_s"]
    assert o["static"]["stall_end"] > o["static"]["link_up_t"]          # resumed only after the link returned
    # the kernel's forwarding decision: backup interface during the outage only with a backup route
    during = {m: next(x for x in r["routes"] if "went down" in x["label"]) for m, r in recorded["runs"].items() if m != "baseline"}
    assert "dev cb0" in during["failover"]["c"] and "no route" in during["static"]["c"]


def test_comparison_rows_and_report(recorded, tmp_path):
    rs = rows(recorded)
    assert [r["mode"] for r in rs] == list(RUN_MODES)
    assert all(r["sha256_match"] for r in rs) and not any(r["retry_required"] for r in rs)
    p = write_report(recorded, tmp_path / "upload.md")
    md = p.read_text(encoding="utf-8")
    assert "Recorded run" in md and "floating static route" in md and "Stall duration" in md


# ---------------------------------------------------------------------------- fallback and register
def test_hosted_deployment_has_no_backend_and_falls_back_to_the_recording(monkeypatch):
    monkeypatch.setenv("ROUTERESQ_PUBLIC", "1")
    st = runner.backend_status()
    assert st["available"] is False and "recorded" in st["reason"]
    with pytest.raises(runner.NetlabError):
        runner.run_sample()
    assert runner.latest(prefer_live=False)["meta"]["source"] == "recorded"


def test_demo_stage_uses_recording_when_the_live_run_fails(monkeypatch):
    from walkthrough import flow

    def boom(*a, **k):
        raise RuntimeError("namespace creation refused")

    monkeypatch.setattr(runner, "run_sample", boom)
    state = flow.new_state()
    e = flow.run_upload(state, {"available": True, "backend": "docker"})
    assert e["status"] == flow.STORED and e["source"] == "stored" and "refused" in e["error"]
    md = flow.build_report(state)
    assert "recorded run" in md and "Upload under link failure" in md


def test_register_rows_for_the_upload_runs(recorded):
    out = cause_report.collect([], {}, None, upload=recorded)
    by = {r["subject"].split(" (")[0]: r for r in out}
    assert by["Healthy baseline"]["status"] == cause_report.NO_FAILURE
    assert by["Link failure · backup route"]["status"] == cause_report.CONFIRMED
    assert by["Link failure · static forwarding"]["status"] == cause_report.CONFIRMED
    assert all("recorded run" in r["subject"] for r in out)


# ---------------------------------------------------------------------------- real end-to-end run
@pytest.mark.netlab
def test_real_upload_under_link_failure():
    st = runner.backend_status()
    if not st["available"]:
        pytest.skip(st["reason"])
    import shutil

    cfg = LabConfig(rate_kib_s=1024, outage_s=1.5, timeout_s=8)
    run_dir = runner.run_experiment(sample_bytes(1024 * 1024), "test-1MiB.bin", cfg)
    try:
        run = runner.load_run(run_dir)
        o = {m: r["outcome"] for m, r in run["runs"].items()}
        assert o["baseline"]["code"] == "completed"
        assert o["failover"]["code"] == "continued_on_backup"
        assert o["static"]["code"] == "stalled_then_resumed"
        assert all(x["sha256_match"] for x in o.values())
        assert not (run_dir / "input.bin").exists()          # the uploaded copy is removed after the run
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)           # keep test runs out of the app's run list
