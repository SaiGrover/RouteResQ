from dataclasses import asdict

import altair as alt
import pandas as pd
import streamlit as st

from communication.experiments import run_comparison
from communication.failures import run_all
from communication.tcp_client import send_bytes, send_message
from communication.tcp_server import TCPTransferServer
from security.tls import run_secure_transfer
from ui.components import bullet, loopback_badge

st.title("TCP / UDP communication & secure transfer")
loopback_badge()
st.caption("Client and server run as real sockets on 127.0.0.1 inside this app. For a two-machine lab setup, "
           "use the command-line server/client in the communication package (see README).")

view = st.segmented_control(
    "Section", ["TCP message & file", "TCP vs UDP", "Secure transfer (TLS)", "Failure demonstrations"],
    default="TCP message & file", required=True, label_visibility="collapsed", key="comm_view",
)


def show_steps(res) -> None:
    for s in res.steps:
        st.markdown(f"- {s}")


if view == "TCP message & file":
    with st.form("tcp_form"):
        msg = st.text_input("Message", "Hello from the RouteResQ client")
        up = st.file_uploader("File to transfer (optional)")
        go = st.form_submit_button("Send over TCP", type="primary", icon=":material/send:")
    if go:
        with TCPTransferServer("127.0.0.1", 0) as srv:
            m = send_message("127.0.0.1", srv.port, msg)
            fres = send_bytes("127.0.0.1", srv.port, up.getvalue(), name=up.name) if up else None
            events = [asdict(e) for e in srv.events]
        c1, c2 = st.columns(2)
        with c1.container(border=True):
            st.markdown("**Message**")
            show_steps(m)
            if m.server_ack:
                st.json(m.server_ack, expanded=False)
        if fres:
            with c2.container(border=True):
                st.markdown("**File**")
                show_steps(fres)
                st.metric("Effective throughput", f"{fres.throughput_mbps} Mb/s" if fres.throughput_mbps else "n/a")
                st.caption("Measured from the first byte sent until the server's acknowledgement.")
        with st.expander("Server-side event log"):
            st.dataframe(pd.DataFrame(events), hide_index=True, alt="Server events")
    st.caption("Framing: each message is a 1-byte type + 4-byte length header + payload; the receiver loops on "
               "recv() until the full frame has arrived, so partial reads are handled.")

elif view == "TCP vs UDP":
    with st.form("cmp_form"):
        c1, c2, c3 = st.columns(3)
        total = c1.number_input("Data per trial (bytes)", 10_000, 20_000_000, 1_000_000, step=100_000)
        size = c2.number_input("UDP datagram payload (bytes)", 64, 60_000, 1024)
        trials = c3.number_input("Trials per protocol", 1, 10, 3)
        c4, c5 = st.columns(2)
        pace = c4.number_input("UDP pacing (datagrams/s, 0 = as fast as possible)", 0, 1_000_000, 0)
        small_buf = c5.toggle("Small UDP receive buffer (8 KB)", help="Makes real datagram loss more likely when "
                                                                    "the sender is faster than the receiver.")
        go = st.form_submit_button("Run experiment", type="primary", icon=":material/science:")
    if go:
        with st.spinner("Running TCP and UDP trials..."):
            st.session_state.cmp_result = run_comparison(int(total), int(size), int(trials),
                                                         float(pace) or None, 8192 if small_buf else None)
    r = st.session_state.get("cmp_result")
    if r:
        st.caption(f"{r['timestamp']} - {r['environment']}")
        df = pd.DataFrame(r["tcp"] + r["udp"])
        st.dataframe(df, hide_index=True, alt="TCP and UDP trial results",
                     column_order=["protocol", "trial", "ok", "connection_setup_ms", "payload_bytes", "delivered_bytes",
                                   "delivered_pct", "duration_s", "throughput_mbps", "integrity_ok", "missing",
                                   "out_of_order", "duplicates", "error"])
        c1, c2 = st.columns(2)
        c1.altair_chart(alt.Chart(df).mark_bar().encode(
            x=alt.X("protocol:N", title=None), xOffset="trial:N", y=alt.Y("delivered_pct:Q", title="Delivered (%)",
                                                                          scale=alt.Scale(domain=[0, 100])),
            color=alt.Color("protocol:N", legend=None), tooltip=["protocol", "trial", "delivered_pct"]
        ).properties(height=220), alt="Delivered data per trial")
        c2.altair_chart(alt.Chart(df).mark_bar().encode(
            x=alt.X("protocol:N", title=None), xOffset="trial:N", y=alt.Y("throughput_mbps:Q", title="Throughput (Mb/s)"),
            color=alt.Color("protocol:N", legend=None), tooltip=["protocol", "trial", "throughput_mbps"]
        ).properties(height=220), alt="Throughput per trial")
        st.markdown("#### Why they behave differently")
        bullet(r["explanation"])

