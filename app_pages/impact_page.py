from pathlib import Path

import pandas as pd
import streamlit as st

from analysis.comparison import compare, save_comparison
from common.paths import SIM_RESULTS_DIR, TCL_SCRIPT
from simulation.experiments import run_and_analyze
from simulation.runner import NS2ExecutionError, NS2UnavailableError
from ui import charts, data
from ui import theme as T
from ui.components import (badge_row, card, card_title, chart, code, e, empty, fmt, method, note, page_header,
                           pill, tiles)

SC = data.scenarios()
status = data.ns2_status()

page_header("Stage 03 · Analyse impact", "NS2 failure simulation",
            "A six-node wired network in the real ns-2.35 simulator. Each scenario injects one known condition, "
            "so the cause is certain and the question becomes what happened to the traffic. Every value below "
            "is reconstructed from the simulator's own trace file.", T.CLAY)
badge_row("sim")
if not status["available"]:
    note(f"<b>NS2 is not available here.</b> {e(status['detail'])} Stored runs can still be explored.", T.CLAY)

labels = {sid: f"{sc.label} · {sc.name.split(' - ', 1)[-1]}" for sid, sc in SC.items()}
st.session_state.setdefault("sim_sid", "link_failure_dv")
sid = st.segmented_control("Scenario", list(SC), format_func=labels.get, key="sim_sid", required=True)
sc = SC[sid]
color = T.SCENARIO_COLOR[sid]

# ------------------------------------------------------------------ run controls
runs = data.runs(sid)
r1, r2, r3 = st.columns([1, 1, 2.2], vertical_alignment="bottom")
run_one = r1.button(f"Run {sc.label} in NS2", type="primary", icon=":material/play_arrow:", width="stretch",
                    disabled=not status["available"])
run_all = r2.button("Run all four", icon=":material/playlist_play:", width="stretch", disabled=not status["available"])
choice = r3.selectbox("Stored run", [str(r) for r in runs], format_func=lambda p: Path(p).name + ("  (newest)" if p == str(runs[0]) else ""),
                      disabled=not runs, placeholder="no stored run", key=f"run_{sid}")
if run_one or run_all:
    todo = SC if run_all else {sid: sc}
    with st.status("Running ns-2.35", expanded=True) as stt:
        try:
            for tid, tsc in todo.items():
                st.write(f"**{tsc.label}** {tid}: simulating, parsing the trace, analysing ...")
                res = run_and_analyze(tsc)
                st.write(f"→ {res['findings']['recovery']['outcome']} · {res['trace_quality']['total_lines']:,} trace lines")
            if run_all:
                save_comparison(compare(list(data.latest_all().values())), SIM_RESULTS_DIR)
            stt.update(label="NS2 run complete", state="complete", expanded=False)
        except (NS2UnavailableError, NS2ExecutionError) as exc:
            stt.update(label="NS2 run failed", state="error")
            st.error(str(exc))
            st.stop()
    st.rerun()

res = data.result_at(Path(choice)) if choice else None

# ------------------------------------------------------------------ topology + config
left, right = st.columns([1.65, 1], gap="medium")
with left, card("topo"):
    card_title("Topology and observed paths", "edge width = delivered packets that crossed the link in the chosen phase")
    phase = st.segmented_control("Phase", ["before", "during", "after"], default="during", key="topo_phase",
                                 label_visibility="collapsed", required=True)
    st.plotly_chart(charts.topology(sc.to_dict(), res, phase), width="stretch", config={"displayModeBar": False})
    if res:
        pu = res["path_usage"].get(phase, {})
        st.html("".join(pill(f"{k}  ·  {v} pkts", T.ALT_PATH if "3" in k.split("-") else T.SIGNAL) for k, v in pu.items())
                or pill("no packet delivered in this phase", T.CLAY))
with right, card("cfg"):
    card_title(sc.name)
    st.html(f'<div class="rr-csub" style="font-size:.84rem;line-height:1.6">{e(sc.description)}</div>')
    st.html(f'<div class="rr-note" style="--c:{color}"><b>Known cause.</b> {code(sc.known_cause)}</div>')
    p = sc.effective
    cfg = [("routing", p["routing"]), ("traffic", f"{p['rate']} CBR/UDP · {p['pkt_size']} B · {p['traffic_start']}-{p['traffic_stop']} s"),
           ("core links", f"{p['core_bw']} · {p['core_delay']} (alt {p['alt_delay']}, cost {p['alt_cost']})"),
           ("queues", f"DropTail · {p['queue_limit']} packets")]
    if sc.has_failure:
        cfg.append(("failure", f"link {p['fail_link']} down {p['fail_at']}-{p['restore_at']} s"))
    if sc.has_cross_traffic:
        cfg.append(("load", f"flow 2 {p['cross_rate']} from {p['cross_start']} to {p['cross_stop']} s"))
    st.html("".join(f'<div class="rr-cause" style="--c:{T.SLATE};padding:.4rem .7rem;margin-bottom:.35rem">'
                    f'<div class="row" style="grid-template-columns:90px 1fr"><b>{k}</b><span>{e(v)}</span></div></div>'
                    for k, v in cfg))

if not res:
    empty("No stored run for this scenario", "Press <b>Run in NS2</b> to simulate it.")
    st.stop()

