"""Run the communication experiments and write reports/communication.md.

    python -m communication.report
"""
from __future__ import annotations

import argparse
from pathlib import Path

from common.paths import PROJECT_ROOT
from common.storage import utc_now_iso
from communication.experiments import run_comparison
from communication.failures import run_all
from security.tls import run_secure_transfer


def build_report(cmp: dict, fails: dict, tls) -> str:
    out = [
        "# RouteResQ communication experiments",
        "",
        f"*Generated {utc_now_iso()}. Real sockets on the loopback interface (127.0.0.1); failures are "
        "injected locally and labelled as such.*",
        "",
        "## TCP vs UDP",
        "",
        f"Parameters: {cmp['parameters']}",
        "",
        "| Protocol | Trial | Setup (ms) | Delivered % | Duration (s) | Throughput (Mb/s) | Integrity | Missing |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in cmp["tcp"] + cmp["udp"]:
        out.append(f"| {r['protocol']} | {r['trial']} | {r['connection_setup_ms']} | {r['delivered_pct']} | "
                   f"{r['duration_s']} | {r['throughput_mbps']} | {r.get('integrity_ok')} | {r.get('missing', '-')} |")
    out += ["", "**Interpretation (generated from the measurements):**", "", *[f"- {x}" for x in cmp["explanation"]], ""]
    f = tls.file
    out += [
        "## TLS secure transfer",
        "",
        f"- TLS version / cipher: {f.tls_info.version} / {f.tls_info.cipher} ({f.tls_info.cipher_bits} bits)"
        if f.tls_info else "- TLS handshake failed",
        f"- Server certificate: {f.tls_info.peer_subject} issued by {f.tls_info.peer_issuer}" if f.tls_info else "",
        f"- File: {f.payload_bytes} bytes, client SHA-256 `{f.local_sha256}`",
        f"- Server SHA-256 `{(f.server_ack or {}).get('sha256')}` -> integrity verified: {f.integrity_ok}",
        "",
        *[f"  {i + 1}. {s}" for i, s in enumerate(f.steps)],
        "",
        "## Communication failure demonstrations",
        "",
        "| Failure | Observed error | Resumed after restore |",
        "|---|---|---|",
    ]
    for r in fails["records"]:
        out.append(f"| {r['failure_type']} | {r['observed_error_kind']}: {(r['observed_error'] or '')[:90]} | "
                   f"{'yes' if r['resumed'] else 'no'} |")
    out.append("")
    for r in fails["records"]:
        out += [f"### {r['failure_type']}", "",
                f"- **Condition (what failed / why):** {r['condition_created']}",
                f"- **Observed error:** `{r['observed_error']}`",
                f"- **Impact (what happened next):** {r['impact']}",
                f"- **Restoration:** {r['restoration']}",
                f"- **Recovery observed:** {'yes' if r['resumed'] else 'no'} - {r['resume_detail']}", ""]
    out += ["## What can and cannot be concluded", "",
            "- Can: how each protocol behaved on this host and how the application detected each failure.",
            "- Cannot: performance on a real network path; loopback has no propagation delay and almost no loss.",
            ""]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=PROJECT_ROOT / "reports" / "communication.md")
    ap.add_argument("--bytes", type=int, default=1_000_000)
    ap.add_argument("--trials", type=int, default=3)
    args = ap.parse_args(argv)
    cmp = run_comparison(args.bytes, 1024, args.trials)
    fails = run_all()
    tls = run_secure_transfer()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(build_report(cmp, fails, tls), encoding="utf-8")
    print(f"Report written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
