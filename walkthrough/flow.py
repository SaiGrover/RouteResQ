"""Guided-demo orchestration, independent of Streamlit.

Every stage runs inside its own error guard, verifies its own results instead of trusting
that a call returned, and records a status:

    not_started | success | partial | failed | stored

``stored`` means NS2 results were loaded from earlier runs rather than produced now; it is
never reported as a fresh measurement. Successful sub-results are kept when a sibling fails,
so a stage can be retried without losing what already worked.
"""
from __future__ import annotations

import traceback
from dataclasses import asdict
from pathlib import Path

from analysis import cause_report
from common.logging_setup import get_logger
from common.paths import DIAG_RESULTS_DIR
from common.storage import utc_now_iso

log = get_logger("walkthrough")

NOT_STARTED, SUCCESS, PARTIAL, FAILED, STORED = "not_started", "success", "partial", "failed", "stored"
STEPS = [("detect", "Detect"), ("diagnose", "Diagnose"), ("impact", "Analyse impact"),
         ("recovery", "Observe recovery"), ("transport", "Transport"), ("report", "Report")]
DEFAULT_TARGETS = ["8.8.8.8", "nonexistent.invalid", "192.0.2.1"]
FAILURE_SCENARIOS = ("link_failure_dv", "link_failure_static", "congestion")
HISTORY_ROOT: Path = DIAG_RESULTS_DIR   # tests point this elsewhere


def new_state() -> dict:
    return {"step": 0, "targets": list(DEFAULT_TARGETS), "scenarios": None,
            "detect": None, "impact": None, "transport": None, "started": utc_now_iso()}


def history():
    from diagnostics.history import DiagnosticHistory

    return DiagnosticHistory(HISTORY_ROOT)


def _err(exc: BaseException) -> str:
    log.warning("demo stage error: %s", "".join(traceback.format_exception(exc))[-1500:])
    return f"{type(exc).__name__}: {exc}"


# ------------------------------------------------------------------ verification
def verify_run(run) -> tuple[bool, str]:
    """A diagnostic run counts as a measurement if DNS failed with a recorded reason, or the
    ping output was parsed into probe counts. Anything else is an incomplete measurement."""
    if run.dns and not run.dns.success and not run.dns.is_ip_literal:
        return (True, f"DNS failure recorded ({run.dns.error_kind})") if run.dns.error_kind else (False, "DNS failed without a reason")
    p = run.ping
    if p is None:
        return False, "no ping result"
    if not p.parsed_ok or p.sent == 0:
        return False, "ping output could not be parsed: " + "; ".join(p.parse_warnings or ["no detail"])
    return True, f"{p.received}/{p.sent} echo replies parsed"


def verify_sim(res: dict) -> tuple[bool, str]:
    q = res.get("trace_quality", {})
    s = res.get("flows", {}).get("1", {}).get("summary", {})
    if res.get("run", {}).get("returncode", 0) != 0:
        return False, f"ns exited with code {res['run']['returncode']}"
    if not q.get("packet_events"):
        return False, "trace contains no packet events"
    if q.get("malformed_lines"):
        return False, f"{q['malformed_lines']} malformed trace lines"
    if not s.get("sent"):
        return False, "monitored flow sent no packets"
    return True, f"{q['total_lines']:,} trace lines, {s['delivered']}/{s['sent']} delivered"


# ------------------------------------------------------------------ stages
def run_detect(state: dict, targets: list[str] | None = None) -> dict:
    from diagnostics import engine
    from failure_analysis.rules import analyze_run

    targets = targets or state["targets"]
    state["targets"] = list(targets)
    h = history()
    per: dict[str, dict] = {}
    for t in targets:
        try:
            run = engine.run_diagnostics(t, ping_count=3, timeout_s=0.6, max_hops=8, label="guided demo")
            rep = analyze_run(run, baseline=h.baseline(t), previous=h.previous(t))
            h.save(run, rep)
            ok, why = verify_run(run)
            per[t] = {"ok": ok, "run_id": run.run_id, "verified": why, "error": None}
        except Exception as exc:  # noqa: BLE001 - reported per target
            per[t] = {"ok": False, "run_id": None, "verified": "", "error": _err(exc)}
    n_ok = sum(1 for v in per.values() if v["ok"])
    status = SUCCESS if n_ok == len(per) else PARTIAL if n_ok else FAILED
    state["detect"] = {"status": status, "per_target": per, "at": utc_now_iso()}
    return state["detect"]


def _stored_run(sid: str) -> tuple[Path | None, dict | None]:
    """Newest stored run found on disk. The run_dir recorded inside results.json is not used:
    it is the path on the machine that produced the run (e.g. a Windows path in the repo)."""
    from common.storage import read_json
    from simulation.runner import list_runs

    for d in list_runs(sid):
        res = read_json(d / "results.json")
        if res:
            return d, res
    return None, None


