"""UDP datagram sender and receiver with sequence-number tracking.

UDP gives no delivery, ordering or duplicate guarantees, and this module deliberately
does not add any (no retransmission). It only *measures* what arrived.

Datagram layout::

    magic "RRQU" | run id (u32) | seq (u32) | total (u32) | send timestamp (f64) | payload

Standalone use::

    python -m communication.udp receive --port 5051
    python -m communication.udp send --port 5051 --count 500 --size 1024
"""
from __future__ import annotations

import argparse
import random
import socket
import struct
import threading
import time
from dataclasses import dataclass, field

HDR = struct.Struct("!4sIIId")
MAGIC = b"RRQU"
MAX_PAYLOAD = 65507 - HDR.size


@dataclass
class UDPReceiveReport:
    run_id: int | None
    expected: int | None
    received: int
    unique: int
    duplicates: int
    out_of_order: int
    missing: list[int]
    missing_ranges: str
    loss_pct: float | None
    bytes_received: int
    first_arrival: float | None
    last_arrival: float | None
    duration_s: float | None
    throughput_mbps: float | None
    timed_out: bool
    idle_timeout_s: float
    malformed: int
    avg_one_way_ms: float | None = None


def _ranges(nums: list[int]) -> str:
    if not nums:
        return "none"
    out, start, prev = [], nums[0], nums[0]
    for n in nums[1:]:
        if n == prev + 1:
            prev = n
            continue
        out.append(f"{start}" if start == prev else f"{start}-{prev}")
        start = prev = n
    out.append(f"{start}" if start == prev else f"{start}-{prev}")
    return ", ".join(out)


@dataclass
class UDPReceiver:
    """Receives one run of datagrams. Ends when all are received, on stop(), or after an
    idle period with no datagrams (``idle_timeout``) - that is the timeout detection."""

    host: str = "127.0.0.1"
    port: int = 0
    idle_timeout: float = 1.5
    rcvbuf: int | None = None
    _seqs: list[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if self.rcvbuf:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, self.rcvbuf)
        self.sock.bind((self.host, self.port))
        self.port = self.sock.getsockname()[1]
        self.sock.settimeout(0.1)
        self._done = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.report: UDPReceiveReport | None = None

    def start(self) -> "UDPReceiver":
        self._thread = threading.Thread(target=self._loop, daemon=True, name=f"udp-recv-{self.port}")
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def wait(self, timeout: float | None = None) -> UDPReceiveReport | None:
        self._done.wait(timeout)
        return self.report

    def _loop(self) -> None:
        seqs: list[int] = []
        seen: set[int] = set()
        dup = ooo = malformed = nbytes = 0
        run_id = total = None
        first = last = None
        highest = -1
        one_way: list[float] = []
        timed_out = False
        try:
            while not self._stop.is_set():
                try:
                    data, _addr = self.sock.recvfrom(65535)
                except socket.timeout:
                    if last is not None and time.time() - last > self.idle_timeout:
                        timed_out = total is None or len(seen) < total
                        break
                    continue
                except OSError:
                    break  # e.g. Windows ICMP port-unreachable reset; keep it simple and stop
                now = time.time()
                if len(data) < HDR.size or data[:4] != MAGIC:
                    malformed += 1
                    continue
                _m, rid, seq, tot, ts = HDR.unpack_from(data)
                if run_id is None:
                    run_id, total = rid, tot
                elif rid != run_id:
                    malformed += 1
                    continue
                first = first or now
                last = now
                nbytes += len(data)
                seqs.append(seq)
                one_way.append(now - ts)
                if seq in seen:
                    dup += 1
                    continue
                if seq < highest:
                    ooo += 1
                highest = max(highest, seq)
                seen.add(seq)
                if total is not None and len(seen) >= total:
                    break
        finally:
            self.sock.close()
        missing = sorted(set(range(total)) - seen) if total is not None else []
        dur = (last - first) if first and last and last > first else None
        self.report = UDPReceiveReport(
            run_id=run_id, expected=total, received=len(seqs), unique=len(seen), duplicates=dup,
            out_of_order=ooo, missing=missing, missing_ranges=_ranges(missing),
            loss_pct=round(100 * len(missing) / total, 2) if total else None,
            bytes_received=nbytes, first_arrival=first, last_arrival=last,
            duration_s=round(dur, 6) if dur else None,
            throughput_mbps=round(nbytes * 8 / dur / 1e6, 3) if dur else None,
            timed_out=timed_out, idle_timeout_s=self.idle_timeout, malformed=malformed,
            avg_one_way_ms=round(sum(one_way) / len(one_way) * 1000, 3) if one_way else None,
        )
        self._done.set()


@dataclass
class UDPSendReport:
    run_id: int
    total: int
    sent: int
    omitted: list[int]
    payload_size: int
    duration_s: float
    errors: list[str]


def send_datagrams(host: str, port: int, count: int, payload_size: int = 1024, rate_pps: float | None = None,
                   omit: set[int] | None = None, run_id: int | None = None) -> UDPSendReport:
    """Send ``count`` sequenced datagrams. ``omit`` lists sequence numbers the sender
    deliberately skips - used only to inject a known, labelled loss in the demonstration."""
    if not 1 <= count <= 100_000:
        raise ValueError("count must be 1-100000")
    if not 0 <= payload_size <= MAX_PAYLOAD:
        raise ValueError(f"payload_size must be 0-{MAX_PAYLOAD}")
    omit = omit or set()
    run_id = run_id if run_id is not None else random.getrandbits(32)
    payload = bytes(payload_size)
    gap = 1.0 / rate_pps if rate_pps else 0.0
    errors: list[str] = []
    sent = 0
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        t0 = time.perf_counter()
        next_t = t0
        for seq in range(count):
            if seq in omit:
                continue
            if gap:
                now = time.perf_counter()
                if next_t > now:
                    time.sleep(next_t - now)
                next_t += gap
            try:
                s.sendto(HDR.pack(MAGIC, run_id, seq, count, time.time()) + payload, (host, port))
                sent += 1
            except OSError as exc:
                if len(errors) < 5:
                    errors.append(f"seq {seq}: {exc}")
        dur = time.perf_counter() - t0
    return UDPSendReport(run_id, count, sent, sorted(omit & set(range(count))), payload_size, round(dur, 6), errors)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="RouteResQ UDP sender/receiver")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("receive")
    r.add_argument("--host", default="127.0.0.1")
    r.add_argument("--port", type=int, default=5051)
    r.add_argument("--idle-timeout", type=float, default=3.0)
    s = sub.add_parser("send")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=5051)
    s.add_argument("--count", type=int, default=500)
    s.add_argument("--size", type=int, default=1024)
    s.add_argument("--rate", type=float, default=None, help="datagrams per second (default: as fast as possible)")
    args = ap.parse_args(argv)
    if args.cmd == "receive":
        rx = UDPReceiver(args.host, args.port, args.idle_timeout).start()
        print(f"Waiting for datagrams on {args.host}:{rx.port} ...")
        rep = rx.wait()
        print(rep)
    else:
        print(send_datagrams(args.host, args.port, args.count, args.size, args.rate))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
