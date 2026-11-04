"""Execute the real NS2 simulator for a scenario.

Two execution back-ends are supported:

* ``local``  - an ``ns`` binary on PATH (typical on Linux: ``sudo apt install ns2``)
* ``docker`` - the ``routeresq-ns2`` image built from ``docker/Dockerfile.ns2``
  (Ubuntu 22.04 + the distribution's ns2 2.35 package). Used on Windows.

Commands are always executed as argument lists (never through a shell).
"""
from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from common.logging_setup import get_logger
from common.paths import PROJECT_ROOT, SIM_RESULTS_DIR, TCL_SCRIPT
from common.storage import timestamp_slug, utc_now_iso, write_json
from simulation.scenario import Scenario

log = get_logger("simulation.runner")

DOCKER_IMAGE = "routeresq-ns2:2.35"
DOCKERFILE = PROJECT_ROOT / "docker" / "Dockerfile.ns2"


class NS2UnavailableError(RuntimeError):
    """No usable NS2 installation was found."""


class NS2ExecutionError(RuntimeError):
    """NS2 ran but failed."""


@dataclass
class NS2Backend:
    kind: str  # "local" | "docker"
    detail: str
    version: str = "unknown"


@dataclass
class SimulationRun:
    scenario_id: str
    run_dir: Path
    trace_file: Path
    events_file: Path
    backend: str
    ns_version: str
    command: list[str]
    started_at: str
    wall_seconds: float
    returncode: int
    stdout: str = ""
    stderr: str = ""
    extra: dict = field(default_factory=dict)


