"""Performance metrics computed from reconstructed packets.

Metric definitions (all from the NS2 trace, never estimated):

* **Packets sent**      packets whose source enqueue time lies in the window.
* **Packets delivered** of those, packets that reached the destination (any time).
* **Packet loss %**     ``lost / (sent - in_flight) * 100`` where *lost* counts every lost fate
                        (queue drop, link-down drop, untraced loss).
* **End-to-end delay**  ``recv_time - send_time`` per delivered packet (includes queueing,
                        transmission and propagation). Reported as mean / min / max.
* **Jitter**            mean absolute difference between delays of consecutively *sent*
                        delivered packets (simplified RFC 3550 inter-packet delay variation).
* **Throughput**        bits of the flow's packets *received at the destination* inside the
                        window, divided by the window length. For a whole flow the window is
                        [first send, last receive].
* Loss and delay use send time to assign packets to a window; throughput uses receive time.
"""
from __future__ import annotations

from collections import defaultdict
from statistics import mean

from analysis.packets import LOST_FATES, PacketRecord, fate_counts
from simulation.trace_parser import ParsedTrace


def _r(x: float | None, n: int = 3) -> float | None:
    return None if x is None else round(x, n)


def window_summary(records: list[PacketRecord], t0: float | None = None, t1: float | None = None) -> dict:
    sent = [r for r in records if r.send_time is not None and (t0 is None or t0 <= r.send_time < t1)]
    sent.sort(key=lambda r: r.send_time)
    delivered = [r for r in sent if r.fate == "delivered"]
    in_flight = sum(1 for r in sent if r.fate == "in_flight")
    lost = [r for r in sent if r.fate in LOST_FATES]
    denom = len(sent) - in_flight
    delays = [r.delay for r in delivered if r.delay is not None]
    jitter = mean(abs(a - b) for a, b in zip(delays[1:], delays[:-1])) if len(delays) > 1 else None

    if t0 is None:
        if delivered:
            w0 = sent[0].send_time
            w1 = max(r.recv_time for r in delivered)
        else:
            w0 = w1 = 0.0
        rx_bits = sum(r.size * 8 for r in delivered)
    else:
        w0, w1 = t0, t1
        rx_bits = sum(r.size * 8 for r in records if r.recv_time is not None and t0 <= r.recv_time < t1)
    duration = (w1 - w0) if w1 and w1 > w0 else 0.0
    fates = fate_counts(sent)
    reorder = sum(1 for a, b in zip(delivered, delivered[1:]) if b.recv_time < a.recv_time)
    return {
        "window_start": _r(w0),
        "window_end": _r(w1),
        "sent": len(sent),
        "delivered": len(delivered),
        "lost": len(lost),
        "in_flight": in_flight,
        "loss_pct": _r(100.0 * len(lost) / denom, 2) if denom > 0 else None,
        "delivery_ratio_pct": _r(100.0 * len(delivered) / denom, 2) if denom > 0 else None,
        "avg_delay_ms": _r(mean(delays) * 1000) if delays else None,
        "min_delay_ms": _r(min(delays) * 1000) if delays else None,
        "max_delay_ms": _r(max(delays) * 1000) if delays else None,
        "jitter_ms": _r(jitter * 1000) if jitter is not None else None,
        "throughput_kbps": _r(rx_bits / duration / 1000, 2) if duration > 0 else None,
        "received_bytes": rx_bits // 8,
        "reordered": reorder,
        "fates": fates,
    }


def phase_summaries(records: list[PacketRecord], phases: dict[str, tuple[float, float]]) -> dict[str, dict]:
    return {name: window_summary(records, t0, t1) for name, (t0, t1) in phases.items()}


