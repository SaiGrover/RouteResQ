import shutil

import streamlit as st

from diagnostics.commands import IS_WINDOWS
from ui.components import cached_backend_status

st.title("RouteResQ")
st.caption("Network failure detection, root-cause analysis and recovery observation")

st.markdown(
    "RouteResQ asks four questions about a network problem: **what failed**, **why it failed**, "
    "**what happened next**, and **how performance changed**. It answers them from evidence "
    "only, in five steps:"
)

with st.container(horizontal=True, gap="medium"):
    for icon, title, body in [
        (":material/search:", "Detect", "Ping, DNS, traceroute and TCP checks against authorised destinations."),
        (":material/psychology:", "Diagnose", "Deterministic rules turn the evidence into findings and possible causes."),
        (":material/insights:", "Analyse impact", "NS2 traces give loss, delay and throughput before, during and after a failure."),
        (":material/healing:", "Observe recovery", "Rerouting and recovery are reported only when the trace shows them."),
        (":material/description:", "Report", "JSON, CSV and Markdown reports with what can and cannot be concluded."),
    ]:
        with st.container(border=True, width=220):
            st.markdown(f"**{icon} {title}**")
            st.caption(body)

st.subheader("Modules")
c1, c2, c3 = st.columns(3)
with c1.container(border=True, height="stretch"):
    st.markdown("**:material/troubleshoot: Diagnostics & root cause**")
    st.badge("Live network", color="green")
    st.write("Runs real ping/traceroute/DNS/TCP checks, classifies symptoms and explains the likely causes. "
             "Keeps a history and baselines so changes can be detected.")
    st.page_link("app_pages/diagnostics_page.py", label="Open diagnostics", icon=":material/arrow_forward:")
with c2.container(border=True, height="stretch"):
    st.markdown("**:material/hub: NS2 failure simulation**")
    st.badge("Simulated", color="violet")
    st.write("A 6-node wired topology in real NS2: healthy baseline, link failure under DV and static "
             "routing, and congestion. The cause is known because it is injected on purpose.")
    st.page_link("app_pages/simulation_page.py", label="Open simulation", icon=":material/arrow_forward:")
with c3.container(border=True, height="stretch"):
    st.markdown("**:material/swap_horiz: TCP / UDP / TLS**")
    st.badge("Loopback sockets", color="blue")
    st.write("TCP and UDP client/server, a TCP vs UDP experiment, TLS-encrypted transfer with SHA-256 "
             "integrity checks, and controlled communication failures.")
    st.page_link("app_pages/communication_page.py", label="Open communication", icon=":material/arrow_forward:")

st.subheader("Environment")
ns2 = cached_backend_status()
tools = ["ping", "tracert" if IS_WINDOWS else "traceroute"]
rows = [{"Component": f"`{t}` command", "Status": "available" if shutil.which(t) else "missing",
         "Detail": shutil.which(t) or "install it to enable this diagnostic"} for t in tools]
rows.append({"Component": "NS2 simulator", "Status": "available" if ns2["available"] else "missing",
             "Detail": f"{ns2['kind']}: {ns2['detail']} (ns2 {ns2['version']})" if ns2["available"] else ns2["detail"]})
st.dataframe(rows, hide_index=True, alt="Availability of the external tools RouteResQ uses")

st.info(
    "Simulated results (NS2) and live measurements are always shown separately and labelled. A failure "
    "observed on the live network is never assumed to have the same cause as a simulated one.",
    icon=":material/info:",
)
