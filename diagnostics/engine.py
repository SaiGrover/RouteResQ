"""Live diagnostic engine: DNS, gateway check, ping, traceroute, TCP connect and
network-configuration inspection. Each step is a real OS command or socket call."""
from __future__ import annotations

import errno
import ipaddress
import platform
import socket
import time
import uuid
from typing import Callable

from common.logging_setup import get_logger
from common.storage import utc_now_iso
from diagnostics.authorization import authorize
from diagnostics.commands import IS_WINDOWS, CommandRunner, SubprocessRunner, ping_command, traceroute_command
from diagnostics.models import DiagnosticRun, DNSResult, NetworkConfig, PingResult, TCPCheckResult, TracerouteResult
from diagnostics.parsers import (
    parse_default_gateway,
    parse_ping,
    parse_resolv_conf,
    parse_traceroute,
    parse_windows_dns_servers,
)

log = get_logger("diagnostics.engine")

Resolver = Callable[[str], list[str]]

_NONAME = {getattr(socket, "EAI_NONAME", -2), 11001, -2, 8}
_AGAIN = {getattr(socket, "EAI_AGAIN", -3), 11002, -3}
_NODATA = {getattr(socket, "EAI_NODATA", -5), 11004, -5, 7}
_UNREACH = {errno.ENETUNREACH, errno.EHOSTUNREACH, 10051, 10065}


