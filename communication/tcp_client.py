"""TCP (optionally TLS) client: messages and file transfer with timing and error handling.

    python -m communication.tcp_client --port 5050 --message "hello"
    python -m communication.tcp_client --port 5050 --file report.pdf
    python -m communication.tcp_client --port 5443 --tls --file report.pdf
"""
from __future__ import annotations

import argparse
import errno
import hashlib
import socket
import ssl
import time
from dataclasses import dataclass, field
from pathlib import Path

from communication.framing import (
    BYE, ERROR, FILE_CHUNK, FILE_END, FILE_META, MSG,
    ConnectionClosed, ProtocolError, decode_json, recv_frame, send_frame, send_json,
)

CHUNK = 64 * 1024


@dataclass
class TLSInfo:
    version: str | None
    cipher: str | None
    cipher_bits: int | None
    peer_subject: str | None
    peer_issuer: str | None
    not_after: str | None
    cert_sha256: str | None


@dataclass
class TransferResult:
    ok: bool
    operation: str
    host: str
    port: int
    tls: bool = False
    bytes_sent: int = 0
    payload_bytes: int = 0
    connect_ms: float | None = None
    handshake_ms: float | None = None
    duration_s: float | None = None
    throughput_mbps: float | None = None
    local_sha256: str | None = None
    server_ack: dict | None = None
    integrity_ok: bool | None = None
    error_kind: str | None = None
    error: str | None = None
    tls_info: TLSInfo | None = None
    steps: list[str] = field(default_factory=list)


def classify_error(exc: BaseException) -> str:
    if isinstance(exc, ssl.SSLCertVerificationError):
        return "tls_certificate"
    if isinstance(exc, ssl.SSLError):
        return "tls_error"
    if isinstance(exc, ConnectionRefusedError):
        return "refused"
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return "timeout"
    if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
        return "reset"
    if isinstance(exc, ConnectionClosed):
        return "closed_by_peer"
    if isinstance(exc, ProtocolError):
        return "protocol"
    if isinstance(exc, socket.gaierror):
        return "dns"
    if isinstance(exc, OSError) and (exc.errno in (errno.ENETUNREACH, errno.EHOSTUNREACH)
                                     or getattr(exc, "winerror", None) in (10051, 10065)):
        return "unreachable"
    return "other"


def tls_info(sock: ssl.SSLSocket) -> TLSInfo:
    der = sock.getpeercert(binary_form=True)
    cert = sock.getpeercert() or {}

    def name(field_: str) -> str | None:
        parts = cert.get(field_)
        if not parts:
            return None
        return ", ".join(f"{k}={v}" for rdn in parts for k, v in rdn)

    c = sock.cipher()
    return TLSInfo(sock.version(), c[0] if c else None, c[2] if c else None, name("subject"), name("issuer"),
                   cert.get("notAfter"), hashlib.sha256(der).hexdigest() if der else None)


def _connect(res: TransferResult, timeout: float, ssl_context: ssl.SSLContext | None,
             server_hostname: str | None) -> socket.socket:
    t0 = time.perf_counter()
    raw = socket.create_connection((res.host, res.port), timeout=timeout)
    res.connect_ms = round((time.perf_counter() - t0) * 1000, 3)
    res.steps.append(f"TCP connection established in {res.connect_ms} ms (3-way handshake)")
    if ssl_context is None:
        return raw
    t1 = time.perf_counter()
    try:
        s = ssl_context.wrap_socket(raw, server_hostname=server_hostname or res.host)
    except BaseException:
        raw.close()
        raise
    res.handshake_ms = round((time.perf_counter() - t1) * 1000, 3)
    res.tls_info = tls_info(s)
    res.steps.append(f"TLS handshake completed in {res.handshake_ms} ms ({s.version()}, {s.cipher()[0]})")
    res.steps.append("Server certificate validated against the trusted CA and host name")
    return s


def _finish(res: TransferResult, exc: BaseException | None) -> TransferResult:
    if exc is not None:
        res.ok = False
        res.error_kind = classify_error(exc)
        res.error = f"{type(exc).__name__}: {exc}"
        res.steps.append(f"Failed: {res.error_kind} - {res.error}")
    return res


