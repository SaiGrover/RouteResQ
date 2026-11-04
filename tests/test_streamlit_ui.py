"""Headless Streamlit smoke tests (AppTest) - every page renders without exceptions."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

pytestmark = pytest.mark.ui
ROOT = Path(__file__).resolve().parent.parent


def run(path: str) -> AppTest:
    return AppTest.from_file(str(ROOT / path), default_timeout=120).run()


def test_entry_point_renders_overview():
    at = run("streamlit_app.py")
    assert not at.exception
    assert at.title[0].value == "RouteResQ"


@pytest.mark.parametrize("page", ["diagnostics_page", "simulation_page", "comparison_page",
                                  "communication_page", "results_page"])
def test_pages_render(page):
    at = run(f"app_pages/{page}.py")
    assert not at.exception, [e.message for e in at.exception]


def test_simulation_page_all_scenarios():
    at = run("app_pages/simulation_page.py")
    for sid in ["healthy", "link_failure_dv", "link_failure_static", "congestion"]:
        at.segmented_control(key="sim_scenario").set_value(sid).run()
        assert not at.exception, (sid, [e.message for e in at.exception])


def test_diagnostics_views_and_authorisation_guard():
    at = run("app_pages/diagnostics_page.py")
    for view in ["History & comparison", "Run diagnostics", "Authorised destinations"]:
        at.segmented_control(key="diag_mode").set_value(view).run()
        assert not at.exception
    # adding a destination without confirming authorisation must be refused
    at.text_input[0].set_value("evil.example.org")
    at.button[0].click().run()
    assert not at.exception
    assert at.error and "Confirm that you are authorised" in at.error[0].value


def test_communication_tcp_send():
    at = run("app_pages/communication_page.py")
    at.button[0].click().run()
    assert not at.exception
