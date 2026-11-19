"""Cached readers for stored results. Caches are keyed on file modification times, so a
new NS2 run or diagnostic run is picked up immediately without stale data."""
from __future__ import annotations

import shutil
from pathlib import Path

import streamlit as st

from common.paths import COMM_RESULTS_DIR, DIAG_RESULTS_DIR, SIM_RESULTS_DIR
from common.storage import read_json, read_jsonl
from simulation.runner import list_runs
from simulation.scenario import load_all_scenarios


@st.cache_data(ttl=3600, show_spinner="Checking the NS2 installation...")  # docker calls are slow; check hourly
def ns2_status() -> dict:
    from simulation.runner import backend_status

    return backend_status()


@st.cache_data(show_spinner=False)
def tools_status() -> dict:
    from diagnostics.commands import IS_WINDOWS

    tr = "tracert" if IS_WINDOWS else "traceroute"
    return {"ping": shutil.which("ping") is not None, "traceroute": shutil.which(tr) is not None
            or (not IS_WINDOWS and shutil.which("tracepath") is not None), "traceroute_cmd": tr}


@st.cache_resource
def scenarios():
    return load_all_scenarios()


@st.cache_data(max_entries=64, show_spinner=False)
def _load(path: str, mtime: float) -> dict | None:
    return read_json(Path(path))


def result_at(run_dir: Path) -> dict | None:
    p = run_dir / "results.json"
    return _load(str(p), p.stat().st_mtime) if p.exists() else None


def runs(sid: str) -> list[Path]:
    return [r for r in list_runs(sid) if (r / "results.json").exists()]


def latest(sid: str) -> dict | None:
    rs = runs(sid)
    return result_at(rs[0]) if rs else None


def latest_all() -> dict[str, dict]:
    return {sid: r for sid in scenarios() if (r := latest(sid))}


def diag_records() -> list[dict]:
    return read_jsonl(DIAG_RESULTS_DIR / "history.jsonl")


def latest_comm(prefix: str) -> dict | None:
    if not COMM_RESULTS_DIR.exists():
        return None
    files = sorted(COMM_RESULTS_DIR.glob(f"{prefix}_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return _load(str(files[0]), files[0].stat().st_mtime) if files else None


def reports() -> list[Path]:
    from common.paths import PROJECT_ROOT

    d = PROJECT_ROOT / "reports"
    return sorted(d.glob("*.md")) if d.exists() else []


def sim_dir() -> Path:
    return SIM_RESULTS_DIR


def cause_rows(latest_per_target: bool = True) -> list[dict]:
    """Root-cause register built from every stored result (see analysis.cause_report)."""
    from analysis.cause_report import _baselines, collect

    hist = diag_records()
    return collect(hist, latest_all(), latest_comm("failure_demo"), latest_per_target, baselines=_baselines(hist),
                   upload=upload_latest())


# ------------------------------------------------------------------ upload under link failure (netlab)
@st.cache_data(ttl=600, show_spinner="Checking the test-network backend...")
def netlab_status() -> dict:
    from netlab.runner import backend_status

    return backend_status()


@st.cache_data(max_entries=16, show_spinner=False)
def _upload_run(path: str, mtime: float) -> dict | None:
    from netlab.runner import load_run

    return load_run(Path(path))


def upload_run(run_dir: Path) -> dict | None:
    meta = run_dir / "meta.json"
    return _upload_run(str(run_dir), meta.stat().st_mtime) if meta.exists() else None


def upload_runs() -> list[Path]:
    """Live runs (newest first), then the recorded run."""
    from netlab.runner import RECORDED_DIR, list_runs

    return list_runs() + ([RECORDED_DIR] if (RECORDED_DIR / "meta.json").exists() else [])


def upload_latest() -> dict | None:
    for d in upload_runs():
        if r := upload_run(d):
            return r
    return None