def run_impact(state: dict, scenario_ids: list[str] | None, ns2: dict) -> dict:
    from simulation import experiments
    from simulation.scenario import load_all_scenarios

    all_sc = load_all_scenarios()
    ids = scenario_ids or list(all_sc)
    state["scenarios"] = list(ids)
    per: dict[str, dict] = {}
    for sid in ids:
        entry = {"source": None, "run_dir": None, "ok": False, "verified": "", "error": None}
        if ns2.get("available"):
            try:
                res = experiments.run_and_analyze(all_sc[sid])
                ok, why = verify_sim(res)
                entry.update(source="fresh", run_dir=res["run"]["run_dir"], ok=ok, verified=why)
            except Exception as exc:  # noqa: BLE001
                entry["error"] = _err(exc)
        else:
            entry["error"] = "NS2 is not available on this server: " + str(ns2.get("detail", ""))[:200]
        if not entry["ok"]:
            stored_dir, stored = _stored_run(sid)
            if stored:
                ok, why = verify_sim(stored)
                entry.update(source="stored", run_dir=str(stored_dir), ok=ok,
                             verified=f"stored run started {stored['run'].get('started_at', '?')} - {why}")
        per[sid] = entry
    fresh = sum(1 for e in per.values() if e["ok"] and e["source"] == "fresh")
    stored = sum(1 for e in per.values() if e["ok"] and e["source"] == "stored")
    failed = len(per) - fresh - stored
    if failed == len(per):
        status = FAILED
    elif failed or (fresh and stored):
        status = PARTIAL
    elif stored:
        status = STORED
    else:
        status = SUCCESS
    state["impact"] = {"status": status, "per_scenario": per, "ns2": ns2.get("detail") if ns2.get("available") else None,
                       "ns2_version": ns2.get("version"), "at": utc_now_iso()}
    return state["impact"]


def run_transport(state: dict) -> dict:
    from communication import experiments as comm_exp
    from communication import failures
    from security import tls

    out: dict[str, dict] = {}
    try:
        r = comm_exp.run_comparison(total_bytes=400_000, datagram_payload=1024, trials=1)
        ok = all(t["ok"] and t["integrity_ok"] for t in r["tcp"]) and all(u["datagrams_sent"] for u in r["udp"])
        out["tcpudp"] = {"ok": ok, "result": r, "error": None,
                         "verified": "TCP integrity verified, UDP delivery measured" if ok else "TCP transfer not verified"}
    except Exception as exc:  # noqa: BLE001
        out["tcpudp"] = {"ok": False, "result": None, "error": _err(exc), "verified": ""}
    try:
        d = tls.run_secure_transfer(data=None, message="guided demo")
        ok = bool(d.file.ok and d.file.integrity_ok and d.file.tls_info)
        out["tls"] = {"ok": ok, "result": {"message": asdict(d.message), "file": asdict(d.file)}, "error": None,
                      "verified": f"{d.file.tls_info.version}, SHA-256 match" if ok else (d.file.error or "integrity not verified")}
    except Exception as exc:  # noqa: BLE001
        out["tls"] = {"ok": False, "result": None, "error": _err(exc), "verified": ""}
    try:
        f = failures.run_all()
        bad = [x["failure_type"] for x in f["records"] if not (x["observed_error_kind"] and x["resumed"])]
        out["drills"] = {"ok": not bad, "result": f, "error": None,
                         "verified": f"{len(f['records'])} faults detected and recovered" if not bad else
                         "not detected or not recovered: " + ", ".join(bad)}
    except Exception as exc:  # noqa: BLE001
        out["drills"] = {"ok": False, "result": None, "error": _err(exc), "verified": ""}
    n_ok = sum(1 for v in out.values() if v["ok"])
    state["transport"] = {"status": SUCCESS if n_ok == 3 else PARTIAL if n_ok else FAILED, "parts": out, "at": utc_now_iso()}
    return state["transport"]


# ------------------------------------------------------------------ derived state
def detect_records(state: dict) -> list[dict]:
    if not state.get("detect"):
        return []
    h = history()
    return [r for v in state["detect"]["per_target"].values() if v["run_id"] and (r := h.get_record(v["run_id"]))]


def sim_results(state: dict) -> dict[str, dict]:
    from common.storage import read_json

    out = {}
    for sid, e in ((state.get("impact") or {}).get("per_scenario") or {}).items():
        if e["ok"] and e["run_dir"]:
            res = read_json(Path(e["run_dir"]) / "results.json")
            if res:
                out[sid] = res
    return out


def step_status(state: dict, key: str) -> str:
    if key in ("detect", "impact", "transport"):
        return (state.get(key) or {}).get("status", NOT_STARTED)
    if key == "diagnose":
        d = state.get("detect")
        if not d:
            return NOT_STARTED
        return SUCCESS if detect_records(state) else FAILED
    if key == "recovery":
        imp = state.get("impact")
        if not imp:
            return NOT_STARTED
        per = imp["per_scenario"]
        usable = [per[s] for s in FAILURE_SCENARIOS if s in per and per[s]["ok"]]
        if not usable:
            return FAILED
        return SUCCESS if all(e["source"] == "fresh" for e in usable) else STORED if all(
            e["source"] == "stored" for e in usable) else PARTIAL
    if key == "report":
        done = [step_status(state, k) for k, _ in STEPS[:-1]]
        return NOT_STARTED if all(s == NOT_STARTED for s in done) else SUCCESS
    return NOT_STARTED


