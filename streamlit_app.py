"""RouteResQ - Streamlit entry point.

    streamlit run streamlit_app.py
"""
from __future__ import annotations

import streamlit as st

from common.logging_setup import setup_logging
from common.paths import ensure_dirs

ensure_dirs()
setup_logging()

st.set_page_config(page_title="RouteResQ", page_icon=":material/network_check:", layout="wide")

pages = {
    "RouteResQ": [
        st.Page("app_pages/overview_page.py", title="Overview", icon=":material/home:", default=True),
    ],
    "Live network": [
        st.Page("app_pages/diagnostics_page.py", title="Diagnostics & root cause", icon=":material/troubleshoot:"),
        st.Page("app_pages/communication_page.py", title="TCP / UDP / TLS", icon=":material/swap_horiz:"),
    ],
    "NS2 simulation": [
        st.Page("app_pages/simulation_page.py", title="Failure simulation", icon=":material/hub:"),
        st.Page("app_pages/comparison_page.py", title="Scenario comparison", icon=":material/compare_arrows:"),
    ],
    "Records": [
        st.Page("app_pages/results_page.py", title="Results, logs & export", icon=":material/folder_open:"),
    ],
}
st.navigation(pages).run()
