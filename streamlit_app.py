"""RouteResQ - Streamlit entry point.

    streamlit run streamlit_app.py

The workflow rail (Detect -> Diagnose -> Analyse impact -> Observe recovery) is the
navigation; Streamlit's own page menu is hidden.
"""
from __future__ import annotations

import streamlit as st

from common.logging_setup import setup_logging
from common.paths import ensure_dirs
from ui import shell, theme

ensure_dirs()
setup_logging()

st.set_page_config(page_title="RouteResQ", page_icon=":material/hub:", layout="wide",
                   initial_sidebar_state="collapsed")

PAGES = [
    ("overview", "Command", "Overview", st.Page("app_pages/overview_page.py", title="Overview", default=True, url_path="overview")),
    ("detect", "01 · Detect", "Diagnostics", st.Page("app_pages/detect_page.py", title="Diagnostics", url_path="detect")),
    ("diagnose", "02 · Diagnose", "Root cause", st.Page("app_pages/diagnose_page.py", title="Root cause", url_path="diagnose")),
    ("impact", "03 · Analyse impact", "NS2 simulation", st.Page("app_pages/impact_page.py", title="NS2 simulation", url_path="simulate")),
    ("recovery", "04 · Observe recovery", "Recovery", st.Page("app_pages/recovery_page.py", title="Failure & recovery", url_path="recovery")),
    ("transport", "Lab · transport", "TCP · UDP · TLS", st.Page("app_pages/transport_page.py", title="TCP · UDP · TLS", url_path="transport")),
    ("report", "05 · Report", "Reports", st.Page("app_pages/report_page.py", title="Reports", url_path="reports")),
    ("demo", "Showcase", "Guided demo", st.Page("app_pages/demo_page.py", title="Guided demo", url_path="demo")),
]

current = st.navigation([p for *_r, p in PAGES], position="hidden")
theme.inject()
shell.brand_bar(demo_page=PAGES[-1][3])
shell.rail([(k, s, t, p) for k, s, t, p in PAGES if k != "demo"], current.title)
current.run()
