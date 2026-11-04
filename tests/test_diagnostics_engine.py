"""Diagnostic pipeline with a mocked command runner (deterministic), plus authorisation,
command construction and history/baseline handling."""
import socket
from pathlib import Path

import pytest

from diagnostics.authorization import TargetNotAllowed, authorize, check_target
from diagnostics.commands import ALLOWED_EXECUTABLES, SubprocessRunner, ping_command, traceroute_command
from diagnostics.engine import resolve, run_diagnostics
from diagnostics.history import DiagnosticHistory, compare_runs
from diagnostics.models import CommandRecord, run_from_dict
from failure_analysis.rules import DNS_FAILURE, HEALTHY, ROUTING, UNREACHABLE, Thresholds, analyze_run

FIX = Path(__file__).parent / "fixtures" / "windows"
ROUTE_PRINT = "          0.0.0.0          0.0.0.0      192.168.1.1      192.168.1.2     50\n"


class FakeRunner:
    """Returns canned (real, captured) Windows outputs keyed by executable + target."""

    def __init__(self, outputs: dict[tuple[str, str], str]):
        self.outputs = outputs
        self.calls: list[list[str]] = []

    def available(self, exe: str) -> bool:
        return True

    def run(self, argv, timeout):
        self.calls.append(argv)
        key = (argv[0], argv[-1])
        if argv[0] == "route":
            return CommandRecord(argv, 0, 0.01, ROUTE_PRINT)
        if argv[0] == "ipconfig":
            return CommandRecord(argv, 0, 0.01, "   DNS Servers . . . . . . . . . . . : 192.168.1.1\n")
        return CommandRecord(argv, 0, 0.1, self.outputs.get(key, ""))


GW_OK = (FIX / "ping_localhost.txt").read_text().replace("127.0.0.1", "192.168.1.1")


def fake_resolver(mapping):
    def _r(host):
        if host in mapping:
            return mapping[host]
        raise socket.gaierror(11001, "getaddrinfo failed")
    return _r


def test_pipeline_reachable_with_mocked_commands():
    runner = FakeRunner({
        ("ping", "192.168.1.1"): GW_OK,
        ("ping", "8.8.8.8"): (FIX / "ping_public.txt").read_text(),
        ("tracert", "8.8.8.8"): (FIX / "tracert_public.txt").read_text(),
    })
    run = run_diagnostics("8.8.8.8", runner=runner, windows=True, max_hops=8)
    assert run.config.default_gateway == "192.168.1.1" and run.config.dns_servers == ["192.168.1.1"]
    assert run.gateway_ping.received == 4 and run.ping.received == 4
    assert not run.traceroute.reached_destination  # hop limit 8 in the captured output
    rep = analyze_run(run, th=Thresholds())
    assert rep.classifications == [HEALTHY]
    assert any("routing failure" in c for c in rep.contradictions)
    assert ["tracert", "-d", "-h", "8", "-w", "1000", "8.8.8.8"] in runner.calls


def test_pipeline_dns_failure_skips_traceroute():
    runner = FakeRunner({("ping", "192.168.1.1"): GW_OK,
                         ("ping", "nonexistent.invalid"): (FIX / "ping_dns_fail.txt").read_text()})
    run = run_diagnostics("nonexistent.invalid", runner=runner, windows=True, resolver=fake_resolver({}))
    assert not run.dns.success and run.dns.error_kind == "nxdomain"
    assert run.traceroute is None and any("traceroute skipped" in e for e in run.errors)
    assert analyze_run(run, th=Thresholds()).classifications == [DNS_FAILURE]


def test_pipeline_unreachable_with_real_timeout_outputs():
    runner = FakeRunner({("ping", "192.168.1.1"): GW_OK,
                         ("ping", "192.0.2.1"): (FIX / "ping_timeout.txt").read_text(),
                         ("tracert", "192.0.2.1"): (FIX / "tracert_timeout.txt").read_text()})
    run = run_diagnostics("192.0.2.1", runner=runner, windows=True, max_hops=5)
    rep = analyze_run(run, th=Thresholds())
    assert UNREACHABLE in rep.classifications and ROUTING in rep.classifications
    assert "TTL 2 (10.240.12.49)" in " ".join(rep.observations)


