"""Restricted OS command execution for diagnostics.

* Only a fixed allow-list of executables can run.
* Commands are passed as argument lists; ``shell=True`` is never used.
* Every argument that comes from the user is validated before it gets here.
"""
from __future__ import annotations

import platform
import shutil
import subprocess
import time
from typing import Protocol

from common.logging_setup import get_logger
from diagnostics.models import CommandRecord

log = get_logger("diagnostics.commands")

ALLOWED_EXECUTABLES = {"ping", "tracert", "traceroute", "tracepath", "route", "ip", "ipconfig"}
IS_WINDOWS = platform.system() == "Windows"


class CommandRunner(Protocol):
    def run(self, argv: list[str], timeout: float) -> CommandRecord: ...

    def available(self, executable: str) -> bool: ...


class SubprocessRunner:
    """Runs allow-listed commands with a timeout."""

    def available(self, executable: str) -> bool:
        return shutil.which(executable) is not None

    def run(self, argv: list[str], timeout: float) -> CommandRecord:
        exe = argv[0]
        if exe not in ALLOWED_EXECUTABLES:
            raise PermissionError(f"Executable not allowed: {exe}")
        path = shutil.which(exe)
        t0 = time.perf_counter()
        if path is None:
            return CommandRecord(argv, None, 0.0, error=f"'{exe}' is not installed or not on PATH")
        try:
            # Windows console tools emit the OEM code page; decode leniently.
            res = subprocess.run(
                [path, *argv[1:]],
                capture_output=True,
                timeout=timeout,
                check=False,
                shell=False,
            )
            out = res.stdout.decode(errors="replace")
            err = res.stderr.decode(errors="replace")
            rec = CommandRecord(argv, res.returncode, round(time.perf_counter() - t0, 3), out, err)
        except subprocess.TimeoutExpired as exc:
            out = (exc.stdout or b"").decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            rec = CommandRecord(argv, None, round(time.perf_counter() - t0, 3), out, "", timed_out=True,
                                error=f"command exceeded {timeout:.0f}s timeout")
        except OSError as exc:
            rec = CommandRecord(argv, None, round(time.perf_counter() - t0, 3), error=str(exc))
        log.info("ran %s rc=%s in %.2fs", " ".join(argv), rec.returncode, rec.duration_s)
        return rec


# ------------------------------------------------------------------ command builders
def ping_command(target: str, count: int, timeout_s: float, windows: bool = IS_WINDOWS) -> tuple[list[str], float]:
    """Return (argv, subprocess timeout)."""
    if windows:
        argv = ["ping", "-n", str(count), "-w", str(int(timeout_s * 1000)), target]
    else:
        argv = ["ping", "-c", str(count), "-W", str(max(1, int(round(timeout_s)))), "-i", "0.5", target]
    return argv, count * (timeout_s + 1.0) + 10


def traceroute_command(
    target: str, max_hops: int, timeout_s: float, windows: bool = IS_WINDOWS, runner: CommandRunner | None = None
) -> tuple[list[str], float]:
    if windows:
        argv = ["tracert", "-d", "-h", str(max_hops), "-w", str(int(timeout_s * 1000)), target]
    elif runner is None or runner.available("traceroute"):
        argv = ["traceroute", "-n", "-m", str(max_hops), "-w", str(max(1, int(round(timeout_s)))), "-q", "3", target]
    else:
        argv = ["tracepath", "-n", "-m", str(max_hops), target]
    return argv, max_hops * 3 * (timeout_s + 0.5) + 15