def send_message(host: str, port: int, text: str, timeout: float = 5.0,
                 ssl_context: ssl.SSLContext | None = None, server_hostname: str | None = None) -> TransferResult:
    data = text.encode()
    res = TransferResult(False, "message", host, port, tls=ssl_context is not None, payload_bytes=len(data),
                         local_sha256=hashlib.sha256(data).hexdigest())
    try:
        with _connect(res, timeout, ssl_context, server_hostname) as s:
            t0 = time.perf_counter()
            send_frame(s, MSG, data)
            res.bytes_sent = len(data)
            ftype, payload = recv_frame(s)
            res.duration_s = round(time.perf_counter() - t0, 6)
            if ftype == ERROR:
                raise ProtocolError(decode_json(payload).get("error", "server error"))
            res.server_ack = decode_json(payload)
            res.integrity_ok = res.server_ack.get("sha256") == res.local_sha256
            res.steps.append(f"Message sent and acknowledged in {res.duration_s * 1000:.2f} ms")
            send_frame(s, BYE)
            res.steps.append("Connection closed (BYE + FIN)")
            res.ok = True
    except BaseException as exc:  # noqa: BLE001 - classified and reported
        if isinstance(exc, KeyboardInterrupt):
            raise
        return _finish(res, exc)
    return res


def send_bytes(host: str, port: int, data: bytes, name: str = "payload.bin", timeout: float = 10.0,
               ssl_context: ssl.SSLContext | None = None, server_hostname: str | None = None,
               chunk: int = CHUNK) -> TransferResult:
    digest = hashlib.sha256(data).hexdigest()
    res = TransferResult(False, "file", host, port, tls=ssl_context is not None, payload_bytes=len(data),
                         local_sha256=digest)
    try:
        with _connect(res, timeout, ssl_context, server_hostname) as s:
            t0 = time.perf_counter()
            send_json(s, FILE_META, {"name": name, "size": len(data), "sha256": digest})
            for i in range(0, len(data), chunk):
                send_frame(s, FILE_CHUNK, data[i:i + chunk])
                res.bytes_sent += len(data[i:i + chunk])
            send_frame(s, FILE_END)
            res.steps.append(f"Sent {res.bytes_sent} bytes in {max(1, -(-len(data) // chunk))} chunk frame(s)")
            ftype, payload = recv_frame(s)
            res.duration_s = round(time.perf_counter() - t0, 6)
            if ftype == ERROR:
                raise ProtocolError(decode_json(payload).get("error", "server error"))
            res.server_ack = decode_json(payload)
            res.integrity_ok = bool(res.server_ack.get("integrity_ok")) and res.server_ack.get("sha256") == digest
            if res.duration_s > 0:
                res.throughput_mbps = round(len(data) * 8 / res.duration_s / 1e6, 3)
            res.steps.append(
                f"Server acknowledged {res.server_ack.get('received_bytes')} bytes; SHA-256 "
                f"{'matches' if res.integrity_ok else 'DOES NOT match'}"
            )
            send_frame(s, BYE)
            res.ok = bool(res.integrity_ok)
    except BaseException as exc:  # noqa: BLE001
        if isinstance(exc, KeyboardInterrupt):
            raise
        return _finish(res, exc)
    return res


def send_file(host: str, port: int, path: Path, **kw) -> TransferResult:
    p = Path(path)
    return send_bytes(host, port, p.read_bytes(), name=p.name, **kw)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="RouteResQ TCP/TLS client")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5050)
    ap.add_argument("--tls", action="store_true")
    ap.add_argument("--cafile", type=Path, help="CA certificate to trust (default: lab CA)")
    ap.add_argument("--server-name", default="localhost")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--message")
    g.add_argument("--file", type=Path)
    args = ap.parse_args(argv)
    ctx = None
    if args.tls:
        from security.certs import ensure_lab_pki
        from security.tls import client_context

        ctx = client_context(args.cafile or ensure_lab_pki().ca_cert)
    kw = {"ssl_context": ctx, "server_hostname": args.server_name if args.tls else None}
    res = send_message(args.host, args.port, args.message, **kw) if args.message else \
        send_file(args.host, args.port, args.file, **kw)
    for s in res.steps:
        print(" -", s)
    print("OK" if res.ok else f"FAILED ({res.error_kind})")
    return 0 if res.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