def _run(cmd: list[str], timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        return _run(["docker", "version", "--format", "{{.Server.Version}}"], 20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def docker_image_present() -> bool:
    try:
        return _run(["docker", "image", "inspect", DOCKER_IMAGE], 20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def build_docker_image(timeout: float = 1200) -> str:
    """Build the NS2 image (needs internet access for apt)."""
    cmd = ["docker", "build", "-f", str(DOCKERFILE), "-t", DOCKER_IMAGE, str(DOCKERFILE.parent)]
    log.info("Building NS2 docker image: %s", " ".join(cmd))
    res = _run(cmd, timeout)
    if res.returncode != 0:
        raise NS2ExecutionError(f"docker build failed:\n{res.stderr[-2000:]}")
    return res.stdout[-2000:]


def detect_backend() -> NS2Backend:
    ns_path = shutil.which("ns")
    if ns_path:
        return NS2Backend("local", ns_path, _local_version(ns_path))
    if _docker_available():
        if docker_image_present():
            return NS2Backend("docker", DOCKER_IMAGE, _docker_version())
        raise NS2UnavailableError(
            f"Docker is available but the image {DOCKER_IMAGE} is missing. Build it with:\n"
            f"  docker build -f docker/Dockerfile.ns2 -t {DOCKER_IMAGE} docker"
        )
    raise NS2UnavailableError(
        "NS2 was not found. Install it (Linux: 'sudo apt install ns2') or install Docker and build "
        f"the {DOCKER_IMAGE} image (see README)."
    )


def _local_version(ns_path: str) -> str:
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        script = Path(td) / "v.tcl"
        script.write_text("puts [ns-version]\nexit 0\n", encoding="utf-8")
        try:
            res = _run([ns_path, str(script)], 30)
            return res.stdout.strip() or "unknown"
        except (OSError, subprocess.TimeoutExpired):
            return "unknown"


def _docker_version() -> str:
    try:
        res = _run(
            ["docker", "run", "--rm", "--entrypoint", "dpkg-query", DOCKER_IMAGE, "-W", "-f=${Version}", "ns2"], 60
        )
        return res.stdout.strip() or "unknown"
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"


def backend_status() -> dict:
    """Non-raising summary used by the UI."""
    try:
        b = detect_backend()
        return {"available": True, "kind": b.kind, "detail": b.detail, "version": b.version}
    except NS2UnavailableError as exc:
        return {"available": False, "kind": None, "detail": str(exc), "version": None}


def run_scenario(
    scenario: Scenario,
    out_root: Path = SIM_RESULTS_DIR,
    backend: NS2Backend | None = None,
    timeout: float = 300,
) -> SimulationRun:
    """Run NS2 for one scenario and return the paths of the produced files."""
    backend = backend or detect_backend()
    run_dir = out_root / scenario.id / timestamp_slug()
    suffix = 1
    while run_dir.exists():
        run_dir = out_root / scenario.id / f"{timestamp_slug()}-{suffix}"
        suffix += 1
    run_dir.mkdir(parents=True)
    trace_name, events_name = "out.tr", "events.log"

    if backend.kind == "local":
        shutil.copy2(TCL_SCRIPT, run_dir / TCL_SCRIPT.name)
        cmd = [backend.detail, TCL_SCRIPT.name, *scenario.ns_args(trace_name, events_name)]
        cwd: Path | None = run_dir
    else:
        shutil.copy2(TCL_SCRIPT, run_dir / TCL_SCRIPT.name)
        cmd = [
            "docker", "run", "--rm",
            "-v", f"{run_dir.resolve()}:/work",
            "-w", "/work",
            DOCKER_IMAGE,
            TCL_SCRIPT.name,
            *scenario.ns_args(trace_name, events_name),
        ]
        cwd = None

    log.info("Running NS2 scenario %s: %s", scenario.id, " ".join(cmd))
    started = utc_now_iso()
    t0 = time.perf_counter()
    try:
        res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise NS2ExecutionError(f"NS2 timed out after {timeout}s") from exc
    wall = time.perf_counter() - t0

    run = SimulationRun(
        scenario_id=scenario.id,
        run_dir=run_dir,
        trace_file=run_dir / trace_name,
        events_file=run_dir / events_name,
        backend=backend.kind,
        ns_version=backend.version,
        command=cmd,
        started_at=started,
        wall_seconds=round(wall, 3),
        returncode=res.returncode,
        stdout=res.stdout[-5000:],
        stderr=res.stderr[-5000:],
    )
    write_json(run_dir / "scenario.json", scenario.to_dict())
    write_json(
        run_dir / "run.json",
        {k: v for k, v in run.__dict__.items() if k not in ("stdout", "stderr")}
        | {"stdout_tail": run.stdout, "stderr_tail": run.stderr},
    )
    if res.returncode != 0 or not run.trace_file.exists() or run.trace_file.stat().st_size == 0:
        raise NS2ExecutionError(
            f"NS2 exited with code {res.returncode}; trace present={run.trace_file.exists()}\n{res.stderr[-2000:]}"
        )
    log.info("Scenario %s finished in %.2fs (%d bytes of trace)", scenario.id, wall, run.trace_file.stat().st_size)
    return run


def load_run(run_dir: Path) -> SimulationRun:
    """Re-create a SimulationRun object from a previous results directory."""
    from common.storage import read_json

    meta = read_json(run_dir / "run.json", {}) or {}
    return SimulationRun(
        scenario_id=meta.get("scenario_id", run_dir.parent.name),
        run_dir=run_dir,
        trace_file=run_dir / "out.tr",
        events_file=run_dir / "events.log",
        backend=meta.get("backend", "unknown"),
        ns_version=meta.get("ns_version", "unknown"),
        command=meta.get("command", []),
        started_at=meta.get("started_at", ""),
        wall_seconds=meta.get("wall_seconds", 0.0),
        returncode=meta.get("returncode", 0),
        stdout=meta.get("stdout_tail", ""),
        stderr=meta.get("stderr_tail", ""),
    )


def list_runs(scenario_id: str | None = None, out_root: Path = SIM_RESULTS_DIR) -> list[Path]:
    """Run directories (newest first) that contain a trace file."""
    if not out_root.exists():
        return []
    dirs = [out_root / scenario_id] if scenario_id else [d for d in out_root.iterdir() if d.is_dir()]
    runs: list[Path] = []
    for d in dirs:
        if d.exists():
            runs.extend(p for p in d.iterdir() if p.is_dir() and (p / "out.tr").exists())
    return sorted(runs, key=_run_sort_key, reverse=True)


def _run_sort_key(run_dir: Path) -> str:
    """Newest first by the UTC start time stored in run.json. Folder names use the local
    clock of whichever machine ran NS2, so they are not comparable across machines."""
    import json

    try:
        started = json.loads((run_dir / "run.json").read_text(encoding="utf-8")).get("started_at", "")
    except (OSError, ValueError):
        started = ""
    return started or "0000"
