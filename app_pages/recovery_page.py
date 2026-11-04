import pandas as pd
import streamlit as st

from analysis.comparison import compare
from analysis.report import comparison_report
from ui import charts, data
from ui import theme as T
from ui.components import (badge_row, card, card_title, chart, e, empty, eyebrow, fmt, method, page_header, tiles,
                           timeline, verdict)

SC = data.scenarios()
sims = data.latest_all()

page_header("Stage 04 · Observe recovery", "Failure & recovery analysis",
            "When did the failure happen, which connection did it hit, how did traffic behave, was it rerouted, "
            "and did service recover? Every answer is backed by events in the NS2 trace; rerouting and recovery "
            "are only claimed when the trace shows them.", T.GREEN)
badge_row("sim")

if not sims:
    empty("No NS2 results yet", "Run the scenarios on the <b>NS2 simulation</b> page first.")
    st.stop()

event_ids = [s for s in ("link_failure_dv", "link_failure_static", "congestion") if s in sims]
labels = {s: f"{SC[s].label} · {SC[s].name.split(' - ', 1)[-1]}" for s in event_ids}
st.session_state.setdefault("rec_sid", event_ids[0] if event_ids else None)
if not event_ids:
    empty("No failure scenario stored", "Run B1, B2 or C on the NS2 simulation page.")
    st.stop()
sid = st.segmented_control("Failure scenario", event_ids, format_func=labels.get, key="rec_sid", required=True)
res, sc = sims[sid], SC[sid]
f = res["findings"]
rec = f["recovery"]
outcome = rec["outcome"]
oc = T.GREEN if outcome.startswith(("rerouted", "recovered")) else T.AMBER if outcome.startswith(("interrupted", "partially")) else T.CLAY
verdict("Recovery outcome", outcome, oc)

ph = res["phases"]["1"]
deg = f["performance_degradation"]
gap = max((g["duration_s"] for g in res["delivery_gaps"]), default=0.0)
t_rec = rec.get("time_to_recovery_s")
tiles([
    ("Event time", f"{fmt(f.get('failure_time'), '', 1)}<small>s</small>", "from the scenario configuration", T.CLAY),
    ("Affected", e(f.get("affected_link") or "-"), f["failure_type"], T.CLAY),
    ("Time to recovery", (f"{t_rec * 1000:,.1f}<small>ms</small>" if t_rec is not None and t_rec < 1 else f"{fmt(t_rec, '', 3)}<small>s</small>")
     if t_rec is not None else "n/a", "first delivery after the event" if sc.has_failure else "queue drained after load stopped", oc),
    ("Delivery gap", f"{fmt(gap, '', 3)}<small>s</small>", "longest period with no arrivals", T.CLAY if gap else T.GREEN),
    ("Loss during event", f"{fmt(ph['during']['loss_pct'])}<small>%</small>", f"{ph['during']['lost']} of {ph['during']['sent']} sent", T.CLAY if ph["during"]["lost"] else T.GREEN),
    ("Rerouting", "observed" if f.get("route_changes") else "none", f"{f.get('route_changes', 0)} path change(s) in trace", T.STEEL if f.get("route_changes") else T.SLATE),
])

# ------------------------------------------------------------------ five questions
q = st.columns(3, gap="medium")
with q[0], card("q1"):
    card_title("What failed?")
    st.write(f["what_failed"])
    card_title("Why?")
    st.markdown(f["why"])
with q[1], card("q2"):
    card_title("What happened next?")
    for x in f["observed_impact"]:
        st.markdown(f"- {x}")
with q[2], card("q3"):
    card_title("Was recovery observed?")
    for x in rec.get("evidence", []):
        st.markdown(f"- {x}")
    st.html(f'<div class="rr-csub" style="margin-top:.4rem">{e(f["routing_behavior"])}</div>')

# ------------------------------------------------------------------ before / during / after topology
eyebrow("Traffic paths before, during and after", "edge width = delivered packets that used the link (from the trace)", T.STEEL)
tc = st.columns(3, gap="small")
for col, phase in zip(tc, ["before", "during", "after"]):
    with col, card(f"tp_{phase}"):
        w0, w1 = res["phases"]["1"][phase]["window_start"], res["phases"]["1"][phase]["window_end"]
        card_title(phase.capitalize(), f"{w0:g}-{w1:g} s · {ph[phase]['delivered']}/{ph[phase]['sent']} delivered")
        st.plotly_chart(charts.topology(sc.to_dict(), res, phase, h=220, labels=False), width="stretch", config={"displayModeBar": False},
                        key=f"topo_{phase}")

