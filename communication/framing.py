"""Length-prefixed message framing over a TCP (or TLS) byte stream.

TCP delivers a byte stream, not messages: one ``send`` may arrive in several ``recv``
calls and several sends may arrive together. Every frame is therefore::

    +--------+----------------------+-----------------+
    | type   | payload length       | payload         |
    | 1 byte | 4 bytes (big endian) | <length> bytes  |
    +--------+----------------------+-----------------+

and the receiver loops until exactly ``length`` bytes have been read (``recv_exact``).
"""
from __future__ import annotations

import json
import socket
import struct

HEADER = struct.Struct("!BI")
MAX_FRAME = 16 * 1024 * 1024

MSG, FILE_META, FILE_CHUNK, FILE_END, ACK, ERROR, BYE = 1, 2, 3, 4, 5, 6, 7
TYPE_NAMES = {MSG: "MSG", FILE_META: "FILE_META", FILE_CHUNK: "FILE_CHUNK", FILE_END: "FILE_END",
              ACK: "ACK", ERROR: "ERROR", BYE: "BYE"}


class ConnectionClosed(ConnectionError):
    """Peer closed the connection (possibly in the middle of a frame)."""


class ProtocolError(ValueError):
    pass


def recv_exact(sock: socket.socket, n: int) -> bytes:
    """Read exactly n bytes, handling partial reads."""
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(min(n - len(buf), 1 << 16))
        if not chunk:
            raise ConnectionClosed(f"connection closed after {len(buf)} of {n} bytes")
        buf.extend(chunk)
    return bytes(buf)


def send_frame(sock: socket.socket, ftype: int, payload: bytes = b"") -> None:
    if len(payload) > MAX_FRAME:
        raise ProtocolError("frame too large")
    sock.sendall(HEADER.pack(ftype, len(payload)) + payload)


def recv_frame(sock: socket.socket) -> tuple[int, bytes]:
    ftype, length = HEADER.unpack(recv_exact(sock, HEADER.size))
    if ftype not in TYPE_NAMES:
        raise ProtocolError(f"unknown frame type {ftype}")
    if length > MAX_FRAME:
        raise ProtocolError(f"frame length {length} exceeds limit")
    return ftype, recv_exact(sock, length) if length else b""


def send_json(sock: socket.socket, ftype: int, obj: dict) -> None:
    send_frame(sock, ftype, json.dumps(obj).encode())


def decode_json(payload: bytes) -> dict:
    try:
        return json.loads(payload.decode())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"invalid JSON payload: {exc}") from exc
