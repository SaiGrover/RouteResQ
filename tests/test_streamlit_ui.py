"""Headless Streamlit tests (AppTest): every page and view renders through the real entry point."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

pytestmark = pytest.mark.ui
ROOT = Path(__file__).resolve().parent.parent
PAGES = ["detect", "diagnose", "impact", "recovery", "upload", "transport", "report", "demo", "about", "presentation"]


@pytest.fixture()
def app() -> AppTest:
    at = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=180).run()
    assert not at.exception, [e.message for e in at.exception]
    return at


def go(at: AppTest, page: str) -> AppTest:
    at.switch_page(f"app_pages/{page}_page.py").run()
    assert not at.exception, (page, [e.message for e in at.exception])
    return at


def test_overview_renders_with_rail_and_brand(app):
    # rail nodes are page links (client-side navigation, no rerun of the page being left)
    labels = {el.proto.label for el in app.get("page_link")}
    assert {"Overview", "Diagnostics", "Root cause", "NS2 simulation", "Recovery", "Upload test", "TCP · UDP · TLS",
            "Reports", "Guided demo", "Problem & solution", "Presentation"} <= labels


@pytest.mark.parametrize("page", PAGES)
def test_every_page_renders(app, page):
    go(app, page)


def test_simulation_scenarios_and_phases(app):
    at = go(app, "impact")
    for sid in ["healthy", "link_failure_static", "congestion", "link_failure_dv"]:
        at.segmented_control(key="sim_sid").set_value(sid).run()
        for phase in ["before", "after", "during"]:
            at.segmented_control(key="topo_phase").set_value(phase).run()
        assert not at.exception, (sid, [e.message for e in at.exception])


def test_recovery_scenarios_and_metrics(app):
    at = go(app, "recovery")
    for sid in ["link_failure_static", "congestion", "link_failure_dv"]:
        at.segmented_control(key="rec_sid").set_value(sid).run()
        for m in ["avg_delay_ms", "loss_pct"]:
            at.segmented_control(key="cmp_metric").set_value(m).run()
        assert not at.exception, (sid, [e.message for e in at.exception])


def test_transport_and_report_views(app):
    at = go(app, "transport")
    for v in ["TCP vs UDP", "Secure transfer", "Failure drills", "Connection"]:
        at.segmented_control(key="tr_view").set_value(v).run()
        assert not at.exception, v
    at = go(at, "report")
    for v in ["Experiment history", "Files & export", "Log", "Reports"]:
        at.segmented_control(key="rep_view").set_value(v).run()
        assert not at.exception, v


def test_tcp_send_uses_real_sockets(app):
    at = go(app, "transport")
    at.button(key="FormSubmitter:tcp_form-Send over TCP").click().run()
    assert not at.exception
    assert "tcp_demo" in at.session_state and at.session_state["tcp_demo"][0].ok


def test_authorisation_guard_on_add_destination(app):
    at = go(app, "detect")
    form_inputs = [t for t in at.text_input if t.label == "Add a destination"]
    form_inputs[0].set_value("evil.example.org")
    at.button(key="FormSubmitter:add_host-Add").click().run()
    assert not at.exception
    assert any("Confirm that you are authorised" in e.value for e in at.error)


def test_demo_transport_step_runs_real_backend(app):
    """Step 5 of the guided demo, with the real TCP/UDP, TLS and failure-drill code."""
    from walkthrough import flow

    at = go(app, "demo")
    state = flow.new_state()
    state["step"] = 4
    at.session_state["wt"] = state
    at.run()
    next(b for b in at.button if b.label == "Run transport experiments").click().run()
    assert not at.exception, [e.message for e in at.exception]
    t = at.session_state["wt"]["transport"]
    assert t["status"] == flow.SUCCESS, {k: v["verified"] or v["error"] for k, v in t["parts"].items()}


def test_upload_page_shows_the_three_runs(app):
    """The upload page renders the stored three-run comparison and its plain-language verdicts."""
    at = go(app, "upload")
    text = " ".join(m.value for m in at.markdown) + " ".join(getattr(c, "value", "") for c in at.caption)
    assert at.dataframe, "comparison table missing"
    assert "Healthy baseline" in str(at.dataframe[0].value)


def test_demo_upload_step_without_backend_uses_labelled_recording(app, monkeypatch):
    """With no test-network backend the demo shows the recorded run and marks the stage 'stored'."""
    from walkthrough import flow

    at = go(app, "demo")
    state = flow.new_state()
    state["step"] = [k for k, _ in flow.STEPS].index("upload")
    at.session_state["wt"] = state
    at.run()
    flow.run_upload(at.session_state["wt"], {"available": False, "reason": "test"})
    at.run()
    assert not at.exception, [e.message for e in at.exception]
    assert at.session_state["wt"]["upload"]["status"] == flow.STORED
