"""Run NS2 scenarios end to end: simulate -> parse -> analyse -> save -> report.

Usage::

    python -m simulation.experiments            # run all scenarios
    python -m simulation.experiments healthy congestion
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path

from analysis.comparison import compare, save_comparison
from analysis.experiment import analyze_experiment, save_experiment
from analysis.report import comparison_report, experiment_report, write_report
from common.logging_setup import get_logger
from common.paths import PROJECT_ROOT, SIM_RESULTS_DIR
from common.storage import read_json
from simulation.runner import NS2Backend, SimulationRun, detect_backend, list_runs, load_run, run_scenario
from simulation.scenario import Scenario, load_all_scenarios

log = get_logger("simulation.experiments")
REPORTS_DIR = PROJECT_ROOT / "reports"


def _run_meta(run: SimulationRun) -> dict:
    d = asdict(run)
    d.pop("stdout", None)
    d.pop("stderr", None)
    return {k: (str(v) if isinstance(v, Path) else v) for k, v in d.items()}


def analyze_run(scenario: Scenario, run: SimulationRun) -> dict:
    result = analyze_experiment(scenario, run.trace_file, run.events_file, _run_meta(run))
    save_experiment(result, run.run_dir)
    write_report(experiment_report(result), run.run_dir / "report.md")
    return result


def run_and_analyze(scenario: Scenario, backend: NS2Backend | None = None, out_root: Path = SIM_RESULTS_DIR) -> dict:
    run = run_scenario(scenario, out_root=out_root, backend=backend)
    return analyze_run(scenario, run)


def latest_result(scenario_id: str, out_root: Path = SIM_RESULTS_DIR) -> dict | None:
    for run_dir in list_runs(scenario_id, out_root):
        res = read_json(run_dir / "results.json")
        if res:
            return res
    return None


def reanalyze_latest(scenarios: dict[str, Scenario], out_root: Path = SIM_RESULTS_DIR) -> list[dict]:
    """Re-run the analysis on the newest stored trace of each scenario (no new simulation)."""
    results = []
    for sid, sc in scenarios.items():
        runs = list_runs(sid, out_root)
        if runs:
            results.append(analyze_run(sc, load_run(runs[0])))
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scenarios", nargs="*", help="scenario ids (default: all)")
    ap.add_argument("--reanalyze", action="store_true", help="re-analyse newest stored traces instead of simulating")
    ap.add_argument("--reports-dir", type=Path, default=REPORTS_DIR)
    args = ap.parse_args(argv)

    all_sc = load_all_scenarios()
    chosen = {k: v for k, v in all_sc.items() if not args.scenarios or k in args.scenarios}
    unknown = set(args.scenarios) - set(all_sc)
    if unknown:
        ap.error(f"unknown scenario(s): {', '.join(sorted(unknown))}")

    if args.reanalyze:
        results = reanalyze_latest(chosen)
    else:
        backend = detect_backend()
        print(f"NS2 backend: {backend.kind} ({backend.detail}), version {backend.version}")
        results = []
        for sid, sc in chosen.items():
            res = run_and_analyze(sc, backend)
            results.append(res)
            f = res["findings"]
            print(f"[{sc.label}] {sid}: {f['recovery']['outcome']} -> {res['run']['run_dir']}")

    for res in results:
        write_report(experiment_report(res), args.reports_dir / f"{res['scenario']['id']}.md")
    if len(results) > 1:
        rows = compare(results)
        save_comparison(rows, SIM_RESULTS_DIR)
        write_report(comparison_report(rows), args.reports_dir / "scenario_comparison.md")
        print(f"Comparison written to {SIM_RESULTS_DIR / 'scenario_comparison.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
