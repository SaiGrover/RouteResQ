import pandas as pd
import streamlit as st

from failure_analysis.rules import CATEGORIES
from ui import charts, data
from ui import theme as T
from ui.components import card, card_title, cause_register, chart, e, empty, eyebrow, fmt, page_header, pill, tiles

page_header("Command centre", "Network failure intelligence",
            "One place to see what RouteResQ has measured on the live network, what the NS2 experiments showed "
            "about failure and recovery, and what is still unexplained. Every number below is read from stored "
            "results produced by the backend.", T.SLATE)

recs = data.diag_records()
sims = data.latest_all()
fails = data.latest_comm("failure_demo")
cmp_ = data.latest_comm("tcp_vs_udp")

last = recs[-1] if recs else None
problem_runs = [r for r in recs if r.get("analysis") and any(c != "Healthy / Reachable" for c in r["analysis"]["classifications"])]
b1, b2, c = sims.get("link_failure_dv"), sims.get("link_failure_static"), sims.get("congestion")

tiles([
    ("Last live check", e(last["run"]["target"]) if last else "none", (", ".join(last["analysis"]["classifications"]) if last and last.get("analysis") else "run a diagnostic"), T.SIGNAL),
    ("Live checks recorded", f"{len(recs)}", f"{len(problem_runs)} with a detected problem", T.AMBER if problem_runs else T.GREEN),
    ("NS2 scenarios analysed", f"{len(sims)}<small>/4</small>", "real ns-2.35 traces", T.SAND),
    ("DV reroute (B1)", (fmt(b1["findings"]["recovery"]["time_to_recovery_s"] * 1000, "", 1) + "<small>ms</small>")
     if b1 and b1["findings"]["recovery"].get("time_to_recovery_s") is not None else "n/a",
     "first delivery on the alternative path", T.STEEL),
    ("Static-route outage (B2)", (fmt(max((g["duration_s"] for g in b2["delivery_gaps"]), default=0.0), "", 2) + "<small>s</small>") if b2 else "n/a",
     "no packets reached n5", T.CLAY),
    ("Transport failures recovered", f"{sum(r['resumed'] for r in fails['records'])}<small>/{len(fails['records'])}</small>" if fails else "n/a",
     "after restoring the condition", T.GREEN),
])

eyebrow("Root causes identified", "the cause of every detected failure and how certain it is", T.AMBER)
cause_register(data.cause_rows(), show_healthy=False)
st.page_link("app_pages/report_page.py", label="Full root-cause report with evidence", icon=":material/description:")

left, right = st.columns([1.55, 1], gap="medium")
with left:
    eyebrow("Failure lifecycle at a glance", "NS2 · flow 1 throughput in every scenario", T.CLAY)
    if sims:
        chart(charts.overlay_throughput(list(sims.values()), h=330),
              what="Throughput received at n5 in 100 ms bins for each stored scenario. The shaded band is the "
                   "3-6 s window in which the link failure or the extra load is applied.",
              why="Scenario B2 (static routing) drops to zero for the whole failure, B1 (distance-vector) barely "
                  "moves because traffic is rerouted, and C loses throughput to the competing flow.")
    else:
        empty("No NS2 results yet", "Open <b>NS2 simulation</b> and run the scenarios.")
with right:
    eyebrow("Recovery verdicts", "from trace evidence", T.GREEN)
    for sid, sc in data.scenarios().items():
        r = sims.get(sid)
        with card("verdict"):
            col = T.SCENARIO_COLOR[sid]
            outcome = r["findings"]["recovery"]["outcome"] if r else "not run yet"
            st.html(f'<div style="display:flex;justify-content:space-between;align-items:center;gap:.6rem">'
                    f'<div><div class="rr-ctitle">{e(sc.label)} · {e(sc.name.split(" - ", 1)[-1])}</div>'
                    f'<div class="rr-csub">{e(outcome)}</div></div>'
                    f'{pill(sc.routing, col)}</div>')

eyebrow("Live network", "most recent diagnostic runs", T.SIGNAL)
if recs:
    rows = []
    for r in reversed(recs[-8:]):
        p = r["run"].get("ping") or {}
        rows.append({"time (UTC)": r["run"]["timestamp"].replace("T", " ")[:19], "destination": r["run"]["target"],
                     "replies": f"{p.get('received', 0)}/{p.get('sent', 0)}", "loss %": p.get("loss_pct"),
                     "avg RTT ms": p.get("avg_ms"), "classification": ", ".join((r.get("analysis") or {}).get("classifications", []))})
    c1, c2 = st.columns([1.6, 1], gap="medium")
    with c1, card("recent"):
        card_title("Recent checks", "live measurements from this server")
        st.dataframe(pd.DataFrame(rows), hide_index=True, alt="Recent live diagnostic runs",
                     column_config={"loss %": st.column_config.ProgressColumn("loss %", min_value=0, max_value=100, format="%.0f%%")})
    with c2, card("cats"):
        card_title("Detected conditions", "how often each classification occurred")
        counts = {k: 0 for k in CATEGORIES}
        for r in recs:
            for k in (r.get("analysis") or {}).get("classifications", []):
                counts[k] = counts.get(k, 0) + 1
        st.html("".join(
            f'<div style="display:flex;justify-content:space-between;align-items:center;margin:.28rem 0">'
            f'{pill(k, T.CATEGORY_COLOR[k])}<span style="font-family:JetBrains Mono;color:{T.MUT};font-size:.8rem">{v}</span></div>'
            for k, v in counts.items() if v))
else:
    empty("No live checks yet", "Open <b>Diagnostics</b> to measure a destination, or start the <b>Guided demo</b>.")

eyebrow("Where to go next", "", T.SLATE)
q = st.columns(4, gap="small")
links = [("app_pages/demo_page.py", "Run the guided demo", ":material/play_circle:", "Every module, end to end, with real measurements."),
         ("app_pages/detect_page.py", "Diagnose a destination", ":material/troubleshoot:", "Ping, traceroute, DNS and TCP checks."),
         ("app_pages/recovery_page.py", "Compare failure scenarios", ":material/healing:", "Before, during and after each injected fault."),
         ("app_pages/transport_page.py", "Test TCP, UDP and TLS", ":material/lock:", "Transfers, integrity checks, failure drills.")]
for col, (pth, label, icon, sub) in zip(q, links):
    with col, card("link"):
        st.page_link(pth, label=label, icon=icon)
        st.caption(sub)
