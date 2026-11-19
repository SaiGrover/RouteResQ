import streamlit as st

from ui import data
from ui import theme as T
from ui.components import card, card_title, e, eyebrow, page_header

page_header("Start here", "The problem, and what RouteResQ does about it",
            "One page for a first-time visitor: why network failures are hard to explain, and how this project "
            "answers it with evidence instead of guesses.", T.SIGNAL)


def block(title: str, body: str, color: str) -> str:
    return (f'<div class="rr-note" style="--c:{color};margin-bottom:.6rem;font-size:.95rem;line-height:1.55">'
            f'<b>{e(title)}</b><br>{body}</div>')


left, right = st.columns(2, gap="large")
with left, card("about_problem"):
    card_title("The problem", "a symptom is not a cause")
    st.html(
        block("“The website is not opening.”",
              "That one sentence has many possible causes: the name did not resolve (DNS), the server is down, a "
              "link broke, the network is congested, the port is closed, or the certificate is wrong.", T.CLAY)
        + block("Everyday tools only show the symptom",
                "<code>ping</code> and <code>traceroute</code> say “no reply”. Many devices ignore ping on purpose, so "
                "even that can mislead. People end up guessing a cause and stating it with false confidence.", T.AMBER)
        + block("And nobody measures what the failure did",
                "If a link fails in the middle of a file upload, does the upload switch to a backup route, freeze until "
                "the link returns, or fail? Usually no one can say, because nothing was measured.", T.AMBER))
with right, card("about_solution"):
    card_title("Our solution", "find the cause, measure the impact, show the recovery, and say how sure we are")
    st.html(
        block("1 · Detect and diagnose real failures",
              "Real DNS, gateway, ping, traceroute and TCP checks. 17 if-then rules turn the results into possible "
              "causes, each marked <i>Likely</i> or <i>Not confirmed</i>, never a made-up percentage.", T.SIGNAL)
        + block("2 · Break things on purpose and measure",
                "In the NS2 simulator we take a link down or overload it and count every packet. In an isolated test "
                "network we take a link down <b>during a real file upload</b> and watch whether it reroutes, stalls or "
                "needs a retry, with SHA-256 proof that the file arrived intact.", T.UPLOAD)
        + block("3 · One honest answer per failure",
                "The root-cause register lists every failure, its cause, and a status: <i>Confirmed (injected)</i> "
                "when we caused it, <i>Likely</i> or <i>Not confirmed</i> for live networks.", T.GREEN))

eyebrow("Where to look in the app", "follow the rail from left to right", T.SIGNAL)
pages = [
    ("app_pages/detect_page.py", "01 · Detect", "Run live checks on an allowed destination."),
    ("app_pages/diagnose_page.py", "02 · Diagnose", "See which rules fired and why, with evidence for and against."),
    ("app_pages/impact_page.py", "03 · Impact", "NS2: what a link failure or congestion did to every packet."),
    ("app_pages/recovery_page.py", "04 · Recovery", "Did service come back, and how?"),
    ("app_pages/upload_page.py", "Lab · Upload", "A real upload while a link fails: reroute, stall or retry."),
    ("app_pages/transport_page.py", "Lab · TCP/UDP/TLS", "Six controlled connection failures and their recovery."),
    ("app_pages/report_page.py", "05 · Report", "The root-cause register and every generated report."),
]
cols = st.columns(len(pages), gap="small")
for col, (path, label, text) in zip(cols, pages):
    with col, card("about_link"):
        st.page_link(path, label=label, width="stretch")
        st.caption(text)

up = data.upload_latest()
if up:
    from netlab.report import rows

    r = {x["mode"]: x for x in rows(up)}
    if "failover" in r and "static" in r:
        st.html(block("Headline result (upload under link failure)",
                      f"With a backup route the server paused for <b>{r['failover']['stall_s']:.2f} s</b> and the same "
                      f"TCP connection carried on over the backup path. Without one it paused for "
                      f"<b>{r['static']['stall_s']:.2f} s</b> until the link returned. "
                      + ("Every file matched its SHA-256 fingerprint." if all(x["sha256_match"] for x in r.values())
                         else "Not every file matched its SHA-256 fingerprint.")
                      + (" (recorded run)" if up["meta"].get("source") == "recorded" else ""), T.UPLOAD))
