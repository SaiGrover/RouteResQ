"""Routing evidence extracted from the trace: paths used, route changes, delivery gaps,
and routing-protocol control traffic. Nothing here is inferred from configuration alone."""
from __future__ import annotations

from collections import Counter

from analysis.packets import PacketRecord
from simulation.trace_parser import ParsedTrace

ROUTING_TYPES = {"rtProtoDV", "rtProtoLS"}


def path_usage(records: list[PacketRecord], phases: dict[str, tuple[float, float]]) -> dict[str, dict[str, int]]:
    """Count of *delivered* packets per complete path, grouped by the phase of their send time."""
    out: dict[str, dict[str, int]] = {}
    for name, (t0, t1) in phases.items():
        c = Counter(r.path_label for r in records if r.fate == "delivered" and t0 <= r.send_time < t1)
        out[name] = dict(c.most_common())
    return out


def route_changes(records: list[PacketRecord], min_run: int = 3) -> list[dict]:
    """Detect when consecutively sent, delivered packets switch to a different path.

    A change is only reported if the new path is then used by at least ``min_run``
    consecutive packets, so a single stray packet is not mistaken for a route change.
    """
    seq = sorted((r for r in records if r.fate == "delivered"), key=lambda r: r.send_time)
    if not seq:
        return []
    runs: list[tuple[str, list[PacketRecord]]] = []
    for r in seq:
        if runs and runs[-1][0] == r.path_label:
            runs[-1][1].append(r)
        else:
            runs.append((r.path_label, [r]))
    # merge short runs into the previous run
    stable: list[tuple[str, list[PacketRecord]]] = []
    for label, pkts in runs:
        if stable and len(pkts) < min_run:
            stable[-1][1].extend(pkts)
        elif stable and stable[-1][0] == label:
            stable[-1][1].extend(pkts)
        else:
            stable.append((label, list(pkts)))
    changes = []
    for (prev_label, prev_pkts), (label, pkts) in zip(stable, stable[1:]):
        last_old = max(prev_pkts, key=lambda r: r.send_time)
        first_new = min(pkts, key=lambda r: r.send_time)
        changes.append(
            {
                "time": round(first_new.send_time, 4),
                "from_path": prev_label,
                "to_path": label,
                "last_packet_old_path": {"seq": last_old.seq, "sent": round(last_old.send_time, 4)},
                "first_packet_new_path": {"seq": first_new.seq, "sent": round(first_new.send_time, 4)},
                "packets_on_new_path": len(pkts),
            }
        )
    return changes


def delivery_gaps(
    records: list[PacketRecord], expected_interval: float, active: tuple[float, float], factor: float = 5.0
) -> list[dict]:
    """Intervals where the destination received nothing for longer than ``factor`` x the
    nominal packet interval (and at least 50 ms) while the flow was active."""
    threshold = max(factor * expected_interval, 0.05)
    times = sorted(r.recv_time for r in records if r.recv_time is not None)
    start, stop = active
    gaps = []
    prev = None
    for t in times:
        if prev is not None and t - prev > threshold:
            gaps.append({"start": round(prev, 4), "end": round(t, 4), "duration_s": round(t - prev, 4)})
        prev = t
    if prev is not None and stop - prev > threshold:
        gaps.append({"start": round(prev, 4), "end": None, "duration_s": round(stop - prev, 4), "open": True})
    if times and times[0] - start > threshold + 0.2:  # allow for the first-packet path delay
        gaps.insert(0, {"start": start, "end": round(times[0], 4), "duration_s": round(times[0] - start, 4)})
    return gaps


def routing_control_traffic(parsed: ParsedTrace, bin_size: float = 0.5) -> dict:
    """Routing protocol messages originated (first enqueue at their source node)."""
    originated = [
        ev.time for ev in parsed.events
        if ev.ptype in ROUTING_TYPES and ev.event == "+" and ev.from_node == ev.src_node
    ]
    nbins = int(parsed.end_time / bin_size) + 1 if parsed.end_time else 0
    counts = [0] * nbins
    for t in originated:
        counts[min(int(t / bin_size), nbins - 1)] += 1
    return {
        "total_messages": len(originated),
        "bin_size": bin_size,
        "series": [{"t": round(i * bin_size, 3), "messages": c} for i, c in enumerate(counts)],
    }


def messages_between(parsed: ParsedTrace, t0: float, t1: float) -> int:
    return sum(
        1 for ev in parsed.events
        if ev.ptype in ROUTING_TYPES and ev.event == "+" and ev.from_node == ev.src_node and t0 <= ev.time < t1
    )