elif view == "Secure transfer (TLS)":
    with st.form("tls_form"):
        msg = st.text_input("Message", "Confidential lab result: 42")
        up = st.file_uploader("File (optional, otherwise 256 KB of random data)")
        go = st.form_submit_button("Send over TLS", type="primary", icon=":material/lock:")
    if go:
        with st.spinner("TLS handshake and transfer..."):
            demo = run_secure_transfer(up.getvalue() if up else None, msg, name=up.name if up else "secure.bin")
        m, f = demo.message, demo.file
        ok = m.ok and f.ok
        (st.success if ok else st.error)(
            "Handshake, certificate validation, encrypted transfer and SHA-256 verification all succeeded."
            if ok else f"Secure transfer failed: {m.error or f.error}", title="Result")
        if f.tls_info:
            t = f.tls_info
            c = st.columns(3)
            c[0].metric("Protocol", t.version, border=True)
            c[1].metric("Cipher suite", t.cipher, border=True)
            c[2].metric("Key bits", t.cipher_bits, border=True)
            st.dataframe(pd.DataFrame([
                {"Field": "Server certificate subject", "Value": t.peer_subject},
                {"Field": "Issuer (trusted CA)", "Value": t.peer_issuer},
                {"Field": "Valid until", "Value": t.not_after},
                {"Field": "Certificate SHA-256 fingerprint", "Value": t.cert_sha256},
                {"Field": "File SHA-256 (client)", "Value": f.local_sha256},
                {"Field": "File SHA-256 (server)", "Value": (f.server_ack or {}).get("sha256")},
                {"Field": "Integrity verified", "Value": str(f.integrity_ok)},
            ]), hide_index=True, alt="TLS session and integrity details")
        c1, c2 = st.columns(2)
        with c1.container(border=True):
            st.markdown("**Message over TLS**")
            show_steps(m)
        with c2.container(border=True):
            st.markdown("**File over TLS**")
            show_steps(f)
        with st.expander("Server-side event log"):
            st.dataframe(pd.DataFrame(demo.server_events), hide_index=True, alt="TLS server events")
    st.caption("TLS comes from Python's ssl module (OpenSSL). The client requires a certificate chain to the "
               "RouteResQ lab CA and a matching host name. No custom cryptography is used.")

else:
    st.markdown("Each demonstration creates a known fault locally, records the error the client actually saw, "
                "restores the condition and tests whether communication resumes.")
    blackhole = st.checkbox("Also try a connect timeout to 192.0.2.1:80 (RFC 5737 documentation address, no host)")
    if st.button("Run all demonstrations", type="primary", icon=":material/bug_report:"):
        with st.spinner("Creating failures and restoring them..."):
            st.session_state.fail_result = run_all(include_blackhole=blackhole)
    r = st.session_state.get("fail_result")
    if r:
        st.caption(f"{r['timestamp']} - {r['environment']}")
        df = pd.DataFrame(r["records"])
        st.dataframe(df, hide_index=True, alt="Failure demonstration summary",
                     column_order=["failure_type", "observed_error_kind", "resumed", "condition_created",
                                   "observed_error", "restoration", "resume_detail"],
                     column_config={"resumed": st.column_config.CheckboxColumn("Resumed after restore")})
        for rec in r["records"]:
            with st.expander(f"{rec['failure_type']} -> {rec['observed_error_kind']}"):
                st.markdown(f"**Condition created:** {rec['condition_created']}")
                st.markdown(f"**Observed error:** `{rec['observed_error']}`")
                st.markdown(f"**Impact on communication:** {rec['impact']}")
                st.markdown(f"**Restoration:** {rec['restoration']}")
                st.markdown(f"**Resumed:** {'yes' if rec['resumed'] else 'no'} - {rec['resume_detail']}")
                if rec.get("details"):
                    st.json(rec["details"], expanded=False)
