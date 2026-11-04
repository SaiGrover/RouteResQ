from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from common.storage import read_json
from simulation.experiments import run_and_analyze
from simulation.runner import NS2ExecutionError, NS2UnavailableError, list_runs
from simulation.scenario import LINKS, NODE_ROLES, Scenario, load_all_scenarios
from ui.components import bullet, cached_backend_status, fmt, sim_badge

scenarios = load_all_scenarios()


@st.cache_data(max_entries=32, show_spinner=False)
def load_result(path: str, mtime: float) -> dict:
    return read_json(Path(path))


def topology_dot(sc: Scenario) -> str:
    e = sc.effective
    failed = sc.failed_link
    lines = ["graph G {", "rankdir=LR; bgcolor=transparent; nodesep=0.35; ranksep=0.55;",
             'node [shape=circle, style=filled, fontname="Helvetica", fontsize=12, width=0.45, fixedsize=true];',
             'edge [fontname="Helvetica", fontsize=9];']
    colors = {0: "#99f6e4", 5: "#99f6e4"}
    for n, role in NODE_ROLES.items():
        lines.append(f'n{n} [label="n{n}", fillcolor="{colors.get(n, "#e2e8f0")}", tooltip="{role}"];')
    for a, b, kind in LINKS:
        bw = e["access_bw"] if kind == "access" else e["core_bw"]
        delay = e["access_delay"] if kind == "access" else e["core_delay"] if kind == "core" else e["alt_delay"]
        cost = f", cost {e['alt_cost']}" if kind == "alt" else ""
        attrs = f'label="{bw}, {delay}{cost}"'
        if failed and {a, b} == set(failed):
            attrs += f', color="#dc2626", style=dashed, penwidth=2.5, fontcolor="#dc2626", label="{bw}, {delay}\\nDOWN {sc.fail_at:g}-{sc.restore_at or "end"}s"'
        elif kind == "alt":
            attrs += ', color="#64748b", style=dotted'
        else:
            attrs += ', penwidth=1.6'
        lines.append(f"n{a} -- n{b} [{attrs}];")
    lines.append("}")
    return "\n".join(lines)


def event_rules(sc: Scenario) -> pd.DataFrame:
    ev = []
    if sc.fail_at is not None:
        ev.append({"t": sc.fail_at, "event": f"link {sc.effective['fail_link']} down"})
    if sc.restore_at is not None:
        ev.append({"t": sc.restore_at, "event": f"link {sc.effective['fail_link']} up"})
    if sc.has_cross_traffic:
        ev += [{"t": float(sc.effective["cross_start"]), "event": "competing flow starts"},
               {"t": float(sc.effective["cross_stop"]), "event": "competing flow stops"}]
    return pd.DataFrame(ev)


def with_events(chart: alt.Chart, sc: Scenario) -> alt.LayerChart | alt.Chart:
    ev = event_rules(sc)
    if ev.empty:
        return chart
    rules = alt.Chart(ev).mark_rule(color="#dc2626", strokeDash=[4, 3]).encode(x="t:Q", tooltip=["event", "t"])
    return alt.layer(chart, rules)


st.title("NS2 failure simulation & recovery analysis")
sim_badge()
st.caption("Real NS2 runs of a 6-node wired topology. Each fault is injected on purpose, so the cause is "
           "known; RouteResQ measures what happened afterwards from the trace file.")

status = cached_backend_status()
if not status["available"]:
    st.warning(status["detail"], title="NS2 is not available", icon=":material/warning:")
else:
    st.caption(f"NS2 backend: {status['kind']} ({status['detail']}), ns2 {status['version']}")

labels = {sid: f"{sc.label}  {sc.name.split(' - ', 1)[-1]}" for sid, sc in scenarios.items()}
sid = st.segmented_control("Scenario", list(scenarios), format_func=labels.get, default=list(scenarios)[0],
                           required=True, key="sim_scenario")
sc = scenarios[sid]

c1, c2 = st.columns([3, 2])
with c1:
    st.graphviz_chart(topology_dot(sc), width="stretch", alt=f"Topology for {sc.name}")
