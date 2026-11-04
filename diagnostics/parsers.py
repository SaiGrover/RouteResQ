"""Parsers for ping / traceroute / routing-table output on Windows and Linux.

The parsers never invent values: if a line cannot be understood it is skipped and a
parse warning is recorded. RouteResQ computes packet statistics from the individual
probe lines and cross-checks them against the tool's own summary line.
"""
from __future__ import annotations

import ipaddress
import re
from statistics import mean, pstdev

from diagnostics.models import Hop, PingResult, TracerouteResult

_IP = r"[0-9a-fA-F:.%]+"

# ------------------------------------------------------------------------------ ping
WIN_PINGING = re.compile(r"^Pinging (?P<name>\S+)(?: \[(?P<ip>[^\]]+)\])? with", re.M)
WIN_REPLY = re.compile(r"Reply from (?P<ip>" + _IP + r"):\s+(?:bytes=\d+\s+)?time(?P<op>[=<])(?P<ms>\d+(?:\.\d+)?)ms", re.I)
WIN_REPLY_ERROR = re.compile(r"Reply from (?P<ip>" + _IP + r"):\s+(?P<msg>(?:Destination|TTL expired)[^.\r\n]*)", re.I)
WIN_SUMMARY = re.compile(r"Packets: Sent = (?P<s>\d+), Received = (?P<r>\d+), Lost = (?P<l>\d+)", re.I)
WIN_DNS_FAIL = re.compile(r"could not find host", re.I)

LNX_PING = re.compile(r"^PING (?P<name>\S+) \((?P<ip>[^)]+)\)", re.M)
LNX_REPLY = re.compile(r"bytes from (?P<ip>[^:\s]+)(?: \([^)]*\))?: icmp_seq=(?P<seq>\d+) .*?time[=<](?P<ms>\d+(?:\.\d+)?) ms")
LNX_FROM_ERROR = re.compile(r"^From (?P<ip>\S+)(?: \([^)]*\))? icmp_seq=\d+ (?P<msg>.+)$", re.M)
LNX_SUMMARY = re.compile(r"(?P<s>\d+) packets transmitted, (?P<r>\d+) (?:packets )?received")
LNX_DNS_FAIL = re.compile(r"(Name or service not known|Temporary failure in name resolution|unknown host|"
                          r"No address associated with hostname|nodename nor servname)", re.I)
NET_UNREACH = re.compile(r"(Network is unreachable|No route to host)", re.I)
GENERAL_FAILURE = re.compile(r"General failure|transmit failed", re.I)
WIN_TIMEOUT = re.compile(r"^Request timed out\.", re.M)


