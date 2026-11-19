"""RouteResQ - Streamlit entry point.

    streamlit run streamlit_app.py

The workflow rail (Detect -> Diagnose -> Analyse impact -> Observe recovery) is the
navigation; Streamlit's own page menu is hidden.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import streamlit as st

# Streamlit re-executes this script on every run but keeps already-imported project modules.
# After a `git pull` on Streamlit Community Cloud (or an edit while the local server runs) that
# meant ui/*.py changes stayed invisible until the app was rebooted. Before importing anything
# from the project, drop our own packages from sys.modules if any of their files changed since
# they were loaded, so this run imports the current code.
_PROJECT_PACKAGES = ("common", "diagnostics", "failure_analysis", "simulation", "analysis",
                     "communication", "security", "ui", "walkthrough", "netlab")


def _process_start() -> float:
    try:
        return os.stat(f"/proc/{os.getpid()}").st_ctime   # Linux (Streamlit Cloud)
    except OSError:
        return time.time()                                 # elsewhere: first run of this script


def _drop_stale_project_modules() -> None:
    root = Path(__file__).resolve().parent
    loaded: dict = sys.__dict__.setdefault("_routeresq_loaded", {})
    start: float = sys.__dict__.setdefault("_routeresq_started", _process_start())
    ours = {n: m for n, m in list(sys.modules.items())
            if n.split(".")[0] in _PROJECT_PACKAGES and getattr(m, "__file__", None)
            and Path(m.__file__).resolve().is_relative_to(root)}
    stale = False
    for name, mod in ours.items():
        try:
            if Path(mod.__file__).stat().st_mtime > loaded.get(name, start):
                stale = True
                break
        except OSError:
            continue
    if stale:
        now = time.time()
        for name in ours:
            del sys.modules[name]
            loaded[name] = now


_drop_stale_project_modules()

from common.logging_setup import setup_logging  # noqa: E402 - must follow the module refresh
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
    ("impact", "03 · Impact", "NS2 simulation", st.Page("app_pages/impact_page.py", title="NS2 simulation", url_path="simulate")),
    ("recovery", "04 · Recovery", "Recovery", st.Page("app_pages/recovery_page.py", title="Failure & recovery", url_path="recovery")),
    ("upload", "Lab · Link failure", "Upload test", st.Page("app_pages/upload_page.py", title="Upload under link failure", url_path="upload")),
    ("transport", "Lab", "TCP · UDP · TLS", st.Page("app_pages/transport_page.py", title="TCP · UDP · TLS", url_path="transport")),
    ("report", "05 · Report", "Reports", st.Page("app_pages/report_page.py", title="Reports", url_path="reports")),
    ("about", "Start here", "Problem & solution", st.Page("app_pages/about_page.py", title="Problem & solution", url_path="about")),
    ("deck", "Slides", "Presentation", st.Page("app_pages/presentation_page.py", title="Presentation", url_path="presentation")),
    ("demo", "Showcase", "Guided demo", st.Page("app_pages/demo_page.py", title="Guided demo", url_path="demo")),
]
_BY_KEY = {k: p for k, _s, _t, p in PAGES}

current = st.navigation([p for *_r, p in PAGES], position="hidden")
theme.inject()
shell.brand_bar(demo_page=_BY_KEY["demo"], about_page=_BY_KEY["about"], deck_page=_BY_KEY["deck"])
shell.rail([(k, s, t, p) for k, s, t, p in PAGES if k not in ("demo", "about", "deck")], current.title)
current.run()
