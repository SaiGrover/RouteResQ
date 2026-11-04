"""Integration tests that execute REAL ping / traceroute / DNS commands (marked ``network``).

Only the loopback address and RFC-reserved test targets are used, so no third-party
host is probed:
* 127.0.0.1            - always reachable
* nonexistent.invalid  - RFC 6761: can never resolve
* 192.0.2.1            - RFC 5737 TEST-NET-1: no host exists
"""
import shutil

import pytest

from diagnostics.commands import IS_WINDOWS
from diagnostics.engine import run_diagnostics, tcp_check
from failure_analysis.rules import DNS_FAILURE, HEALTHY, UNREACHABLE, Thresholds, analyze_run

pytestmark = [pytest.mark.network,
              pytest.mark.skipif(shutil.which("ping") is None, reason="ping not installed")]


def test_loopback_is_healthy():
    run = run_diagnostics("127.0.0.1", ping_count=3, do_traceroute=False, check_gateway=False)
    assert run.ping.parsed_ok and run.ping.received == 3 and run.ping.loss_pct == 0
    assert analyze_run(run, th=Thresholds()).classifications == [HEALTHY]


def test_reserved_invalid_name_gives_dns_failure():
    run = run_diagnostics("nonexistent.invalid", ping_count=1, do_traceroute=True, check_gateway=False)
    assert not run.dns.success and run.traceroute is None
    assert DNS_FAILURE in analyze_run(run, th=Thresholds()).classifications


def test_documentation_address_is_unreachable():
    run = run_diagnostics("192.0.2.1", ping_count=2, timeout_s=0.5, do_traceroute=False, check_gateway=False)
    assert run.ping.received == 0
    rep = analyze_run(run, th=Thresholds())
    assert UNREACHABLE in rep.classifications
    assert "could not be reached" in rep.conclusion


@pytest.mark.skipif(shutil.which("tracert" if IS_WINDOWS else "traceroute") is None, reason="traceroute missing")
def test_traceroute_to_loopback_reaches_destination():
    run = run_diagnostics("127.0.0.1", ping_count=1, do_traceroute=True, max_hops=3, check_gateway=False)
    assert run.traceroute.parsed_ok and run.traceroute.reached_destination


def test_tcp_check_closed_local_port_is_refused():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    r = tcp_check("127.0.0.1", port, timeout_s=5)
    assert not r.success and r.error_kind == "refused"