with c2.container(border=True):
    st.markdown(f"**{sc.name}**")
    st.write(sc.description)
    st.markdown(f"**Known experimental cause:** {sc.known_cause}")
    e = sc.effective
    st.caption(f"Routing: {e['routing']} | traffic: {e['rate']} CBR/UDP, {e['pkt_size']} B packets, "
               f"{e['traffic_start']}-{e['traffic_stop']} s | queues: DropTail, {e['queue_limit']} pkts | "
               f"phases: " + ", ".join(f"{k} {v[0]:g}-{v[1]:g}s" for k, v in sc.phases.items()))

runs = list_runs(sid)
cc1, cc2, cc3 = st.columns([1, 1, 2], vertical_alignment="bottom")
run_now = cc1.button("Run in NS2", type="primary", icon=":material/play_arrow:", disabled=not status["available"])
run_all = cc2.button("Run all scenarios", icon=":material/playlist_play:", disabled=not status["available"])
run_choice = cc3.selectbox("Stored run", [str(r) for r in runs], format_func=lambda p: Path(p).name,
                           disabled=not runs, placeholder="no stored runs yet")

if run_now or run_all:
    targets = scenarios if run_all else {sid: sc}
    with st.status("Running NS2...", expanded=True) as stat:
        try:
            for tid, tsc in targets.items():
                st.write(f"Simulating and analysing **{tsc.label} {tid}**...")
                res = run_and_analyze(tsc)
                st.write(f"-> {res['findings']['recovery']['outcome']}")
            if run_all:
                from analysis.comparison import compare, save_comparison
                from common.paths import SIM_RESULTS_DIR
                from simulation.experiments import latest_result

                rows = compare([r for r in (latest_result(t) for t in scenarios) if r])
                save_comparison(rows, SIM_RESULTS_DIR)
            stat.update(label="NS2 run complete", state="complete", expanded=False)
        except (NS2UnavailableError, NS2ExecutionError) as exc:
            stat.update(label="NS2 run failed", state="error")
            st.error(str(exc))
            st.stop()
    st.rerun()

if not runs:
    st.info("No stored run for this scenario yet. Press **Run in NS2**.")
    st.stop()

res_path = Path(run_choice) / "results.json"
if not res_path.exists():
    st.warning("This run has no analysis results (results.json missing).")
    st.stop()
res = load_result(str(res_path), res_path.stat().st_mtime)
f = res["findings"]
ph = res["phases"]["1"]

st.divider()
tab_names = ["Findings", "Before / during / after", "Timeline", "Routing & paths", "Queues & losses", "Files"]
tabs = st.tabs(tab_names)

with tabs[0]:
    q1, q2 = st.columns(2)
    with q1.container(border=True, height="stretch"):
        st.markdown("##### :material/report: What failed?")
        st.write(f["what_failed"])
        st.markdown("##### :material/help: Why did it fail?")
        st.write(f["why"])
    with q2.container(border=True, height="stretch"):
        st.markdown("##### :material/healing: Was recovery observed?")
        st.markdown(f"**{f['recovery']['outcome']}**")
        bullet(f["recovery"].get("evidence", []))
    with st.container(border=True):
        st.markdown("##### :material/timeline: What happened next?")
        bullet(f["observed_impact"])
        st.markdown(f"**Routing behaviour.** {f['routing_behavior']}")
    with st.container(border=True):
        st.markdown("##### :material/school: Technical explanation")
        st.write(f["explanation"])
        a, b = st.columns(2)
        with a:
            st.markdown("**Can be concluded**")
            bullet(f.get("can_conclude", []))
        with b:
            st.markdown("**Cannot be concluded**")
            bullet(f.get("cannot_conclude", []))

