"""Parser for NS2 wired trace files (``$ns trace-all``) and the RouteResQ event log.

Wired trace line format (12 fields)::

    event time from_node to_node pkt_type pkt_size flags fid src_addr dst_addr seq_num pkt_id
    +     1.0  0         1       cbr      1000     ------- 1  0.0      5.0      0       0

``event`` is ``+`` (enqueue), ``-`` (dequeue / start of transmission), ``r`` (received
at ``to_node``) or ``d`` (dropped). ``src_addr``/``dst_addr`` are ``node.port``.
``pkt_id`` is NS2's globally unique packet uid, which is what we use to match events
belonging to the same packet across hops.

Link dynamics (from ``rtmodel-at``) appear as::

    v 3 link-down 1 2
    v 6 link-up 1 2

NS2 2.35 prints each of these lines twice; duplicates are collapsed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class TraceEvent:
    event: str
    time: float
    from_node: int
    to_node: int
    ptype: str
    size: int
    flags: str
    fid: int
    src_node: int
    src_port: int
    dst_node: int
    dst_port: int
    seq: int
    pkt_id: int


@dataclass(frozen=True, slots=True)
class LinkStateEvent:
    time: float
    state: str  # "down" | "up"
    a: int
    b: int


@dataclass(frozen=True, slots=True)
class LoggedEvent:
    """A line written by the Tcl ``log_event`` procedure (configuration-driven)."""

    time: float
    kind: str
    detail: str


@dataclass
class ParsedTrace:
    events: list[TraceEvent] = field(default_factory=list)
    link_events: list[LinkStateEvent] = field(default_factory=list)
    malformed_lines: int = 0
    malformed_examples: list[str] = field(default_factory=list)
    total_lines: int = 0
    end_time: float = 0.0

    def link_down_intervals(self) -> dict[frozenset[int], list[tuple[float, float]]]:
        """Intervals during which each (undirected) link was down. Open intervals end at +inf."""
        out: dict[frozenset[int], list[tuple[float, float]]] = {}
        open_since: dict[frozenset[int], float] = {}
        for ev in sorted(self.link_events, key=lambda e: e.time):
            key = frozenset((ev.a, ev.b))
            if ev.state == "down" and key not in open_since:
                open_since[key] = ev.time
            elif ev.state == "up" and key in open_since:
                out.setdefault(key, []).append((open_since.pop(key), ev.time))
        for key, t in open_since.items():
            out.setdefault(key, []).append((t, float("inf")))
        return out

    def link_down_at(self, a: int, b: int, t: float) -> bool:
        for t0, t1 in self.link_down_intervals().get(frozenset((a, b)), []):
            if t0 <= t < t1:
                return True
        return False


def _split_addr(addr: str) -> tuple[int, int]:
    node, _, port = addr.partition(".")
    return int(node), int(port or 0)


def parse_line(line: str) -> TraceEvent | LinkStateEvent | None:
    """Parse one trace line. Returns None for lines that are irrelevant (e.g. annotations).

    Raises ValueError for lines that look like packet events but are malformed.
    """
    parts = line.split()
    if not parts:
        return None
    tag = parts[0]
    if tag == "v":
        if len(parts) >= 5 and parts[2] in ("link-down", "link-up"):
            return LinkStateEvent(float(parts[1]), parts[2].split("-")[1], int(parts[3]), int(parts[4]))
        return None
    if tag not in ("+", "-", "r", "d"):
        raise ValueError(f"unknown event tag {tag!r}")
    if len(parts) != 12:
        raise ValueError(f"expected 12 fields, got {len(parts)}")
    src_node, src_port = _split_addr(parts[8])
    dst_node, dst_port = _split_addr(parts[9])
    return TraceEvent(
        event=tag,
        time=float(parts[1]),
        from_node=int(parts[2]),
        to_node=int(parts[3]),
        ptype=parts[4],
        size=int(parts[5]),
        flags=parts[6],
        fid=int(parts[7]),
        src_node=src_node,
        src_port=src_port,
        dst_node=dst_node,
        dst_port=dst_port,
        seq=int(parts[10]),
        pkt_id=int(parts[11]),
    )


def parse_trace_lines(lines) -> ParsedTrace:
    parsed = ParsedTrace()
    seen_link: set[tuple[float, str, int, int]] = set()
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        parsed.total_lines += 1
        try:
            item = parse_line(line)
        except (ValueError, IndexError):
            parsed.malformed_lines += 1
            if len(parsed.malformed_examples) < 5:
                parsed.malformed_examples.append(line[:120])
            continue
        if item is None:
            continue
        if isinstance(item, LinkStateEvent):
            key = (item.time, item.state, item.a, item.b)
            if key not in seen_link:
                seen_link.add(key)
                parsed.link_events.append(item)
        else:
            parsed.events.append(item)
        parsed.end_time = max(parsed.end_time, item.time)
    parsed.events.sort(key=lambda e: e.time)  # NS2 already writes in time order; be safe.
    return parsed


def parse_trace(path: Path) -> ParsedTrace:
    with Path(path).open("r", encoding="utf-8", errors="replace") as fh:
        return parse_trace_lines(fh)


def parse_events_log(path: Path) -> list[LoggedEvent]:
    """Parse the experiment event log written by ``log_event`` in routeresq.tcl."""
    out: list[LoggedEvent] = []
    p = Path(path)
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        parts = line.split(maxsplit=2)
        if len(parts) < 2:
            continue
        try:
            out.append(LoggedEvent(float(parts[0]), parts[1], parts[2] if len(parts) > 2 else ""))
        except ValueError:
            continue
    return out
