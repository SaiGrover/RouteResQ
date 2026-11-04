"""Builders for deterministic, mocked test inputs (synthetic NS2 traces and diagnostic runs)."""
from __future__ import annotations

from diagnostics.models import (
    DiagnosticRun, DNSResult, Hop, NetworkConfig, PingResult, TCPCheckResult, TracerouteResult,
)


def _line(ev: str, t: float, a: int, b: int, seq: int, pid: int, fid: int = 1, size: int = 1000,
          src: int = 0, dst: int = 5, ptype: str = "cbr") -> str:
    return f"{ev} {t:.6f} {a} {b} {ptype} {size} ------- {fid} {src}.0 {dst}.0 {seq} {pid}"


def packet(pid: int, seq: int, t0: float, path: list[int], hop_delay: float = 0.01, *, fid: int = 1,
           drop_hop: int | None = None, stop: tuple[str, int] | None = None) -> list[tuple[float, str]]:
    """Events of one packet travelling along ``path``.

    drop_hop=i  -> 'd' right after the enqueue on hop i (queue drop or link-down drop)
    stop=('arrive', i)  -> packet arrives at the end of hop i and is never seen again
    stop=('dequeue', i) -> packet starts transmission on hop i and is never received
    """
    out: list[tuple[float, str]] = []
    t = t0
    src, dst = path[0], path[-1]
    for i, (a, b) in enumerate(zip(path, path[1:])):
        out.append((t, _line("+", t, a, b, seq, pid, fid, src=src, dst=dst)))
        if drop_hop == i:
            out.append((t, _line("d", t, a, b, seq, pid, fid, src=src, dst=dst)))
            return out
        out.append((t, _line("-", t, a, b, seq, pid, fid, src=src, dst=dst)))
        if stop == ("dequeue", i):
            return out
        t = round(t + hop_delay, 6)
        out.append((t, _line("r", t, a, b, seq, pid, fid, src=src, dst=dst)))
        if stop == ("arrive", i):
            return out
    return out


def trace_text(events: list[tuple[float, str]]) -> str:
    return "\n".join(line for _t, line in sorted(events, key=lambda x: x[0])) + "\n"


# ------------------------------------------------------------------ diagnostic runs
def make_run(
    target: str = "example.com",
    *,
    dns_ok: bool = True,
    dns_kind: str | None = None,
    ip_literal: bool = False,
    resolved: str = "93.184.216.34",
    sent: int = 4,
    rtts: list[float] | None = None,
    unreachable: list[str] | None = None,
    ping_parsed: bool = True,
    gateway: str | None = "192.168.1.1",
    gateway_replies: int | None = 4,
    tr_hops: list[tuple[str | None, list[float | None]]] | None = None,
    tr_reached: bool | None = None,
    tcp: tuple[bool, str | None] | None = None,
    run_id: str = "r1",
    throughput: float | None = None,
) -> DiagnosticRun:
    rtts = [10.0, 11.0, 12.0, 11.0] if rtts is None else rtts
    dns = DNSResult(target, ip_literal, [resolved] if dns_ok else [], dns_ok,
                    None if dns_ok else (dns_kind or "nxdomain"),
                    None if dns_ok else "[11001] getaddrinfo failed", 5.0)
    ping = None
    if dns_ok or ip_literal:
        recv = len(rtts)
        ping = PingResult(target=resolved, resolved_ip=resolved, sent=sent if ping_parsed else 0, received=recv,
                          rtts_ms=list(rtts), parsed_ok=ping_parsed,
                          loss_pct=round(100 * (sent - recv) / sent, 2) if ping_parsed and sent else None,
                          timeouts=sent - recv - len(unreachable or []),
                          unreachable_reports=list(unreachable or []))
        if rtts:
            from statistics import mean, pstdev
            ping.min_ms, ping.max_ms, ping.avg_ms = min(rtts), max(rtts), round(mean(rtts), 3)
            ping.stdev_ms = round(pstdev(rtts), 3) if len(rtts) > 1 else None
        if not ping_parsed:
            ping.parse_warnings.append("no probes could be identified in the output")
    gw_ping = None
    if gateway and gateway_replies is not None:
        gw_ping = PingResult(target=gateway, sent=4, received=gateway_replies, parsed_ok=True,
                             rtts_ms=[1.0] * gateway_replies,
                             loss_pct=100.0 * (4 - gateway_replies) / 4)
    tr = None
    if tr_hops is not None:
        tr = TracerouteResult(target=resolved, resolved_ip=resolved,
                              hops=[Hop(i + 1, a, r) for i, (a, r) in enumerate(tr_hops)], parsed_ok=True)
        tr.reached_destination = tr_reached if tr_reached is not None else any(a == resolved for a, _ in tr_hops)
        tr.max_hops = len(tr_hops)
    tcp_res = None
    if tcp is not None:
        tcp_res = TCPCheckResult(resolved, 443, tcp[0], 5.0 if tcp[0] else None, tcp[1], None if tcp[0] else tcp[1])
    return DiagnosticRun(
        run_id=run_id, target=target, timestamp="2026-01-01T00:00:00+00:00", platform="test", options={},
        dns=dns, ping=ping, gateway_ping=gw_ping, traceroute=tr, tcp_check=tcp_res,
        config=NetworkConfig("host", "test", ["192.168.1.2"], gateway, ["192.168.1.1"]),
        throughput_kbps=throughput,
    )
