"""Failure timeline: configured events (from the Tcl event log) merged with events
observed in the NS2 trace. Every entry says which of the two it came from."""
from __future__ import annotations

from analysis.packets import PacketRecord
from simulation.trace_parser import LoggedEvent, ParsedTrace

CONFIG_TEXT = {
    "SIM_START": "Simulation starts ({detail}).",
    "TRAFFIC_START": "Monitored CBR traffic starts (flow 1, n0 -> n5).",
    "TRAFFIC_STOP": "Monitored CBR traffic stops.",
    "LINK_DOWN": "Configured failure: link {detail} is taken down (rtmodel-at down).",
    "LINK_UP": "Configured restoration: link {detail} is brought back up (rtmodel-at up).",
    "CROSS_TRAFFIC_START": "Configured load increase: competing flow 2 starts.",
    "CROSS_TRAFFIC_STOP": "Competing flow 2 stops.",
    "SIM_END": "Simulation ends.",
}


def _entry(t: float, source: str, event: str, text: str) -> dict:
    return {"time": round(t, 4), "source": source, "event": event, "description": text}


def _loss_time(r: PacketRecord) -> float | None:
    if r.drop:
        return r.drop[0]
    return r.last_event.time if r.last_event else None


def build_timeline(
    logged: list[LoggedEvent],
    parsed: ParsedTrace,
    monitored: list[PacketRecord],
    route_changes: list[dict],
    gaps: list[dict],
    queue_series: dict[str, list[tuple[float, int]]],
    *,
    fail_at: float | None,
    restore_at: float | None,
    cross_window: tuple[float, float] | None,
    bottleneck: str | None,
    queue_limit: int,
    dv_messages_after_fail: int | None,
) -> list[dict]:
    tl: list[dict] = []
    for ev in logged:
        text = CONFIG_TEXT.get(ev.kind, ev.kind).format(detail=ev.detail)
        tl.append(_entry(ev.time, "configured", ev.kind, text))

    seen: set[tuple[float, str, frozenset[int]]] = set()
    for le in parsed.link_events:  # NS2 logs one event per direction; report each link once
        key = (le.time, le.state, frozenset((le.a, le.b)))
        if key in seen:
            continue
        seen.add(key)
        a, b = sorted((le.a, le.b))
        tl.append(_entry(le.time, "trace", f"LINK_{le.state.upper()}_TRACED",
                         f"Trace records link {a}-{b} {le.state} (NS2 'v link-{le.state}' event)."))

    delivered = sorted((r for r in monitored if r.recv_time is not None), key=lambda r: r.recv_time)
    if delivered:
        f = delivered[0]
        tl.append(_entry(f.recv_time, "trace", "FIRST_DELIVERY",
                         f"First monitored packet delivered (seq {f.seq}, path {f.path_label}, "
                         f"delay {f.delay * 1000:.1f} ms)."))

    lost = sorted((r for r in monitored if r.lost), key=lambda r: _loss_time(r) or 0)
    if fail_at is not None:
        after = [r for r in lost if (_loss_time(r) or 0) >= fail_at - 1e-9]
        if after:
            r = after[0]
            tl.append(_entry(_loss_time(r), "trace", "FIRST_LOSS_AFTER_FAILURE",
                             f"First monitored packet lost after the failure (seq {r.seq}): {r.fate_detail}."))
            window_end = restore_at if restore_at is not None else parsed.end_time
            n = sum(1 for r in after if (_loss_time(r) or 0) < window_end + 0.1)
            tl.append(_entry(window_end, "trace", "LOSS_TOTAL_DURING_FAILURE",
                             f"{n} monitored packet(s) were lost between the failure and t={window_end:.2f}s."))
        if dv_messages_after_fail is not None:
            tl.append(_entry(fail_at, "trace", "ROUTING_UPDATES",
                             f"{dv_messages_after_fail} distance-vector routing message(s) were originated "
                             f"in the 0.5 s after the failure."))
    elif lost:
        r = lost[0]
        tl.append(_entry(_loss_time(r), "trace", "FIRST_LOSS",
                         f"First monitored packet lost (seq {r.seq}): {r.fate_detail}."))

    for ch in route_changes:
        tl.append(_entry(ch["time"], "trace", "ROUTE_CHANGE",
                         f"Delivered packets switch from path {ch['from_path']} to {ch['to_path']} "
                         f"(first packet on new path: seq {ch['first_packet_new_path']['seq']})."))

    for g in gaps:
        if g.get("open"):
            tl.append(_entry(g["start"], "trace", "DELIVERY_STOPPED",
                             f"Destination receives nothing from t={g['start']:.3f}s until traffic stops "
                             f"({g['duration_s']:.3f} s)."))
        else:
            tl.append(_entry(g["start"], "trace", "DELIVERY_GAP_START",
                             f"Delivery gap begins: no packets reach n5 for {g['duration_s']:.3f} s."))
            tl.append(_entry(g["end"], "trace", "DELIVERY_RESUMED",
                             f"Delivery resumes at the destination after a {g['duration_s']:.3f} s gap."))

    if cross_window and bottleneck and bottleneck in queue_series:
        s = queue_series[bottleneck]
        c0, c1 = cross_window
        full = [t for t, q in s if q >= queue_limit and c0 <= t]
        if full:
            tl.append(_entry(full[0], "trace", "QUEUE_FULL",
                             f"Queue of link {bottleneck} reaches its limit ({queue_limit} packets)."))
        drained = [t for t, q in s if t >= c1 and q == 0]
        if drained:
            tl.append(_entry(drained[0], "trace", "QUEUE_DRAINED",
                             f"Queue of link {bottleneck} has drained to 0 after the competing flow stopped."))
        drops = sorted(r.drop[0] for r in monitored if r.fate == "dropped_queue" and r.drop)
        if drops:
            tl.append(_entry(drops[0], "trace", "FIRST_QUEUE_DROP",
                             f"First queue-overflow drop of a monitored packet at link {bottleneck}."))
            tl.append(_entry(drops[-1], "trace", "LAST_QUEUE_DROP",
                             f"Last queue-overflow drop of a monitored packet ({len(drops)} in total)."))

    if delivered:
        last = delivered[-1]
        tl.append(_entry(last.recv_time, "trace", "LAST_DELIVERY",
                         f"Last monitored packet delivered (seq {last.seq})."))

    order = {"configured": 0, "trace": 1}
    tl.sort(key=lambda e: (e["time"], order[e["source"]]))
    return tl
