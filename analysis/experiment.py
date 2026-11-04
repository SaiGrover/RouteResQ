"""Analyse one NS2 experiment and answer:
What failed? Why? What happened next? How did performance change? Did it recover?

Every statement in the generated findings is derived from trace evidence; where the
trace cannot support a conclusion, the result says so explicitly.
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from analysis.metrics import (
    drops_by_link,
    phase_summaries,
    queue_occupancy,
    queue_series_binned,
    queue_stats,
    time_series,
    window_summary,
)
from analysis.packets import PacketRecord, build_packet_records
from analysis.routing import (
    delivery_gaps,
    messages_between,
    path_usage,
    route_changes,
    routing_control_traffic,
)
from analysis.timeline import build_timeline
from common.storage import write_csv, write_json
from simulation.scenario import Scenario, parse_bandwidth
from simulation.trace_parser import ParsedTrace, parse_events_log, parse_trace


def _pct_change(before: float | None, after: float | None) -> float | None:
    if before in (None, 0) or after is None:
        return None
    return round(100.0 * (after - before) / before, 1)


def _link_in_path(path: list[int], a: int, b: int) -> bool:
    return any({x, y} == {a, b} for x, y in zip(path, path[1:]))


def _degradation(ph: dict[str, dict]) -> dict:
    out = {}
    for metric in ("throughput_kbps", "avg_delay_ms", "max_delay_ms", "jitter_ms", "loss_pct", "delivery_ratio_pct"):
        b, d, a = (ph[p].get(metric) for p in ("before", "during", "after"))
        out[metric] = {
            "before": b,
            "during": d,
            "after": a,
            "during_vs_before_pct": _pct_change(b, d),
            "after_vs_before_pct": _pct_change(b, a),
        }
    return out


def _fmt(x, unit="", nd=1) -> str:
    return "n/a" if x is None else f"{x:.{nd}f}{unit}"


# --------------------------------------------------------------------------- healthy
def _interpret_healthy(sc: Scenario, ctx: dict) -> dict:
    ov = ctx["overall"][1]
    usage_all = {k: v for ph in ctx["paths"].values() for k, v in ph.items()}
    paths = sorted(usage_all)
    impact = [
        f"{ov['sent']} packets sent, {ov['delivered']} delivered, {ov['lost']} lost "
        f"({_fmt(ov['loss_pct'], '%', 2)} loss).",
        f"Average end-to-end delay {_fmt(ov['avg_delay_ms'], ' ms', 2)}, "
        f"throughput {_fmt(ov['throughput_kbps'], ' kb/s')}.",
        f"Delivered packets used path(s): {', '.join(paths) or 'none'}.",
    ]
    unexpected = ov["lost"] > 0
    if unexpected:
        impact.append("Unexpected: losses occurred even though no fault was configured; see the drop table.")
    return {
        "failure_type": "none (baseline)",
        "known_cause": sc.known_cause,
        "failure_time": None,
        "affected_link": None,
        "what_failed": "Nothing. No fault was introduced; this is the control experiment.",
        "why": sc.known_cause,
        "observed_impact": impact,
        "routing_behavior": f"Only path {paths[0]} was used." if len(paths) == 1 else
                            f"Paths used: {', '.join(paths)}.",
        "route_changes": len(ctx["route_changes"]),
        "recovery": {"outcome": "not applicable", "evidence": []},
        "explanation": (
            f"With all links up and an offered load of {parse_bandwidth(sc.effective['rate']) / 1e6:g} Mb/s on "
            f"{parse_bandwidth(sc.effective['core_bw']) / 1e6:g} Mb/s core links, every "
            "packet followed the lowest-cost path. "
            + ("No packets were lost. " if not unexpected else "Some packets were lost (see drops). ")
            + "These numbers are the baseline for the other scenarios."
        ),
        "can_conclude": ["Baseline throughput, delay and loss of the configured model."],
        "cannot_conclude": ["NS2 results describe this configured model, not any real network."],
    }


# ---------------------------------------------------------------------- link failure
def _interpret_link_failure(sc: Scenario, ctx: dict, parsed: ParsedTrace) -> dict:
    a, b = sc.failed_link  # type: ignore[misc]
    fail_at = sc.fail_at
    restore_at = sc.restore_at
    end = restore_at if restore_at is not None else sc.phases["during"][1]
    mon: list[PacketRecord] = ctx["monitored"]
    ph = ctx["phases"][1]

    traced_down = [e for e in parsed.link_events if {e.a, e.b} == {a, b} and e.state == "down"]
    traced_up = [e for e in parsed.link_events if {e.a, e.b} == {a, b} and e.state == "up"]
    confirmation = (
        f"Confirmed by the trace: link-down event at t={traced_down[0].time:g} s."
        if traced_down else "The link-down event was NOT found in the trace; the failure may not have taken effect."
    )

    def loss_t(r: PacketRecord) -> float:
        return r.drop[0] if r.drop else (r.last_event.time if r.last_event else 0.0)

    lost_in_failure = [r for r in mon if r.lost and fail_at - 1e-9 <= loss_t(r) <= end + 0.1]
    fate_split: dict[str, int] = {}
    for r in lost_in_failure:
        fate_split[r.fate] = fate_split.get(r.fate, 0) + 1

    sent_during = [r for r in mon if r.send_time is not None and fail_at <= r.send_time < end]
    delivered_during = [r for r in sent_during if r.fate == "delivered"]
    alt_delivered = [r for r in delivered_during if not _link_in_path(r.path, a, b)]
    alt_paths = sorted({r.path_label for r in alt_delivered})
    changes = ctx["route_changes"]
    changes_in_failure = [c for c in changes if fail_at - 0.05 <= c["time"] < end]
    changes_after_restore = [c for c in changes if restore_at is not None and c["time"] >= restore_at - 0.05]
    gaps_in_failure = [
        g for g in ctx["gaps"]
        if g["start"] <= end and (g["end"] is None or g["end"] >= fail_at)
    ]

    impact: list[str] = [
        f"{len(lost_in_failure)} monitored packet(s) were lost from the failure until "
        f"t={end:g}s ({', '.join(f'{k}: {v}' for k, v in fate_split.items()) or 'none'}).",
        f"Of {len(sent_during)} packets sent while the link was down, {len(delivered_during)} were delivered.",
    ]
    if gaps_in_failure:
        for g in gaps_in_failure:
            if g.get("open"):
                impact.append(f"Delivery stopped at t={g['start']:.3f}s and did not resume before traffic ended.")
            else:
                impact.append(
                    f"Delivery gap at the destination from t={g['start']:.3f}s to t={g['end']:.3f}s "
                    f"({g['duration_s']:.3f} s)."
                )
    else:
        impact.append("No delivery gap longer than the detection threshold was observed at the destination.")

    # routing behaviour
    rb: list[str] = []
    if changes_in_failure:
        for c in changes_in_failure:
            rb.append(f"Route changed at t={c['time']:.4f}s from {c['from_path']} to {c['to_path']}.")
    else:
        rb.append("No route change was observed for delivered packets after the failure.")
    if alt_paths:
        rb.append(f"During the failure, packets were delivered over {', '.join(alt_paths)}, "
                  f"which avoids link {a}-{b}.")
    for c in changes_after_restore:
        rb.append(f"After restoration, route changed at t={c['time']:.4f}s from {c['from_path']} to {c['to_path']}.")
    dv_msgs = ctx.get("dv_messages_after_fail")
    if sc.routing == "DV" and dv_msgs is not None:
        rb.append(f"{dv_msgs} distance-vector update(s) were originated in the 0.5 s after the failure "
                  f"(vs. {ctx['dv_messages_baseline_rate']:.1f} per 0.5 s on average before it).")
    if sc.routing == "Static":
        rb.append("Static routing computes routes once; no routing-protocol messages exist in this run.")

    # recovery classification
    evidence: list[str] = []
    recovery_time = None
    outcome: str
    if alt_delivered:
        first_alt = min(alt_delivered, key=lambda r: r.recv_time)
        outcome = "rerouted - delivery continued over an alternative path"
        recovery_time = round(first_alt.recv_time - fail_at, 4)
        evidence.append(
            f"First packet delivered via {first_alt.path_label} arrived at t={first_alt.recv_time:.4f}s "
            f"({recovery_time * 1000:.1f} ms after the failure)."
        )
    else:
        after_restore = [
            r for r in mon if r.recv_time is not None and restore_at is not None and r.recv_time >= restore_at
        ]
        if restore_at is not None and after_restore:
            first = min(after_restore, key=lambda r: r.recv_time)
            outcome = "interrupted - delivery resumed only after the link was restored"
            recovery_time = round(first.recv_time - fail_at, 4)
            evidence.append(
                f"No packet sent during the failure was delivered; first delivery after restoration at "
                f"t={first.recv_time:.4f}s ({first.recv_time - restore_at:.4f} s after link-up, "
                f"{recovery_time:.3f} s after the failure)."
            )
        else:
            outcome = "not recovered within the simulation"
            evidence.append("No packets were delivered after the failure.")

    after = ph["after"]
    before = ph["before"]
    if after["delivery_ratio_pct"] is not None and before["throughput_kbps"]:
        ratio = (after["throughput_kbps"] or 0) / before["throughput_kbps"]
        evidence.append(
            f"After-phase throughput is {ratio * 100:.1f}% of the before-phase value with "
            f"{_fmt(after['loss_pct'], '%', 2)} loss and {_fmt(after['avg_delay_ms'], ' ms', 2)} average delay."
        )
    if traced_up:
        evidence.append(f"Trace records link {a}-{b} up again at t={traced_up[0].time:g}s.")

    # explanation
    if alt_delivered:
        mech = (
            f"When link {a}-{b} went down, NS2's distance-vector agents at the adjacent routers were notified "
            f"and sent triggered updates; node {a} already had a route via the alternative path, so forwarding "
            f"switched almost immediately. Only packets that were already queued on or in transit over "
            f"the failed link were lost."
        )
    elif sc.routing == "Static":
        mech = (
            f"With static routing the forwarding table still pointed at link {a}-{b}, so node {a} received "
            f"the packets but could not forward them. NS2 discarded them without writing 'd' events; their "
            f"loss was detected because they were never seen again after arriving at node {a}. Delivery "
            f"resumed only when the link came back."
        )
    else:
        mech = "Packets could not reach the destination while the link was down."
    if ph["during"]["avg_delay_ms"] is None:
        delay_txt = "No packet sent during the failure was delivered, so no delay can be measured for that phase."
    else:
        delay_txt = (
            f"Average delay changed from {_fmt(before['avg_delay_ms'], ' ms', 2)} before the failure to "
            f"{_fmt(ph['during']['avg_delay_ms'], ' ms', 2)} during it"
            + (" because the alternative path is longer." if alt_delivered and
               (ph['during']['avg_delay_ms'] or 0) > (before['avg_delay_ms'] or 0) else ".")
        )
    explanation = f"Link {a}-{b} failed at t={fail_at:g} s. {mech} {delay_txt}"
    cannot = [
        "Results describe NS2's model of DV/static routing on this topology; real routing protocols "
        "(e.g. RIP with hold-down timers) can converge much more slowly.",
    ]
    if any(r.fate in ("lost_at_node", "lost_on_link") for r in lost_in_failure):
        cannot.append(
            "NS2 2.35 does not write 'd' events for some of these losses; their location is inferred from the "
            "last traced event of each packet."
        )
    return {
        "failure_type": "link failure",
        "known_cause": sc.known_cause,
        "failure_time": fail_at,
        "restore_time": restore_at,
        "affected_link": f"n{a}-n{b}",
        "what_failed": f"Link n{a}-n{b} failed at t={fail_at:g} s. {confirmation}",
        "why": sc.known_cause,
        "observed_impact": impact,
        "packets_lost_due_to_failure": len(lost_in_failure),
        "loss_fates": fate_split,
        "routing_behavior": " ".join(rb),
        "route_changes": len(changes),
        "destination_reachable_during_failure": bool(delivered_during),
        "communication_stopped": bool(gaps_in_failure) and not alt_delivered,
        "recovery": {"outcome": outcome, "time_to_recovery_s": recovery_time, "evidence": evidence},
        "explanation": explanation,
        "can_conclude": [
            "Which packets were lost and where (from the trace).",
            "Whether and when the forwarding path changed (from per-packet paths).",
        ],
        "cannot_conclude": cannot,
    }


# ------------------------------------------------------------------------ congestion
def _interpret_congestion(sc: Scenario, ctx: dict) -> dict:
    ph = ctx["phases"][1]
    e = sc.effective
    c0, c1 = float(e["cross_start"]), float(e["cross_stop"])
    offered = parse_bandwidth(e["rate"]) + parse_bandwidth(e["cross_rate"])
    capacity = parse_bandwidth(e["core_bw"])
    qstats = ctx["queue_stats"]
    bottleneck = ctx["bottleneck"]
    bq = qstats.get(bottleneck, {}) if bottleneck else {}
    qlimit = int(e["queue_limit"])
    all_recs: list[PacketRecord] = ctx["all_records"]
    qdrops = [r for r in all_recs if r.fate == "dropped_queue"]
    qdrops_mon = [r for r in qdrops if r.fid == 1]
    other_loss = [r for r in all_recs if r.lost and r.fate != "dropped_queue"]
    deg = ctx["degradation"]

    impact = [
        f"Offered load on the core path during t={c0:g}-{c1:g}s: {offered / 1e6:.2f} Mb/s vs "
        f"{capacity / 1e6:.2f} Mb/s capacity ({offered / capacity * 100:.0f}% utilisation demand).",
    ]
    if bq:
        impact.append(
            f"Queue at link {bottleneck} peaked at {bq['max_queue_pkts']} packets (limit {qlimit}) at "
            f"t={bq['time_of_max']:.3f}s."
        )
    impact.append(
        f"Monitored flow average delay: {_fmt(deg['avg_delay_ms']['before'], ' ms', 2)} before -> "
        f"{_fmt(deg['avg_delay_ms']['during'], ' ms', 2)} during -> "
        f"{_fmt(deg['avg_delay_ms']['after'], ' ms', 2)} after."
    )
    impact.append(
        f"Monitored flow throughput: {_fmt(deg['throughput_kbps']['before'], ' kb/s')} before -> "
        f"{_fmt(deg['throughput_kbps']['during'], ' kb/s')} during -> "
        f"{_fmt(deg['throughput_kbps']['after'], ' kb/s')} after."
    )
    if qdrops:
        by_flow: dict[int, int] = {}
        for r in qdrops:
            by_flow[r.fid] = by_flow.get(r.fid, 0) + 1
        impact.append(
            f"Congestion loss confirmed: {len(qdrops)} queue-overflow drops ('d' events on an up link) - "
            + ", ".join(f"flow {k}: {v}" for k, v in sorted(by_flow.items())) + "."
        )
        loss_statement = "Packet loss was caused by queue overflow at the bottleneck (confirmed by d events)."
    else:
        impact.append("No queue-overflow drops were recorded: the queue absorbed the extra load.")
        loss_statement = "The trace shows no congestion drops, so no congestion loss is claimed."
    if other_loss:
        impact.append(f"{len(other_loss)} packet(s) were lost for other reasons (see fates).")

    drained_at = None
    if bottleneck and bottleneck in ctx["queue_series"]:
        drained = [t for t, q in ctx["queue_series"][bottleneck] if t >= c1 and q == 0]
        drained_at = drained[0] if drained else None
    after = ph["after"]
    evidence = []
    if drained_at is not None:
        evidence.append(f"Bottleneck queue drained to 0 at t={drained_at:.4f}s "
                        f"({drained_at - c1:.4f} s after competing traffic stopped).")
    evidence.append(
        f"After-phase loss {_fmt(after['loss_pct'], '%', 2)}, delay {_fmt(after['avg_delay_ms'], ' ms', 2)} "
        f"(before-phase delay {_fmt(ph['before']['avg_delay_ms'], ' ms', 2)})."
    )
    # Recovery is judged on packets sent after the bottleneck queue drained, so that
    # packets caught in the draining queue are reported as a transient, not as non-recovery.
    traffic_stop = float(e["traffic_stop"])
    post = window_summary(ctx["monitored"], drained_at, traffic_stop) if drained_at and drained_at < traffic_stop else None
    base_delay = ph["before"]["avg_delay_ms"]
    recovered = bool(
        post and post["sent"] > 0 and post["loss_pct"] == 0
        and post["avg_delay_ms"] is not None and base_delay is not None
        and post["avg_delay_ms"] <= base_delay * 1.1
    )
    if post:
        evidence.append(
            f"Packets sent after the queue drained (t={drained_at:.3f}-{traffic_stop:g}s): {post['sent']} sent, "
            f"{_fmt(post['loss_pct'], '%', 2)} loss, {_fmt(post['avg_delay_ms'], ' ms', 2)} average delay."
        )
    transient = [r for r in qdrops_mon if r.send_time is not None and r.send_time >= c1]
    if transient:
        evidence.append(
            f"{len(transient)} monitored packet(s) sent just after t={c1:g}s were still dropped by the full "
            "queue before it drained (transient)."
        )
    if drained_at is None:
        outcome = "not recovered - the bottleneck queue never drained"
    elif recovered:
        outcome = "recovered - delay and loss returned to baseline once the queue drained"
    else:
        outcome = "partially recovered - queue drained but delay or loss stayed above baseline"
    return {
        "failure_type": "congestion (increased traffic load)",
        "known_cause": sc.known_cause,
        "failure_time": c0,
        "restore_time": c1,
        "affected_link": f"n{bottleneck.replace('->', '-n')}" if bottleneck else None,
        "what_failed": (
            "No component failed. Offered load exceeded the capacity of the core link, degrading service "
            f"between t={c0:g}s and t={c1:g}s."
        ),
        "why": sc.known_cause,
        "observed_impact": impact,
        "routing_behavior": (
            "No route change was observed (NS2 DV routing is not load-aware)." if not ctx["route_changes"]
            else f"{len(ctx['route_changes'])} route change(s) observed."
        ),
        "route_changes": len(ctx["route_changes"]),
        "queue_drops": len(qdrops),
        "queue_drops_monitored_flow": len(qdrops_mon),
        "recovery": {"outcome": outcome, "time_to_recovery_s": round(drained_at - c1, 4) if drained_at else None,
                     "evidence": evidence},
        "explanation": (
            f"Between t={c0:g}s and t={c1:g}s the core link {bottleneck} was offered more traffic than it can "
            f"carry, so its DropTail queue filled. Queueing added delay, and once the queue was full new "
            f"arrivals were dropped. {loss_statement}"
        ),
        "can_conclude": [
            "Queue build-up, delay increase and drop counts at the bottleneck (from the trace).",
        ],
        "cannot_conclude": [
            "How a TCP flow would react (both flows are CBR/UDP and do not back off).",
            "NS2 results describe this configured model, not any real network.",
        ],
    }


# ------------------------------------------------------------------------------ main
def analyze_experiment(sc: Scenario, trace_path: Path, events_path: Path, run_meta: dict | None = None) -> dict:
    parsed = parse_trace(trace_path)
    logged = parse_events_log(events_path)
    fids = {f.fid for f in sc.flows}
    records = build_packet_records(parsed, fids)
    by_flow = {fid: [r for r in records.values() if r.fid == fid] for fid in fids}
    mon = by_flow[1]

    overall = {fid: window_summary(recs) for fid, recs in by_flow.items()}
    phases = {fid: phase_summaries(recs, sc.phases) for fid, recs in by_flow.items()}
    paths = path_usage(mon, sc.phases)
    changes = route_changes(mon)
    gaps = delivery_gaps(mon, sc.packet_interval, (float(sc.effective["traffic_start"]), float(sc.effective["traffic_stop"])))
    qseries = queue_occupancy(parsed)
    qstats = queue_stats(qseries)
    bottleneck = max(qstats, key=lambda k: qstats[k]["max_queue_pkts"]) if qstats else None
    ctrl = routing_control_traffic(parsed)

    ctx: dict = {
        "monitored": mon,
        "all_records": list(records.values()),
        "overall": overall,
        "phases": phases,
        "paths": paths,
        "route_changes": changes,
        "gaps": gaps,
        "queue_series": qseries,
        "queue_stats": qstats,
        "bottleneck": bottleneck,
        "degradation": _degradation(phases[1]),
    }
    dv_after = None
    if sc.routing == "DV" and sc.fail_at is not None:
        dv_after = messages_between(parsed, sc.fail_at, sc.fail_at + 0.5)
        pre = messages_between(parsed, 0.5, sc.fail_at)  # skip the start-up exchange
        ctx["dv_messages_baseline_rate"] = pre / max((sc.fail_at - 0.5) / 0.5, 1)
    ctx["dv_messages_after_fail"] = dv_after

    if sc.category == "healthy":
        findings = _interpret_healthy(sc, ctx)
    elif sc.category == "link_failure":
        findings = _interpret_link_failure(sc, ctx, parsed)
    else:
        findings = _interpret_congestion(sc, ctx)
    findings["performance_degradation"] = ctx["degradation"]

    cross_window = (
        (float(sc.effective["cross_start"]), float(sc.effective["cross_stop"])) if sc.has_cross_traffic else None
    )
    timeline = build_timeline(
        logged, parsed, mon, changes, gaps, qseries,
        fail_at=sc.fail_at, restore_at=sc.restore_at, cross_window=cross_window,
        bottleneck=bottleneck, queue_limit=int(sc.effective["queue_limit"]),
        dv_messages_after_fail=dv_after,
    )

    ts = time_series(mon, parsed.end_time)
    if 2 in by_flow:
        ts2 = time_series(by_flow[2], parsed.end_time)
        for row, row2 in zip(ts, ts2):
            row["cross_throughput_kbps"] = row2["throughput_kbps"]
    if bottleneck:
        for row, qrow in zip(ts, queue_series_binned(qseries[bottleneck], parsed.end_time)):
            row["bottleneck_queue_pkts"] = qrow["queue_pkts"]

    return {
        "scenario": sc.to_dict(),
        "run": run_meta or {},
        "trace_quality": {
            "total_lines": parsed.total_lines,
            "packet_events": len(parsed.events),
            "malformed_lines": parsed.malformed_lines,
            "malformed_examples": parsed.malformed_examples,
            "trace_end_time": parsed.end_time,
            "link_events": [asdict(e) for e in parsed.link_events],
        },
        "flows": {str(f.fid): {**f.__dict__, "summary": overall[f.fid]} for f in sc.flows},
        "phases": {str(fid): v for fid, v in phases.items()},
        "path_usage": paths,
        "route_changes": changes,
        "delivery_gaps": gaps,
        "queue_stats": qstats,
        "bottleneck_link": bottleneck,
        "drops_by_location": drops_by_link(list(records.values())),
        "routing_control": ctrl,
        "timeline": timeline,
        "timeseries": ts,
        "findings": findings,
        "lost_packets": [
            {"fid": r.fid, "seq": r.seq, "pkt_id": r.pkt_id, "sent": r.send_time, "fate": r.fate,
             "detail": r.fate_detail, "path_so_far": r.path_label}
            for r in sorted((r for r in records.values() if r.lost), key=lambda r: (r.fid, r.seq))
        ],
    }


def save_experiment(result: dict, out_dir: Path) -> dict[str, Path]:
    """Write the reusable JSON/CSV outputs of one experiment."""
    files = {
        "results_json": write_json(out_dir / "results.json", result),
        "timeline_csv": write_csv(out_dir / "timeline.csv", result["timeline"]),
        "timeseries_csv": write_csv(out_dir / "timeseries.csv", result["timeseries"]),
        "lost_packets_csv": write_csv(
            out_dir / "lost_packets.csv", result["lost_packets"],
            ["fid", "seq", "pkt_id", "sent", "fate", "detail", "path_so_far"],
        ),
    }
    rows = []
    for fid, ph in result["phases"].items():
        for name, m in ph.items():
            rows.append({"flow": fid, "phase": name, **{k: v for k, v in m.items() if k != "fates"},
                         **{f"fate_{k}": v for k, v in m["fates"].items()}})
    files["phase_metrics_csv"] = write_csv(out_dir / "phase_metrics.csv", rows)
    return files
