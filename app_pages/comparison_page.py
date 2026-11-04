import altair as alt
import pandas as pd
import streamlit as st

from analysis.comparison import compare, save_comparison
from analysis.report import comparison_report
from common.paths import SIM_RESULTS_DIR
from simulation.experiments import latest_result
from simulation.scenario import load_all_scenarios
from ui.components import sim_badge

st.title("Scenario comparison")
sim_badge()
st.caption("Healthy baseline vs link failure (DV and static routing) vs congestion, using the newest stored "
           "NS2 run of each scenario.")

scenarios = load_all_scenarios()
results = [r for r in (latest_result(s) for s in scenarios) if r]
missing = [s for s in scenarios if latest_result(s) is None]
if missing:
    st.warning(f"No stored run yet for: {', '.join(missing)}. Run them on the Failure simulation page.")
if not results:
    st.stop()

rows = compare(results)
df = pd.DataFrame(rows)
st.dataframe(
    df, hide_index=True, alt="Comparison of NS2 scenarios",
    column_order=["label", "scenario", "routing", "sent", "delivered", "loss_pct", "avg_delay_ms", "max_delay_ms",
                  "throughput_kbps", "during_throughput_kbps", "during_loss_pct", "route_changes",
                  "longest_delivery_gap_s", "max_queue_pkts", "throughput_vs_baseline_pct",
                  "delay_vs_baseline_pct", "recovery_outcome"],
    column_config={"recovery_outcome": st.column_config.TextColumn("recovery", width="large")},
)

phase_rows = []
for r in results:
    for ph, m in r["phases"]["1"].items():
        phase_rows.append({"scenario": f"{r['scenario']['label']} {r['scenario']['id']}", "phase": ph,
                           "throughput_kbps": m["throughput_kbps"], "avg_delay_ms": m["avg_delay_ms"],
                           "loss_pct": m["loss_pct"]})
pdf = pd.DataFrame(phase_rows)
metric = st.segmented_control("Metric", ["throughput_kbps", "avg_delay_ms", "loss_pct"], default="throughput_kbps",
                              format_func={"throughput_kbps": "Throughput (kb/s)", "avg_delay_ms": "Avg delay (ms)",
                                           "loss_pct": "Loss (%)"}.get, required=True)
chart = alt.Chart(pdf).mark_bar().encode(
    x=alt.X("phase:N", sort=["before", "during", "after"], title=None),
    xOffset=alt.XOffset("scenario:N"),
    y=alt.Y(f"{metric}:Q", title=metric),
    color=alt.Color("scenario:N", title="Scenario"),
    tooltip=["scenario", "phase", metric],
).properties(height=300)
st.altair_chart(chart, alt="Per-phase metric across scenarios")
st.caption("Monitored flow 1 only. Phase windows: before 1-3 s, during 3-6 s, after 6-9 s in every scenario.")

with st.container(horizontal=True):
    if st.button("Save comparison (CSV + JSON)", icon=":material/save:"):
        paths = save_comparison(rows, SIM_RESULTS_DIR)
        st.success(f"Saved {paths['csv']} and {paths['json']}")
    st.download_button("Download comparison CSV", df.to_csv(index=False).encode(), "scenario_comparison.csv",
                       "text/csv", icon=":material/download:")
    st.download_button("Download comparison report (Markdown)", comparison_report(rows).encode(),
                       "scenario_comparison.md", "text/markdown", icon=":material/description:")

st.subheader("What the comparison shows")
for r in results:
    f = r["findings"]
    with st.expander(f"{r['scenario']['label']}  {r['scenario']['name']}"):
        st.write(f["explanation"])
        st.markdown(f"**Recovery:** {f['recovery']['outcome']}")
