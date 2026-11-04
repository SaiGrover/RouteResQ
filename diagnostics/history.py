"""Diagnostic history (JSON-lines), baselines and run-to-run comparison."""
from __future__ import annotations

from pathlib import Path

from common.paths import DIAG_RESULTS_DIR
from common.storage import append_jsonl, read_json, read_jsonl, write_csv, write_json
from diagnostics.models import DiagnosticRun, run_from_dict
from failure_analysis.rules import AnalysisReport, route_signature


class DiagnosticHistory:
    def __init__(self, root: Path = DIAG_RESULTS_DIR):
        self.root = root
        self.history_file = root / "history.jsonl"
        self.baseline_file = root / "baselines.json"

    # ---- storage ----
    def save(self, run: DiagnosticRun, report: AnalysisReport | None = None) -> None:
        rec = {"run": run.to_dict(), "analysis": report.to_dict() if report else None}
        append_jsonl(self.history_file, rec)

    def records(self, target: str | None = None) -> list[dict]:
        recs = read_jsonl(self.history_file)
        if target:
            recs = [r for r in recs if r["run"]["target"] == target]
        return recs

    def runs(self, target: str | None = None) -> list[DiagnosticRun]:
        return [run_from_dict(r["run"]) for r in self.records(target)]

    def get(self, run_id: str) -> DiagnosticRun | None:
        for r in self.records():
            if r["run"]["run_id"] == run_id:
                return run_from_dict(r["run"])
        return None

    def get_record(self, run_id: str) -> dict | None:
        return next((r for r in self.records() if r["run"]["run_id"] == run_id), None)

    def targets(self) -> list[str]:
        seen: list[str] = []
        for r in self.records():
            t = r["run"]["target"]
            if t not in seen:
                seen.append(t)
        return seen

    def previous(self, target: str, before_run_id: str | None = None) -> DiagnosticRun | None:
        runs = self.runs(target)
        if before_run_id:
            ids = [r.run_id for r in runs]
            if before_run_id in ids:
                runs = runs[: ids.index(before_run_id)]
        return runs[-1] if runs else None

    # ---- baselines ----
    def set_baseline(self, target: str, run_id: str) -> None:
        data = read_json(self.baseline_file, {}) or {}
        data[target] = run_id
        write_json(self.baseline_file, data)

    def clear_baseline(self, target: str) -> None:
        data = read_json(self.baseline_file, {}) or {}
        data.pop(target, None)
        write_json(self.baseline_file, data)

    def baseline(self, target: str) -> DiagnosticRun | None:
        run_id = (read_json(self.baseline_file, {}) or {}).get(target)
        return self.get(run_id) if run_id else None

    def export_csv(self, path: Path | None = None) -> Path:
        rows = [summary_row(r["run"], r.get("analysis")) for r in self.records()]
        return write_csv(path or self.root / "history.csv", rows)


def summary_row(run: dict, analysis: dict | None) -> dict:
    p = run.get("ping") or {}
    tr = run.get("traceroute") or {}
    return {
        "run_id": run["run_id"],
        "timestamp": run["timestamp"],
        "target": run["target"],
        "label": run.get("label", ""),
        "dns_ok": (run.get("dns") or {}).get("success"),
        "sent": p.get("sent"),
        "received": p.get("received"),
        "loss_pct": p.get("loss_pct"),
        "avg_rtt_ms": p.get("avg_ms"),
        "stdev_rtt_ms": p.get("stdev_ms"),
        "traceroute_reached": tr.get("reached_destination") if tr else None,
        "traceroute_hops": len(tr.get("hops", [])) if tr else None,
        "classifications": "; ".join((analysis or {}).get("classifications", [])),
    }


def _delta(a, b):
    if a is None or b is None:
        return None
    return round(b - a, 3)


def compare_runs(old: DiagnosticRun, new: DiagnosticRun) -> dict:
    """Field-by-field comparison of two runs against the same destination."""
    op, np_ = old.ping, new.ping
    rows = []

    def add(metric, a, b):
        rows.append({"metric": metric, "earlier": a, "current": b,
                     "change": _delta(a, b) if isinstance(a, (int, float)) and isinstance(b, (int, float)) else
                     ("same" if a == b else "changed")})

    add("DNS resolved", old.dns.success if old.dns else None, new.dns.success if new.dns else None)
    add("Echo replies", op.received if op else None, np_.received if np_ else None)
    add("Packet loss %", op.loss_pct if op else None, np_.loss_pct if np_ else None)
    add("Average RTT ms", op.avg_ms if op else None, np_.avg_ms if np_ else None)
    add("Max RTT ms", op.max_ms if op else None, np_.max_ms if np_ else None)
    add("RTT std-dev ms", op.stdev_ms if op else None, np_.stdev_ms if np_ else None)
    add("Traceroute reached", old.traceroute.reached_destination if old.traceroute else None,
        new.traceroute.reached_destination if new.traceroute else None)
    old_path, new_path = route_signature(old.traceroute), route_signature(new.traceroute)
    return {
        "earlier": {"run_id": old.run_id, "timestamp": old.timestamp},
        "current": {"run_id": new.run_id, "timestamp": new.timestamp},
        "metrics": rows,
        "path_earlier": old_path,
        "path_current": new_path,
        "path_changed": bool(old_path and new_path and old_path != new_path),
        "status_earlier": "reachable" if op and op.received else "unreachable",
        "status_current": "reachable" if np_ and np_.received else "unreachable",
    }