def evidence_chain(record: dict) -> dict:
    """Symptom -> measurement -> explanation -> limitations -> next check, for one live run,
    using the current rule engine on the stored measurements."""
    a = cause_report._current_analysis(record, None, None)
    c = cause_report.live_cause(record["run"], a)
    return {
        "target": record["run"]["target"],
        "symptoms": [f["title"] + f" ({f['level'].replace('_', ' ')})" for f in a["findings"]] or ["no fault symptom"],
        "measurements": a["observations"],
        "status": c["status"] if c else "n/a",
        "explanation": c["cause"] if c else "",
        "alternatives": c["alternatives"] if c else [],
        "limitations": (a["contradictions"] or []) + (["Several explanations remain possible; the cause is not confirmed."]
                                                      if c and c["status"] == cause_report.NOT_CONFIRMED else [])
        + ["ICMP-based tools only see what devices choose to answer."],
        "next_checks": (c["next_checks"] if c else []) or ["None needed"],
    }


def build_report(state: dict) -> str:
    """Markdown summary that states exactly which results are fresh, stored or failed."""
    lines = ["# RouteResQ guided demo report", "", f"Generated {utc_now_iso()}.", ""]
    statuses = {k: step_status(state, k) for k, _ in STEPS}
    fresh_all = all(statuses[k] == SUCCESS for k, _ in STEPS)
    if fresh_all:
        lines.append("**Every stage completed with fresh, verified measurements.**")
    else:
        notes = []
        if STORED in (statuses["impact"], statuses["recovery"]) or (state.get("impact") and any(
                e["source"] == "stored" for e in state["impact"]["per_scenario"].values())):
            notes.append("some NS2 results are **stored runs**, not fresh simulations")
        bad = [n for k, n in STEPS if statuses[k] in (FAILED, PARTIAL)]
        if bad:
            notes.append("these stages failed or completed partially: " + ", ".join(bad))
        missing = [n for k, n in STEPS if statuses[k] == NOT_STARTED]
        if missing:
            notes.append("not run: " + ", ".join(missing))
        lines.append("**Not every stage produced fresh, verified results** - " + "; ".join(notes) + ".")
    lines += ["", "## Stage status", "", "| Stage | Status | Verification |", "|---|---|---|"]
    for k, name in STEPS:
        detail = ""
        if k == "detect" and state.get("detect"):
            detail = "; ".join(f"{t}: {v['verified'] or v['error']}" for t, v in state["detect"]["per_target"].items())
        elif k == "impact" and state.get("impact"):
            detail = "; ".join(f"{s}: {e['source'] or 'none'} - {e['verified'] or e['error']}"
                               for s, e in state["impact"]["per_scenario"].items())
        elif k == "transport" and state.get("transport"):
            detail = "; ".join(f"{p}: {v['verified'] or v['error']}" for p, v in state["transport"]["parts"].items())
        lines.append(f"| {name} | {statuses[k]} | {detail.replace('|', '/')} |")

    recs = detect_records(state)
    sims = sim_results(state)
    drills = ((state.get("transport") or {}).get("parts", {}).get("drills") or {}).get("result")
    rows = cause_report.collect(recs, sims, drills, latest_per_target=True)
    if rows:
        lines += ["", "## Root causes identified", "", "| Source | Subject | Failure | Cause status | Root cause |",
                  "|---|---|---|---|---|"]
        for r in rows:
            src = r["source"] + (" (stored run)" if r["source"] == "NS2 simulation" and any(
                e["source"] == "stored" and r["subject"].endswith(s) for s, e in state["impact"]["per_scenario"].items()) else "")
            lines.append(f"| {src} | {r['subject']} | {r['failure']} | **{r['status']}** | "
                         f"{str(r['cause']).replace('|', '/')} |")
        lines += ["", "## Evidence chains (live diagnostics)", ""]
        for rec in recs:
            ch = evidence_chain(rec)
            lines += [f"### {ch['target']}", "",
                      "- **Symptom:** " + "; ".join(ch["symptoms"]),
                      "- **Measurement:** " + "; ".join(ch["measurements"]),
                      f"- **Explanation ({ch['status']}):** {ch['explanation']}",
                      "- **Limitations:** " + "; ".join(ch["limitations"]),
                      "- **Next check:** " + "; ".join(ch["next_checks"]), ""]
        lines += ["## Mechanism of each injected failure", ""]
        for r in rows:
            if r["status"] == cause_report.CONFIRMED and r["mechanism"]:
                lines.append(f"- **{r['subject']}:** {r['mechanism']}")
    errors = []
    for k in ("detect", "impact", "transport"):
        st_ = state.get(k) or {}
        items = st_.get("per_target") or st_.get("per_scenario") or st_.get("parts") or {}
        errors += [f"{k} / {name}: {v['error']}" for name, v in items.items() if v.get("error")]
    if errors:
        lines += ["", "## Errors encountered", "", *[f"- {x}" for x in errors]]
    lines.append("")
    return "\n".join(lines)
