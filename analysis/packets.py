"""Per-packet reconstruction from an NS2 trace.

Counting rules (they prevent double counting at intermediate routers):

* **sent**      - the first ``+`` (enqueue) event of a packet at its *source* node
                  (``from_node == src_node``). Forwarding ``+`` events at routers are ignored.
* **received**  - an ``r`` event whose ``to_node`` is the packet's *destination* node.
                  ``r`` events at intermediate routers only extend the packet's path.
* events of one packet are matched with NS2's unique packet id (last trace column).

Each packet that was sent ends with exactly one *fate*:

==========================  =====================================================================
``delivered``               received at the destination
``dropped_queue``           explicit ``d`` event on a link that was up -> DropTail queue overflow
``dropped_link_down``       explicit ``d`` event on a link that the trace shows as down
``lost_at_node``            no ``d`` event; the last event is arrival (``r``) at a router that
                            never forwarded it. NS2 2.35 discards such packets without tracing
                            them (e.g. static route still pointing at a failed link).
``lost_on_link``            no ``d`` event; last event is ``+``/``-`` on a link (lost in transit)
``in_flight``               sent so close to the end of the trace that it could not arrive yet
==========================  =====================================================================
"""
from __future__ import annotations

from dataclasses import dataclass, field

from simulation.trace_parser import ParsedTrace, TraceEvent

DATA_TYPES = {"cbr", "udp", "tcp", "exp", "pareto"}
FATES = ("delivered", "dropped_queue", "dropped_link_down", "lost_at_node", "lost_on_link", "in_flight")
LOST_FATES = ("dropped_queue", "dropped_link_down", "lost_at_node", "lost_on_link")


@dataclass
class PacketRecord:
    pkt_id: int
    fid: int
    seq: int
    size: int
    ptype: str
    src: int
    dst: int
    send_time: float | None = None
    recv_time: float | None = None
    hops: list[tuple[int, int, float]] = field(default_factory=list)  # (from, to, arrival time)
    drop: tuple[float, int, int] | None = None  # (time, from, to)
    last_event: TraceEvent | None = None
    fate: str = "unknown"
    fate_detail: str = ""

    @property
    def path(self) -> list[int]:
        nodes = [self.src]
        for _a, b, _t in self.hops:
            nodes.append(b)
        return nodes

    @property
    def path_label(self) -> str:
        return "-".join(str(n) for n in self.path)

    @property
    def delay(self) -> float | None:
        if self.send_time is None or self.recv_time is None:
            return None
        return self.recv_time - self.send_time

    @property
    def lost(self) -> bool:
        return self.fate in LOST_FATES


def build_packet_records(
    parsed: ParsedTrace,
    fids: set[int] | None = None,
    in_flight_grace: float = 0.5,
) -> dict[int, PacketRecord]:
    """Reconstruct every data packet (optionally only the given flow ids)."""
    records: dict[int, PacketRecord] = {}
    for ev in parsed.events:
        if ev.ptype not in DATA_TYPES:
            continue
        if fids is not None and ev.fid not in fids:
            continue
        rec = records.get(ev.pkt_id)
        if rec is None:
            rec = PacketRecord(ev.pkt_id, ev.fid, ev.seq, ev.size, ev.ptype, ev.src_node, ev.dst_node)
            records[ev.pkt_id] = rec
        if ev.event == "+" and ev.from_node == rec.src and rec.send_time is None:
            rec.send_time = ev.time
        elif ev.event == "r":
            rec.hops.append((ev.from_node, ev.to_node, ev.time))
            if ev.to_node == rec.dst and rec.recv_time is None:
                rec.recv_time = ev.time
        elif ev.event == "d" and rec.drop is None:
            rec.drop = (ev.time, ev.from_node, ev.to_node)
        rec.last_event = ev

    end = parsed.end_time
    for rec in records.values():
        _classify(rec, parsed, end, in_flight_grace)
    return records


def _adjacent_down_links(parsed: ParsedTrace, node: int, t: float) -> list[str]:
    out = []
    for key, intervals in parsed.link_down_intervals().items():
        if node in key and any(t0 <= t < t1 for t0, t1 in intervals):
            a, b = sorted(key)
            out.append(f"{a}-{b}")
    return out


def _classify(rec: PacketRecord, parsed: ParsedTrace, end: float, grace: float) -> None:
    if rec.recv_time is not None:
        rec.fate = "delivered"
        return
    if rec.drop is not None:
        t, a, b = rec.drop
        if parsed.link_down_at(a, b, t):
            rec.fate = "dropped_link_down"
            rec.fate_detail = f"d event on link {a}->{b} at t={t:.4f}s while link {min(a, b)}-{max(a, b)} was down"
        else:
            rec.fate = "dropped_queue"
            rec.fate_detail = f"d event at queue of link {a}->{b} at t={t:.4f}s (link up -> DropTail overflow)"
        return
    last = rec.last_event
    if last is None:
        rec.fate = "unknown"
        return
    if last.time >= end - grace:
        rec.fate = "in_flight"
        rec.fate_detail = f"last seen at t={last.time:.4f}s, within {grace}s of trace end"
        return
    if last.event == "r":
        node = last.to_node
        down = _adjacent_down_links(parsed, node, last.time)
        rec.fate = "lost_at_node"
        reason = f"; adjacent link(s) down at that time: {', '.join(down)}" if down else ""
        rec.fate_detail = (
            f"arrived at node {node} at t={last.time:.4f}s and was never forwarded "
            f"(no d event written by NS2){reason}"
        )
    else:
        a, b = last.from_node, last.to_node
        state = "down" if parsed.link_down_at(a, b, last.time + 1e-9) else "up"
        rec.fate = "lost_on_link"
        rec.fate_detail = f"last event '{last.event}' on link {a}->{b} at t={last.time:.4f}s (link {state} then)"


def fate_counts(records) -> dict[str, int]:
    counts = {f: 0 for f in FATES}
    for r in records:
        if r.send_time is None:
            continue
        counts[r.fate] = counts.get(r.fate, 0) + 1
    return counts
