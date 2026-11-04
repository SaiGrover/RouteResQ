"""Deterministic, rule-based root-cause analysis for live diagnostic runs.

No machine learning and no confidence percentages. Every output is labelled with one of:

* ``confirmed``              - directly observed in command output (an observation, not a cause)
* ``likely``                 - the explanation most consistent with all collected evidence
* ``possible``               - consistent with the evidence but not distinguishable from alternatives
* ``insufficient_evidence``  - the data cannot support a conclusion

Each rule records whether it fired and why, so the reasoning can be audited (rule trace).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from common.paths import CONFIG_DIR
from diagnostics.models import DiagnosticRun, TracerouteResult

HEALTHY = "Healthy / Reachable"
DNS_FAILURE = "DNS Resolution Failure"
UNREACHABLE = "Unreachable Destination"
HIGH_LATENCY = "High Latency"
PACKET_LOSS = "Packet Loss"
ROUTING = "Possible Routing Issue"
CONGESTION = "Possible Congestion"
INCONCLUSIVE = "Inconclusive / Insufficient Evidence"
CATEGORIES = [HEALTHY, DNS_FAILURE, UNREACHABLE, HIGH_LATENCY, PACKET_LOSS, ROUTING, CONGESTION, INCONCLUSIVE]

CONFIRMED, LIKELY, POSSIBLE, INSUFFICIENT = "confirmed", "likely", "possible", "insufficient_evidence"


@dataclass
class Thresholds:
    high_rtt_ms: float = 150.0
    high_jitter_ms: float = 30.0
    loss_threshold_pct: float = 5.0
    min_rtt_samples: int = 3
    baseline_rtt_factor: float = 1.5
    baseline_rtt_min_increase_ms: float = 20.0
    baseline_loss_increase_pct: float = 10.0
    baseline_jitter_factor: float = 2.0
    throughput_drop_pct: float = 30.0

    @classmethod
    def load(cls, path: Path = CONFIG_DIR / "thresholds.json") -> "Thresholds":
        if not path.exists():
            return cls()
        data = {k: v for k, v in json.loads(path.read_text(encoding="utf-8")).items() if not k.startswith("_")}
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class Finding:
    rule_id: str
    category: str
    level: str
    title: str
    evidence: list[str] = field(default_factory=list)


@dataclass
class Explanation:
    cause: str
    level: str  # likely | possible
    supporting_evidence: list[str] = field(default_factory=list)
    contrary_evidence: list[str] = field(default_factory=list)
    checks_to_confirm: list[str] = field(default_factory=list)
    recommended_actions: list[str] = field(default_factory=list)


@dataclass
class RuleTrace:
    rule_id: str
    description: str
    fired: bool
    reason: str


@dataclass
class AnalysisReport:
    run_id: str
    target: str
    classifications: list[str]
    observations: list[str]
    findings: list[Finding]
    explanations: list[Explanation]
    conclusion: str
    contradictions: list[str]
    rule_trace: list[RuleTrace]
    baseline_run_id: str | None = None
    previous_run_id: str | None = None
    thresholds: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# ------------------------------------------------------------------------ helpers
class _Facts:
    """Normalised view of a run so that rules read clearly."""

    def __init__(self, run: DiagnosticRun):
        self.run = run
        d, p, tr, tcp, gw = run.dns, run.ping, run.traceroute, run.tcp_check, run.gateway_ping
        self.dns_ok = bool(d and d.success)
        self.dns_failed = bool(d and not d.success) or bool(p and p.dns_failure and not self.dns_ok)
        self.dns_kind = d.error_kind if d else None
        self.ping_usable = bool(p and p.parsed_ok and p.sent > 0)
        self.sent = p.sent if p else 0
        self.received = p.received if p else 0
        self.loss = p.loss_pct if self.ping_usable else None
        self.avg = p.avg_ms if p else None
        self.stdev = p.stdev_ms if p else None
        self.samples = len(p.rtts_ms) if p else 0
        self.os_unreachable = list(p.unreachable_reports) if p else []
        self.general_failure = bool(p and p.general_failure)
        self.gw_known = bool(run.config and run.config.default_gateway)
        self.gw_ip = run.config.default_gateway if run.config else None
        self.gw_tested = bool(gw and gw.parsed_ok and gw.sent > 0)
        self.gw_reachable = bool(gw and gw.received > 0)
        self.tr = tr
        self.tr_usable = bool(tr and tr.parsed_ok and tr.hops)
        self.tr_reached = bool(tr and tr.reached_destination)
        self.tr_annotations = [a for h in (tr.hops if tr else []) for a in h.annotations if a.startswith("!") or "unreachable" in a.lower()]
        self.tcp = tcp
        self.tcp_ok = bool(tcp and tcp.success)
        self.tcp_refused = bool(tcp and tcp.error_kind == "refused")
        self.tcp_timeout = bool(tcp and tcp.error_kind == "timeout")
        self.host_responds = self.received > 0 or self.tcp_ok or self.tcp_refused or self.tr_reached


def _hop_desc(tr: TracerouteResult) -> str:
    last = tr.last_responding_hop
    if last is None:
        return "no hop responded"
    return f"last responding hop is TTL {last.ttl} ({last.address}), followed by {tr.trailing_timeouts} silent hop(s)"


def _latency_jump(tr: TracerouteResult | None) -> str | None:
    """Largest increase in median hop RTT between consecutive responding hops."""
    if not tr:
        return None
    pts = []
    for h in tr.hops:
        vals = sorted(r for r in h.rtts_ms if r is not None)
        if h.address and vals:
            pts.append((h.ttl, h.address, vals[len(vals) // 2]))
    best = None
    for (t1, a1, r1), (t2, a2, r2) in zip(pts, pts[1:]):
        if best is None or r2 - r1 > best[0]:
            best = (r2 - r1, t1, a1, t2, a2)
    if best and best[0] > 0:
        return f"largest RTT increase (+{best[0]:.0f} ms) between hop {best[1]} ({best[2]}) and hop {best[3]} ({best[4]})"
    return None


def route_signature(tr: TracerouteResult | None) -> list[str]:
    return [h.address for h in tr.hops if h.address] if tr else []


# ------------------------------------------------------------------------ analysis
def analyze_run(
    run: DiagnosticRun,
    baseline: DiagnosticRun | None = None,
    previous: DiagnosticRun | None = None,
    th: Thresholds | None = None,
) -> AnalysisReport:
    th = th or Thresholds.load()
    f = _Facts(run)
    fb = _Facts(baseline) if baseline else None
    findings: list[Finding] = []
    trace: list[RuleTrace] = []
    observations: list[str] = []
    contradictions: list[str] = []

    def rule(rid: str, desc: str, fired: bool, reason: str) -> bool:
        trace.append(RuleTrace(rid, desc, fired, reason))
        return fired

    # ---- observations (confirmed facts only) ----
    if run.dns:
        if run.dns.is_ip_literal:
            observations.append(f"Destination given as IP address {run.target}; no DNS lookup needed.")
        elif f.dns_ok:
            observations.append(f"DNS resolved {run.target} to {', '.join(run.dns.addresses)} in {run.dns.duration_ms} ms.")
        else:
            observations.append(f"DNS lookup for {run.target} failed ({run.dns.error_kind}: {run.dns.error}).")
    if f.gw_known:
        if f.gw_tested:
            observations.append(
                f"Default gateway {f.gw_ip}: {run.gateway_ping.received}/{run.gateway_ping.sent} echo replies."
            )
        else:
            observations.append(f"Default gateway {f.gw_ip} found but its ping result could not be used.")
    elif run.config:
        observations.append("No default gateway found in the routing table.")
    if f.ping_usable:
        rtt = (f", RTT min/avg/max {run.ping.min_ms}/{run.ping.avg_ms}/{run.ping.max_ms} ms"
               + (f", std-dev {f.stdev} ms" if f.stdev is not None else "")) if f.samples else ""
        observations.append(f"Ping: {f.received}/{f.sent} replies ({f.loss}% loss){rtt}.")
    elif run.ping and not f.dns_failed:
        observations.append("Ping output could not be interpreted: " + "; ".join(run.ping.parse_warnings or ["unknown"]))
    for rep in f.os_unreachable:
        observations.append(f"Operating system / router reported: {rep}.")
    if f.tr_usable:
        observations.append(
            f"Traceroute: {len(f.tr.hops)} hop(s) listed; destination "
            f"{'reached' if f.tr_reached else 'NOT reached'}; {_hop_desc(f.tr)}."
        )
    if run.tcp_check:
        t = run.tcp_check
        observations.append(
            f"TCP connect to port {t.port}: " + ("succeeded" if t.success else f"failed ({t.error_kind})")
            + (f" in {t.connect_ms} ms" if t.connect_ms is not None else "") + "."
        )
    if run.throughput_kbps is not None:
        observations.append(f"Measured throughput: {run.throughput_kbps} kb/s.")

    # ---- R-DNS-01 ----
    if rule("R-DNS-01", "DNS lookup of a host name fails", f.dns_failed,
            f"resolver error kind = {f.dns_kind}" if f.dns_failed else "name resolved or IP literal given"):
        findings.append(Finding("R-DNS-01", DNS_FAILURE, CONFIRMED, "Destination name could not be resolved",
                                [f"resolver error: {run.dns.error}" if run.dns else "ping reported unknown host"]))

    # ---- R-PING-00: ping unusable ----
    rule("R-PING-00", "Ping output is missing or unparseable",
         not f.ping_usable and not f.dns_failed,
         "; ".join(run.ping.parse_warnings) if run.ping and not f.ping_usable else "ping output parsed")

    # ---- R-REACH-01: no echo replies ----
    no_replies = f.ping_usable and f.received == 0 and not f.dns_failed
    if rule("R-REACH-01", "All ICMP echo requests unanswered", no_replies,
            f"{f.received}/{f.sent} replies" if f.ping_usable else "ping not usable"):
        if f.tcp_ok or f.tcp_refused:
            contradictions.append(
                f"Ping received no replies, but a TCP connection attempt got an answer "
                f"({'connected' if f.tcp_ok else 'refused'}): the host is up and ICMP echo is probably filtered."
            )
        elif f.tr_reached:
            contradictions.append(
                "Ping received no replies, but traceroute reached the destination: ICMP echo may be filtered or "
                "the loss was transient."
            )
        else:
            ev = [f"{f.sent} echo requests, 0 replies"]
            if run.ping.timeouts:
                ev.append(f"{run.ping.timeouts} request(s) timed out")
            findings.append(Finding("R-REACH-01", UNREACHABLE, CONFIRMED,
                                    "Destination did not answer any ping (complete loss)", ev))

    # ---- R-REACH-02: OS/router reported unreachable / no route ----
    unreach_reports = f.os_unreachable + [f"traceroute annotation {a}" for a in f.tr_annotations]
    if rule("R-REACH-02", "OS or a router explicitly reports 'unreachable' / 'no route'",
            bool(unreach_reports) and f.received == 0,
            "; ".join(unreach_reports) if unreach_reports else "no unreachable reports in output"):
        findings.append(Finding("R-REACH-02", UNREACHABLE, CONFIRMED, "An unreachable / no-route report was received",
                                unreach_reports))

    # ---- R-TCP-01: TCP timeout ----
    if rule("R-TCP-01", "TCP connection attempt timed out", f.tcp_timeout,
            run.tcp_check.error if run.tcp_check and run.tcp_check.error else "no TCP timeout"):
        findings.append(Finding("R-TCP-01", UNREACHABLE, CONFIRMED,
                                f"Connection timeout on TCP port {run.tcp_check.port}", [run.tcp_check.error or ""]))

    # ---- R-LOSS-01 / R-LOSS-02 ----
    partial = f.ping_usable and 0 < (f.loss or 0) < 100
    if rule("R-LOSS-01", f"Partial packet loss at or above {th.loss_threshold_pct}%",
            partial and f.loss >= th.loss_threshold_pct, f"loss = {f.loss}%"):
        ev = [f"{f.sent - f.received} of {f.sent} probes lost ({f.loss}%)"]
        if f.sent < 20:
            ev.append(f"only {f.sent} probes were sent, so one lost probe changes loss by {100 / f.sent:.0f} points")
        findings.append(Finding("R-LOSS-01", PACKET_LOSS, CONFIRMED, "Partial packet loss", ev))
    elif partial:
        trace[-1].reason += f" (below the {th.loss_threshold_pct}% threshold - reported as an observation only)"
    if rule("R-LOSS-02", "Complete packet loss (100%)", no_replies and not contradictions,
            f"loss = {f.loss}%"):
        findings.append(Finding("R-LOSS-02", PACKET_LOSS, CONFIRMED, "Complete packet loss",
                                [f"{f.sent}/{f.sent} probes lost"]))

    # ---- latency ----
    enough = f.samples >= th.min_rtt_samples
    high = f.avg is not None and f.avg > th.high_rtt_ms
    if rule("R-LAT-01", f"Average RTT above {th.high_rtt_ms} ms", high and enough,
            f"avg = {f.avg} ms from {f.samples} sample(s)"):
        findings.append(Finding("R-LAT-01", HIGH_LATENCY, CONFIRMED, "High round-trip time",
                                [f"average RTT {f.avg} ms > threshold {th.high_rtt_ms} ms ({f.samples} samples)"]))
    elif high:
        findings.append(Finding("R-LAT-01", INCONCLUSIVE, INSUFFICIENT,
                                "RTT above threshold but too few samples to judge",
                                [f"only {f.samples} RTT sample(s); at least {th.min_rtt_samples} required"]))
    jitter = f.stdev is not None and f.stdev > th.high_jitter_ms and enough
    if rule("R-LAT-02", f"RTT standard deviation above {th.high_jitter_ms} ms", jitter,
            f"std-dev = {f.stdev} ms"):
        findings.append(Finding("R-LAT-02", HIGH_LATENCY, CONFIRMED, "Large RTT variation (jitter)",
                                [f"RTT std-dev {f.stdev} ms > {th.high_jitter_ms} ms"]))

    # ---- baseline comparison ----
    rtt_up = loss_up = jitter_up = tput_down = False
    if fb and fb.avg is not None and f.avg is not None:
        rtt_up = f.avg > fb.avg * th.baseline_rtt_factor and f.avg - fb.avg >= th.baseline_rtt_min_increase_ms
        if rule("R-BASE-01", "RTT significantly higher than the recorded baseline", rtt_up and enough,
                f"avg {f.avg} ms vs baseline {fb.avg} ms (factor {th.baseline_rtt_factor}, "
                f"min +{th.baseline_rtt_min_increase_ms} ms)"):
            findings.append(Finding("R-BASE-01", HIGH_LATENCY, CONFIRMED, "RTT increased compared with baseline",
                                    [f"{fb.avg} ms (baseline {baseline.timestamp}) -> {f.avg} ms"]))
    else:
        rule("R-BASE-01", "RTT significantly higher than the recorded baseline", False,
             "no baseline with RTT samples for this destination")
    if fb and fb.loss is not None and f.loss is not None:
        loss_up = f.loss - fb.loss >= th.baseline_loss_increase_pct and f.loss < 100
        rule("R-BASE-02", "Packet loss increased compared with baseline", loss_up,
             f"loss {f.loss}% vs baseline {fb.loss}%")
    if fb and fb.stdev is not None and f.stdev is not None:
        jitter_up = f.stdev > max(fb.stdev * th.baseline_jitter_factor, th.high_jitter_ms / 3)
        rule("R-BASE-03", "RTT variation increased compared with baseline", jitter_up,
             f"std-dev {f.stdev} ms vs baseline {fb.stdev} ms")
    if baseline and baseline.throughput_kbps and run.throughput_kbps is not None:
        tput_down = run.throughput_kbps < baseline.throughput_kbps * (1 - th.throughput_drop_pct / 100)
        rule("R-BASE-04", "Throughput decreased compared with baseline", tput_down,
             f"{run.throughput_kbps} vs baseline {baseline.throughput_kbps} kb/s")

    # ---- R-CONG-01: congestion needs at least two independent indicators ----
    indicators = []
    if rtt_up:
        indicators.append("RTT above baseline")
    elif high and enough and not fb:
        indicators.append(f"RTT above {th.high_rtt_ms} ms (no baseline available)")
    if loss_up:
        indicators.append("loss above baseline")
    elif partial:
        indicators.append(f"partial packet loss ({f.loss}%)")
    if jitter_up or jitter:
        indicators.append("increased RTT variation")
    if tput_down:
        indicators.append("throughput below baseline")
    cong = len(indicators) >= 2 and f.received > 0
    if rule("R-CONG-01", "Two or more congestion indicators present together", cong,
            f"indicators: {', '.join(indicators) or 'none'}"
            + ("" if cong or len(indicators) != 1 else " - a single indicator is not enough to suggest congestion")):
        findings.append(Finding("R-CONG-01", CONGESTION, POSSIBLE,
                                "Symptoms consistent with congestion on the path", indicators))

    # ---- routing ----
    tr_incomplete = f.tr_usable and not f.tr_reached
    if rule("R-ROUTE-01", "Traceroute does not reach the destination while ping also fails",
            tr_incomplete and f.received == 0 and not (f.tcp_ok or f.tcp_refused),
            (_hop_desc(f.tr) if f.tr_usable else "no usable traceroute")
            + (f"; ping replies = {f.received}" if f.tr_usable else "")):
        findings.append(Finding("R-ROUTE-01", ROUTING, POSSIBLE, "Path stops responding before the destination",
                                [_hop_desc(f.tr)]))
    if tr_incomplete and f.received > 0:
        contradictions.append(
            f"Traceroute did not reach the destination ({_hop_desc(f.tr)}) although ping got replies: "
            "intermediate routers or a firewall/NAT are likely not answering traceroute probes, or the hop limit "
            f"({f.tr.max_hops}) is too small. This is not evidence of a routing failure."
        )
    if previous and previous.traceroute and run.traceroute and f.tr_usable:
        old, new = route_signature(previous.traceroute), route_signature(run.traceroute)
        changed = bool(old) and bool(new) and old != new
        if rule("R-ROUTE-02", "Responding hop sequence differs from the previous run", changed,
                f"previous {old} vs current {new}" if changed else "same responding hops (or not comparable)"):
            findings.append(Finding("R-ROUTE-02", ROUTING, CONFIRMED, "Route changed since the previous run",
                                    [f"previous: {' > '.join(old)}", f"current: {' > '.join(new)}"]))
    else:
        rule("R-ROUTE-02", "Responding hop sequence differs from the previous run", False,
             "no previous traceroute to compare")

    # ---- R-GW-01: gateway ----
    if f.gw_tested and not f.gw_reachable and f.host_responds:
        contradictions.append(
            f"The default gateway {f.gw_ip} did not answer ping, yet the destination did respond: the gateway "
            "probably ignores ICMP echo. Gateway silence alone is not treated as a fault."
        )

    # ---- classification ----
    cats = []
    for fd in findings:
        if fd.category not in cats and fd.level != INSUFFICIENT:
            cats.append(fd.category)
    fully_ok = (
        f.dns_ok or (run.dns and run.dns.is_ip_literal)
    ) and f.host_responds and not any(c in cats for c in (DNS_FAILURE, UNREACHABLE))
    if fully_ok:
        cats.insert(0, HEALTHY)
    if rule("R-OK-01", "Destination reachable", fully_ok,
            "replies received / TCP answered" if fully_ok else "no positive reachability evidence"):
        pass
    if not cats or (not f.ping_usable and not f.dns_failed and not f.tcp and not f.tr_usable):
        if INCONCLUSIVE not in cats:
            cats.append(INCONCLUSIVE)
    if contradictions and not fully_ok and INCONCLUSIVE not in cats and not findings:
        cats.append(INCONCLUSIVE)

    explanations = _explain(run, f, findings, contradictions, cats)
    conclusion = _conclude(run, f, cats, contradictions)
    return AnalysisReport(
        run_id=run.run_id,
        target=run.target,
        classifications=cats,
        observations=observations,
        findings=findings,
        explanations=explanations,
        conclusion=conclusion,
        contradictions=contradictions,
        rule_trace=trace,
        baseline_run_id=baseline.run_id if baseline else None,
        previous_run_id=previous.run_id if previous else None,
        thresholds=asdict(th),
    )


# ------------------------------------------------------------------- explanations
def _explain(run: DiagnosticRun, f: _Facts, findings: list[Finding], contradictions: list[str],
             cats: list[str]) -> list[Explanation]:
    ex: list[Explanation] = []
    gw_ev = (f"default gateway {f.gw_ip} answered ping" if f.gw_reachable
             else f"default gateway {f.gw_ip} did not answer ping" if f.gw_tested else None)

    if DNS_FAILURE in cats:
        if f.dns_kind == "nxdomain":
            ex.append(Explanation(
                "The name does not exist in DNS or is misspelt (NXDOMAIN / host not found)", "likely",
                [f"resolver returned 'host not found' ({run.dns.error})"] + ([gw_ev] if f.gw_reachable else []),
                [gw_ev] if f.gw_tested and not f.gw_reachable else [],
                ["Check the spelling of the name", "Query another resolver, e.g. 'nslookup <name> 1.1.1.1'"],
                ["Correct the host name", "Ask the domain owner whether the record exists"]))
        else:
            ex.append(Explanation(
                "The configured DNS server is unreachable or not answering", "likely" if f.gw_reachable else "possible",
                [f"resolver error kind '{f.dns_kind}'"] + ([gw_ev] if gw_ev else []),
                [], [f"Ping the DNS server(s) {', '.join(run.config.dns_servers) if run.config else ''}",
                     "Query another resolver directly with nslookup"],
                ["Switch to a different DNS server", "Check firewall rules for UDP/TCP port 53"]))
        if f.gw_tested and not f.gw_reachable:
            ex.append(Explanation(
                "There is no working local network connection", "possible",
                [gw_ev], [], ["Check link/Wi-Fi status and IP configuration (ipconfig / ip addr)"],
                ["Reconnect to the network", "Renew the DHCP lease"]))

    if UNREACHABLE in cats or ROUTING in cats:
        reports = f.os_unreachable + f.tr_annotations
        if reports:
            ex.append(Explanation(
                "A router on the path has no route to the destination", "likely",
                reports, [], ["Run traceroute again to see which hop reports the error",
                              "Check the routing table on that router if you administer it"],
                ["Report the unreachable network to the network/ISP administrator"]))
        if f.gw_tested and not f.gw_reachable and f.received == 0:
            ex.append(Explanation(
                "Local network or default-gateway problem", "likely" if not f.tr_usable or not f.tr.last_responding_hop else "possible",
                [gw_ev, "destination did not answer either"],
                [], ["Check cable/Wi-Fi and interface status", "Ping another host on the local network"],
                ["Restore the local link or gateway before investigating further"]))
        elif f.gw_reachable or (f.tr_usable and f.tr.last_responding_hop):
            sup = []
            if gw_ev:
                sup.append(gw_ev)
            if f.tr_usable:
                sup.append(f"traceroute: {_hop_desc(f.tr)}")
            ex.append(Explanation(
                "The destination host is down or offline", "possible", sup,
                ["a TCP port answered"] if (f.tcp_ok or f.tcp_refused) else [],
                ["Try a TCP connection to a known service port", "Ask the host owner whether it is running"],
                ["Wait and re-run the diagnostics"]))
            ex.append(Explanation(
                "A downstream part of the path (beyond the last responding hop) is inaccessible", "possible", sup, [],
                ["Re-run traceroute later and compare the last responding hop",
                 "Traceroute to a different host behind the same network"],
                ["Report the last responding hop to the network operator"]))
            ex.append(Explanation(
                "ICMP / traceroute probes are filtered by a firewall", "possible",
                sup + (["TCP connect timed out as well"] if f.tcp_timeout else []),
                ["TCP connect also failed"] if f.tcp and not (f.tcp_ok or f.tcp_refused) and not f.tcp_timeout else [],
                ["Test reachability with TCP to a port the host is expected to serve"],
                ["Use a TCP-based check where ICMP is blocked"]))

    if contradictions and HEALTHY in cats and (f.tcp_ok or f.tcp_refused) and f.received == 0:
        ex.append(Explanation(
            "ICMP echo is blocked, but the host is reachable", "likely",
            [c for c in contradictions if "TCP" in c], [],
            ["Check firewall rules for ICMP on the destination"], ["Use TCP checks to monitor this host"]))

    if PACKET_LOSS in cats and f.received > 0:
        ex.append(Explanation(
            "Intermittent loss on a link (congestion, Wi-Fi interference or a faulty link)", "possible",
            [fd.evidence[0] for fd in findings if fd.category == PACKET_LOSS],
            [], ["Repeat with more probes (e.g. 50) to measure loss more precisely",
                 "Ping the gateway with many probes to see whether loss is local"],
            ["If loss is local, check Wi-Fi signal or cabling"]))
        ex.append(Explanation(
            "Routers rate-limit ICMP replies (loss of probes, not of user traffic)", "possible",
            [], [], ["Compare with a TCP-based transfer measurement"], []))

    if HIGH_LATENCY in cats:
        jump = _latency_jump(run.traceroute)
        ex.append(Explanation(
            "Long or slow network path (distance, satellite/mobile link, slow hop)", "possible",
            [fd.evidence[0] for fd in findings if fd.category == HIGH_LATENCY] + ([jump] if jump else []),
            [], ["Compare with a recorded baseline for this destination",
                 "Look at per-hop RTT in traceroute to find where delay is added"],
            ["Record a baseline when the network is healthy"]))

    if CONGESTION in cats:
        cf = next(fd for fd in findings if fd.category == CONGESTION)
        ex.append(Explanation(
            "Congestion on the path (queues filling at a bottleneck)", "possible", cf.evidence, [],
            ["Repeat the test at a quieter time and compare", "Check link utilisation on your own devices"],
            ["Reduce competing traffic or schedule heavy transfers elsewhere"]))
    return ex


def _conclude(run: DiagnosticRun, f: _Facts, cats: list[str], contradictions: list[str]) -> str:
    if DNS_FAILURE in cats:
        return (f"The name {run.target} could not be resolved, so no connection was attempted. "
                + ("The local network appears to work (gateway reachable), which points to a naming/DNS problem. "
                   if f.gw_reachable else "")
                + "The exact cause is not confirmed.")
    if UNREACHABLE in cats:
        tail = (" A router explicitly reported that the destination is unreachable." if f.os_unreachable or f.tr_annotations
                else " No device reported an explicit error, so the precise cause is not confirmed.")
        return f"{run.target} could not be reached using the available diagnostic methods.{tail}"
    if HEALTHY in cats:
        issues = [c for c in cats if c != HEALTHY]
        if not issues:
            extra = " Some evidence was contradictory (see notes)." if contradictions else ""
            return f"{run.target} is reachable and no problem was detected with the configured thresholds.{extra}"
        return f"{run.target} is reachable, but the following conditions were observed: {', '.join(issues)}."
    if INCONCLUSIVE in cats:
        return "The collected evidence is insufficient or contradictory; no conclusion can be drawn."
    return f"Observed conditions: {', '.join(cats)}."
