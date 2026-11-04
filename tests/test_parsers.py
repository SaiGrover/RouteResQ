"""Unit tests for ping / traceroute / routing-table parsers.

Fixtures under tests/fixtures/windows and tests/fixtures/linux are REAL outputs captured
on Windows 11 and Ubuntu 24.04. Inline strings are synthetic examples of documented
formats (unreachable replies, truncated output, garbage) that are hard to provoke on demand.
"""
from pathlib import Path

import pytest

from diagnostics.parsers import (
    parse_default_gateway, parse_ping, parse_resolv_conf, parse_traceroute, parse_windows_dns_servers,
)

FIX = Path(__file__).parent / "fixtures"


def fx(os_: str, name: str) -> str:
    return (FIX / os_ / name).read_text(encoding="utf-8", errors="replace")


# --------------------------------------------------------------------------- ping
def test_windows_ping_reachable_real():
    r = parse_ping(fx("windows", "ping_public.txt"), "8.8.8.8", windows=True)
    assert r.parsed_ok and r.sent == 4 and r.received == 4 and r.loss_pct == 0
    assert r.rtts_ms == [5.0, 4.0, 4.0, 4.0]
    assert r.avg_ms == pytest.approx(4.25) and r.min_ms == 4 and r.max_ms == 5


def test_windows_ping_sub_millisecond_recorded_as_zero_with_note():
    r = parse_ping(fx("windows", "ping_localhost.txt"), "127.0.0.1", windows=True)
    assert r.received == 4 and r.rtts_ms == [0.0] * 4
    assert any("<1ms" in w for w in r.parse_warnings)


def test_windows_ping_timeout_real():
    r = parse_ping(fx("windows", "ping_timeout.txt"), "192.0.2.1", windows=True)
    assert r.sent == 3 and r.received == 0 and r.loss_pct == 100 and r.timeouts == 3
    assert r.avg_ms is None


def test_windows_ping_dns_failure_real():
    r = parse_ping(fx("windows", "ping_dns_fail.txt"), "nonexistent.invalid", windows=True)
    assert r.dns_failure and r.parsed_ok and r.sent == 0


def test_windows_unreachable_reply_not_counted_as_received():
    out = """
Pinging 10.9.9.9 with 32 bytes of data:
Reply from 192.168.1.2: Destination host unreachable.
Reply from 192.168.1.2: Destination host unreachable.
Request timed out.

Ping statistics for 10.9.9.9:
    Packets: Sent = 3, Received = 2, Lost = 1 (33% loss),
"""
    r = parse_ping(out, "10.9.9.9", windows=True)
    assert r.received == 0 and r.sent == 3 and r.loss_pct == 100
    assert len(r.unreachable_reports) == 2 and "192.168.1.2" in r.unreachable_reports[0]
    assert any("counts only genuine echo replies" in w for w in r.parse_warnings)


def test_windows_general_failure():
    r = parse_ping("PING: transmit failed. General failure.\n", "10.0.0.1", windows=True)
    assert r.general_failure


def test_linux_ping_reachable_real():
    r = parse_ping(fx("linux", "ping_public.txt"), "8.8.8.8", windows=False)
    assert r.sent == 4 and r.received == 4 and r.loss_pct == 0
    assert r.rtts_ms == [7.15, 5.91, 5.44, 5.44]
    assert r.stdev_ms is not None and r.stdev_ms > 0


def test_linux_ping_timeout_real():
    r = parse_ping(fx("linux", "ping_timeout.txt"), "192.0.2.1", windows=False)
    assert r.sent == 4 and r.received == 0 and r.loss_pct == 100


def test_linux_ping_dns_failure_real():
    r = parse_ping(fx("linux", "ping_dns_fail.txt"), "nonexistent.invalid", windows=False)
    assert r.dns_failure


def test_linux_partial_loss_and_unreachable_from_router():
    out = """PING 10.1.1.1 (10.1.1.1) 56(84) bytes of data.
64 bytes from 10.1.1.1: icmp_seq=1 ttl=63 time=20.1 ms
From 10.0.0.1 icmp_seq=2 Destination Host Unreachable
64 bytes from 10.1.1.1: icmp_seq=3 ttl=63 time=22.3 ms

--- 10.1.1.1 ping statistics ---
4 packets transmitted, 2 received, +1 errors, 50% packet loss, time 3004ms
"""
    r = parse_ping(out, "10.1.1.1", windows=False)
    assert r.sent == 4 and r.received == 2 and r.loss_pct == 50
    assert r.unreachable_reports == ["Destination Host Unreachable (reported by 10.0.0.1)"]


def test_truncated_output_without_summary():
    out = "PING 1.1.1.1 (1.1.1.1) 56(84) bytes of data.\n64 bytes from 1.1.1.1: icmp_seq=1 ttl=57 time=9.8 ms\n"
    r = parse_ping(out, "1.1.1.1", windows=False)
    assert r.received == 1 and r.sent == 1
    assert any("summary line missing" in w for w in r.parse_warnings)


