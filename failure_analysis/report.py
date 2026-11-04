"""Markdown report for one live diagnostic run (generated from the run and its analysis)."""
from __future__ import annotations

from diagnostics.models import DiagnosticRun
from failure_analysis.rules import AnalysisReport


def _root_cause(run: DiagnosticRun, a: AnalysisReport) -> list[str]:
    from analysis.cause_report import live_cause

    c = live_cause({"target": run.target, "timestamp": run.timestamp, "run_id": run.run_id}, a.to_dict())
    out = ["### Root cause", "", f"**Cause status: {c['status']}.** {c['cause']}", ""]
    if c["mechanism"]:
        out += [c["mechanism"], ""]
    if c["evidence"]:
        out += ["Evidence:", "", *[f"- {x}" for x in c["evidence"]], ""]
    if c["alternatives"]:
        out += ["Other possible causes: " + "; ".join(c["alternatives"]) + ".", ""]
    if c["next_checks"]:
        out += ["Checks needed to confirm: " + "; ".join(c["next_checks"]) + ".", ""]
    return out


def diagnostic_report(run: DiagnosticRun, a: AnalysisReport) -> str:
    out = [
        f"## Live diagnostics: {run.target}",
        "",
        f"*Live network measurement - run {run.run_id}, {run.timestamp}, {run.platform}"
        + (f", label '{run.label}'" if run.label else "") + "*",
        "",
        f"**Classification:** {', '.join(a.classifications)}",
        "",
        f"**Conclusion:** {a.conclusion}",
        "",
        *_root_cause(run, a),
        "### What was observed (confirmed)",
        "",
        *[f"- {o}" for o in a.observations],
        "",
    ]
    if a.findings:
        out += ["### Findings", "", "| Rule | Level | Category | Finding | Evidence |", "|---|---|---|---|---|"]
        out += [f"| {f.rule_id} | {f.level} | {f.category} | {f.title} | {'; '.join(f.evidence)} |" for f in a.findings]
        out.append("")
    if a.contradictions:
        out += ["### Contradictory evidence", "", *[f"- {c}" for c in a.contradictions], ""]
    if a.explanations:
        out += ["### Possible root causes", ""]
        for e in a.explanations:
            out += [f"**{e.cause}** ({e.level})", ""]
            if e.supporting_evidence:
                out.append("- Supporting evidence: " + "; ".join(e.supporting_evidence))
            if e.contrary_evidence:
                out.append("- Evidence against: " + "; ".join(e.contrary_evidence))
            if e.checks_to_confirm:
                out.append("- Checks to confirm: " + "; ".join(e.checks_to_confirm))
            if e.recommended_actions:
                out.append("- Recommended actions: " + "; ".join(e.recommended_actions))
            out.append("")
    if run.traceroute and run.traceroute.hops:
        out += ["### Traceroute", "", "| TTL | Address | RTTs (ms) |", "|---|---|---|"]
        out += [f"| {h.ttl} | {h.address or '*'} | {', '.join('*' if r is None else f'{r:g}' for r in h.rtts_ms)} |"
                for h in run.traceroute.hops]
        out.append("")
    out += ["### What can and cannot be concluded", "",
            "- Can: the observations above, which come directly from command output.",
            "- Cannot: the precise cause, unless an explanation is marked *likely* and its checks are done. "
            "ICMP-based tools only show what devices choose to answer.", ""]
    return "\n".join(out)