with tabs[1]:
    m = st.columns(4)
    deg = f["performance_degradation"]
    for col, key, label, unit in [(m[0], "throughput_kbps", "Throughput", " kb/s"),
                                  (m[1], "avg_delay_ms", "Avg delay", " ms"),
                                  (m[2], "loss_pct", "Loss", " %"),
                                  (m[3], "jitter_ms", "Jitter", " ms")]:
        d = deg[key]
        delta = None
        if d["during"] is not None and d["before"] is not None:
            delta = round(d["during"] - d["before"], 2)
        col.metric(f"{label} during (vs before)", fmt(d["during"], unit), delta=delta,
                   delta_color="inverse" if key != "throughput_kbps" else "normal", border=True)
    table = pd.DataFrame([{"phase": k, **{c: v[c] for c in ("window_start", "window_end", "sent", "delivered", "lost",
                                                          "loss_pct", "avg_delay_ms", "max_delay_ms", "jitter_ms",
                                                          "throughput_kbps", "reordered")}} for k, v in ph.items()])
    st.dataframe(table, hide_index=True, alt="Monitored-flow metrics per phase")
    if sc.phase_note:
        st.caption(sc.phase_note)
    st.caption("Loss and delay are assigned to a phase by send time; throughput by receive time. "
               "Packets lost because of a failure can therefore appear in the phase in which they were sent.")
    long = table.melt(id_vars="phase", value_vars=["throughput_kbps", "avg_delay_ms", "loss_pct"])
    long["phase"] = pd.Categorical(long["phase"], ["before", "during", "after"])
    chart = alt.Chart(long).mark_bar().encode(
        x=alt.X("phase:N", sort=["before", "during", "after"], title=None),
        y=alt.Y("value:Q", title=None), color=alt.Color("phase:N", legend=None,
                                                        scale=alt.Scale(range=["#0f766e", "#dc2626", "#2563eb"])),
        column=alt.Column("variable:N", title=None), tooltip=["phase", "variable", "value"],
    ).resolve_scale(y="independent").properties(width=180, height=200)
    st.altair_chart(chart, alt="Before, during and after comparison of throughput, delay and loss")
    if "2" in res["phases"]:
        st.markdown("**Competing flow 2**")
        st.dataframe(pd.DataFrame([{"phase": k, **{c: v[c] for c in ("sent", "delivered", "lost", "loss_pct",
                                                                     "avg_delay_ms", "throughput_kbps")}}
                                   for k, v in res["phases"]["2"].items()]), hide_index=True,
                     alt="Competing-flow metrics per phase")

with tabs[2]:
    ts = pd.DataFrame(res["timeseries"])
    tcols = ["throughput_kbps"] + (["cross_throughput_kbps"] if "cross_throughput_kbps" in ts else [])
    tl = ts.melt(id_vars="t", value_vars=tcols, var_name="flow", value_name="kbps")
    tl["flow"] = tl["flow"].map({"throughput_kbps": "flow 1 (monitored)", "cross_throughput_kbps": "flow 2 (competing)"})
    thr = alt.Chart(tl).mark_line(interpolate="step-after").encode(
        x=alt.X("t:Q", title="Simulation time (s)"), y=alt.Y("kbps:Q", title="Throughput (kb/s, 100 ms bins)"),
        color=alt.Color("flow:N", title=None), tooltip=["t", "flow", "kbps"]).properties(height=240)
    st.altair_chart(with_events(thr, sc), alt="Throughput at the destination over time")
    # points, not a line: bins with no delivered packet stay empty instead of being bridged
    dl = alt.Chart(ts.dropna(subset=["avg_delay_ms"])).mark_circle(size=18).encode(
        x=alt.X("t:Q", title="Send time (s)"), y=alt.Y("avg_delay_ms:Q", title="End-to-end delay (ms)"),
        tooltip=["t", "avg_delay_ms", "path"]).properties(height=200)
    lost = alt.Chart(ts[ts["lost"] > 0]).mark_bar(color="#dc2626", opacity=0.6).encode(
        x="t:Q", y=alt.Y("lost:Q", title="Lost packets (by send time)"), tooltip=["t", "lost"]).properties(height=120)
    st.altair_chart(with_events(dl, sc), alt="End-to-end delay over time")
    if (ts["lost"] > 0).any():
        st.altair_chart(with_events(lost, sc), alt="Lost packets over time")
    st.markdown("**Event timeline**")
    st.caption("'configured' entries come from the scenario (Tcl event log); 'trace' entries were observed in "
               "the NS2 trace.")
    st.dataframe(pd.DataFrame(res["timeline"]), hide_index=True, alt="Failure timeline",
                 column_config={"description": st.column_config.TextColumn(width="large")})