def test_missing_executable_is_reported_not_fabricated(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda exe: None)
    rec = SubprocessRunner().run(["ping", "-n", "1", "127.0.0.1"], 5)
    assert rec.returncode is None and "not installed" in rec.error


def test_runner_refuses_non_allowlisted_executables():
    with pytest.raises(PermissionError):
        SubprocessRunner().run(["powershell", "-c", "whoami"], 5)
    assert "cmd" not in ALLOWED_EXECUTABLES and "sh" not in ALLOWED_EXECUTABLES


def test_command_builders_use_argument_lists():
    argv, _ = ping_command("8.8.8.8", 4, 1.0, windows=True)
    assert argv == ["ping", "-n", "4", "-w", "1000", "8.8.8.8"]
    argv, _ = ping_command("8.8.8.8", 3, 2.0, windows=False)
    assert argv[:3] == ["ping", "-c", "3"] and argv[-1] == "8.8.8.8"
    argv, _ = traceroute_command("1.1.1.1", 10, 1.0, windows=False)
    assert argv[0] == "traceroute" and "-n" in argv


@pytest.mark.parametrize("bad", ["", "-n 1 8.8.8.8", "8.8.8.8; rm -rf /", "a b", "evil.example.org", "$(whoami)"])
def test_unauthorised_or_malformed_targets_rejected(bad):
    with pytest.raises(TargetNotAllowed):
        authorize(bad)


@pytest.mark.parametrize("ok", ["127.0.0.1", "localhost", "8.8.8.8", "192.168.1.1", "nonexistent.invalid", "192.0.2.1"])
def test_authorised_targets(ok):
    assert check_target(ok).allowed


def test_input_validation():
    with pytest.raises(ValueError):
        run_diagnostics("127.0.0.1", ping_count=500, runner=FakeRunner({}))
    with pytest.raises(ValueError):
        run_diagnostics("127.0.0.1", max_hops=99, runner=FakeRunner({}))


def test_resolve_ip_literal_and_errors():
    assert resolve("10.1.2.3").is_ip_literal
    r = resolve("x.example", resolver=fake_resolver({}))
    assert not r.success and r.error_kind == "nxdomain"
    r2 = resolve("y.example", resolver=lambda h: (_ for _ in ()).throw(socket.gaierror(11002, "try again")))
    assert r2.error_kind == "temporary"


def test_history_baseline_and_comparison(tmp_path):
    h = DiagnosticHistory(tmp_path)
    from tests.helpers import make_run

    a = make_run(run_id="a", tr_hops=[("192.168.1.1", [1]), ("10.0.0.1", [4]), ("93.184.216.34", [9])])
    b = make_run(run_id="b", rtts=[40, 41, 42, 40], tr_hops=[("192.168.1.1", [1]), ("10.0.0.9", [4]),
                                                             ("93.184.216.34", [9])])
    h.save(a, analyze_run(a, th=Thresholds()))
    h.save(b, analyze_run(b, th=Thresholds()))
    assert [r.run_id for r in h.runs("example.com")] == ["a", "b"]
    assert h.previous("example.com", before_run_id="b").run_id == "a"
    h.set_baseline("example.com", "a")
    assert h.baseline("example.com").run_id == "a"
    cmp = compare_runs(h.get("a"), h.get("b"))
    rtt = next(m for m in cmp["metrics"] if m["metric"] == "Average RTT ms")
    assert rtt["change"] == pytest.approx(40.75 - 11.0) and cmp["path_changed"]
    csv = h.export_csv()
    assert csv.exists() and "classifications" in csv.read_text()
    # round trip through JSON keeps nested objects
    rt = run_from_dict(h.records()[0]["run"])
    assert rt.traceroute.hops[1].address == "10.0.0.1"


def test_public_deployment_restrictions(monkeypatch, tmp_path):
    from diagnostics.authorization import add_authorized_host

    monkeypatch.setenv("ROUTERESQ_PUBLIC", "1")
    assert not check_target("192.168.1.1").allowed  # hosting provider's internal network
    assert check_target("127.0.0.1").allowed and check_target("8.8.8.8").allowed
    with pytest.raises(TargetNotAllowed):
        add_authorized_host("example.org")
    monkeypatch.setenv("ROUTERESQ_PUBLIC", "0")
    assert check_target("192.168.1.1").allowed
