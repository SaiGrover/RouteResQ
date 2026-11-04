"""Controlled communication-failure demonstrations.

Each demonstration (1) creates a known failure condition, (2) records the error the
application actually observed, (3) restores the condition and (4) checks whether
communication works again. Faults are created locally; nothing external is disturbed.
"""
from __future__ import annotations

import os
import socket
import time
from dataclasses import asdict, dataclass, field

from common.paths import COMM_RESULTS_DIR
from common.storage import timestamp_slug, utc_now_iso, write_json
from communication.tcp_client import send_bytes, send_message
from communication.tcp_server import TCPTransferServer
from communication.udp import UDPReceiver, send_datagrams


@dataclass
class FailureRecord:
    failure_type: str
    condition_created: str
    observed_error_kind: str | None
    observed_error: str | None
    impact: str
    restoration: str
    resumed: bool
    resume_detail: str
    injected: bool = True
    details: dict = field(default_factory=dict)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def demo_server_unavailable() -> FailureRecord:
    port = _free_port()
    # Windows retries a refused SYN for ~2 s before reporting WSAECONNREFUSED, so allow 5 s.
    t0 = time.perf_counter()
    r1 = send_message("127.0.0.1", port, "hello?", timeout=5)
    elapsed = time.perf_counter() - t0
    with TCPTransferServer("127.0.0.1", port):
        r2 = send_message("127.0.0.1", port, "hello again", timeout=2)
    return FailureRecord(
        "Server unavailable",
        f"No process listening on 127.0.0.1:{port}",
        r1.error_kind, r1.error,
        (f"The connection was refused after {elapsed:.2f} s: the OS answered the SYN with a TCP RST "
         "(Windows retries a refused SYN for about 2 s before reporting it). No data was sent.")
        if r1.error_kind == "refused" else f"Connection failed ({r1.error_kind}) after {elapsed:.2f} s; no data was sent.",
        f"Started the server on port {port}",
        r2.ok, "; ".join(r2.steps[-2:]) if r2.ok else (r2.error or ""),
    )


def demo_connection_timeout(timeout_s: float = 1.5) -> FailureRecord:
    with TCPTransferServer("127.0.0.1", 0, silent=True, client_timeout=timeout_s + 2) as srv:
        r1 = send_message("127.0.0.1", srv.port, "anyone there?", timeout=timeout_s)
    with TCPTransferServer("127.0.0.1", 0) as srv2:
        r2 = send_message("127.0.0.1", srv2.port, "anyone there?", timeout=timeout_s)
    return FailureRecord(
        "Connection timeout",
        f"Server accepts the TCP connection but never replies; client read timeout {timeout_s}s",
        r1.error_kind, r1.error,
        f"TCP connected ({r1.connect_ms} ms) but no reply arrived within {timeout_s}s, so the client gave up. "
        "A timeout alone cannot tell a slow server from a dead one.",
        "Replaced the silent server with a responsive one",
        r2.ok, f"reply received in {r2.duration_s * 1000:.2f} ms" if r2.ok and r2.duration_s else (r2.error or ""),
    )


def demo_connect_timeout_blackhole(timeout_s: float = 2.0) -> FailureRecord:
    """Optional: SYN to 192.0.2.1 (RFC 5737 documentation address, no host) - connect timeout."""
    r1 = send_message("192.0.2.1", 80, "x", timeout=timeout_s)
    return FailureRecord(
        "Connection timeout (no SYN-ACK)",
        "Connect to 192.0.2.1:80 (RFC 5737 TEST-NET-1, no host exists)",
        r1.error_kind, r1.error,
        "No SYN-ACK came back, so the TCP handshake never finished.",
        "Not applicable (no host exists at a documentation address)", False, "not restorable by design",
    )


def demo_interrupted_transfer(size: int = 2_000_000, abort_after: int = 300_000) -> FailureRecord:
    data = os.urandom(size)
    with TCPTransferServer("127.0.0.1", 0, abort_after_bytes=abort_after) as srv:
        r1 = send_bytes("127.0.0.1", srv.port, data, name="interrupted.bin", timeout=5)
    with TCPTransferServer("127.0.0.1", 0) as srv2:
        r2 = send_bytes("127.0.0.1", srv2.port, data, name="interrupted.bin", timeout=10)
    return FailureRecord(
        "Interrupted TCP transfer",
        f"Server resets the connection (RST) after receiving about {abort_after} of {size} bytes",
        r1.error_kind, r1.error,
        f"The transfer stopped: the client had written {r1.bytes_sent} bytes when the error was raised and "
        "got no acknowledgement, so it cannot know how much the server kept.",
        "Restarted a normal server and re-sent the whole file (no partial resume)",
        r2.ok,
        f"{(r2.server_ack or {}).get('received_bytes')} bytes received, SHA-256 match = {r2.integrity_ok}"
        if r2.server_ack else (r2.error or ""),
        details={"bytes_written_before_failure": r1.bytes_sent},
    )


