"""Markdown experiment reports generated from analysed results (no hand-written numbers)."""
from __future__ import annotations

from pathlib import Path


def _v(x, nd=2) -> str:
    if x is None:
        return "n/a"
    if isinstance(x, float):
        return f"{x:.{nd}f}"
    return str(x)


def experiment_report(result: dict) -> str:
    sc = result["scenario"]
    f = result["findings"]
    run = result.get("run", {})
    ph = result["phases"]["1"]
    lines = [
        f"# {sc['name']}",
        "",
        f"*Simulated condition (NS2 {run.get('ns_version', '')}, backend: {run.get('backend', 'n/a')}, "
        f"run {run.get('run_dir', 'n/a')}). These are simulation results, not live-network measurements.*",
        "",
        sc["description"],
        "",
        "## What failed?",
        "",
        f["what_failed"],
        "",
        "## Root cause",
        "",
        ("**Cause status: No failure (control experiment).**" if sc["category"] == "healthy"
         else "**Cause status: Confirmed - the cause was injected deliberately in this experiment.**"),
        "",
        f"- **Cause:** {f['why']}",
        f"- **How it caused the failure (from the trace):** {f['explanation']}",
        "",
        "## What happened next?",
        "",
        *[f"- {x}" for x in f["observed_impact"]],
        "",
        f"**Routing behaviour:** {f['routing_behavior']}",
        "",
        "## How did performance change? (monitored flow 1)",
        "",
        "| Phase | Window (s) | Sent | Delivered | Loss % | Avg delay (ms) | Max delay (ms) | Jitter (ms) | Throughput (kb/s) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for name in ("before", "during", "after"):
        m = ph[name]
        lines.append(
            f"| {name} | {_v(m['window_start'])}-{_v(m['window_end'])} | {m['sent']} | {m['delivered']} | "
            f"{_v(m['loss_pct'])} | {_v(m['avg_delay_ms'])} | {_v(m['max_delay_ms'])} | {_v(m['jitter_ms'], 3)} | "
            f"{_v(m['throughput_kbps'], 1)} |"
        )
    if sc.get("phase_note"):
        lines += ["", f"*{sc['phase_note']}*"]
    lines += [
        "",
        "Loss and delay are assigned to a phase by **send time**; throughput by **receive time**.",
        "",
        "## Was recovery observed?",
        "",
        f"**{f['recovery']['outcome']}**",
        "",
        *[f"- {x}" for x in f["recovery"].get("evidence", [])],
        "",
        "## Timeline",
        "",
        "| t (s) | Source | Event | Description |",
        "|---|---|---|---|",
        *[f"| {e['time']:.4f} | {e['source']} | {e['event']} | {e['description']} |" for e in result["timeline"]],
        "",
        "## What can and cannot be concluded",
        "",
        *[f"- Can: {x}" for x in f.get("can_conclude", [])],
        *[f"- Cannot: {x}" for x in f.get("cannot_conclude", [])],
        "",
        f"Trace quality: {result['trace_quality']['total_lines']} lines, "
        f"{result['trace_quality']['malformed_lines']} malformed.",
        "",
    ]
    return "\n".join(lines)


def comparison_report(rows: list[dict]) -> str:
    cols = [
        ("label", "Scenario"), ("routing", "Routing"), ("sent", "Sent"), ("delivered", "Delivered"),
        ("loss_pct", "Loss %"), ("avg_delay_ms", "Avg delay ms"), ("max_delay_ms", "Max delay ms"),
        ("throughput_kbps", "Throughput kb/s"), ("during_throughput_kbps", "During-phase kb/s"),
        ("route_changes", "Route changes"), ("longest_delivery_gap_s", "Longest gap s"),
        ("max_queue_pkts", "Max queue"), ("recovery_outcome", "Recovery"),
    ]
    out = [
        "# NS2 scenario comparison",
        "",
        "*All values come from real NS2 traces of the four configured scenarios.*",
        "",
        "| " + " | ".join(c[1] for c in cols) + " |",
        "|" + "---|" * len(cols),
    ]
    for r in rows:
        out.append("| " + " | ".join(_v(r.get(k)) for k, _ in cols) + " |")
    out += ["", "## Root cause of each scenario", "",
            "The cause of every NS2 failure is known because it was injected; the mechanism is what the trace shows.", "",
            "| Scenario | Cause status | Root cause | How it affected traffic |", "|---|---|---|---|"]
    for r in rows:
        status = "No failure (control)" if r["category"] == "healthy" else "Confirmed (injected)"
        out.append(f"| {r['label']} {r['scenario']} | {status} | {r.get('known_cause', '')} | "
                   f"{str(r.get('mechanism', '')).replace('|', '/')} |")
    out.append("")
    return "\n".join(out)


def write_report(text: str, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
