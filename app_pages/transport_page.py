from dataclasses import asdict

import pandas as pd
import streamlit as st

from common.paths import CERT_DIR, COMM_RESULTS_DIR
from communication.experiments import run_comparison
from communication.failures import run_all
from communication.tcp_client import TransferResult, send_bytes, send_message
from communication.tcp_server import TCPTransferServer
from security.tls import run_secure_transfer
from ui import charts, data
from ui import theme as T
from ui.components import (badge_row, card, card_title, chain, chart, e, empty, eyebrow, fmt, method, note, page_header,
                           pill, tiles, verdict)

page_header("Lab · Transport layer", "TCP, UDP and secure communication",
            "Real client and server sockets on the loopback interface: framed TCP transfers, sequenced UDP datagrams, "
            "TLS with certificate validation and SHA-256 integrity, and controlled failure drills. For two lab PCs use "
            "the command-line server and client.", T.STEEL)
badge_row("loopback")

view = st.segmented_control("Section", ["Connection", "TCP vs UDP", "Secure transfer", "Failure drills"],
                            default="Connection", required=True, key="tr_view", label_visibility="collapsed")


def connection_chain(r: TransferResult, tls: bool = False) -> None:
    """Build the chain only from what the client actually recorded."""
    failed = not r.ok
    stages = [("TCP connect", "ok" if r.connect_ms is not None else "fail",
               f"3-way handshake {fmt(r.connect_ms, ' ms', 3)}" if r.connect_ms is not None else (r.error_kind or "no connection"))]
    if tls:
        stages.append(("TLS handshake", "ok" if r.handshake_ms is not None else ("fail" if r.connect_ms is not None else "skip"),
                       f"{r.tls_info.version} · {fmt(r.handshake_ms, ' ms', 3)}" if r.tls_info else (r.error_kind or "")))
        stages.append(("Certificate check", "ok" if r.tls_info else ("fail" if r.error_kind == "tls_certificate" else "skip"),
                       "chain to lab CA + host name" if r.tls_info else (r.error or "")))
    sent = r.bytes_sent > 0
    stages.append(("Data transfer", "ok" if sent and r.server_ack else ("fail" if failed and r.connect_ms is not None else "skip"),
                   f"{r.bytes_sent:,} bytes framed" if sent else "nothing sent"))
    if r.operation == "file" or tls:
        stages.append(("Integrity (SHA-256)", "ok" if r.integrity_ok else ("fail" if r.server_ack else "skip"),
                       "client = server digest" if r.integrity_ok else ("digest mismatch" if r.server_ack else "not reached")))
    stages.append(("Close", "ok" if r.ok else "skip", "BYE + FIN" if r.ok else "aborted"))
    chain(stages)


# ================================================================== connection
if view == "Connection":
    with st.container(key="card_tcpform"), st.form("tcp_form", border=False):
        a, b = st.columns([1.4, 1], vertical_alignment="bottom")
        msg = a.text_input("Message", "Hello from the RouteResQ client")
        up = b.file_uploader("File (optional)", label_visibility="visible")
        go = st.form_submit_button("Send over TCP", type="primary", icon=":material/send:")
    if go:
        with TCPTransferServer("127.0.0.1", 0) as srv:
            m = send_message("127.0.0.1", srv.port, msg)
            fr = send_bytes("127.0.0.1", srv.port, up.getvalue(), name=up.name) if up else None
            ev = [asdict(x) for x in srv.events]
        st.session_state.tcp_demo = (m, fr, ev)
    if "tcp_demo" in st.session_state:
        m, fr, ev = st.session_state.tcp_demo
        eyebrow("Message", f"{m.payload_bytes} bytes", T.SIGNAL)
        connection_chain(m)
        r = fr or m
        tiles([("Connect", f"{fmt(r.connect_ms, '', 3)}<small>ms</small>", "SYN → SYN-ACK → ACK", T.SIGNAL),
               ("Round trip", f"{fmt((m.duration_s or 0) * 1000, '', 3)}<small>ms</small>", "message → acknowledgement", T.SIGNAL),
               ("File", f"{fr.payload_bytes:,}<small>B</small>" if fr else "none", "uploaded payload", T.SLATE),
               ("Throughput", f"{fmt(fr.throughput_mbps, '', 1)}<small>Mb/s</small>" if fr and fr.throughput_mbps else "n/a",
                "first byte → server ACK", T.STEEL),
               ("Integrity", "verified" if fr and fr.integrity_ok else ("n/a" if not fr else "FAILED"), "SHA-256 client vs server",
                T.GREEN if fr and fr.integrity_ok else T.SLATE)])
        if fr:
            eyebrow("File", fr.server_ack.get("name", "") if fr.server_ack else "", T.STEEL)
            connection_chain(fr)
        with card("srvlog"):
            card_title("Server event log", "recorded by the server thread")
            st.dataframe(pd.DataFrame(ev), hide_index=True, alt="Server events")
    else:
        empty("No transfer yet", "Send a message, optionally with a file, to see each connection stage.")
    note("<b>Framing.</b> Each message is a 1-byte type plus a 4-byte length header plus the payload; the receiver loops "
         "on <code>recv()</code> until the whole frame has arrived, so partial reads are handled.", T.SIGNAL)