def time_series(records: list[PacketRecord], end_time: float, bin_size: float = 0.1) -> list[dict]:
    """Per-bin throughput (by receive time), delay and losses (by send time), dominant path."""
    nbins = int(end_time / bin_size) + 1
    rx = [0] * nbins
    sent = [0] * nbins
    lost = [0] * nbins
    delays: list[list[float]] = [[] for _ in range(nbins)]
    paths: list[dict[str, int]] = [defaultdict(int) for _ in range(nbins)]
    for r in records:
        if r.recv_time is not None:
            rx[min(int(r.recv_time / bin_size), nbins - 1)] += r.size * 8
        if r.send_time is None:
            continue
        i = min(int(r.send_time / bin_size), nbins - 1)
        sent[i] += 1
        if r.lost:
            lost[i] += 1
        if r.delay is not None:
            delays[i].append(r.delay)
            paths[i][r.path_label] += 1
    rows = []
    for i in range(nbins):
        dom = max(paths[i].items(), key=lambda kv: kv[1])[0] if paths[i] else ""
        rows.append(
            {
                "t": round(i * bin_size, 3),
                "throughput_kbps": round(rx[i] / bin_size / 1000, 2),
                "sent": sent[i],
                "lost": lost[i],
                "avg_delay_ms": round(mean(delays[i]) * 1000, 3) if delays[i] else None,
                "path": dom,
            }
        )
    return rows


def queue_occupancy(parsed: ParsedTrace, links: list[tuple[int, int]] | None = None) -> dict[str, list[tuple[float, int]]]:
    """Queue length over time per directed link, rebuilt from +, - and d events.

    A packet joins the queue on ``+`` and leaves on ``-`` (start of transmission) or on
    ``d`` (dropped while queued). A ``d`` for a packet already dequeued (lost while being
    transmitted on a failing link) does not change the queue length.
    """
    queues: dict[tuple[int, int], set[int]] = defaultdict(set)
    series: dict[tuple[int, int], list[tuple[float, int]]] = defaultdict(list)
    for ev in parsed.events:
        key = (ev.from_node, ev.to_node)
        if links is not None and key not in links:
            continue
        q = queues[key]
        before = len(q)
        if ev.event == "+":
            q.add(ev.pkt_id)
        elif ev.event in ("-", "d"):
            q.discard(ev.pkt_id)
        else:
            continue
        if len(q) != before:
            series[key].append((ev.time, len(q)))
    return {f"{a}->{b}": s for (a, b), s in series.items()}


def queue_stats(series: dict[str, list[tuple[float, int]]]) -> dict[str, dict]:
    out = {}
    for link, s in series.items():
        if not s:
            continue
        t_max, q_max = max(s, key=lambda x: x[1])
        out[link] = {"max_queue_pkts": q_max, "time_of_max": round(t_max, 4), "samples": len(s)}
    return out


def queue_series_binned(series: list[tuple[float, int]], end_time: float, bin_size: float = 0.1) -> list[dict]:
    """Maximum queue length per time bin (for plotting)."""
    nbins = int(end_time / bin_size) + 1
    mx = [0] * nbins
    cur = 0
    idx = 0
    for i in range(nbins):
        t_end = (i + 1) * bin_size
        peak = cur
        while idx < len(series) and series[idx][0] < t_end:
            cur = series[idx][1]
            peak = max(peak, cur)
            idx += 1
        mx[i] = peak
    return [{"t": round(i * bin_size, 3), "queue_pkts": mx[i]} for i in range(nbins)]


def drops_by_link(records: list[PacketRecord]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in records:
        if r.fate in ("dropped_queue", "dropped_link_down") and r.drop:
            _, a, b = r.drop
            out[f"{a}->{b}"][r.fate] += 1
        elif r.fate in ("lost_at_node", "lost_on_link") and r.last_event is not None:
            ev = r.last_event
            where = f"node {ev.to_node}" if r.fate == "lost_at_node" else f"{ev.from_node}->{ev.to_node}"
            out[where][r.fate] += 1
    return {k: dict(v) for k, v in out.items()}