def parse_ping(output: str, target: str, windows: bool) -> PingResult:
    res = PingResult(target=target)
    text = output or ""
    if not text.strip():
        res.parse_warnings.append("ping produced no output")
        return res

    if windows:
        m = WIN_PINGING.search(text)
        if m:
            res.resolved_ip = m.group("ip") or m.group("name")
        if WIN_DNS_FAIL.search(text):
            res.dns_failure = True
        for m in WIN_REPLY.finditer(text):
            ms = float(m.group("ms"))
            if m.group("op") == "<":
                # "time<1ms": the true value is below the tool's 1 ms resolution
                ms = 0.0
                if "sub-millisecond RTTs reported by Windows as '<1ms' are recorded as 0 ms" not in res.parse_warnings:
                    res.parse_warnings.append("sub-millisecond RTTs reported by Windows as '<1ms' are recorded as 0 ms")
            res.rtts_ms.append(ms)
        for m in WIN_REPLY_ERROR.finditer(text):
            res.unreachable_reports.append(f"{m.group('msg').strip()} (reported by {m.group('ip')})")
        for line in text.splitlines():
            s = line.strip()
            if s.lower().startswith("destination") and "unreachable" in s.lower():
                res.unreachable_reports.append(s.rstrip("."))
        res.timeouts = len(WIN_TIMEOUT.findall(text))
        sm = WIN_SUMMARY.search(text)
    else:
        m = LNX_PING.search(text)
        if m:
            res.resolved_ip = m.group("ip")
        if LNX_DNS_FAIL.search(text):
            res.dns_failure = True
        for m in LNX_REPLY.finditer(text):
            res.rtts_ms.append(float(m.group("ms")))
        for m in LNX_FROM_ERROR.finditer(text):
            res.unreachable_reports.append(f"{m.group('msg').strip()} (reported by {m.group('ip')})")
        sm = LNX_SUMMARY.search(text)

    if NET_UNREACH.search(text):
        res.unreachable_reports.append(NET_UNREACH.search(text).group(1) + " (reported by local OS)")
    if GENERAL_FAILURE.search(text):
        res.general_failure = True

    res.received = len(res.rtts_ms)
    if sm:
        res.summary_sent = int(sm.group("s"))
        res.summary_received = int(sm.group("r"))
        res.sent = res.summary_sent
        if res.summary_received != res.received:
            res.parse_warnings.append(
                f"tool summary reports {res.summary_received} received but {res.received} echo replies were "
                "found; RouteResQ counts only genuine echo replies (Windows also counts ICMP error replies)"
            )
    else:
        probes = res.received + res.timeouts + len(res.unreachable_reports)
        res.sent = probes
        if not res.dns_failure:
            res.parse_warnings.append("summary line missing (output incomplete?); counts derived from probe lines")

    if res.sent > 0:
        res.loss_pct = round(100.0 * (res.sent - res.received) / res.sent, 2)
        res.parsed_ok = True
    elif res.dns_failure:
        res.parsed_ok = True  # a DNS failure is a valid, understood result
    else:
        res.parse_warnings.append("no probes could be identified in the output")

    if res.rtts_ms:
        res.min_ms = round(min(res.rtts_ms), 3)
        res.max_ms = round(max(res.rtts_ms), 3)
        res.avg_ms = round(mean(res.rtts_ms), 3)
        res.stdev_ms = round(pstdev(res.rtts_ms), 3) if len(res.rtts_ms) > 1 else None
    return res


# ------------------------------------------------------------------------ traceroute
WIN_TR_HEADER = re.compile(r"Tracing route to (?P<name>\S+)(?: \[(?P<ip>[^\]]+)\])?")
WIN_TR_HOP = re.compile(r"^\s*(?P<ttl>\d+)\s+(?P<rtts>(?:(?:<?\d+\s*ms|\*)\s+){1,3})(?P<rest>.*)$")
WIN_TR_DNS = re.compile(r"Unable to resolve target system name", re.I)
LNX_TR_HEADER = re.compile(r"^traceroute to (?P<name>\S+) \((?P<ip>[^)]+)\)", re.M)
LNX_TR_HOP = re.compile(r"^\s*(?P<ttl>\d+)\s+(?P<rest>.+)$")
LNX_TR_DNS = re.compile(r"(Name or service not known|Cannot handle \"host\" cmdline arg|Temporary failure in name resolution)", re.I)
TRACEPATH_HOP = re.compile(r"^\s*(?P<ttl>\d+)\??:\s+(?P<addr>\S+)\s+(?P<ms>\d+(?:\.\d+)?)ms")
TRACEPATH_NOREPLY = re.compile(r"^\s*(?P<ttl>\d+)\??:\s+no reply")


def _is_ip(token: str) -> bool:
    try:
        ipaddress.ip_address(token.split("%")[0])
        return True
    except ValueError:
        return False


def _extract_ip(text: str) -> str | None:
    m = re.search(r"\[(" + _IP + r")\]", text)
    if m and _is_ip(m.group(1)):
        return m.group(1)
    for tok in text.split():
        if _is_ip(tok):
            return tok
    return None