# ================================================================== tcp vs udp
elif view == "TCP vs UDP":
    with st.container(key="card_cmpform"), st.form("cmp_form", border=False):
        a, b, c, d, f_ = st.columns(5, vertical_alignment="bottom")
        total = a.number_input("Data per trial (bytes)", 10_000, 20_000_000, 1_000_000, step=100_000)
        size = b.number_input("UDP payload (bytes)", 64, 60_000, 1024)
        trials = c.number_input("Trials", 1, 10, 3)
        pace = d.number_input("UDP pacing (pps, 0 = max)", 0, 1_000_000, 0)
        small = f_.toggle("8 KB UDP buffer", help="Makes real datagram loss likely when the sender outpaces the receiver.")
        go = st.form_submit_button("Run experiment", type="primary", icon=":material/science:")
    if go:
        with st.spinner("Running TCP and UDP trials on real sockets ..."):
            run_comparison(int(total), int(size), int(trials), float(pace) or None, 8192 if small else None)
    r = data.latest_comm("tcp_vs_udp")
    if not r:
        empty("No experiment yet", "Run the experiment to compare the two protocols on identical data.")
    else:
        rows = r["tcp"] + r["udp"]
        tcp, udp = r["tcp"], r["udp"]
        st.caption(f"{r['timestamp']} · {r['environment']} · parameters {r['parameters']}")
        tiles([("TCP delivered", f"{min(x['delivered_pct'] for x in tcp):g}<small>%</small>", "lowest across trials", T.SIGNAL),
               ("UDP delivered", f"{min(x['delivered_pct'] for x in udp):g}<small>%</small>", "lowest across trials",
                T.GREEN if min(x['delivered_pct'] for x in udp) == 100 else T.AMBER),
               ("TCP setup", f"{fmt(sum(x['connection_setup_ms'] for x in tcp) / len(tcp), '', 3)}<small>ms</small>", "mean handshake", T.SIGNAL),
               ("UDP setup", "0<small>ms</small>", "connectionless", T.AMBER),
               ("Integrity", "verified" if all(x["integrity_ok"] for x in tcp) else "failed", "TCP SHA-256", T.GREEN)])
        c1, c2, c3 = st.columns(3, gap="medium")
        with c1:
            chart(charts.protocol_bars(rows, "delivered_pct", "delivered (%)", rng=[0, 105]), "Delivery", "per trial",
                  what="Share of the payload that reached the receiver.", why="TCP retransmits; UDP does not.")
        with c2:
            chart(charts.protocol_bars(rows, "throughput_mbps", "Mb/s"), "Throughput", "per trial",
                  what="TCP: until acknowledged. UDP: first to last arrival at the receiver.",
                  why="Depends on host, pacing and buffers; neither protocol is faster in general.")
        with c3:
            chart(charts.protocol_bars(rows, "connection_setup_ms", "ms"), "Connection set-up", "per trial",
                  what="Time for the TCP three-way handshake; UDP has none.", why="The cost of TCP's reliability starts before any data.")
        with card("expl"):
            card_title("Why they behave differently", "generated from these measurements")
            for line in r["explanation"]:
                st.markdown(f"- {line}")
        with st.expander("Trial table"):
            st.dataframe(pd.DataFrame(rows), hide_index=True, alt="TCP and UDP trials")

