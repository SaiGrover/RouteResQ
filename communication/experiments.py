"""Controlled TCP vs UDP experiment on the loopback interface (or a lab server).

Both protocols carry the same amount of application data. The numbers are measured
every time; the explanation is generated from the measurements, not assumed.
"""
from __future__ import annotations

import os
from statistics import mean

from common.paths import COMM_RESULTS_DIR
from common.storage import timestamp_slug, utc_now_iso, write_json
from communication.tcp_client import send_bytes
from communication.tcp_server import TCPTransferServer
from communication.udp import UDPReceiver, send_datagrams


def run_tcp_trial(total_bytes: int) -> dict:
    data = os.urandom(total_bytes)
    with TCPTransferServer("127.0.0.1", 0) as srv:
        r = send_bytes("127.0.0.1", srv.port, data, name="tcp_trial.bin")
    return {
        "protocol": "TCP",
        "ok": r.ok,
        "connection_setup_ms": r.connect_ms,
        "payload_bytes": total_bytes,
        "delivered_bytes": (r.server_ack or {}).get("received_bytes"),
        "delivered_pct": round(100 * (r.server_ack or {}).get("received_bytes", 0) / total_bytes, 2),
        "duration_s": r.duration_s,
        "throughput_mbps": r.throughput_mbps,
        "integrity_ok": r.integrity_ok,
        "error": r.error,
    }


def run_udp_trial(total_bytes: int, datagram_payload: int, rate_pps: float | None,
                  rcvbuf: int | None = None) -> dict:
    count = max(1, -(-total_bytes // datagram_payload))
    rx = UDPReceiver("127.0.0.1", 0, idle_timeout=1.0, rcvbuf=rcvbuf).start()
    snd = send_datagrams("127.0.0.1", rx.port, count, datagram_payload, rate_pps)
    rep = rx.wait(timeout=30)
    if rep is None:
        rx.stop()
        rep = rx.wait(timeout=5)
    delivered = rep.unique if rep else 0
    return {
        "protocol": "UDP",
        "ok": rep is not None and not rep.missing,
        "connection_setup_ms": 0.0,
        "payload_bytes": count * datagram_payload,
        "datagrams_sent": snd.sent,
        "datagrams_received": delivered,
        "delivered_bytes": delivered * datagram_payload,
        "delivered_pct": round(100 * delivered / count, 2),
        "missing": rep.missing_ranges if rep else "unknown",
        "duplicates": rep.duplicates if rep else None,
        "out_of_order": rep.out_of_order if rep else None,
        "sender_duration_s": snd.duration_s,
        "duration_s": rep.duration_s if rep else None,
        "throughput_mbps": rep.throughput_mbps if rep else None,
        "receiver_timed_out": rep.timed_out if rep else None,
        "integrity_ok": None,
        "error": "; ".join(snd.errors) or None,
    }


def explain(tcp: list[dict], udp: list[dict]) -> list[str]:
    lines = []
    setup = [t["connection_setup_ms"] for t in tcp if t["connection_setup_ms"] is not None]
    if setup:
        lines.append(
            f"TCP spent {mean(setup):.3f} ms on average establishing a connection (SYN, SYN-ACK, ACK) before any "
            "data; UDP sends its first datagram immediately because it is connectionless."
        )
    if all(t["ok"] for t in tcp):
        lines.append("Every TCP trial delivered 100% of the bytes, and the SHA-256 check matched: TCP retransmits "
                     "lost segments and delivers bytes in order.")
    else:
        lines.append("At least one TCP trial failed; see the error column.")
    lossy = [u for u in udp if u["delivered_pct"] < 100]
    if lossy:
        lines.append(
            f"{len(lossy)} of {len(udp)} UDP trial(s) lost datagrams (lowest delivery "
            f"{min(u['delivered_pct'] for u in udp)}%). The missing datagrams were never resent: UDP has no "
            "acknowledgements or retransmission, so the application has to detect gaps itself (sequence numbers)."
        )
    else:
        lines.append("All UDP datagrams arrived in these trials. UDP does not guarantee this; on a congested or "
                     "lossy path (or with a small receive buffer) datagrams would be lost without notice.")
    reord = sum(u["out_of_order"] or 0 for u in udp)
    if reord:
        lines.append(f"{reord} UDP datagram(s) arrived out of order; TCP would have re-ordered them.")
    tt = [t["throughput_mbps"] for t in tcp if t["throughput_mbps"]]
    ut = [u["throughput_mbps"] for u in udp if u["throughput_mbps"]]
    if tt and ut:
        faster = "TCP" if mean(tt) > mean(ut) else "UDP"
        lines.append(
            f"Measured throughput: TCP {mean(tt):.1f} Mb/s (until acknowledged) vs UDP {mean(ut):.1f} Mb/s "
            f"(at the receiver). {faster} was faster in this run, but this depends on datagram size, pacing, "
            "buffers and the host. Neither protocol is faster in general, and UDP's figure counts only what arrived."
        )
    return lines


def run_comparison(total_bytes: int = 1_000_000, datagram_payload: int = 1024, trials: int = 3,
                   udp_rate_pps: float | None = None, udp_rcvbuf: int | None = None, save: bool = True) -> dict:
    if not 1_000 <= total_bytes <= 50_000_000:
        raise ValueError("total_bytes must be between 1 kB and 50 MB")
    tcp = [run_tcp_trial(total_bytes) for _ in range(trials)]
    udp = [run_udp_trial(total_bytes, datagram_payload, udp_rate_pps, udp_rcvbuf) for _ in range(trials)]
    for i, r in enumerate(tcp + udp):
        r["trial"] = i % trials + 1
    result = {
        "timestamp": utc_now_iso(),
        "environment": "loopback (127.0.0.1) - real sockets, no simulated loss",
        "parameters": {"total_bytes": total_bytes, "datagram_payload": datagram_payload, "trials": trials,
                       "udp_rate_pps": udp_rate_pps, "udp_rcvbuf": udp_rcvbuf},
        "tcp": tcp,
        "udp": udp,
        "explanation": explain(tcp, udp),
    }
    if save:
        write_json(COMM_RESULTS_DIR / f"tcp_vs_udp_{timestamp_slug()}.json", result)
    return result


def as_rows(result: dict) -> list[dict]:
    return [dict(r) for r in result["tcp"] + result["udp"]]

