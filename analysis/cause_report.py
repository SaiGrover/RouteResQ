"""Root-cause register: one row per detected failure, across live diagnostics, NS2 experiments
and transport-layer drills, stating the cause and how certain it is.

Cause status vocabulary (never a percentage):

* ``Confirmed (injected)``  - the cause was introduced deliberately in a controlled experiment
                              (NS2 scenario or transport drill) and its effect is observed in the evidence
* ``Likely``                - live diagnostics: the rule engine rated one explanation *likely*
* ``Not confirmed``         - live diagnostics: several explanations remain *possible*
* ``No failure detected``   - nothing to explain

Usage::

    python -m analysis.cause_report            # writes reports/root_cause_report.md
"""
from __future__ import annotations

import argparse
from pathlib import Path

from common.storage import utc_now_iso

CONFIRMED, LIKELY, NOT_CONFIRMED, NO_FAILURE = "Confirmed (injected)", "Likely", "Not confirmed", "No failure detected"
STATUS_ORDER = {CONFIRMED: 0, LIKELY: 1, NOT_CONFIRMED: 2, NO_FAILURE: 3}


def live_cause(run: dict, analysis: dict) -> dict:
    """Cause entry for one live diagnostic run, taken from the rule engine's own output."""
    cats = analysis.get("classifications", [])
    problems = [c for c in cats if c != "Healthy / Reachable"]
    expl = analysis.get("explanations", [])
    likely = [x for x in expl if x["level"] == "likely"]
    possible = [x for x in expl if x["level"] == "possible"]
    row = {
        "source": "Live diagnostics",
        "subject": run["target"],
        "when": run.get("timestamp", ""),
        "ref": run.get("run_id", ""),
        "failure": ", ".join(problems) or "none",
        "observed": analysis.get("observations", []),
        "contradictions": analysis.get("contradictions", []),
        "conclusion": analysis.get("conclusion", ""),
    }
    if not problems:
        row.update(status=NO_FAILURE, cause="No failure to explain.", mechanism="", alternatives=[],
                   evidence=[], next_checks=[])
        if analysis.get("contradictions"):
            row["mechanism"] = "Reachable; some evidence disagreed and is listed under notes."
        return row
    if likely:
        top = likely[0]
        row.update(status=LIKELY, cause=top["cause"], evidence=top["supporting_evidence"],
                   alternatives=[x["cause"] for x in expl if x is not top], next_checks=top["checks_to_confirm"],
                   mechanism="Rated likely because it is the only explanation consistent with all collected evidence.")
    elif possible:
        row.update(status=NOT_CONFIRMED,
                   cause="Not determined - possible causes: " + "; ".join(x["cause"] for x in possible) + ".",
                   evidence=possible[0]["supporting_evidence"], alternatives=[x["cause"] for x in possible],
                   next_checks=list(dict.fromkeys(c for x in possible for c in x["checks_to_confirm"])),
                   mechanism="Several explanations fit the evidence equally well; the checks listed would separate them.")
    else:
        row.update(status=NOT_CONFIRMED, cause="Not determined: symptoms observed but no explanation rule applied.",
                   evidence=[e for f in analysis.get("findings", []) for e in f["evidence"]], alternatives=[],
                   next_checks=["Repeat the measurement with more probes", "Record a baseline for this destination"],
                   mechanism="")
    return row


def sim_cause(result: dict) -> dict:
    sc, f = result["scenario"], result["findings"]
    healthy = sc["category"] == "healthy"
    return {
        "source": "NS2 simulation",
        "subject": f"{sc.get('label', '')} {sc['id']}",
        "when": result.get("run", {}).get("started_at", ""),
        "ref": Path(str(result.get("run", {}).get("run_dir", ""))).name,
        "failure": "none (control)" if healthy else f"{f['failure_type']} - {f.get('affected_link') or ''}".strip(" -"),
        "status": NO_FAILURE if healthy else CONFIRMED,
        "cause": "No fault introduced." if healthy else sc["known_cause"],
        "mechanism": f["explanation"],
        "evidence": [f["what_failed"]] + f["observed_impact"][:3] + [f"Recovery: {f['recovery']['outcome']}"],
        "alternatives": [],
        "next_checks": [],
        "observed": [],
        "contradictions": [],
        "conclusion": f["recovery"]["outcome"],
    }


def transport_cause(rec: dict, when: str = "") -> dict:
    return {
        "source": "Transport drill",
        "subject": rec["failure_type"],
        "when": when,
        "ref": "",
        "failure": rec["observed_error_kind"] or "none observed",
        "status": CONFIRMED if rec["observed_error_kind"] else NO_FAILURE,
        "cause": rec["condition_created"],
        "mechanism": rec["impact"],
        "evidence": [f"Observed error: {rec['observed_error']}"] if rec["observed_error"] else [],
        "alternatives": [],
        "next_checks": [],
        "observed": [],
        "contradictions": [],
        "conclusion": f"{rec['restoration']} -> {'communication resumed' if rec['resumed'] else 'did not resume'}",
    }


SOURCE_ORDER = {"Live diagnostics": 0, "NS2 simulation": 1, "Transport drill": 2}


def _current_analysis(rec: dict, previous: dict | None, baseline: dict | None) -> dict:
    """Re-run the current rule engine on the stored measurements, so the register always reflects
    today's rules (a stored analysis may predate a rule fix)."""
    from diagnostics.models import run_from_dict
    from failure_analysis.rules import analyze_run

    prev = run_from_dict(previous["run"]) if previous else None
    base = run_from_dict(baseline) if baseline else None
    return analyze_run(run_from_dict(rec["run"]), baseline=base, previous=prev).to_dict()


