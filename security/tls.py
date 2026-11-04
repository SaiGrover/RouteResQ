"""TLS contexts and the secure-transfer demonstration, built on Python's ``ssl`` module."""
from __future__ import annotations

import os
import ssl
from dataclasses import dataclass
from pathlib import Path

from communication.tcp_client import TransferResult, send_bytes, send_message
from communication.tcp_server import TCPTransferServer
from security.certs import LabPKI, ensure_lab_pki


def server_context(certfile: Path, keyfile: Path) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(certfile, keyfile)
    return ctx


def client_context(cafile: Path) -> ssl.SSLContext:
    """Verifying client: certificate chain AND host name are checked (CERT_REQUIRED)."""
    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=str(cafile))
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


@dataclass
class SecureTransferDemo:
    message: TransferResult
    file: TransferResult
    server_events: list


def run_secure_transfer(data: bytes | None = None, message: str = "RouteResQ secure hello",
                        pki: LabPKI | None = None, name: str = "secure.bin") -> SecureTransferDemo:
    """Start a local TLS server, send a message and a file, verify SHA-256 on both ends."""
    pki = pki or ensure_lab_pki()
    data = data if data is not None else os.urandom(256 * 1024)
    with TCPTransferServer("127.0.0.1", 0, ssl_context=server_context(pki.server_cert, pki.server_key)) as srv:
        ctx = client_context(pki.ca_cert)
        m = send_message("127.0.0.1", srv.port, message, ssl_context=ctx, server_hostname="localhost")
        f = send_bytes("127.0.0.1", srv.port, data, name=name, ssl_context=ctx, server_hostname="localhost")
        events = list(srv.events)
    return SecureTransferDemo(m, f, [e.__dict__ for e in events])
