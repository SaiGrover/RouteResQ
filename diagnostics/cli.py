"""Command-line diagnostics.

    python -m diagnostics.cli 8.8.8.8
    python -m diagnostics.cli 8.8.8.8 nonexistent.invalid 192.0.2.1 --report reports/live_diagnostics.md
    python -m diagnostics.cli 8.8.8.8 --set-baseline
"""
from __future__ import annotations

import argparse
from pathlib import Path

from common.storage import utc_now_iso
from diagnostics.authorization import TargetNotAllowed
from diagnostics.engine import run_diagnostics
from diagnostics.history import DiagnosticHistory
from failure_analysis.report import diagnostic_report
from failure_analysis.rules import analyze_run


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="RouteResQ live diagnostics")
    ap.add_argument("targets", nargs="+")
    ap.add_argument("--count", type=int, default=4)
    ap.add_argument("--timeout", type=float, default=1.0)
    ap.add_argument("--max-hops", type=int, default=15)
    ap.add_argument("--no-traceroute", action="store_true")
    ap.add_argument("--tcp-port", type=int)
    ap.add_argument("--label", default="")
    ap.add_argument("--set-baseline", action="store_true", help="store this run as the baseline for the target")
    ap.add_argument("--report", type=Path, help="write a Markdown report")
    args = ap.parse_args(argv)

    history = DiagnosticHistory()
    sections = [f"# RouteResQ live diagnostics report\n\nGenerated {utc_now_iso()}. All values are live "
                "measurements from commands executed on this machine.\n"]
    rc = 0
    for t in args.targets:
        try:
            baseline, previous = history.baseline(t), history.previous(t)
            run = run_diagnostics(t, ping_count=args.count, timeout_s=args.timeout, max_hops=args.max_hops,
                                  do_traceroute=not args.no_traceroute, tcp_port=args.tcp_port, label=args.label)
        except TargetNotAllowed as exc:
            print(f"[refused] {exc}")
            rc = 2
            continue
        rep = analyze_run(run, baseline=baseline, previous=previous)
        history.save(run, rep)
        if args.set_baseline:
            history.set_baseline(run.target, run.run_id)
        print(f"\n== {run.target}: {', '.join(rep.classifications)}")
        for o in rep.observations:
            print(f"   - {o}")
        print(f"   => {rep.conclusion}")
        sections.append(diagnostic_report(run, rep))
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text("\n".join(sections), encoding="utf-8")
        print(f"\nReport written to {args.report}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
