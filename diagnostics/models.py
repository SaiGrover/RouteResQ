"""Data structures for live network diagnostics. All values originate from executed
commands or socket calls; nothing in here is estimated."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class CommandRecord:
    """An executed OS command, kept for transparency in the UI and reports."""

    argv: list[str]
    returncode: int | None
    duration_s: float
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    error: str | None = None  # e.g. executable not found


@dataclass
class DNSResult:
    query: str
    is_ip_literal: bool
    addresses: list[str] = field(default_factory=list)
    success: bool = False
    error_kind: str | None = None  # "nxdomain" | "temporary" | "no_data" | "other"
    error: str | None = None
    duration_ms: float | None = None


@dataclass
class PingResult:
    target: str
    resolved_ip: str | None = None
    sent: int = 0
    received: int = 0
    rtts_ms: list[float] = field(default_factory=list)
    loss_pct: float | None = None
    min_ms: float | None = None
    avg_ms: float | None = None
    max_ms: float | None = None
    stdev_ms: float | None = None
    # OS-reported conditions
    dns_failure: bool = False
    timeouts: int = 0
    unreachable_reports: list[str] = field(default_factory=list)  # e.g. "Destination host unreachable (from 192.168.1.1)"
    general_failure: bool = False
    # Parse quality
    parsed_ok: bool = False
    summary_sent: int | None = None
    summary_received: int | None = None
    parse_warnings: list[str] = field(default_factory=list)
    command: CommandRecord | None = None


@dataclass
class Hop:
    ttl: int
    address: str | None
    rtts_ms: list[float | None] = field(default_factory=list)
    annotations: list[str] = field(default_factory=list)  # e.g. "!H", "!N"

    @property
    def responded(self) -> bool:
        return self.address is not None and any(r is not None for r in self.rtts_ms)


@dataclass
class TracerouteResult:
    target: str
    resolved_ip: str | None = None
    hops: list[Hop] = field(default_factory=list)
    reached_destination: bool = False
    max_hops: int = 0
    dns_failure: bool = False
    parsed_ok: bool = False
    parse_warnings: list[str] = field(default_factory=list)
    command: CommandRecord | None = None

    @property
    def last_responding_hop(self) -> Hop | None:
        responding = [h for h in self.hops if h.responded]
        return responding[-1] if responding else None

    @property
    def trailing_timeouts(self) -> int:
        n = 0
        for h in reversed(self.hops):
            if h.responded:
                break
            n += 1
        return n

    @property
    def path(self) -> list[str | None]:
        return [h.address for h in self.hops]


@dataclass
class TCPCheckResult:
    host: str
    port: int
    success: bool
    connect_ms: float | None = None
    error_kind: str | None = None  # "refused" | "timeout" | "unreachable" | "dns" | "other"
    error: str | None = None


@dataclass
class NetworkConfig:
    hostname: str
    platform: str
    local_addresses: list[str] = field(default_factory=list)
    default_gateway: str | None = None
    dns_servers: list[str] = field(default_factory=list)
    primary_source_ip: str | None = None
    notes: list[str] = field(default_factory=list)
    commands: list[CommandRecord] = field(default_factory=list)


@dataclass
class DiagnosticRun:
    run_id: str
    target: str
    timestamp: str
    platform: str
    options: dict[str, Any]
    dns: DNSResult | None = None
    ping: PingResult | None = None
    gateway_ping: PingResult | None = None
    traceroute: TracerouteResult | None = None
    tcp_check: TCPCheckResult | None = None
    config: NetworkConfig | None = None
    throughput_kbps: float | None = None  # only set when a throughput measurement was made
    label: str = ""
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---- rebuild from stored JSON (history files) ----
def _cmd(d: dict | None) -> CommandRecord | None:
    return CommandRecord(**d) if d else None


def ping_from_dict(d: dict | None) -> PingResult | None:
    if not d:
        return None
    d = dict(d)
    d["command"] = _cmd(d.get("command"))
    return PingResult(**d)


def traceroute_from_dict(d: dict | None) -> TracerouteResult | None:
    if not d:
        return None
    d = dict(d)
    d["command"] = _cmd(d.get("command"))
    d["hops"] = [Hop(**h) for h in d.get("hops", [])]
    return TracerouteResult(**d)


def run_from_dict(d: dict) -> DiagnosticRun:
    cfg = d.get("config")
    if cfg:
        cfg = dict(cfg)
        cfg["commands"] = [CommandRecord(**c) for c in cfg.get("commands", [])]
        cfg = NetworkConfig(**cfg)
    return DiagnosticRun(
        run_id=d["run_id"],
        target=d["target"],
        timestamp=d["timestamp"],
        platform=d.get("platform", ""),
        options=d.get("options", {}),
        dns=DNSResult(**d["dns"]) if d.get("dns") else None,
        ping=ping_from_dict(d.get("ping")),
        gateway_ping=ping_from_dict(d.get("gateway_ping")),
        traceroute=traceroute_from_dict(d.get("traceroute")),
        tcp_check=TCPCheckResult(**d["tcp_check"]) if d.get("tcp_check") else None,
        config=cfg,
        throughput_kbps=d.get("throughput_kbps"),
        label=d.get("label", ""),
        errors=d.get("errors", []),
    )