@pytest.mark.parametrize("garbage", ["", "   \n", "segmentation fault\n", "random text 123 ms"])
def test_unparseable_output_is_not_ok(garbage):
    r = parse_ping(garbage, "x", windows=False)
    assert not r.parsed_ok and r.parse_warnings


# --------------------------------------------------------------------- traceroute
def test_windows_tracert_hop_limit_not_reached_real():
    r = parse_traceroute(fx("windows", "tracert_public.txt"), "8.8.8.8", windows=True)
    assert r.parsed_ok and len(r.hops) == 8 and not r.reached_destination
    assert r.hops[0].address == "192.168.1.1" and r.hops[0].rtts_ms == [1.0, 1.0, 1.0]
    assert r.hops[2].address is None and not r.hops[2].responded
    assert r.hops[5].rtts_ms == [None, 4.0, 4.0] and r.hops[5].responded
    assert r.last_responding_hop.ttl == 8 and r.trailing_timeouts == 0


def test_windows_tracert_timeouts_real():
    r = parse_traceroute(fx("windows", "tracert_timeout.txt"), "192.0.2.1", windows=True)
    assert not r.reached_destination and r.trailing_timeouts == 3
    assert r.last_responding_hop.address == "10.240.12.49"


def test_windows_tracert_dns_failure_real():
    r = parse_traceroute(fx("windows", "tracert_dns_fail.txt"), "nonexistent.invalid", windows=True)
    assert r.dns_failure and not r.hops


def test_windows_tracert_reached_and_reports_annotation():
    out = """
Tracing route to 10.5.5.5 over a maximum of 30 hops

  1    <1 ms    <1 ms    <1 ms  192.168.1.1
  2  192.168.1.1  reports: Destination net unreachable.

Trace complete.
"""
    r = parse_traceroute(out, "10.5.5.5", windows=True, resolved_ip="10.5.5.5")
    assert r.hops[0].rtts_ms == [0.0, 0.0, 0.0]
    assert not r.reached_destination


def test_linux_traceroute_real_probes_dropped():
    r = parse_traceroute(fx("linux", "traceroute_public.txt"), "8.8.8.8", windows=False)
    assert r.resolved_ip == "8.8.8.8" and len(r.hops) == 8
    assert r.hops[0].address == "172.17.0.1" and r.trailing_timeouts == 7 and not r.reached_destination


def test_linux_traceroute_dns_failure_real():
    r = parse_traceroute(fx("linux", "traceroute_dns_fail.txt"), "nonexistent.invalid", windows=False)
    assert r.dns_failure


def test_linux_traceroute_annotations_and_multiple_addresses():
    out = """traceroute to 10.9.9.9 (10.9.9.9), 30 hops max, 60 byte packets
 1  192.168.1.1  0.5 ms  0.4 ms  0.4 ms
 2  10.0.0.1  5.1 ms 10.0.0.2  6.0 ms  5.5 ms
 3  10.0.0.9  7.0 ms !H  * 7.2 ms !H
 4  10.9.9.9  9.0 ms  9.1 ms  9.2 ms
"""
    r = parse_traceroute(out, "10.9.9.9", windows=False)
    assert r.reached_destination and len(r.hops) == 4
    assert "also answered by 10.0.0.2" in r.hops[1].annotations
    assert r.hops[2].annotations.count("!H") == 2 and r.hops[2].rtts_ms == [7.0, None, 7.2]


def test_tracepath_format():
    out = """ 1?: [LOCALHOST]                      pmtu 1500
 1:  192.168.1.1                                           0.512ms
 1:  192.168.1.1                                           0.490ms
 2:  no reply
 3:  8.8.8.8                                              10.3ms reached
"""
    r = parse_traceroute(out, "8.8.8.8", windows=False, resolved_ip="8.8.8.8")
    assert [h.ttl for h in r.hops] == [1, 2, 3] and r.reached_destination


def test_empty_traceroute_output():
    r = parse_traceroute("", "x", windows=True)
    assert not r.parsed_ok and r.parse_warnings


# ------------------------------------------------------------- routes / DNS config
def test_windows_default_gateway_lowest_metric():
    out = """Active Routes:
Network Destination        Netmask          Gateway       Interface  Metric
          0.0.0.0          0.0.0.0      10.0.0.1      10.0.0.5     70
          0.0.0.0          0.0.0.0      192.168.1.1      192.168.1.2     50
        127.0.0.0        255.0.0.0         On-link         127.0.0.1    331
"""
    assert parse_default_gateway(out, windows=True) == "192.168.1.1"


def test_linux_default_gateway_real():
    assert parse_default_gateway(fx("linux", "ip_route.txt"), windows=False) == "172.17.0.1"
    assert parse_default_gateway("10.0.0.0/8 dev eth0\n", windows=False) is None


def test_dns_server_parsing():
    ipconfig = """   DNS Servers . . . . . . . . . . . : 192.168.1.1
                                       8.8.8.8
   NetBIOS over Tcpip. . . . . . . . : Enabled
"""
    assert parse_windows_dns_servers(ipconfig) == ["192.168.1.1", "8.8.8.8"]
    assert parse_resolv_conf(fx("linux", "resolv.conf.txt")) == ["192.168.65.7"]
