"""One experiment run inside the isolated test network (Linux, root, see topology.py).

    python -m netlab.lab --input FILE --name NAME --out DIR [--config JSON]

For each requested mode (baseline, failover, static) the lab builds a fresh copy of the test
network, starts a TCP server in the server namespace and a paced TCP client in the client
namespace, and uploads the real file bytes using RouteResQ's framing (communication.framing):
FILE_META, FILE_CHUNK..., FILE_END, then the server's ACK with its SHA-256.

All threads share one clock (time.monotonic, t = 0 when the upload starts):

* the server records every increase in the bytes it has read (receiver-confirmed progress);
* the controller takes the primary link down once the server has received ``fault_at_pct`` of
  the file, and brings it back ``outage_s`` later;
* samplers read interface byte counters in all three namespaces every ``sample_ms``;
* ``ip route get`` snapshots record the kernel's forwarding decision before, during and after.

The network is removed after every run (success, failure or abort); the client never resumes
from a byte offset - a retry is a new TCP connection that re-sends the file from byte 0.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import socket
import sys
import threading
import time
from pathlib import Path

from communication.framing import (ACK, FILE_CHUNK, FILE_END, FILE_META, HEADER, ConnectionClosed, ProtocolError,
                                   decode_json, recv_exact, recv_frame, send_frame, send_json)
from netlab import analysis
from netlab.config import RUN_DESCRIPTIONS, RUN_LABELS, LabConfig, check_file_size
from netlab.topology import CLIENT_SVC, PORT, SERVER_SVC, Topology, enter_netns, read_counters

COUNTER_KEYS = {  # namespace role -> {iface: (key for rx bytes, key for tx bytes)}
    "c": {"cp0": (None, "c_primary_tx"), "cb0": (None, "c_backup_tx")},
    "r": {"rc0": ("r_backup_rx", None)},
    "s": {"sp0": ("s_primary_rx", None), "sb0": ("s_backup_rx", None)},
}


class Recorder:
    """Shared clock and event log for one run."""

    def __init__(self) -> None:
        self.t0 = time.monotonic()
        self.events: list[dict] = []
        self.progress: list[tuple[float, int, int]] = []   # (t, bytes received on this connection, connection id)
        self._lock = threading.Lock()

    def now(self) -> float:
        return round(time.monotonic() - self.t0, 6)

    def event(self, kind: str, detail: str = "", t: float | None = None, **extra) -> float:
        t = self.now() if t is None else t
        with self._lock:
            self.events.append({"t": t, "kind": kind, "detail": detail, **extra})
        return t


# ---------------------------------------------------------------------------- server
class LabServer(threading.Thread):
    def __init__(self, ns_path: str, rec: Recorder, cfg: LabConfig):
        super().__init__(daemon=True, name="lab-server")
        self.ns_path, self.rec, self.cfg = ns_path, rec, cfg
        self.ready, self.stop = threading.Event(), threading.Event()
        self.conns: dict[int, dict] = {}
        self.error: str | None = None
        self._active: socket.socket | None = None

    def bytes_on(self, cid: int) -> int:
        return self.conns.get(cid, {}).get("bytes", 0)

    def run(self) -> None:
        srv = None
        try:
            enter_netns(self.ns_path)
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind((SERVER_SVC, PORT))
            srv.listen(4)
            srv.settimeout(0.1)
            self.ready.set()
            cid = 0
            while not self.stop.is_set():
                try:
                    conn, peer = srv.accept()
                except socket.timeout:
                    continue
                cid += 1
                self._handle(conn, peer, cid)
        except Exception as exc:  # noqa: BLE001 - reported in the run record
            self.error = f"{type(exc).__name__}: {exc}"
            self.ready.set()
        finally:
            if srv:
                srv.close()

    def abort(self) -> None:
        self.stop.set()
        if self._active:
            try:
                self._active.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def _handle(self, conn: socket.socket, peer, cid: int) -> None:
        rec = self.rec
        info = {"id": cid, "peer": f"{peer[0]}:{peer[1]}", "accepted": rec.now(), "bytes": 0, "outcome": None,
                "ended": None, "sha256": None, "integrity_ok": None}
        self.conns[cid] = info
        self._active = conn
        rec.event("server_accept", f"connection {cid} accepted from {peer[0]}:{peer[1]}", conn=cid)
        conn.settimeout(self.cfg.timeout_s)
        h, got = hashlib.sha256(), 0
        try:
            ftype, payload = recv_frame(conn)
            if ftype != FILE_META:
                raise ProtocolError("expected FILE_META")
            meta = decode_json(payload)
            info["attempt"] = meta.get("attempt")
            while True:
                ftype, length = HEADER.unpack(recv_exact(conn, HEADER.size))
                if ftype == FILE_CHUNK:
                    remaining = length
                    while remaining:
                        chunk = conn.recv(min(remaining, 65536))
                        if not chunk:
                            raise ConnectionClosed(f"closed after {got} file bytes")
                        h.update(chunk)
                        got += len(chunk)
                        remaining -= len(chunk)
                        info["bytes"] = got
                        rec.progress.append((rec.now(), got, cid))
                elif ftype == FILE_END:
                    if length:
                        recv_exact(conn, length)
                    digest = h.hexdigest()
                    ok = got == meta.get("size") and digest == meta.get("sha256")
                    info.update(outcome="complete", sha256=digest, integrity_ok=ok, ended=rec.now())
                    rec.event("server_complete", f"connection {cid}: {got:,} bytes, SHA-256 {'matches' if ok else 'MISMATCH'}",
                              conn=cid)
                    send_json(conn, ACK, {"received": got, "sha256": digest, "integrity_ok": ok})
                    return
                else:
                    raise ProtocolError(f"unexpected frame type {ftype}")
        except socket.timeout:
            info.update(outcome="timeout", ended=rec.now())
            rec.event("server_timeout", f"connection {cid}: nothing received for {self.cfg.timeout_s:g} s", conn=cid)
        except (ConnectionClosed, ProtocolError, OSError) as exc:
            info.update(outcome=type(exc).__name__, ended=rec.now())
            rec.event("server_closed", f"connection {cid}: {type(exc).__name__}: {exc}", conn=cid)
        finally:
            self._active = None
            conn.close()


# ---------------------------------------------------------------------------- client
class LabClient(threading.Thread):
    def __init__(self, ns_path: str, rec: Recorder, cfg: LabConfig, data: bytes, name: str):
        super().__init__(daemon=True, name="lab-client")
        self.ns_path, self.rec, self.cfg, self.data, self.name = ns_path, rec, cfg, data, name
        self.sha256 = hashlib.sha256(data).hexdigest()
        self.done, self.stop = threading.Event(), threading.Event()
        self.attempts: list[dict] = []
        self.ack: dict | None = None
        self._sock: socket.socket | None = None

    def abort(self) -> None:
        self.stop.set()
        if self._sock:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def run(self) -> None:
        rec, cfg = self.rec, self.cfg
        try:
            enter_netns(self.ns_path)
            for attempt in range(1, cfg.retries + 2):
                if self.stop.is_set():
                    break
                a = {"attempt": attempt, "started": rec.now(), "local_port": None, "outcome": None,
                     "error_kind": None, "error": None, "handed_to_socket": 0, "ended": None}
                self.attempts.append(a)
                if attempt > 1:
                    rec.event("retry_started", f"new TCP connection (attempt {attempt}); the file is re-sent from byte 0",
                              attempt=attempt)
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self._sock = s
                try:
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, cfg.sndbuf_kib * 1024)
                    s.bind((CLIENT_SVC, 0))
                    s.settimeout(cfg.timeout_s)
                    s.connect((SERVER_SVC, PORT))
                    a["local_port"] = s.getsockname()[1]
                    rec.event("client_connected", f"attempt {attempt}: {CLIENT_SVC}:{a['local_port']} -> {SERVER_SVC}:{PORT}",
                              attempt=attempt)
                    send_json(s, FILE_META, {"name": self.name, "size": len(self.data), "sha256": self.sha256,
                                             "attempt": attempt})
                    step, rate, start = cfg.chunk_kib * 1024, cfg.rate_kib_s * 1024, time.monotonic()
                    for off in range(0, len(self.data), step):
                        due = start + off / rate
                        while (wait := due - time.monotonic()) > 0:
                            if self.stop.is_set():
                                raise ConnectionAbortedError("run stopped")
                            time.sleep(min(wait, 0.02))
                        piece = self.data[off:off + step]
                        send_frame(s, FILE_CHUNK, piece)
                        a["handed_to_socket"] = off + len(piece)
                    send_frame(s, FILE_END)
                    ftype, payload = recv_frame(s)
                    if ftype != ACK:
                        raise ProtocolError(f"expected ACK, got frame type {ftype}")
                    self.ack = decode_json(payload)
                    a.update(outcome="acknowledged", ended=rec.now())
                    rec.event("client_ack", f"attempt {attempt}: server acknowledged {self.ack.get('received', 0):,} bytes",
                              attempt=attempt)
                    break
                except (socket.timeout, TimeoutError):
                    a.update(outcome="failed", error_kind="timeout", ended=rec.now(),
                             error=f"no progress for {cfg.timeout_s:g} s (socket timeout)")
                except (ConnectionClosed, ProtocolError, OSError) as exc:
                    a.update(outcome="failed", error_kind=type(exc).__name__, error=str(exc), ended=rec.now())
                finally:
                    self._sock = None
                    s.close()
                rec.event("client_failed", f"attempt {attempt}: {a['error']}", attempt=attempt)
        except Exception as exc:  # noqa: BLE001
            self.attempts.append({"attempt": len(self.attempts) + 1, "outcome": "failed", "error_kind": "lab_error",
                                  "error": f"{type(exc).__name__}: {exc}", "ended": rec.now()})
        finally:
            self.done.set()


# ---------------------------------------------------------------------------- counters
class Sampler(threading.Thread):
    def __init__(self, ns_path: str, role: str, rec: Recorder, interval_s: float):
        super().__init__(daemon=True, name=f"sampler-{role}")
        self.ns_path, self.role, self.rec, self.interval = ns_path, role, rec, interval_s
        self.stop = threading.Event()
        self.samples: list[tuple[float, dict]] = []

    def run(self) -> None:
        try:
            enter_netns(self.ns_path)
            keys = COUNTER_KEYS[self.role]
            while not self.stop.is_set():
                raw = read_counters()
                vals = {}
                for ifc, (rx_key, tx_key) in keys.items():
                    rx, tx = raw.get(ifc, (None, None))
                    if rx_key and rx is not None:
                        vals[rx_key] = rx
                    if tx_key and tx is not None:
                        vals[tx_key] = tx
                self.samples.append((self.rec.now(), vals))
                self.stop.wait(self.interval)
        except Exception:  # noqa: BLE001 - missing samples show up as n/a
            pass


# ---------------------------------------------------------------------------- one run
def run_once(mode: str, data: bytes, name: str, cfg: LabConfig) -> dict:
    topo = Topology(mode, cfg.primary_delay_ms, cfg.backup_delay_ms)
    rec = Recorder()
    server = client = None
    samplers: list[Sampler] = []
    routes: list[dict] = []
    t_down = t_down_done = t_up = t_start = None
    fault_bytes = int(len(data) * cfg.fault_at_pct / 100) if mode != "baseline" else None
    lab_error = None
    try:
        topo.build()
        rec = Recorder()                                   # t = 0 once the network exists
        routes.append({"t": rec.now(), "label": "before the fault", **topo.route_get()})
        server = LabServer(topo.ns_path("s"), rec, cfg)
        server.start()
        if not server.ready.wait(5) or server.error:
            raise RuntimeError(f"server did not start: {server.error}")
        samplers = [Sampler(topo.ns_path(r), r, rec, cfg.sample_ms / 1000) for r in ("c", "r", "s")]
        for s in samplers:
            s.start()
        time.sleep(0.2)                                    # a few counter samples before any traffic
        client = LabClient(topo.ns_path("c"), rec, cfg, data, name)
        t_start = rec.event("transfer_start", f"upload of {len(data):,} bytes starts")
        client.start()
        deadline = time.monotonic() + cfg.max_run_s
        snap_during = snap_after = False
        while True:
            now = rec.now()
            if fault_bytes is not None and t_down is None and not client.done.is_set() and server.bytes_on(1) >= fault_bytes:
                t_cmd, at = rec.now(), server.bytes_on(1)
                topo.link_down()
                t_down_done = rec.now()
                t_down = rec.event("link_down", f"primary link down at {at:,} bytes received "
                                   f"({at / len(data) * 100:.1f}%)", t=t_cmd, applied=t_down_done, bytes=at)
            if t_down is not None and not snap_during and now >= t_down + 0.3:
                routes.append({"t": now, "label": "0.3 s after the link went down", **topo.route_get()})
                snap_during = True
            if t_down is not None and t_up is None and now >= t_down + cfg.outage_s:
                t_cmd = rec.now()
                topo.link_up()
                t_up = rec.event("link_up", "primary link restored (both ends up, primary route re-installed)",
                                 t=t_cmd, applied=rec.now())
            if t_up is not None and not snap_after and now >= t_up + 0.3:
                routes.append({"t": now, "label": "0.3 s after the link came back", **topo.route_get()})
                snap_after = True
            if client.done.is_set():
                if t_down is None or snap_after:
                    break
            if time.monotonic() > deadline:
                rec.event("run_limit", f"run stopped after the {cfg.max_run_s:g} s limit")
                client.abort()
                break
            time.sleep(0.002)
        time.sleep(0.2)                                    # trailing counter samples
    except Exception as exc:  # noqa: BLE001
        lab_error = f"{type(exc).__name__}: {exc}"
        rec.event("lab_error", lab_error)
    finally:
        if client:
            client.abort()
            client.join(5)
        if server:
            server.abort()
            server.join(5)
        for s in samplers:
            s.stop.set()
            s.join(2)
        topo.teardown()
        rec.event("cleanup", "sockets closed, namespaces and links removed")

    counters = sorted((x for s in samplers for x in s.samples), key=lambda x: x[0])
    return build_result(mode, data, name, cfg, rec, server, client, counters, routes, t_start, t_down, t_up,
                        fault_bytes, lab_error, topo.commands, t_down_done)


def build_result(mode, data, name, cfg, rec, server, client, counters, routes, t_start, t_down, t_up,
                 fault_bytes, lab_error, commands, t_down_done=None) -> dict:
    attempts = client.attempts if client else []
    conns = [server.conns[k] for k in sorted(server.conns)] if server else []
    completed = bool(client and client.ack)
    sha_client = hashlib.sha256(data).hexdigest()
    sha_server = client.ack.get("sha256") if completed else None
    sha_match = (sha_server == sha_client and bool(client.ack.get("integrity_ok"))) if completed else None
    first = attempts[0] if attempts else {}
    first_failed = first.get("outcome") == "failed"
    end_t = attempts[-1].get("ended") if attempts else None
    fault = mode != "baseline"
    fault_during = bool(t_down is not None and first.get("ended") and first["ended"] > t_down)

    st = analysis.stall(rec.progress, 1, t_fault=t_down if fault else None,
                        t_gave_up=first.get("ended") if first_failed else None)
    if fault and t_down is not None:
        # counter windows start once the link-down commands have completed in both namespaces
        w0 = t_down_done if t_down_done is not None else t_down
        window_end = t_up if t_up is not None else end_t
        backup_bytes = analysis.delta(counters, "c_backup_tx", w0, window_end) if window_end else None
        primary_bytes = analysis.delta(counters, "c_primary_tx", w0, window_end) if window_end else None
        first_backup = analysis.first_traffic(counters, "c_backup_tx", w0)
        if first_backup is not None and t_up is not None and first_backup > t_up:
            first_backup = None
    else:
        backup_bytes = analysis.delta(counters, "c_backup_tx", t_start or 0, end_t or rec.now()) if counters else None
        primary_bytes = analysis.delta(counters, "c_primary_tx", t_start or 0, end_t or rec.now()) if counters else None
        first_backup = None
    backup_used = None if backup_bytes is None else backup_bytes >= analysis.BACKUP_MIN_BYTES
    resumed_before_up = (st["end"] is not None and t_up is not None and st["end"] < t_up) if fault else None
    resumed_after_up = (round(st["end"] - t_up, 4) if fault and st["end"] is not None and t_up is not None
                        and st["end"] >= t_up else None)
    code, label = analysis.classify(fault, fault_during or not fault, completed, len(attempts), backup_used,
                                    resumed_before_up)
    if lab_error and not completed:
        code, label = "lab_error", f"Lab error: {lab_error}"

    derived = []
    if first_backup is not None:
        derived.append({"t": first_backup, "kind": "first_backup_traffic",
                        "detail": "first upload bytes seen on the client's backup interface", "derived": True})
    if fault and st["end"] is not None:
        derived.append({"t": st["end"], "kind": "progress_resumed",
                        "detail": f"server received bytes again after a {st['stall_s']:.2f} s pause", "derived": True})
    events = sorted(rec.events + derived, key=lambda e: e["t"])

    outcome = {
        "code": code, "label": label, "completed": completed, "sha256_match": sha_match,
        "connections": len(attempts), "retry_required": len(attempts) > 1,
        "same_connection": completed and len(attempts) == 1,
        "first_failure": first.get("error") if first_failed else None,
        "total_s": round(end_t - t_start, 4) if completed and end_t is not None and t_start is not None else None,
        "stall_s": st["stall_s"], "stall_start": st["start"], "stall_end": st["end"], "stall_resumed": st["resumed"],
        "fault_at_bytes": fault_bytes, "fault_during_transfer": fault_during if fault else None,
        "link_down_t": t_down, "link_up_t": t_up, "first_backup_traffic_t": first_backup,
        "backup_bytes": backup_bytes, "primary_bytes_during_outage": primary_bytes if fault else None,
        "backup_used": backup_used, "resumed_before_link_up": resumed_before_up,
        "resumed_after_link_up_s": resumed_after_up,
    }
    result = {
        "mode": mode, "label": RUN_LABELS[mode], "description": RUN_DESCRIPTIONS[mode],
        "file": {"name": name, "size": len(data), "sha256": sha_client},
        "server_sha256": sha_server, "config": cfg.to_dict(),
        "events": events, "progress": [list(p) for p in rec.progress], "counters": [[t, v] for t, v in counters],
        "routes": routes, "attempts": attempts, "server_connections": conns, "outcome": outcome,
        "commands": commands, "lab_error": lab_error,
    }
    result["summary"] = analysis.plain_summary(result)
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="RouteResQ upload-under-link-failure lab (Linux, root)")
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--name", default=None)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--config", default="{}", help="JSON with LabConfig fields")
    args = ap.parse_args(argv)
    cfg = LabConfig.from_dict(json.loads(args.config))
    data = args.input.read_bytes()
    check_file_size(len(data))
    name = args.name or args.input.name
    args.out.mkdir(parents=True, exist_ok=True)
    env = {"kernel": platform.release(), "python": platform.python_version(),
           "backend": os.environ.get("ROUTERESQ_NETLAB_BACKEND", "native")}
    for mode in cfg.runs:
        result = run_once(mode, data, name, cfg)
        result["environment"] = env
        (args.out / f"{mode}.json").write_text(json.dumps(result, indent=1))
        print(f"{mode}: {result['outcome']['label']} | {result['summary']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