def _default_resolver(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    out: list[str] = []
    for fam, *_rest, sockaddr in infos:
        ip = sockaddr[0]
        if ip not in out and fam in (socket.AF_INET, socket.AF_INET6):
            out.append(ip)
    # Prefer IPv4 so that ping/traceroute use the same family on every OS
    return sorted(out, key=lambda a: ":" in a)


def resolve(target: str, resolver: Resolver | None = None) -> DNSResult:
    try:
        ipaddress.ip_address(target)
        return DNSResult(target, True, [target], True, duration_ms=0.0)
    except ValueError:
        pass
    resolver = resolver or _default_resolver
    t0 = time.perf_counter()
    try:
        addrs = resolver(target)
        ms = round((time.perf_counter() - t0) * 1000, 2)
        if not addrs:
            return DNSResult(target, False, [], False, "no_data", "resolver returned no addresses", ms)
        return DNSResult(target, False, addrs, True, duration_ms=ms)
    except socket.gaierror as exc:
        ms = round((time.perf_counter() - t0) * 1000, 2)
        code = exc.args[0] if exc.args else None
        kind = "nxdomain" if code in _NONAME else "temporary" if code in _AGAIN else "no_data" if code in _NODATA else "other"
        return DNSResult(target, False, [], False, kind, f"[{code}] {exc.strerror or exc}", ms)
    except (OSError, UnicodeError) as exc:
        ms = round((time.perf_counter() - t0) * 1000, 2)
        return DNSResult(target, False, [], False, "other", str(exc), ms)


def ping(target: str, count: int = 4, timeout_s: float = 1.0, runner: CommandRunner | None = None,
         windows: bool = IS_WINDOWS) -> PingResult:
    runner = runner or SubprocessRunner()
    argv, sub_timeout = ping_command(target, count, timeout_s, windows)
    rec = runner.run(argv, sub_timeout)
    res = parse_ping(rec.stdout + ("\n" + rec.stderr if rec.stderr else ""), target, windows)
    res.command = rec
    if rec.error:
        res.parse_warnings.insert(0, rec.error)
        res.parsed_ok = False if rec.error and not rec.stdout else res.parsed_ok
    return res


def traceroute(target: str, max_hops: int = 15, timeout_s: float = 1.0, runner: CommandRunner | None = None,
               windows: bool = IS_WINDOWS, resolved_ip: str | None = None) -> TracerouteResult:
    runner = runner or SubprocessRunner()
    argv, sub_timeout = traceroute_command(target, max_hops, timeout_s, windows, runner)
    rec = runner.run(argv, sub_timeout)
    res = parse_traceroute(rec.stdout + ("\n" + rec.stderr if rec.stderr else ""), target, windows, resolved_ip)
    res.command = rec
    if rec.error:
        res.parse_warnings.insert(0, rec.error)
    if rec.timed_out:
        res.parse_warnings.append("traceroute was stopped by the timeout; the hop list may be incomplete")
    return res


def tcp_check(host: str, port: int, timeout_s: float = 3.0) -> TCPCheckResult:
    if not 1 <= port <= 65535:
        raise ValueError("port must be 1-65535")
    t0 = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return TCPCheckResult(host, port, True, round((time.perf_counter() - t0) * 1000, 2))
    except ConnectionRefusedError as exc:
        return TCPCheckResult(host, port, False, round((time.perf_counter() - t0) * 1000, 2), "refused", str(exc))
    except (socket.timeout, TimeoutError) as exc:
        return TCPCheckResult(host, port, False, None, "timeout", f"no response within {timeout_s}s ({exc})")
    except socket.gaierror as exc:
        return TCPCheckResult(host, port, False, None, "dns", str(exc))
    except OSError as exc:
        kind = "unreachable" if exc.errno in _UNREACH or getattr(exc, "winerror", None) in _UNREACH else "other"
        return TCPCheckResult(host, port, False, None, kind, str(exc))


def _primary_source_ip() -> str | None:
    """Local address the OS would use for outbound traffic (UDP connect sends no packet)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            return s.getsockname()[0]
    except OSError:
        return None


def inspect_network(runner: CommandRunner | None = None, windows: bool = IS_WINDOWS) -> NetworkConfig:
    runner = runner or SubprocessRunner()
    cfg = NetworkConfig(hostname=socket.gethostname(), platform=f"{platform.system()} {platform.release()}")
    try:
        addrs = {i[4][0] for i in socket.getaddrinfo(cfg.hostname, None)}
        cfg.local_addresses = sorted(addrs, key=lambda a: (":" in a, a))
    except OSError as exc:
        cfg.notes.append(f"could not list local addresses: {exc}")
    cfg.primary_source_ip = _primary_source_ip()
    if windows:
        r = runner.run(["route", "print", "-4"], 20)
        cfg.commands.append(r)
        cfg.default_gateway = parse_default_gateway(r.stdout, True)
        r2 = runner.run(["ipconfig", "/all"], 20)
        cfg.commands.append(r2)
        cfg.dns_servers = parse_windows_dns_servers(r2.stdout)
    else:
        r = runner.run(["ip", "route"], 20)
        cfg.commands.append(r)
        cfg.default_gateway = parse_default_gateway(r.stdout, False)
        try:
            with open("/etc/resolv.conf", encoding="utf-8") as fh:
                cfg.dns_servers = parse_resolv_conf(fh.read())
        except OSError as exc:
            cfg.notes.append(f"could not read /etc/resolv.conf: {exc}")
    if cfg.default_gateway is None:
        cfg.notes.append("no default gateway found in the routing table")
    return cfg


def run_diagnostics(
    target: str,
    *,
    ping_count: int = 4,
    timeout_s: float = 1.0,
    do_traceroute: bool = True,
    max_hops: int = 15,
    tcp_port: int | None = None,
    check_gateway: bool = True,
    label: str = "",
    runner: CommandRunner | None = None,
    resolver: Resolver | None = None,
    windows: bool = IS_WINDOWS,
    skip_authorization: bool = False,
) -> DiagnosticRun:
    """Run the full diagnostic sequence against one authorised destination."""
    if not 1 <= ping_count <= 50:
        raise ValueError("ping_count must be between 1 and 50")
    if not 1 <= max_hops <= 30:
        raise ValueError("max_hops must be between 1 and 30")
    if not 0.2 <= timeout_s <= 10:
        raise ValueError("timeout_s must be between 0.2 and 10 seconds")
    target = target.strip() if skip_authorization else authorize(target)
    runner = runner or SubprocessRunner()
    run = DiagnosticRun(
        run_id=uuid.uuid4().hex[:12],
        target=target,
        timestamp=utc_now_iso(),
        platform=f"{platform.system()} {platform.release()}",
        options={"ping_count": ping_count, "timeout_s": timeout_s, "traceroute": do_traceroute,
                 "max_hops": max_hops, "tcp_port": tcp_port, "check_gateway": check_gateway},
        label=label,
    )
    log.info("diagnostics start %s (%s)", target, run.run_id)
    try:
        run.config = inspect_network(runner, windows)
    except Exception as exc:  # inspection is supporting evidence only
        run.errors.append(f"network inspection failed: {exc}")

    run.dns = resolve(target, resolver)
    probe_target = run.dns.addresses[0] if run.dns.success else target

    if check_gateway and run.config and run.config.default_gateway:
        run.gateway_ping = ping(run.config.default_gateway, min(ping_count, 4), timeout_s, runner, windows)

    run.ping = ping(probe_target, ping_count, timeout_s, runner, windows)
    if run.dns.success and not run.ping.resolved_ip:
        run.ping.resolved_ip = probe_target

    if do_traceroute:
        if run.dns.success:
            run.traceroute = traceroute(probe_target, max_hops, timeout_s, runner, windows, resolved_ip=probe_target)
        else:
            run.errors.append("traceroute skipped: destination name could not be resolved")

    if tcp_port:
        run.tcp_check = tcp_check(probe_target, tcp_port, timeout_s=max(timeout_s * 3, 2.0))
    log.info("diagnostics done %s (%s)", target, run.run_id)
    return run
