"""TCP / UDP / TLS tests with real sockets on the loopback interface."""
import hashlib
import os
import socket
import threading

import pytest

from communication.experiments import run_comparison
from communication.failures import (
    demo_connection_timeout, demo_interrupted_transfer, demo_invalid_tls_certificate, demo_missing_udp,
    demo_server_unavailable,
)
from communication.framing import FILE_CHUNK, FILE_END, FILE_META, ConnectionClosed, recv_frame, send_frame, send_json
from communication.tcp_client import send_bytes, send_message
from communication.tcp_server import TCPTransferServer
from communication.udp import UDPReceiver, send_datagrams
from security.certs import generate_lab_pki
from security.integrity import sha256_bytes, sha256_file, verify
from security.tls import client_context, run_secure_transfer, server_context


@pytest.fixture(scope="module")
def pki(tmp_path_factory):
    return generate_lab_pki(tmp_path_factory.mktemp("pki"))


# ------------------------------------------------------------------- framing
def test_framing_handles_partial_reads():
    a, b = socket.socketpair()
    payload = os.urandom(10_000)
    import struct
    frame = struct.pack("!BI", 1, len(payload)) + payload

    def dribble():
        for i in range(0, len(frame), 7):  # 7-byte writes force many partial reads
            a.sendall(frame[i:i + 7])

    t = threading.Thread(target=dribble)
    t.start()
    ftype, data = recv_frame(b)
    t.join()
    assert ftype == 1 and data == payload
    a.close()
    b.close()


def test_framing_detects_connection_closed_mid_frame():
    a, b = socket.socketpair()
    a.sendall(b"\x01\x00\x00\x00\x10abc")  # announces 16 bytes, sends 3
    a.close()
    with pytest.raises(ConnectionClosed):
        recv_frame(b)
    b.close()


# ----------------------------------------------------------------------- TCP
def test_tcp_message_and_file_transfer(tmp_path):
    data = os.urandom(300_000)
    with TCPTransferServer("127.0.0.1", 0, storage_dir=tmp_path) as srv:
        m = send_message("127.0.0.1", srv.port, "hello")
        f = send_bytes("127.0.0.1", srv.port, data, name="../../evil name.bin")
        events = [e.event for e in srv.events]
    assert m.ok and m.server_ack["echo"] == "hello" and m.integrity_ok
    assert f.ok and f.integrity_ok and f.server_ack["received_bytes"] == len(data)
    assert f.duration_s > 0 and f.throughput_mbps > 0 and f.connect_ms is not None
    stored = list(tmp_path.iterdir())
    assert len(stored) == 1 and stored[0].parent == tmp_path  # path traversal neutralised
    assert sha256_file(stored[0]) == hashlib.sha256(data).hexdigest()
    assert "FILE_DONE" in events and "BYE" in events


def test_server_detects_integrity_mismatch():
    with TCPTransferServer("127.0.0.1", 0) as srv:
        with socket.create_connection(("127.0.0.1", srv.port), timeout=5) as s:
            send_json(s, FILE_META, {"name": "x", "size": 3, "sha256": "0" * 64})
            send_frame(s, FILE_CHUNK, b"abc")
            send_frame(s, FILE_END)
            _t, payload = recv_frame(s)
    import json
    ack = json.loads(payload)
    assert ack["integrity_ok"] is False and ack["sha256"] == sha256_bytes(b"abc")


# ----------------------------------------------------------------------- UDP
def test_udp_all_datagrams_received_in_order():
    rx = UDPReceiver("127.0.0.1", 0, idle_timeout=1.0).start()
    snd = send_datagrams("127.0.0.1", rx.port, 100, 256, rate_pps=5000)
    rep = rx.wait(10)
    assert snd.sent == 100 and rep.unique == 100 and rep.missing == [] and rep.loss_pct == 0
    assert not rep.timed_out and rep.duplicates == 0