def collect(history: list[dict], sims: dict[str, dict], drills: dict | None, latest_per_target: bool = True,
            baselines: dict[str, dict] | None = None, reanalyze: bool = True) -> list[dict]:
    """baselines: target -> stored run dict of that target's baseline (optional)."""
    rows: list[dict] = []
    baselines = baselines or {}
    prev_of: dict[int, dict | None] = {}
    last_seen: dict[str, dict] = {}
    for i, r in enumerate(history):
        prev_of[i] = last_seen.get(r["run"]["target"])
        last_seen[r["run"]["target"]] = r
    chosen = [i for i, r in enumerate(history) if not latest_per_target or last_seen[r["run"]["target"]] is r]
    for i in chosen:
        r = history[i]
        if reanalyze:
            base = baselines.get(r["run"]["target"])
            if base and base.get("run_id") == r["run"]["run_id"]:
                base = None
            analysis = _current_analysis(r, prev_of[i], base)
        else:
            analysis = r.get("analysis")
        if analysis:
            rows.append(live_cause(r["run"], analysis))
    rows += [sim_cause(r) for r in sims.values()]
    if drills:
        rows += [transport_cause(x, drills.get("timestamp", "")) for x in drills["records"]]
    return sorted(rows, key=lambda r: (SOURCE_ORDER[r["source"]], STATUS_ORDER[r["status"]], r["subject"]))


def _md(t: str) -> str:
    return str(t).replace("|", "/").replace("\n", " ")


def cause_report_markdown(rows: list[dict]) -> str:
    failures = [r for r in rows if r["status"] != NO_FAILURE]
    out = [
        "# RouteResQ root-cause report",
        "",
        f"*Generated {utc_now_iso()} from stored results. Live rows are measurements from the machine running RouteResQ; "
        "NS2 rows are simulations whose cause was injected; transport rows are drills on the loopback interface.*",
        "",
        "## Cause status",
        "",
        "- **Confirmed (injected)** - the cause was introduced on purpose in a controlled experiment and its effect is "
        "visible in the evidence.",
        "- **Likely** - live network: one explanation is consistent with all collected evidence.",
        "- **Not confirmed** - live network: several explanations fit; the next checks would separate them.",
        "",
        "## Summary",
        "",
        "| Source | Subject | Failure | Cause status | Root cause |",
        "|---|---|---|---|---|",
        *[f"| {r['source']} | {_md(r['subject'])} | {_md(r['failure'])} | **{r['status']}** | {_md(r['cause'])} |"
          for r in rows],
        "",
        f"{len(failures)} failure(s) explained out of {len(rows)} subject(s).",
        "",
        "## Details",
        "",
    ]
    for r in failures:
        out += [f"### {r['source']}: {r['subject']}", "",
                f"- **Failure:** {r['failure']}",
                f"- **Root cause ({r['status']}):** {r['cause']}"]
        if r["mechanism"]:
            out.append(f"- **How it caused the failure:** {r['mechanism']}")
        if r["evidence"]:
            out.append("- **Evidence:**")
            out += [f"  - {x}" for x in r["evidence"]]
        if r["alternatives"]:
            out.append("- **Other possible causes:** " + "; ".join(r["alternatives"]))
        if r["next_checks"]:
            out.append("- **Checks needed to confirm:** " + "; ".join(r["next_checks"]))
        if r["contradictions"]:
            out.append("- **Contradictory evidence:** " + " ".join(r["contradictions"]))
        if r["conclusion"]:
            out.append(f"- **Outcome:** {r['conclusion']}")
        out.append("")
    out += ["## Limits", "",
            "- A live cause marked *Not confirmed* is reported as such: ICMP-based tools only see what devices answer, "
            "so the engine never guesses between equally supported explanations.",
            "- NS2 causes are certain because they were configured; the mechanism is read from the simulator's trace.",
            ""]
    return "\n".join(out)


def _baselines(history: list[dict]) -> dict[str, dict]:
    from common.paths import DIAG_RESULTS_DIR
    from common.storage import read_json

    ids = read_json(DIAG_RESULTS_DIR / "baselines.json", {}) or {}
    by_id = {r["run"]["run_id"]: r["run"] for r in history}
    return {t: by_id[i] for t, i in ids.items() if i in by_id}


def main(argv: list[str] | None = None) -> int:
    from common.paths import COMM_RESULTS_DIR, DIAG_RESULTS_DIR, PROJECT_ROOT
    from common.storage import read_json, read_jsonl
    from simulation.experiments import latest_result
    from simulation.scenario import load_all_scenarios

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=PROJECT_ROOT / "reports" / "root_cause_report.md")
    ap.add_argument("--all-runs", action="store_true", help="include every live run, not only the latest per destination")
    args = ap.parse_args(argv)
    history = read_jsonl(DIAG_RESULTS_DIR / "history.jsonl")
    sims = {s: r for s in load_all_scenarios() if (r := latest_result(s))}
    drill_files = sorted(COMM_RESULTS_DIR.glob("failure_demo_*.json"), key=lambda p: p.stat().st_mtime) if COMM_RESULTS_DIR.exists() else []
    drills = read_json(drill_files[-1]) if drill_files else None
    rows = collect(history, sims, drills, latest_per_target=not args.all_runs, baselines=_baselines(history))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(cause_report_markdown(rows), encoding="utf-8")
    print(f"{len(rows)} rows -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
