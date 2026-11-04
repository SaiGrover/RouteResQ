"""Scenario configuration: loading, validation and conversion to NS2 arguments."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from common.paths import SCENARIO_DIR

# Every parameter the Tcl script accepts, with a validator. Values are passed to
# NS2 as "key=value" arguments and are interpolated into Tcl strings, so they are
# validated strictly (no spaces, brackets, braces, semicolons or '$').
_BW = re.compile(r"^\d+(\.\d+)?(b|Kb|Mb|Gb)$")
_DELAY = re.compile(r"^\d+(\.\d+)?(s|ms|us)$")
_LINK = re.compile(r"^[0-5]-[0-5]$")

PARAM_RULES: dict[str, str] = {
    "stop": "float",
    "routing": "routing",
    "access_bw": "bw",
    "access_delay": "delay",
    "core_bw": "bw",
    "core_delay": "delay",
    "alt_delay": "delay",
    "queue_limit": "int",
    "alt_cost": "int",
    "pkt_size": "int",
    "rate": "bw",
    "traffic_start": "float",
    "traffic_stop": "float",
    "fail_link": "link",
    "fail_at": "float",
    "restore_at": "float",
    "cross_rate": "bw_or_zero",
    "cross_start": "float",
    "cross_stop": "float",
    "dv_advert": "float",
}

# Defaults mirror the Tcl script so the analysis knows the effective values.
DEFAULTS: dict[str, Any] = {
    "stop": 10.0,
    "routing": "DV",
    "access_bw": "10Mb",
    "access_delay": "2ms",
    "core_bw": "2Mb",
    "core_delay": "10ms",
    "alt_delay": "15ms",
    "queue_limit": 20,
    "alt_cost": 3,
    "pkt_size": 1000,
    "rate": "1Mb",
    "traffic_start": 1.0,
    "traffic_stop": 9.0,
    "fail_link": "none",
    "fail_at": -1,
    "restore_at": -1,
    "cross_rate": 0,
    "cross_start": -1,
    "cross_stop": -1,
    "dv_advert": 2,
}

CATEGORIES = ("healthy", "link_failure", "congestion")

# Static description of the topology, used by the analysis and the UI.
NODE_ROLES: dict[int, str] = {
    0: "source host",
    1: "edge router (ingress)",
    2: "core router (primary path)",
    3: "core router (alternative path)",
    4: "edge router (egress)",
    5: "destination host",
}
LINKS: list[tuple[int, int, str]] = [
    (0, 1, "access"),
    (1, 2, "core"),
    (2, 4, "core"),
    (1, 3, "alt"),
    (3, 4, "alt"),
    (4, 5, "access"),
]


class ScenarioError(ValueError):
    """Raised for invalid scenario configuration."""


def parse_bandwidth(value: str | int | float) -> float:
    """Return bits per second for NS2 bandwidth strings such as '1.5Mb'."""
    if isinstance(value, (int, float)):
        return float(value)
    m = re.match(r"^(\d+(?:\.\d+)?)(b|Kb|Mb|Gb)$", value)
    if not m:
        raise ScenarioError(f"Invalid bandwidth: {value!r}")
    mult = {"b": 1, "Kb": 1e3, "Mb": 1e6, "Gb": 1e9}[m.group(2)]
    return float(m.group(1)) * mult


def parse_delay(value: str) -> float:
    """Return seconds for NS2 delay strings such as '10ms'."""
    m = re.match(r"^(\d+(?:\.\d+)?)(s|ms|us)$", value)
    if not m:
        raise ScenarioError(f"Invalid delay: {value!r}")
    return float(m.group(1)) * {"s": 1, "ms": 1e-3, "us": 1e-6}[m.group(2)]


def _validate_value(key: str, value: Any) -> str:
    rule = PARAM_RULES.get(key)
    if rule is None:
        raise ScenarioError(f"Unknown NS2 parameter: {key}")
    s = str(value)
    ok = {
        "float": lambda: re.fullmatch(r"-?\d+(\.\d+)?", s) is not None,
        "int": lambda: re.fullmatch(r"\d+", s) is not None,
        "bw": lambda: _BW.fullmatch(s) is not None,
        "bw_or_zero": lambda: s == "0" or _BW.fullmatch(s) is not None,
        "delay": lambda: _DELAY.fullmatch(s) is not None,
        "link": lambda: s == "none" or _LINK.fullmatch(s) is not None,
        "routing": lambda: s in ("DV", "Static"),
    }[rule]()
    if not ok:
        raise ScenarioError(f"Invalid value for {key}: {value!r}")
    return s


@dataclass
class Flow:
    fid: int
    src: int
    dst: int
    rate_bps: float
    start: float
    stop: float
    role: str


@dataclass
class Scenario:
    id: str
    name: str
    category: str
    description: str
    known_cause: str
    params: dict[str, Any]
    phases: dict[str, tuple[float, float]]
    label: str = ""
    phase_note: str = ""
    source_file: str | None = None
    effective: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z0-9_]+", self.id):
            raise ScenarioError(f"Invalid scenario id: {self.id!r}")
        if self.category not in CATEGORIES:
            raise ScenarioError(f"Unknown category: {self.category!r}")
        for k, v in self.params.items():
            _validate_value(k, v)
        self.effective = {**DEFAULTS, **self.params}
        e = self.effective
        if float(e["traffic_start"]) >= float(e["traffic_stop"]):
            raise ScenarioError("traffic_start must be before traffic_stop")
        if float(e["traffic_stop"]) > float(e["stop"]):
            raise ScenarioError("traffic_stop must not exceed the simulation stop time")
        if self.has_failure:
            a, b = self.failed_link  # type: ignore[misc]
            if (a, b) not in {(x, y) for x, y, _ in LINKS} and (b, a) not in {(x, y) for x, y, _ in LINKS}:
                raise ScenarioError(f"fail_link {a}-{b} is not a link in the topology")
            if float(e["fail_at"]) < 0:
                raise ScenarioError("fail_at must be set when fail_link is given")
            if float(e["restore_at"]) >= 0 and float(e["restore_at"]) <= float(e["fail_at"]):
                raise ScenarioError("restore_at must be after fail_at")
        if self.category == "link_failure" and not self.has_failure:
            raise ScenarioError("link_failure scenarios need fail_link and fail_at")
        if self.category == "congestion" and not self.has_cross_traffic:
            raise ScenarioError("congestion scenarios need cross_rate/cross_start/cross_stop")
        norm: dict[str, tuple[float, float]] = {}
        for name in ("before", "during", "after"):
            if name not in self.phases:
                raise ScenarioError(f"Missing phase window: {name}")
            t0, t1 = (float(x) for x in self.phases[name])
            if t1 <= t0:
                raise ScenarioError(f"Phase {name} has an empty window")
            norm[name] = (t0, t1)
        self.phases = norm

    # ---- derived properties ----
    @property
    def has_failure(self) -> bool:
        return str(self.effective["fail_link"]) != "none"

    @property
    def failed_link(self) -> tuple[int, int] | None:
        if not self.has_failure:
            return None
        a, b = str(self.effective["fail_link"]).split("-")
        return int(a), int(b)

    @property
    def fail_at(self) -> float | None:
        return float(self.effective["fail_at"]) if self.has_failure else None

    @property
    def restore_at(self) -> float | None:
        if not self.has_failure or float(self.effective["restore_at"]) < 0:
            return None
        return float(self.effective["restore_at"])

    @property
    def has_cross_traffic(self) -> bool:
        return str(self.effective["cross_rate"]) != "0"

    @property
    def routing(self) -> str:
        return str(self.effective["routing"])

    @property
    def flows(self) -> list[Flow]:
        e = self.effective
        flows = [
            Flow(1, 0, 5, parse_bandwidth(e["rate"]), float(e["traffic_start"]), float(e["traffic_stop"]), "monitored"),
        ]
        if self.has_cross_traffic:
            flows.append(
                Flow(2, 0, 5, parse_bandwidth(e["cross_rate"]), float(e["cross_start"]), float(e["cross_stop"]), "competing")
            )
        return flows

    @property
    def packet_interval(self) -> float:
        e = self.effective
        return int(e["pkt_size"]) * 8 / parse_bandwidth(e["rate"])

    def ns_args(self, trace_path: str, events_path: str) -> list[str]:
        """Command-line arguments for routeresq.tcl."""
        args = [f"trace={trace_path}", f"events={events_path}"]
        for k, v in self.params.items():
            args.append(f"{k}={_validate_value(k, v)}")
        return args

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "known_cause": self.known_cause,
            "params": self.params,
            "effective_params": self.effective,
            "phases": {k: list(v) for k, v in self.phases.items()},
            "phase_note": self.phase_note,
        }


def scenario_from_dict(data: dict[str, Any], source_file: str | None = None) -> Scenario:
    required = ("id", "name", "category", "description", "known_cause", "params", "phases")
    missing = [k for k in required if k not in data]
    if missing:
        raise ScenarioError(f"Scenario is missing fields: {', '.join(missing)}")
    return Scenario(
        id=data["id"],
        name=data["name"],
        category=data["category"],
        description=data["description"],
        known_cause=data["known_cause"],
        params=dict(data["params"]),
        phases={k: tuple(v) for k, v in data["phases"].items()},
        label=data.get("label", ""),
        phase_note=data.get("phase_note", ""),
        source_file=source_file,
    )


def load_scenario(path: Path) -> Scenario:
    return scenario_from_dict(json.loads(path.read_text(encoding="utf-8")), source_file=str(path))


def load_all_scenarios(directory: Path = SCENARIO_DIR) -> dict[str, Scenario]:
    order = {"A": 0, "B1": 1, "B2": 2, "C": 3}
    scenarios = [load_scenario(p) for p in sorted(directory.glob("*.json"))]
    scenarios.sort(key=lambda s: (order.get(s.label, 99), s.id))
    return {s.id: s for s in scenarios}
