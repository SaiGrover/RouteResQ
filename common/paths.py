"""Central filesystem locations used across RouteResQ."""
from __future__ import annotations

from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
CONFIG_DIR: Path = PROJECT_ROOT / "config"
RESULTS_DIR: Path = PROJECT_ROOT / "results"
DIAG_RESULTS_DIR: Path = RESULTS_DIR / "diagnostics"
SIM_RESULTS_DIR: Path = RESULTS_DIR / "simulation"
COMM_RESULTS_DIR: Path = RESULTS_DIR / "communication"
LOG_DIR: Path = RESULTS_DIR / "logs"
CERT_DIR: Path = RESULTS_DIR / "certs"
SCENARIO_DIR: Path = PROJECT_ROOT / "simulation" / "scenarios"
TCL_SCRIPT: Path = PROJECT_ROOT / "simulation" / "tcl" / "routeresq.tcl"


def ensure_dirs() -> None:
    """Create every output directory that the application writes to."""
    for d in (RESULTS_DIR, DIAG_RESULTS_DIR, SIM_RESULTS_DIR, COMM_RESULTS_DIR, LOG_DIR, CERT_DIR):
        d.mkdir(parents=True, exist_ok=True)