def parse_traceroute(output: str, target: str, windows: bool, resolved_ip: str | None = None) -> TracerouteResult:
    res = TracerouteResult(target=target, resolved_ip=resolved_ip)
    text = output or ""
    if not text.strip():
        res.parse_warnings.append("traceroute produced no output")
        return res

    if windows:
        if WIN_TR_DNS.search(text):
            res.dns_failure = True
            res.parsed_ok = True
            return res
        hm = WIN_TR_HEADER.search(text)
        if hm:
            res.resolved_ip = res.resolved_ip or hm.group("ip") or (hm.group("name") if _is_ip(hm.group("name")) else None)
        for line in text.splitlines():
            m = WIN_TR_HOP.match(line)
            if not m:
                continue
            rtts: list[float | None] = []
            for tok in re.findall(r"<?\d+\s*ms|\*", m.group("rtts")):
                if tok == "*":
                    rtts.append(None)
                else:
                    v = re.sub(r"\s*ms", "", tok)
                    rtts.append(0.0 if v.startswith("<") else float(v))
            rest = m.group("rest").strip()
            hop = Hop(ttl=int(m.group("ttl")), address=None, rtts_ms=rtts)
            if "timed out" not in rest.lower():
                hop.address = _extract_ip(rest)
            if "reports:" in rest:
                hop.annotations.append(rest.split("reports:", 1)[1].strip().rstrip("."))
            res.hops.append(hop)
    else:
        if LNX_TR_DNS.search(text):
            res.dns_failure = True
            res.parsed_ok = True
            return res
        hm = LNX_TR_HEADER.search(text)
        if hm:
            res.resolved_ip = res.resolved_ip or hm.group("ip")
        for line in text.splitlines():
            tp = TRACEPATH_HOP.match(line)
            if tp:
                res.hops.append(Hop(int(tp.group("ttl")), tp.group("addr"), [float(tp.group("ms"))]))
                continue
            if TRACEPATH_NOREPLY.match(line):
                res.hops.append(Hop(int(TRACEPATH_NOREPLY.match(line).group("ttl")), None, [None]))
                continue
            m = LNX_TR_HOP.match(line)
            if not m or line.startswith("traceroute"):
                continue
            hop = Hop(ttl=int(m.group("ttl")), address=None)
            toks = m.group("rest").split()
            i = 0
            while i < len(toks):
                t = toks[i]
                if t == "*":
                    hop.rtts_ms.append(None)
                elif _is_ip(t):
                    if hop.address is None:
                        hop.address = t
                    elif t != hop.address:
                        hop.annotations.append(f"also answered by {t}")
                elif re.fullmatch(r"\d+(\.\d+)?", t) and i + 1 < len(toks) and toks[i + 1] == "ms":
                    hop.rtts_ms.append(float(t))
                    i += 1
                elif t.startswith("!"):
                    hop.annotations.append(t)
                i += 1
            res.hops.append(hop)

    # collapse duplicate TTL lines (tracepath prints some TTLs twice)
    seen: dict[int, Hop] = {}
    for h in res.hops:
        if h.ttl in seen:
            if not seen[h.ttl].responded and h.responded:
                seen[h.ttl] = h
        else:
            seen[h.ttl] = h
    res.hops = [seen[k] for k in sorted(seen)]
    res.max_hops = max((h.ttl for h in res.hops), default=0)
    if res.hops:
        res.parsed_ok = True
    else:
        res.parse_warnings.append("no hop lines could be parsed")
    if res.resolved_ip:
        res.reached_destination = any(h.address == res.resolved_ip for h in res.hops)
    return res


# ----------------------------------------------------------------------- route table
def parse_default_gateway(output: str, windows: bool) -> str | None:
    """Default gateway with the lowest metric (Windows ``route print -4`` / Linux ``ip route``)."""
    best: tuple[int, str] | None = None
    for line in (output or "").splitlines():
        parts = line.split()
        if windows:
            if len(parts) >= 5 and parts[0] == "0.0.0.0" and parts[1] == "0.0.0.0" and _is_ip(parts[2]):
                try:
                    metric = int(parts[4])
                except ValueError:
                    metric = 9999
                if best is None or metric < best[0]:
                    best = (metric, parts[2])
        else:
            if len(parts) >= 3 and parts[0] == "default" and parts[1] == "via" and _is_ip(parts[2]):
                metric = int(parts[parts.index("metric") + 1]) if "metric" in parts else 0
                if best is None or metric < best[0]:
                    best = (metric, parts[2])
    return best[1] if best else None


def parse_windows_dns_servers(ipconfig_all: str) -> list[str]:
    servers: list[str] = []
    collecting = False
    for line in (ipconfig_all or "").splitlines():
        if "DNS Servers" in line and ":" in line:
            collecting = True
            cand = line.split(":", 1)[1].strip()
        elif collecting and line.startswith(" " * 20) and _is_ip(line.strip()):
            cand = line.strip()
        else:
            collecting = False
            continue
        if cand and _is_ip(cand) and cand not in servers:
            servers.append(cand)
    return servers


def parse_resolv_conf(text: str) -> list[str]:
    return [p.split()[1] for p in (text or "").splitlines() if p.startswith("nameserver") and len(p.split()) > 1]
