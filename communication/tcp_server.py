"""TCP (optionally TLS) server for message and file transfer.

Run standalone::

    python -m communication.tcp_server --host 0.0.0.0 --port 5050
    python -m communication.tcp_server --port 5443 --tls      # uses the lab certificates

Fault-injection options exist only for the controlled failure demonstrations:
``abort_after_bytes`` resets the connection mid-transfer and ``silent`` accepts
connections but never answers (to provoke a read timeout).
"""
from __future__ import annotations

import argparse
import hashlib
import re
import socket
import ssl
import struct
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from common.logging_setup import get_logger
from communication.framing import (
    ACK, BYE, ERROR, FILE_CHUNK, FILE_END, FILE_META, MSG,
    ConnectionClosed, ProtocolError, decode_json, recv_frame, send_json,
)

log = get_logger("communication.tcp_server")
MAX_FILE = 200 * 1024 * 1024


@dataclass
class ServerEvent:
    time: float
    peer: str
    event: str
    detail: str = ""


@dataclass
class TCPTransferServer:
    host: str = "127.0.0.1"
    port: int = 0
    ssl_context: ssl.SSLContext | None = None
    storage_dir: Path | None = None
    abort_after_bytes: int | None = None
    silent: bool = False
    client_timeout: float = 30.0
    events: list[ServerEvent] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()

    # ---- lifecycle ----
    def start(self) -> "TCPTransferServer":
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((self.host, self.port))
        s.listen(16)
        s.settimeout(0.2)
        self._sock = s
        self.port = s.getsockname()[1]
        self._thread = threading.Thread(target=self._accept_loop, name=f"tcp-server-{self.port}", daemon=True)
        self._thread.start()
        self._event("-", "LISTEN", f"{self.host}:{self.port} tls={'yes' if self.ssl_context else 'no'}")
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        if self._sock:
            self._sock.close()
        self._event("-", "STOPPED")

    def __enter__(self) -> "TCPTransferServer":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    def _event(self, peer: str, event: str, detail: str = "") -> None:
        with self._lock:
            self.events.append(ServerEvent(round(time.time(), 4), peer, event, detail))
        log.info("[%s] %s %s", peer, event, detail)

    # ---- connection handling ----
    def _accept_loop(self) -> None:
        assert self._sock is not None
        while not self._stop.is_set():
            try:
                conn, addr = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._serve, args=(conn, f"{addr[0]}:{addr[1]}"), daemon=True).start()

    def _serve(self, conn: socket.socket, peer: str) -> None:
        self._event(peer, "CONNECTED")
        try:
            if self.ssl_context:
                try:
                    conn = self.ssl_context.wrap_socket(conn, server_side=True)
                    self._event(peer, "TLS_HANDSHAKE_OK", f"{conn.version()} {conn.cipher()[0]}")
                except (ssl.SSLError, OSError) as exc:
                    self._event(peer, "TLS_HANDSHAKE_FAILED", str(exc))
                    return
            conn.settimeout(self.client_timeout)
            if self.silent:
                self._event(peer, "SILENT_MODE", "accepting but not answering (fault injection)")
                self._stop.wait(self.client_timeout)
                return
            self._session(conn, peer)
        except (ConnectionClosed, ConnectionError, socket.timeout, ProtocolError, OSError) as exc:
            self._event(peer, "CONNECTION_ENDED", f"{type(exc).__name__}: {exc}")
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def _session(self, conn: socket.socket, peer: str) -> None:
        while True:
            ftype, payload = recv_frame(conn)
            if ftype == MSG:
                text = payload.decode(errors="replace")
                self._event(peer, "MSG", f"{len(payload)} bytes")
                send_json(conn, ACK, {"type": "msg", "bytes": len(payload),
                                      "sha256": hashlib.sha256(payload).hexdigest(), "echo": text[:200]})
            elif ftype == FILE_META:
                self._receive_file(conn, peer, decode_json(payload))
            elif ftype == BYE:
                self._event(peer, "BYE")
                return
            else:
                send_json(conn, ERROR, {"error": f"unexpected frame type {ftype}"})
                return

    def _receive_file(self, conn: socket.socket, peer: str, meta: dict) -> None:
        name = re.sub(r"[^A-Za-z0-9._-]", "_", str(meta.get("name", "upload.bin")))[:100] or "upload.bin"
        size = int(meta.get("size", -1))
        expected = str(meta.get("sha256", ""))
        if not 0 <= size <= MAX_FILE:
            send_json(conn, ERROR, {"error": "invalid or too large file size"})
            return
        self._event(peer, "FILE_START", f"{name} ({size} bytes)")
        h = hashlib.sha256()
        received = 0
        t0 = time.perf_counter()
        out = None
        if self.storage_dir:
            self.storage_dir.mkdir(parents=True, exist_ok=True)
            out = (self.storage_dir / name).open("wb")
        try:
            while True:
                ftype, payload = recv_frame(conn)
                if ftype == FILE_CHUNK:
                    received += len(payload)
                    h.update(payload)
                    if out:
                        out.write(payload)
                    if self.abort_after_bytes is not None and received >= self.abort_after_bytes:
                        self._event(peer, "ABORT_INJECTED", f"resetting connection after {received} bytes")
                        conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
                        conn.close()
                        return
                    if received > size:
                        send_json(conn, ERROR, {"error": "more data than announced"})
                        return
                elif ftype == FILE_END:
                    break
                else:
                    raise ProtocolError(f"unexpected frame {ftype} during file transfer")
        finally:
            if out:
                out.close()
        digest = h.hexdigest()
        ok = received == size and digest == expected
        dur = time.perf_counter() - t0
        self._event(peer, "FILE_DONE", f"{received} bytes, integrity {'OK' if ok else 'FAILED'}")
        send_json(conn, ACK, {"type": "file", "name": name, "received_bytes": received, "sha256": digest,
                              "integrity_ok": ok, "server_duration_s": round(dur, 4)})


def main(argv: list[str] | None = None) -> int:
    from common.paths import COMM_RESULTS_DIR

    ap = argparse.ArgumentParser(description="RouteResQ TCP/TLS transfer server")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5050)
    ap.add_argument("--tls", action="store_true", help="serve TLS using the lab certificate")
    ap.add_argument("--save", action="store_true", help="store received files under results/communication/received")
    args = ap.parse_args(argv)
    ctx = None
    if args.tls:
        from security.certs import ensure_lab_pki
        from security.tls import server_context

        pki = ensure_lab_pki()
        ctx = server_context(pki.server_cert, pki.server_key)
    srv = TCPTransferServer(args.host, args.port, ssl_context=ctx,
                            storage_dir=COMM_RESULTS_DIR / "received" if args.save else None)
    srv.start()
    print(f"Listening on {args.host}:{srv.port} ({'TLS' if ctx else 'plain TCP'}). Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        srv.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
