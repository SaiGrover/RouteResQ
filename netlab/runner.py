"""Host side of the upload-under-link-failure experiment.

Picks a backend that can genuinely build the isolated test network, runs the lab there, and
stores every run under ``results/netlab``:

* ``native`` - Linux, running as root, with ``ip netns`` working;
* ``docker`` - the ``routeresq-netlab:1`` image (Windows/macOS, or Linux without root). The
  container gets NET_ADMIN and SYS_ADMIN for *its own* namespaces; the host's network is untouched;
* none     - e.g. Streamlit Community Cloud, which has neither root nor Docker. The app then shows
  the recorded run in ``results/netlab/recorded`` and labels it as recorded.

    python -m netlab.runner                 # run all three modes with the bundled sample
    python -m netlab.runner --file my.bin   # or with your own file (64 KiB - 8 MiB)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from common.deployment import is_public_deployment
from common.paths import PROJECT_ROOT, RESULTS_DIR
from netlab.config import RUN_MODES, SAMPLE_NAME, LabConfig, check_file_size, sample_bytes

NETLAB_DIR = RESULTS_DIR / "netlab"
RUNS_DIR = NETLAB_DIR / "runs"            # live runs (machine-specific, not committed)
RECORDED_DIR = NETLAB_DIR / "recorded"    # one captured run, committed, shown on the hosted app
IMAGE = "routeresq-netlab:1"
DOCKER_SECURITY = ["--cap-add", "NET_ADMIN", "--cap-add", "SYS_ADMIN", "--security-opt", "apparmor=unconfined",
                   "--security-opt", "systempaths=unconfined"]


class NetlabError(RuntimeError):
    pass


def _ok(cmd: list[str], timeout: float = 15) -> bool:
    try:
        return subprocess.run(cmd, capture_output=True, timeout=timeout).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def backend_status() -> dict:
    """Which backend can run the experiment here, and why not if none can."""
    if is_public_deployment():
        return {"available": False, "backend": None,
                "reason": "Hosted deployment: no root and no Docker, so it cannot create an isolated test network. "
                          "Showing a recorded run captured locally."}
    if sys.platform.startswith("linux") and hasattr(os, "geteuid") and os.geteuid() == 0 and shutil.which("ip"):
        probe = f"rrqprobe{uuid.uuid4().hex[:4]}"
        if _ok(["ip", "netns", "add", probe]):
            _ok(["ip", "netns", "del", probe])
            return {"available": True, "backend": "native", "reason": "Linux, root: network namespaces available"}
    if shutil.which("docker"):
        if not _ok(["docker", "info"], 20):
            return {"available": False, "backend": None, "reason": "Docker is installed but its engine is not running."}
        if not _ok(["docker", "image", "inspect", IMAGE], 20):
            return {"available": False, "backend": None,
                    "reason": f"Docker image {IMAGE} is missing. Build it once with: "
                              f"docker build -f docker/Dockerfile.netlab -t {IMAGE} docker"}
        return {"available": True, "backend": "docker", "reason": f"Docker image {IMAGE} (isolated namespaces in a container)"}
    return {"available": False, "backend": None,
            "reason": "Needs Linux with root, or Docker with the routeresq-netlab image."}


def run_experiment(data: bytes, name: str, cfg: LabConfig | None = None, backend: str | None = None) -> Path:
    """Run the requested modes on real sockets in the test network; return the run folder."""
    cfg = (cfg or LabConfig()).validate()
    check_file_size(len(data))
    status = backend_status() if backend is None else {"available": True, "backend": backend}
    if not status["available"]:
        raise NetlabError(status["reason"])
    backend = status["backend"]
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:4]
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    inp = run_dir / "input.bin"
    inp.write_bytes(data)
    rel = run_dir.relative_to(PROJECT_ROOT).as_posix()
    lab_args = ["--input", f"{rel}/input.bin", "--name", name, "--out", rel, "--config", json.dumps(cfg.to_dict())]
    timeout = len(cfg.runs) * (cfg.max_run_s + 20) + 60
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    name_c = f"rrq-netlab-{run_id.lower()}"
    if backend == "docker":
        cmd = ["docker", "run", "--rm", "--name", name_c, *DOCKER_SECURITY, "-e", "ROUTERESQ_NETLAB_BACKEND=docker",
               "-v", f"{PROJECT_ROOT}:/work", "-w", "/work", IMAGE, "python", "-m", "netlab.lab", *lab_args]
    else:
        cmd = [sys.executable, "-m", "netlab.lab", *lab_args]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=PROJECT_ROOT)
    except subprocess.TimeoutExpired as exc:
        if backend == "docker":
            _ok(["docker", "kill", name_c])
        raise NetlabError(f"the lab did not finish within {timeout:.0f} s and was stopped") from exc
    finally:
        inp.unlink(missing_ok=True)              # never keep the uploaded file itself
    if p.returncode != 0:
        raise NetlabError(f"lab exited with code {p.returncode}: {(p.stderr or p.stdout).strip()[-1500:]}")
    meta = {"run_id": run_id, "source": "live", "backend": backend, "started": started,
            "finished": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "file": {"name": name, "size": len(data)}, "config": cfg.to_dict(), "command": " ".join(cmd[:4]) + " ..."}
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=1))
    return run_dir


def run_sample(cfg: LabConfig | None = None) -> Path:
    return run_experiment(sample_bytes(), SAMPLE_NAME, cfg)


# ---------------------------------------------------------------------------- stored runs
def load_run(run_dir: Path) -> dict | None:
    meta_p = run_dir / "meta.json"
    if not meta_p.exists():
        return None
    meta = json.loads(meta_p.read_text())
    runs = {}
    for mode in RUN_MODES:
        p = run_dir / f"{mode}.json"
        if p.exists():
            runs[mode] = json.loads(p.read_text())
    return {"dir": str(run_dir), "meta": meta, "runs": runs} if runs else None


def list_runs() -> list[Path]:
    """Live runs, newest first."""
    if not RUNS_DIR.exists():
        return []
    return sorted((d for d in RUNS_DIR.iterdir() if (d / "meta.json").exists()), key=lambda d: d.name, reverse=True)


def recorded_run() -> dict | None:
    return load_run(RECORDED_DIR) if RECORDED_DIR.exists() else None


def latest(prefer_live: bool = True) -> dict | None:
    """Newest live run if there is one (and prefer_live), otherwise the recorded run."""
    if prefer_live:
        for d in list_runs():
            r = load_run(d)
            if r:
                return r
    return recorded_run()


def record(run_dir: Path) -> Path:
    """Copy a live run into results/netlab/recorded (the run the hosted app shows)."""
    if RECORDED_DIR.exists():
        shutil.rmtree(RECORDED_DIR)
    shutil.copytree(run_dir, RECORDED_DIR, ignore=shutil.ignore_patterns("input.bin"))
    meta_p = RECORDED_DIR / "meta.json"
    meta = json.loads(meta_p.read_text())
    meta["source"] = "recorded"
    meta["recorded_from"] = Path(run_dir).name
    meta_p.write_text(json.dumps(meta, indent=1))
    return RECORDED_DIR


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run the upload-under-link-failure experiment")
    ap.add_argument("--file", type=Path, help="file to upload (64 KiB - 8 MiB); default: the bundled sample")
    ap.add_argument("--config", default="{}", help="JSON with LabConfig fields, e.g. '{\"fault_at_pct\": 40}'")
    ap.add_argument("--record", action="store_true", help="also copy the run to results/netlab/recorded")
    ap.add_argument("--report", action="store_true", help="also write reports/file_upload_link_failure.md")
    args = ap.parse_args(argv)
    cfg = LabConfig.from_dict(json.loads(args.config))
    print(backend_status()["reason"])
    run_dir = (run_experiment(args.file.read_bytes(), args.file.name, cfg) if args.file else run_sample(cfg))
    run = load_run(run_dir)
    for mode, r in run["runs"].items():
        print(f"{mode:9s} {r['outcome']['label']}\n          {r['summary']}")
    if args.record:
        print("recorded ->", record(run_dir))
    if args.report:
        from netlab.report import write_report
        print("report ->", write_report(load_run(RECORDED_DIR) if args.record else run))
    print("run folder ->", run_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
