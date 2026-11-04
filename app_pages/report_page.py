import io
import zipfile
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from common.logging_setup import LOG_FILE
from common.paths import COMM_RESULTS_DIR, PROJECT_ROOT, RESULTS_DIR
from diagnostics.history import summary_row
from ui import data
from ui import theme as T
from ui.components import card, card_title, empty, eyebrow, page_header, tiles

page_header("Stage 05 · Report", "Reports & experiment history",
            "Every experiment is stored as JSON, CSV, Markdown or raw NS2 trace. Nothing here is typed in by hand: "
            "the reports are generated from the same results the other pages display.", T.SAND)

recs = data.diag_records()
sims = data.latest_all()
reps = data.reports()
files = sorted((p for p in RESULTS_DIR.rglob("*") if p.is_file() and "certs" not in p.relative_to(RESULTS_DIR).parts),
               key=lambda p: p.stat().st_mtime, reverse=True)
comm = sorted(COMM_RESULTS_DIR.glob("*.json")) if COMM_RESULTS_DIR.exists() else []
sim_runs = sum(len(data.runs(s)) for s in data.scenarios())
tiles([("Reports", f"{len(reps)}", "Markdown, generated", T.SAND),
       ("Live diagnostic runs", f"{len(recs)}", "history.jsonl", T.SIGNAL),
       ("NS2 runs stored", f"{sim_runs}", f"{len(sims)} scenarios with results", T.CLAY),
       ("Transport experiments", f"{len(comm)}", "TCP/UDP and failure drills", T.STEEL),
       ("Result files", f"{len(files)}", f"{sum(p.stat().st_size for p in files) / 1048576:.1f} MB on disk", T.SLATE)])

view = st.segmented_control("View", ["Reports", "Experiment history", "Files & export", "Log"], default="Reports",
                            required=True, label_visibility="collapsed", key="rep_view")

if view == "Reports":
    if not reps:
        empty("No reports yet", "Run <code>python -m simulation.experiments</code> or the NS2 page to generate them.")
    else:
        left, right = st.columns([1, 3], gap="medium")
        with left, card("replist"):
            card_title("Reports", "generated from stored results")
            pick = st.radio("Report", reps, format_func=lambda p: p.stem.replace("_", " "), label_visibility="collapsed")
            st.download_button("Download .md", pick.read_bytes(), pick.name, "text/markdown", icon=":material/download:", width="stretch")
            st.caption(f"Modified {datetime.fromtimestamp(pick.stat().st_mtime):%Y-%m-%d %H:%M}")
        with right, card("repview"):
            st.markdown(pick.read_text(encoding="utf-8"))

elif view == "Experiment history":
    eyebrow("Live diagnostics", f"{len(recs)} runs", T.SIGNAL)
    if recs:
        df = pd.DataFrame([summary_row(r["run"], r.get("analysis")) for r in reversed(recs)])
        st.dataframe(df, hide_index=True, alt="Diagnostic history",
                     column_config={"loss_pct": st.column_config.ProgressColumn("loss %", min_value=0, max_value=100, format="%.0f%%")})
        st.download_button("Download CSV", df.to_csv(index=False).encode(), "diagnostic_history.csv", "text/csv", icon=":material/download:")
    else:
        empty("No live runs", "Use the Diagnostics page.")
    eyebrow("NS2 runs", f"{sim_runs} stored", T.CLAY)
    rows = []
    for sid in data.scenarios():
        for rd in data.runs(sid):
            r = data.result_at(rd)
            s = r["flows"]["1"]["summary"]
            rows.append({"scenario": sid, "run": rd.name, "started (UTC)": r["run"].get("started_at", ""),
                         "backend": r["run"].get("backend"), "delivered": s["delivered"], "sent": s["sent"],
                         "loss %": s["loss_pct"], "avg delay ms": s["avg_delay_ms"],
                         "outcome": r["findings"]["recovery"]["outcome"]})
    st.dataframe(pd.DataFrame(rows), hide_index=True, alt="NS2 run history",
                 column_config={"outcome": st.column_config.TextColumn(width="large")})
    eyebrow("Transport experiments", f"{len(comm)} files", T.STEEL)
    st.dataframe(pd.DataFrame([{"file": p.name, "kB": round(p.stat().st_size / 1024, 1),
                                "modified": datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")}
                               for p in sorted(comm, reverse=True)]) if comm else pd.DataFrame({"file": ["none yet"]}),
                 hide_index=True, alt="Transport experiment files")

elif view == "Files & export":
    df = pd.DataFrame([{"file": str(p.relative_to(RESULTS_DIR)), "kB": round(p.stat().st_size / 1024, 1),
                        "modified": datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")} for p in files])
    if df.empty:
        empty("No result files", "Run an experiment first.")
    else:
        flt = st.text_input("Filter", placeholder="e.g. congestion, .csv, history")
        view_df = df[df["file"].str.contains(flt, case=False, regex=False)] if flt else df
        st.dataframe(view_df, hide_index=True, alt="Stored result files", height=360)
        c1, c2 = st.columns([2, 1], vertical_alignment="bottom")
        pick = c1.selectbox("Download one file", view_df["file"].tolist())
        if pick:
            c2.download_button(f"Download {Path(pick).name}", (RESULTS_DIR / pick).read_bytes(), Path(pick).name,
                               icon=":material/download:", width="stretch")
        if st.button("Build ZIP of all results and reports", icon=":material/folder_zip:"):
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                for p in files:
                    z.write(p, Path("results") / p.relative_to(RESULTS_DIR))
                for p in reps:
                    z.write(p, Path("reports") / p.name)
            st.download_button("Download routeresq_results.zip", buf.getvalue(), "routeresq_results.zip", "application/zip",
                               icon=":material/download:", type="primary")

else:
    if LOG_FILE.exists():
        lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
        n = st.slider("Last N lines", 50, 2000, 300, step=50)
        st.code("\n".join(lines[-n:]), language=None)
        st.download_button("Download log", LOG_FILE.read_bytes(), "routeresq.log", icon=":material/download:")
    else:
        empty("No log yet", f"Logs are written to <code>{LOG_FILE.relative_to(PROJECT_ROOT)}</code>.")