# ------------------------------------------------------------------ KPIs
ov = res["flows"]["1"]["summary"]
f = res["findings"]
gap = max((g["duration_s"] for g in res["delivery_gaps"]), default=0.0)
tiles([
    ("Packets delivered", f"{ov['delivered']:,}<small>/{ov['sent']:,}</small>", "monitored flow n0 → n5", color),
    ("Packet loss", f"{fmt(ov['loss_pct'])}<small>%</small>", f"{ov['lost']} lost · {ov['in_flight']} in flight", T.CLAY if ov["lost"] else T.GREEN),
    ("Avg end-to-end delay", f"{fmt(ov['avg_delay_ms'])}<small>ms</small>", f"max {fmt(ov['max_delay_ms'])} ms", T.SIGNAL),
    ("Throughput", f"{fmt(ov['throughput_kbps'], '', 1)}<small>kb/s</small>", "first send → last receive", T.SIGNAL),
    ("Route changes", f"{len(res['route_changes'])}", "from per-packet paths", T.STEEL if res["route_changes"] else T.SLATE),
    ("Longest delivery gap", f"{fmt(gap, '', 3)}<small>s</small>", "no arrivals at n5", T.CLAY if gap else T.GREEN),
])

# ------------------------------------------------------------------ charts
c1, c2 = st.columns(2, gap="medium")
with c1:
    chart(charts.throughput(res), "Throughput at the destination", "100 ms bins · shaded = configured event window",
          what="Bits received at n5 per 100 ms. Small oscillation is quantisation: 12 or 13 packets fit in a bin.",
          why="The shape over time shows whether the event interrupted delivery, degraded it, or was absorbed.")
with c2:
    chart(charts.delay(res), "End-to-end delay by path", "average per 100 ms of send time",
          what="Delay of delivered packets, coloured by the path they took. A gap means nothing sent then was delivered.",
          why="A step up on a different colour is rerouting onto a longer path; a ramp on the same path is queueing.")
c3, c4 = st.columns(2, gap="medium")
with c3:
    chart(charts.fates(res), "What happened to every packet", "per phase, by send time",
          what="Each sent packet ends with exactly one fate. 'lost at node' are packets NS2 discarded without "
               "writing a drop line; RouteResQ finds them because they are never seen again.",
          why="Separates congestion (queue drops) from failure (link-down and silent route losses).")
with c4:
    if sc.category == "congestion":
        chart(charts.queue(res), f"Queue at {res['bottleneck_link']}", "rebuilt from enqueue / dequeue / drop events",
              what="Packets waiting in the busiest queue. Drops happen when it reaches the configured limit.",
              why="Confirms congestion loss from the trace instead of assuming it.")
    elif res["routing_control"]["total_messages"]:
        chart(charts.routing_messages(res), "Distance-vector routing messages", "originated by routers",
              what="Routing updates sent by the DV agents. Periodic adverts plus triggered updates after link changes.",
              why="A burst right after the failure is the mechanism behind the reroute.")
    else:
        chart(charts.losses(res), "Lost packets over time", "by send time",
              what="Packets lost in each 100 ms of send time.", why="Static routing sends no updates, so loss lasts the whole failure.")
chart(charts.phases(res), "Before · during · after", "monitored flow, consistent 3-second windows",
      what="Phase metrics: loss and delay by send time, throughput by receive time.",
      why="The core before/during/after comparison; the Failure & recovery page explains it in depth.")

with st.expander(f"Lost packets ({len(res['lost_packets'])})"):
    st.dataframe(pd.DataFrame(res["lost_packets"]), hide_index=True, alt="Lost packets", height=280)

run_dir = Path(choice)
with st.expander("Downloads"):
    dl = st.columns(4)
    for i, name in enumerate(["report.md", "results.json", "phase_metrics.csv", "timeline.csv", "timeseries.csv",
                              "lost_packets.csv", "out.tr", "routeresq.tcl"]):
        fp = run_dir / name
        if fp.exists():
            dl[i % 4].download_button(name, fp.read_bytes(), file_name=f"{sid}_{name}", icon=":material/download:",
                                      key=f"dl_{name}", width="stretch")

method([
    ("Configure", f"<code>simulation/scenarios/{sid}.json</code> is validated strictly (no Tcl injection possible) "
     "and turned into <code>key=value</code> arguments."),
    ("Simulate", f"<code>ns routeresq.tcl</code> runs on {e(res['run'].get('backend', ''))} ns2 {e(res['run'].get('ns_version', ''))}; "
     "failures use <code>rtmodel-at</code>, load uses a second CBR flow."),
    ("Parse the trace", f"{res['trace_quality']['total_lines']:,} lines, {res['trace_quality']['malformed_lines']} malformed. "
     "Packets are matched by NS2's unique id so routers are never double counted."),
    ("Reconstruct", "Per-packet path, delay and fate; queue occupancy per link; route changes; delivery gaps."),
    ("Interpret", "Answers what failed, why, what happened next, how performance changed and whether recovery was observed."),
], "ns-2.35 + analysis", [("routeresq.tcl", TCL_SCRIPT), ("scenario JSON", Path(SC[sid].source_file or ""))],
   [("out.tr (trace)", run_dir / "out.tr"), ("results.json", run_dir / "results.json"),
    ("timeseries.csv", run_dir / "timeseries.csv"), ("report.md", run_dir / "report.md")],
   T.CLAY, f"run {run_dir.name}")