def test_udp_missing_datagrams_and_timeout_detected():
    rx = UDPReceiver("127.0.0.1", 0, idle_timeout=0.5).start()
    send_datagrams("127.0.0.1", rx.port, 50, 128, rate_pps=5000, omit={3, 4, 5, 49})
    rep = rx.wait(10)
    assert rep.missing == [3, 4, 5, 49] and rep.missing_ranges == "3-5, 49"
    assert rep.timed_out  # last datagram never came -> idle timeout ended the run
    assert rep.loss_pct == 8.0


def test_udp_parameter_validation():
    with pytest.raises(ValueError):
        send_datagrams("127.0.0.1", 9, 0)
    with pytest.raises(ValueError):
        send_datagrams("127.0.0.1", 9, 1, payload_size=70_000)


def test_tcp_vs_udp_comparison_is_measured():
    r = run_comparison(total_bytes=200_000, datagram_payload=1000, trials=1, udp_rate_pps=20_000, save=False)
    tcp, udp = r["tcp"][0], r["udp"][0]
    assert tcp["ok"] and tcp["integrity_ok"] and tcp["delivered_pct"] == 100
    assert tcp["connection_setup_ms"] > 0 and udp["connection_setup_ms"] == 0
    assert udp["datagrams_sent"] == 200
    assert any("connectionless" in line for line in r["explanation"])
    assert not any("always" in line.lower() and "faster" in line.lower() for line in r["explanation"])


# ----------------------------------------------------------------------- TLS
def test_tls_secure_transfer_and_integrity(pki):
    data = os.urandom(100_000)
    demo = run_secure_transfer(data, "secret", pki=pki)
    assert demo.message.ok and demo.file.ok and demo.file.integrity_ok
    assert demo.file.tls_info.version in ("TLSv1.2", "TLSv1.3")
    assert "RouteResQ Lab CA" in demo.file.tls_info.peer_issuer
    assert demo.file.server_ack["sha256"] == hashlib.sha256(data).hexdigest()
    assert any(e["event"] == "TLS_HANDSHAKE_OK" for e in demo.server_events)


def test_tls_rejects_untrusted_and_mismatched_certificates(pki):
    ctx = client_context(pki.ca_cert)
    for cert, key in [(pki.rogue_server_cert, pki.rogue_server_key), (pki.wrong_host_cert, pki.wrong_host_key)]:
        with TCPTransferServer("127.0.0.1", 0, ssl_context=server_context(cert, key)) as srv:
            r = send_message("127.0.0.1", srv.port, "secret", ssl_context=ctx, server_hostname="localhost")
        assert not r.ok and r.error_kind == "tls_certificate" and r.bytes_sent == 0


def test_plain_client_cannot_talk_to_tls_server(pki):
    with TCPTransferServer("127.0.0.1", 0, ssl_context=server_context(pki.server_cert, pki.server_key)) as srv:
        r = send_message("127.0.0.1", srv.port, "hello", timeout=2)
    assert not r.ok


def test_integrity_helpers(tmp_path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"routeresq")
    assert sha256_file(p) == sha256_bytes(b"routeresq") and verify(b"routeresq", sha256_bytes(b"routeresq"))
    assert not verify(b"routeresq!", sha256_bytes(b"routeresq"))


# ------------------------------------------------------- failure demonstrations
def test_server_unavailable_then_restored():
    r = demo_server_unavailable()
    assert r.observed_error_kind == "refused" and r.resumed


def test_read_timeout_then_restored():
    r = demo_connection_timeout(timeout_s=0.8)
    assert r.observed_error_kind == "timeout" and r.resumed


def test_interrupted_transfer_then_resent():
    r = demo_interrupted_transfer(size=1_500_000, abort_after=200_000)
    assert r.observed_error_kind in ("reset", "closed_by_peer") and r.resumed
    assert r.details["bytes_written_before_failure"] < 1_500_000


def test_missing_udp_detection_matches_injection():
    r = demo_missing_udp()
    assert r.details["detection_matches_injection"] and r.resumed


def test_invalid_certificate_demos():
    recs = demo_invalid_tls_certificate()
    assert [r.observed_error_kind for r in recs] == ["tls_certificate", "tls_certificate"]
    assert "Hostname mismatch" in recs[1].observed_error and all(r.resumed for r in recs)
