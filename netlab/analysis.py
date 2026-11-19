"""Turn the events recorded during one run into measured outcomes.

Pure functions only (no sockets, no namespaces), so they are unit-tested on any OS.

Definitions used everywhere (app, report, slides):

* **Receiver progress** - file bytes the *server* has read from the TCP connection, timestamped by
  the server. Bytes the client handed to its socket may still be buffered, so they are not used.
* **Stall duration** - the longest interval during which the server's received byte count did not
  increase. In a fault run only intervals that end after the link went down are considered (the
  pause caused by the fault); in the baseline the whole transfer is considered. If progress never
  resumed on that connection, the stall runs until the connection was given up.
* **Backup path used** - the client's backup interface sent at least ``BACKUP_MIN_BYTES`` more
  bytes during the outage than before it. Interface counters are direct evidence; a completed
  upload on its own says nothing about the path it took.
* **Same connection** - the upload finished on the TCP connection it started on (same client
  port, connection id 1). A **retry** is any later connection; it re-sends the file from byte 0.
"""
from __future__ import annotations

BACKUP_MIN_BYTES = 16 * 1024   # well above ARP/neighbour chatter, well below one second of upload


def increments(progress: list, conn: int | None = None) -> list[tuple[float, int]]:
    """(t, bytes) points where the server's received byte count went up, for one connection."""
    out, last = [], None
    for t, b, c in progress:
        if conn is not None and c != conn:
            continue
        if last is None or b > last:
            out.append((t, b))
            last = b
    return out


def stall(progress: list, conn: int, t_fault: float | None = None, t_gave_up: float | None = None) -> dict:
    """Longest pause in receiver progress (see module docstring)."""
    none = {"stall_s": None, "start": None, "end": None, "resumed": None}
    pts = increments(progress, conn)
    if not pts:
        return none
    gaps = [(a, b) for (a, _), (b, _) in zip(pts, pts[1:]) if t_fault is None or b > t_fault]
    best = max(gaps, key=lambda g: g[1] - g[0], default=None)
    if t_gave_up is not None:
        # the connection was given up: the time from its last received byte is an open-ended pause
        last = pts[-1][0]
        open_gap = t_gave_up - last
        if open_gap > 0 and (best is None or open_gap > best[1] - best[0]):
            return {"stall_s": round(open_gap, 4), "start": last, "end": None, "resumed": False}
    if best is None:
        return none
    return {"stall_s": round(best[1] - best[0], 4), "start": best[0], "end": best[1], "resumed": True}


def value_at(counters: list, key: str, t: float) -> int | None:
    """Counter value from the last sample at or before t."""
    v = None
    for ts, vals in counters:
        if ts > t:
            break
        if key in vals:
            v = vals[key]
    return v


def value_from(counters: list, key: str, t: float) -> int | None:
    """Counter value from the first sample at or after t."""
    for ts, vals in counters:
        if ts >= t and key in vals:
            return vals[key]
    return None


def delta(counters: list, key: str, t0: float, t1: float) -> int | None:
    """Growth of a counter inside [t0, t1]: from the first sample at/after t0 to the last at/before t1,
    so bytes counted before t0 never leak into the window."""
    a, b = value_from(counters, key, t0), value_at(counters, key, t1)
    return None if a is None or b is None else max(0, b - a)


def first_traffic(counters: list, key: str, t_from: float, min_bytes: int = BACKUP_MIN_BYTES) -> float | None:
    """Time of the first sample after t_from where ``key`` has grown by at least min_bytes."""
    base = value_from(counters, key, t_from)
    if base is None:
        return None
    for ts, vals in counters:
        if ts > t_from and key in vals and vals[key] - base >= min_bytes:
            return ts
    return None


def classify(fault: bool, fault_during_transfer: bool, completed: bool, connections: int,
             backup_used: bool | None, resumed_before_link_up: bool | None) -> tuple[str, str]:
    """(code, short label) for one run."""
    if fault and not fault_during_transfer:
        return "fault_not_during_transfer", "Invalid: the fault did not hit an upload in progress"
    if not completed:
        return "failed", "Failed: the upload did not complete"
    if connections > 1:
        return "completed_after_retry", "Failed, then completed on a retry (new TCP connection)"
    if not fault:
        return "completed", "Completed normally"
    if backup_used and resumed_before_link_up:
        return "continued_on_backup", "Continued on the backup path (same TCP connection)"
    return "stalled_then_resumed", "Stalled until the link returned, then resumed (same TCP connection)"


def _mib(n: int | None) -> str:
    return "n/a" if n is None else f"{n / 1048576:.2f} MiB"


def plain_summary(r: dict) -> str:
    """One paragraph a non-specialist can follow, built only from measured values."""
    o, f = r["outcome"], r["file"]
    code = o["code"]
    if code == "completed":
        return (f"No fault was injected. The server received all {_mib(f['size'])} in {o['total_s']:.2f} s on the "
                f"primary link; its longest pause was {o['stall_s']:.3f} s. "
                + ("The SHA-256 fingerprints matched." if o["sha256_match"] else "The SHA-256 fingerprints did NOT match."))
    if code == "fault_not_during_transfer":
        return "The upload finished before the fault point, so this run says nothing about link failure."
    if o.get("fault_at_bytes") is None:          # no fault was injected, but the upload did not complete
        return f"No fault was injected, yet the upload did not complete ({o.get('first_failure') or code})."
    head = (f"The primary link went down after the server had received {o['fault_at_bytes'] / f['size'] * 100:.0f}% "
            f"of the file ({_mib(o['fault_at_bytes'])}). ")
    stall_txt = ("The server stopped receiving bytes for "
                 + (f"{o['stall_s']:.2f} s. " if o["stall_s"] is not None else "an unmeasured time. "))
    sha = "and the file matched (SHA-256)." if o["sha256_match"] else "but the file did NOT match."
    if code == "continued_on_backup":
        return (head + stall_txt + f"The same TCP connection then continued on the backup path "
                f"({_mib(o['backup_bytes'])} left through the client's backup interface during the outage), " + sha)
    if code == "stalled_then_resumed":
        after = o.get("resumed_after_link_up_s")
        when = (f"{after:.2f} s after the link came back" if after is not None and after >= 0
                else "after the link came back")
        via = ("No upload traffic used the backup path, because forwarding had no route to it. "
               if not o.get("backup_used") else "")
        return head + stall_txt + via + f"The same TCP connection resumed {when}, " + sha
    if code == "completed_after_retry":
        return (head + f"The first connection failed ({o.get('first_failure') or 'error'}). The client opened a new "
                f"TCP connection and re-sent the whole file from byte 0 ({o['connections']} connections in total), " + sha)
    return head + f"The upload did not complete ({o.get('first_failure') or 'error'})."