# ================================================================== tls
elif view == "Secure transfer":
    with st.container(key="card_tlsform"), st.form("tls_form", border=False):
        a, b = st.columns([1.4, 1], vertical_alignment="bottom")
        msg = a.text_input("Message", "Confidential lab result: 42")
        up = b.file_uploader("File (optional, else 256 KB random)")
        go = st.form_submit_button("Send over TLS", type="primary", icon=":material/lock:")
    if go:
        with st.spinner("TLS handshake, certificate validation and transfer ..."):
            st.session_state.tls_demo = run_secure_transfer(up.getvalue() if up else None, msg, name=up.name if up else "secure.bin")
    demo = st.session_state.get("tls_demo")
    if not demo:
        empty("No secure transfer yet", "Send a message and file over TLS. The client trusts only the RouteResQ lab CA "
              "and checks the host name.")
    else:
        fr = demo.file
        verdict("Verified by the backend" if fr.ok else "Secure transfer failed",
                "TLS handshake completed, the server certificate chained to the lab CA and matched 'localhost', and the "
                "SHA-256 digest computed by the server equals the client's." if fr.ok else (fr.error or ""),
                T.GREEN if fr.ok else T.CLAY)
        connection_chain(fr, tls=True)
        t = fr.tls_info
        if t:
            tiles([("Protocol", e(t.version), "negotiated", T.GREEN), ("Cipher suite", e(t.cipher.replace("TLS_", "")), f"{t.cipher_bits}-bit", T.STEEL),
                   ("Handshake", f"{fmt(fr.handshake_ms, '', 2)}<small>ms</small>", "after TCP connect", T.SIGNAL),
                   ("Payload", f"{fr.payload_bytes:,}<small>B</small>", f"{fmt(fr.throughput_mbps, '', 1)} Mb/s", T.SIGNAL)])
            with card("cert"):
                card_title("Certificate and integrity details")
                st.dataframe(pd.DataFrame([
                    {"field": "server certificate subject", "value": t.peer_subject},
                    {"field": "issuer (trusted lab CA)", "value": t.peer_issuer},
                    {"field": "valid until", "value": t.not_after},
                    {"field": "certificate SHA-256 fingerprint", "value": t.cert_sha256},
                    {"field": "file SHA-256 (client)", "value": fr.local_sha256},
                    {"field": "file SHA-256 (server)", "value": (fr.server_ack or {}).get("sha256")},
                ]), hide_index=True, alt="TLS certificate and digest details")
        note("These indicators report what the handshake negotiated and what the integrity check computed. They are "
             "not a security audit: the lab CA and its keys are generated locally for demonstration.", T.AMBER)

# ================================================================== failure drills
else:
    bh = st.checkbox("Include a SYN timeout to 192.0.2.1:80 (RFC 5737 documentation address, no host)")
    if st.button("Run all failure drills", type="primary", icon=":material/bug_report:"):
        with st.spinner("Creating each failure, recording the error, restoring the condition ..."):
            run_all(include_blackhole=bh)
    r = data.latest_comm("failure_demo")
    if not r:
        empty("No drills run yet", "Each drill creates a known fault locally, records the error the client saw, "
              "restores the condition and checks whether communication resumes.")
    else:
        recs = r["records"]
        st.caption(f"{r['timestamp']} · {r['environment']}")
        tiles([("Drills", f"{len(recs)}", "faults injected locally", T.STEEL),
               ("Detected", f"{sum(1 for x in recs if x['observed_error_kind'])}", "client observed an error", T.CLAY),
               ("Recovered", f"{sum(x['resumed'] for x in recs)}<small>/{len(recs)}</small>", "after restoring the condition", T.GREEN)])
        for x in recs:
            with card("drill"):
                h1, h2 = st.columns([3, 1], vertical_alignment="center")
                h1.html(f'<div class="rr-ctitle">{e(x["failure_type"])}</div><div class="rr-csub">{e(x["condition_created"])}</div>')
                h2.html(f'<div style="text-align:right">{pill(x["observed_error_kind"] or "no error", T.CLAY)}'
                        f'{pill("resumed" if x["resumed"] else "not resumed", T.GREEN if x["resumed"] else T.SLATE)}</div>')
                chain([("Fault injected", "ok", x["condition_created"]),
                       ("Error observed", "fail" if x["observed_error_kind"] else "skip", x["observed_error"] or ""),
                       ("Condition restored", "ok", x["restoration"]),
                       ("Communication", "ok" if x["resumed"] else "skip", x["resume_detail"])])
                st.caption(x["impact"])

method([
    ("Framed TCP", "Length-prefixed frames; <code>recv_exact()</code> handles partial reads; errors classified as refused, "
     "timeout, reset, TLS certificate and others."),
    ("Sequenced UDP", "Run id, sequence number and timestamp in every datagram; the receiver reports missing ranges, "
     "duplicates, reordering and idle timeouts. No retransmission is added."),
    ("TLS from the standard library", "Python <code>ssl</code> (OpenSSL), TLS 1.2 minimum, CERT_REQUIRED with host-name "
     "checks; certificates generated with <code>cryptography</code>."),
    ("Verify integrity", "SHA-256 over the payload on both ends; the server reports its digest in the acknowledgement."),
], "communication + security", [("lab CA", CERT_DIR / "lab-ca.pem"), ("server cert", CERT_DIR / "server.pem")],
   [("results/communication", f"{len(list(COMM_RESULTS_DIR.glob('*.json'))) if COMM_RESULTS_DIR.exists() else 0} JSON files")],
   T.STEEL, "real sockets, real TLS")
