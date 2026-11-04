"""Cross-scenario comparison built only from analysed NS2 results."""
from __future__ import annotations

from pathlib import Path

from common.storage import write_csv, write_json


def comparison_row(result: dict) -> dict:
    sc = result["scenario"]
    f = result["findings"]
    overall = result["flows"]["1"]["summary"]
    ph = result["phases"]["1"]
    gaps = result["delivery_gaps"]
    return {
        "scenario": sc["id"],
        "label": sc.get("label", ""),
        "category": sc["category"],
        "routing": sc["effective_params"]["routing"],
        "sent": overall["sent"],
        "delivered": overall["delivered"],
        "lost": overall["lost"],
        "loss_pct": overall["loss_pct"],
        "avg_delay_ms": overall["avg_delay_ms"],
        "max_delay_ms": overall["max_delay_ms"],
        "jitter_ms": overall["jitter_ms"],
        "throughput_kbps": overall["throughput_kbps"],
        "before_throughput_kbps": ph["before"]["throughput_kbps"],
        "during_throughput_kbps": ph["during"]["throughput_kbps"],
        "after_throughput_kbps": ph["after"]["throughput_kbps"],
        "during_loss_pct": ph["during"]["loss_pct"],
        "during_avg_delay_ms": ph["during"]["avg_delay_ms"],
        "route_changes": len(result["route_changes"]),
        "longest_delivery_gap_s": max((g["duration_s"] for g in gaps), default=0.0),
        "max_queue_pkts": (result["queue_stats"].get(result["bottleneck_link"]) or {}).get("max_queue_pkts")
        if result["bottleneck_link"] else None,
        "recovery_outcome": f["recovery"]["outcome"],
        "known_cause": sc["known_cause"],
        "mechanism": f["explanation"],
    }


def compare(results: list[dict]) -> list[dict]:
    rows = [comparison_row(r) for r in results]
    base = next((r for r in rows if r["category"] == "healthy"), None)
    for r in rows:
        if base and base["throughput_kbps"] and r["throughput_kbps"] is not None:
            r["throughput_vs_baseline_pct"] = round(100 * (r["throughput_kbps"] - base["throughput_kbps"]) / base["throughput_kbps"], 1)
        else:
            r["throughput_vs_baseline_pct"] = None
        if base and base["avg_delay_ms"] and r["avg_delay_ms"] is not None:
            r["delay_vs_baseline_pct"] = round(100 * (r["avg_delay_ms"] - base["avg_delay_ms"]) / base["avg_delay_ms"], 1)
        else:
            r["delay_vs_baseline_pct"] = None
    return rows


def save_comparison(rows: list[dict], out_dir: Path) -> dict[str, Path]:
    return {
        "json": write_json(out_dir / "scenario_comparison.json", rows),
        "csv": write_csv(out_dir / "scenario_comparison.csv", rows),
    }
