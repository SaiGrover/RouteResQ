import io
import zipfile
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from common.logging_setup import LOG_FILE
from common.paths import PROJECT_ROOT, RESULTS_DIR
from diagnostics.history import DiagnosticHistory

st.title("Results, logs & export")
st.caption("Everything RouteResQ produces is stored as JSON, CSV, Markdown or raw NS2 trace files under "
           "results/ and reports/. No database is used.")

SKIP = {"certs"}
files = sorted(
    (p for p in RESULTS_DIR.rglob("*") if p.is_file() and not (set(p.relative_to(RESULTS_DIR).parts) & SKIP)),
    key=lambda p: p.stat().st_mtime, reverse=True,
)
reports = sorted((PROJECT_ROOT / "reports").glob("*.md")) if (PROJECT_ROOT / "reports").exists() else []

c1, c2, c3 = st.columns(3)
c1.metric("Result files", len(files), border=True)
c2.metric("Diagnostic runs", len(DiagnosticHistory().records()), border=True)
c3.metric("Reports", len(reports), border=True)

area = st.segmented_control("Area", ["Files", "Reports", "Log"], default="Files", required=True,
                            label_visibility="collapsed")

if area == "Files":
    df = pd.DataFrame([{"file": str(p.relative_to(RESULTS_DIR)), "kB": round(p.stat().st_size / 1024, 1),
                        "modified": datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")}
                       for p in files])
    if df.empty:
        st.info("No results yet.")
    else:
        flt = st.text_input("Filter", placeholder="e.g. congestion, .csv, history")
        view = df[df["file"].str.contains(flt, case=False, regex=False)] if flt else df
        st.dataframe(view, hide_index=True, alt="Stored result files")
        pick = st.selectbox("Download a file", view["file"].tolist())
        if pick:
            p = RESULTS_DIR / pick
            st.download_button(f"Download {p.name}", p.read_bytes(), file_name=p.name, icon=":material/download:")
        if st.button("Build ZIP of all results and reports", icon=":material/folder_zip:"):
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                for p in files:
                    z.write(p, Path("results") / p.relative_to(RESULTS_DIR))
                for p in reports:
                    z.write(p, Path("reports") / p.name)
            st.download_button("Download routeresq_results.zip", buf.getvalue(), "routeresq_results.zip",
                               "application/zip", icon=":material/download:")

elif area == "Reports":
    if not reports:
        st.info("No reports yet. Run 'python -m simulation.experiments' or the simulation page.")
    else:
        pick = st.selectbox("Report", reports, format_func=lambda p: p.name)
        st.download_button("Download", pick.read_bytes(), pick.name, "text/markdown", icon=":material/download:")
        with st.container(border=True):
            st.markdown(pick.read_text(encoding="utf-8"))

else:
    if LOG_FILE.exists():
        lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
        n = st.slider("Show last N lines", 50, 2000, 300, step=50)
        st.code("\n".join(lines[-n:]), language=None)
        st.download_button("Download log", LOG_FILE.read_bytes(), "routeresq.log", icon=":material/download:")
    else:
        st.info("No log file yet.")
