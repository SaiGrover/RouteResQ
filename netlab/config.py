"""Settings for the upload-under-link-failure experiment, with hard bounds.

The same ``LabConfig`` is used by the host-side runner (to validate what the user typed) and by
the lab inside the test network (to run it), so both sides always agree on the limits.
"""
from __future__ import annotations

import random
from dataclasses import asdict, dataclass, field

KIB = 1024
MIB = 1024 * 1024

MIN_FILE_BYTES = 64 * KIB
MAX_FILE_BYTES = 8 * MIB          # bound on the upload size
MAX_RUN_S = 60.0                  # bound on one run (the lab aborts and cleans up after this)
SAMPLE_BYTES = 2 * MIB
SAMPLE_NAME = "routeresq-sample-2MiB.bin"
SAMPLE_SEED = 20261119

RUN_MODES = ("baseline", "failover", "static")
RUN_LABELS = {
    "baseline": "Healthy baseline",
    "failover": "Link failure · backup route",
    "static": "Link failure · static forwarding",
}
RUN_DESCRIPTIONS = {
    "baseline": "The primary link stays up for the whole upload.",
    "failover": ("The primary link goes down mid-upload. A backup route through the router is pre-installed "
                 "with a higher metric (a floating static route), so forwarding can switch to it."),
    "static": ("The same link goes down at the same point. The backup path is still connected and forwarding, "
               "but there is no route to it, so forwarding cannot switch."),
}


class ConfigError(ValueError):
    pass


@dataclass
class LabConfig:
    fault_at_pct: float = 30.0        # inject the fault once the server has received this share of the file
    outage_s: float = 3.0             # how long the primary link stays down
    rate_kib_s: float = 512.0         # client pacing, so the upload is still in progress at the fault
    chunk_kib: int = 8                # size of each FILE_CHUNK frame
    timeout_s: float = 10.0           # socket timeout: no progress for this long fails the connection
    retries: int = 1                  # new TCP connections allowed after a failure (each re-sends from byte 0)
    sndbuf_kib: int = 64              # client socket send buffer (keeps client-side buffering small)
    primary_delay_ms: float = 5.0     # one-way delay on each end of the primary link (netem)
    backup_delay_ms: float = 10.0     # one-way delay on each hop of the backup path (netem)
    sample_ms: int = 50               # interface-counter sampling interval
    max_run_s: float = MAX_RUN_S
    runs: list[str] = field(default_factory=lambda: list(RUN_MODES))

    def validate(self) -> "LabConfig":
        def need(ok: bool, msg: str) -> None:
            if not ok:
                raise ConfigError(msg)

        need(5 <= self.fault_at_pct <= 90, "fault point must be between 5% and 90% of the file")
        need(0.5 <= self.outage_s <= 30, "outage must be between 0.5 s and 30 s")
        need(32 <= self.rate_kib_s <= 8192, "pacing rate must be between 32 and 8192 KiB/s")
        need(1 <= self.chunk_kib <= 256, "chunk size must be between 1 and 256 KiB")
        need(1 <= self.timeout_s <= 30, "timeout must be between 1 s and 30 s")
        need(0 <= self.retries <= 3, "retries must be between 0 and 3")
        need(16 <= self.sndbuf_kib <= 4096, "send buffer must be between 16 and 4096 KiB")
        need(0 <= self.primary_delay_ms <= 200 and 0 <= self.backup_delay_ms <= 200, "link delays must be 0-200 ms")
        need(10 <= self.sample_ms <= 500, "sampling interval must be between 10 and 500 ms")
        need(5 <= self.max_run_s <= MAX_RUN_S, f"run limit must be between 5 and {MAX_RUN_S:g} s")
        need(bool(self.runs) and all(r in RUN_MODES for r in self.runs), f"runs must be among {RUN_MODES}")
        return self

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "LabConfig":
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known).validate()


def check_file_size(n: int) -> None:
    if n < MIN_FILE_BYTES:
        raise ConfigError(f"file is {n:,} bytes; use at least {MIN_FILE_BYTES // KIB} KiB so the upload is "
                          "still running when the fault is injected")
    if n > MAX_FILE_BYTES:
        raise ConfigError(f"file is {n:,} bytes; the limit is {MAX_FILE_BYTES // MIB} MiB")


def sample_bytes(n: int = SAMPLE_BYTES) -> bytes:
    """The bundled sample: deterministic pseudo-random bytes, identical on every machine."""
    return random.Random(SAMPLE_SEED).randbytes(n)