c1, c2 = st.columns([1.5, 1], gap="medium")
with c1:
    chart(charts.throughput(res), "Throughput through the event", "flow 1 at n5, 100 ms bins",
          what="The dotted red line is the configured event, the green line its end.",
          why="Shows interruption, degradation and recovery as they unfolded.")
    chart(charts.phases(res), "Before · during · after", "same windows in every scenario",
          what="Loss and delay by send time, throughput by receive time.",
          why="Quantifies how much performance changed and whether it returned to the before level.")
with c2, card("tl"):
    card_title("Event timeline", "configured events (sand) merged with trace observations (blue)")
    timeline(res["timeline"])

with st.expander("Route changes, delivery gaps and degradation table"):
    a, b = st.columns(2)
    a.dataframe(pd.DataFrame([{k: v for k, v in c.items() if not isinstance(v, dict)} for c in res["route_changes"]])
                if res["route_changes"] else pd.DataFrame({"route changes": ["none observed"]}), hide_index=True, alt="Route changes")
    b.dataframe(pd.DataFrame(res["delivery_gaps"]) if res["delivery_gaps"] else pd.DataFrame({"delivery gaps": ["none"]}),
                hide_index=True, alt="Delivery gaps")
    st.dataframe(pd.DataFrame([{"metric": k, **v} for k, v in deg.items()]), hide_index=True, alt="Degradation per metric")

cc = st.columns(2, gap="medium")
with cc[0], card("can"):
    card_title("Can be concluded")
    for x in f.get("can_conclude", []):
        st.markdown(f"- {x}")
with cc[1], card("cannot"):
    card_title("Cannot be concluded")
    for x in f.get("cannot_conclude", []):
        st.markdown(f"- {x}")
st.html(f'<div class="rr-card"><h4>Technical explanation</h4><div class="sub">{e(f["explanation"])}</div></div>')

# ------------------------------------------------------------------ cross-scenario
eyebrow("Scenario comparison", "healthy vs link failure (DV / static) vs congestion", T.SAND)
rows = compare(list(sims.values()))
k1, k2 = st.columns([1.3, 1], gap="medium")
with k1:
    chart(charts.overlay_throughput(list(sims.values())), "Flow 1 throughput in every scenario",
          what="All scenarios share the same 3-6 s event window, so the curves line up.",
          why="One picture of the difference routing makes: DV keeps delivering, static stops, congestion degrades.")
with k2, card("metric"):
    metric = st.segmented_control("Metric", ["throughput_kbps", "avg_delay_ms", "loss_pct"], default="throughput_kbps",
                                  format_func={"throughput_kbps": "Throughput", "avg_delay_ms": "Delay", "loss_pct": "Loss"}.get,
                                  required=True, key="cmp_metric")
    unit = {"throughput_kbps": "kb/s", "avg_delay_ms": "ms", "loss_pct": "%"}[metric]
    st.plotly_chart(charts.scenario_compare(list(sims.values()), metric, f"{metric.split('_')[0]} ({unit})", h=300),
                    width="stretch", config={"displayModeBar": False})
with card("table"):
    card_title("Comparison table", "from the newest stored run of each scenario")
    st.dataframe(pd.DataFrame(rows), hide_index=True, alt="Scenario comparison",
                 column_order=["label", "routing", "sent", "delivered", "loss_pct", "avg_delay_ms", "max_delay_ms",
                               "throughput_kbps", "during_throughput_kbps", "route_changes", "longest_delivery_gap_s",
                               "max_queue_pkts", "throughput_vs_baseline_pct", "recovery_outcome"],
                 column_config={"recovery_outcome": st.column_config.TextColumn("recovery", width="large")})
    d1, d2, _ = st.columns([1, 1, 2])
    d1.download_button("Comparison CSV", pd.DataFrame(rows).to_csv(index=False).encode(), "scenario_comparison.csv",
                       "text/csv", icon=":material/download:", width="stretch")
    d2.download_button("Comparison report", comparison_report(rows).encode(), "scenario_comparison.md", "text/markdown",
                       icon=":material/description:", width="stretch")

method([
    ("Locate the event", "Configured times come from the Tcl event log; the trace's <code>v link-down/up</code> lines confirm them."),
    ("Follow every packet", "Each delivered packet's hop list gives its path; consecutive packets switching path for at "
     "least three packets is a route change."),
    ("Measure the outage", "Gaps in arrivals longer than max(5 × packet interval, 50 ms) are delivery interruptions."),
    ("Decide recovery from evidence", "Rerouted only if packets sent during the failure arrived on a path avoiding the "
     "failed link; recovered (congestion) only if packets sent after the queue drained show baseline loss and delay."),
], "analysis.experiment", [("results.json × scenarios", f"{len(sims)} stored")],
   [("comparison", f"{len(rows)} rows"), ("timeline", f"{len(res['timeline'])} events")], T.GREEN, "recovery is never assumed")