with tabs[3]:
    pu = res["path_usage"]
    rows = [{"phase": p, "path": path, "delivered packets": n} for p, d in pu.items() for path, n in d.items()]
    st.markdown("**Paths taken by delivered packets** (reconstructed hop by hop from the trace)")
    st.dataframe(pd.DataFrame(rows), hide_index=True, alt="Path usage per phase")
    st.markdown("**Route changes**")
    if res["route_changes"]:
        st.dataframe(pd.DataFrame([{**{k: v for k, v in c.items() if not isinstance(v, dict)},
                                    "last old-path seq": c["last_packet_old_path"]["seq"],
                                    "first new-path seq": c["first_packet_new_path"]["seq"]}
                                   for c in res["route_changes"]]), hide_index=True, alt="Detected route changes")
    else:
        st.write("None observed.")
    st.markdown("**Delivery gaps at the destination**")
    st.write(pd.DataFrame(res["delivery_gaps"]) if res["delivery_gaps"] else "None longer than the detection threshold.")
    rc = res["routing_control"]
    if rc["total_messages"]:
        st.markdown(f"**Distance-vector routing messages** ({rc['total_messages']} originated)")
        ch = alt.Chart(pd.DataFrame(rc["series"])).mark_bar(color="#7c3aed").encode(
            x=alt.X("t:Q", title="Time (s)"), y=alt.Y("messages:Q", title=f"DV messages per {rc['bin_size']} s"),
            tooltip=["t", "messages"]).properties(height=180)
        st.altair_chart(with_events(ch, sc), alt="Routing protocol messages over time")
    else:
        st.caption("No routing-protocol messages in this run (static routing).")

with tabs[4]:
    if res["queue_stats"]:
        qs = pd.DataFrame([{"link": k, **v} for k, v in res["queue_stats"].items()]).sort_values(
            "max_queue_pkts", ascending=False)
        st.markdown(f"**Queue occupancy** (rebuilt from +/-/d events). Busiest queue: `{res['bottleneck_link']}`")
        st.dataframe(qs, hide_index=True, alt="Maximum queue length per directed link")
        ts = pd.DataFrame(res["timeseries"])
        if "bottleneck_queue_pkts" in ts:
            qc = alt.Chart(ts).mark_area(opacity=0.5, color="#0f766e", interpolate="step-after").encode(
                x=alt.X("t:Q", title="Time (s)"),
                y=alt.Y("bottleneck_queue_pkts:Q", title=f"Queue {res['bottleneck_link']} (max pkts per 100 ms)"),
                tooltip=["t", "bottleneck_queue_pkts"]).properties(height=200)
            st.altair_chart(with_events(qc, sc), alt="Queue length of the busiest link over time")
    st.markdown("**Losses by location and fate**")
    st.dataframe(pd.DataFrame([{"location": k, **v} for k, v in res["drops_by_location"].items()]) if
                 res["drops_by_location"] else pd.DataFrame({"location": ["none"]}),
                 hide_index=True, alt="Packet losses grouped by location")
    with st.expander(f"Every lost packet ({len(res['lost_packets'])})"):
        st.dataframe(pd.DataFrame(res["lost_packets"]), hide_index=True, alt="Lost packet list")
    st.caption("Fates: dropped_queue = 'd' event on a link that was up (DropTail overflow); dropped_link_down = "
               "'d' event on a failed link; lost_at_node / lost_on_link = no 'd' event was written, the location "
               "is the packet's last traced event.")

with tabs[5]:
    run_dir = Path(run_choice)
    st.caption(f"Run directory: {run_dir}")
    st.json(res.get("run", {}), expanded=False)
    for name, mime in [("report.md", "text/markdown"), ("results.json", "application/json"),
                       ("phase_metrics.csv", "text/csv"), ("timeline.csv", "text/csv"),
                       ("timeseries.csv", "text/csv"), ("lost_packets.csv", "text/csv"),
                       ("out.tr", "text/plain"), ("events.log", "text/plain"), ("routeresq.tcl", "text/plain")]:
        p = run_dir / name
        if p.exists():
            st.download_button(f"Download {name}", p.read_bytes(), file_name=f"{sid}_{name}", mime=mime,
                               icon=":material/download:", key=f"dl_{name}")
    with st.expander("Report preview"):
        rp = run_dir / "report.md"
        if rp.exists():
            st.markdown(rp.read_text(encoding="utf-8"))