def demo_missing_udp(count: int = 200, omit: tuple[int, ...] = (50, 51, 52, 53, 54, 120, 199)) -> FailureRecord:
    rx = UDPReceiver("127.0.0.1", 0, idle_timeout=1.0).start()
    send_datagrams("127.0.0.1", rx.port, count, 512, rate_pps=2000, omit=set(omit))
    rep = rx.wait(timeout=10)
    rx2 = UDPReceiver("127.0.0.1", 0, idle_timeout=1.0).start()
    send_datagrams("127.0.0.1", rx2.port, count, 512, rate_pps=2000)
    rep2 = rx2.wait(timeout=10)
    return FailureRecord(
        "Missing UDP datagrams",
        f"Sender deliberately skipped sequence numbers {list(omit)} (injected loss)",
        "missing_datagrams" if rep and rep.missing else None,
        (f"receiver detected missing seq {rep.missing_ranges}; idle timeout after {rep.idle_timeout_s}s"
         if rep else "no report"),
        f"{rep.unique if rep else 0}/{count} datagrams arrived. UDP did not notice or recover the loss; only the "
        "sequence numbers revealed it.",
        "Sent the run again without skipping",
        bool(rep2 and not rep2.missing),
        f"{rep2.unique}/{count} received, missing: {rep2.missing_ranges}" if rep2 else "no report",
        details={"injected": list(omit), "detected": rep.missing if rep else None,
                 "detection_matches_injection": bool(rep and rep.missing == sorted(omit))},
    )


def demo_invalid_tls_certificate() -> list[FailureRecord]:
    from security.certs import ensure_lab_pki
    from security.tls import client_context, server_context

    pki = ensure_lab_pki()
    trust_lab_ca = client_context(pki.ca_cert)
    out = []
    for label, cert, key, cond in [
        ("Invalid TLS certificate (untrusted issuer)", pki.rogue_server_cert, pki.rogue_server_key,
         "Server presents a certificate signed by a CA the client does not trust"),
        ("Invalid TLS certificate (host name mismatch)", pki.wrong_host_cert, pki.wrong_host_key,
         "Server presents a lab-CA certificate issued for 'wrong-host.example' while the client connects to 'localhost'"),
    ]:
        with TCPTransferServer("127.0.0.1", 0, ssl_context=server_context(cert, key)) as srv:
            r1 = send_message("127.0.0.1", srv.port, "secret", ssl_context=trust_lab_ca, server_hostname="localhost")
        with TCPTransferServer("127.0.0.1", 0, ssl_context=server_context(pki.server_cert, pki.server_key)) as srv2:
            r2 = send_message("127.0.0.1", srv2.port, "secret", ssl_context=trust_lab_ca, server_hostname="localhost")
        out.append(FailureRecord(
            label, cond, r1.error_kind, r1.error,
            "The client aborted the TLS handshake, so no application data was sent. This is the intended "
            "protection against impersonation.",
            "Server switched to the valid lab certificate for 'localhost'",
            r2.ok, f"{r2.tls_info.version} {r2.tls_info.cipher}" if r2.ok and r2.tls_info else (r2.error or ""),
        ))
    return out


def run_all(include_blackhole: bool = False, save: bool = True) -> dict:
    records: list[FailureRecord] = [
        demo_server_unavailable(),
        demo_connection_timeout(),
        demo_interrupted_transfer(),
        demo_missing_udp(),
        *demo_invalid_tls_certificate(),
    ]
    if include_blackhole:
        records.append(demo_connect_timeout_blackhole())
    result = {"timestamp": utc_now_iso(), "environment": "loopback (127.0.0.1); faults injected locally",
              "records": [asdict(r) for r in records]}
    if save:
        write_json(COMM_RESULTS_DIR / f"failure_demo_{timestamp_slug()}.json", result)
    return result
