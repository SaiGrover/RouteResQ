"""Destination validation and authorisation for active network tests."""
from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import dataclass
from pathlib import Path

from common.deployment import is_public_deployment
from common.paths import CONFIG_DIR

AUTH_FILE = CONFIG_DIR / "authorized_targets.json"
_HOSTNAME = re.compile(r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*\.?$")


class TargetNotAllowed(ValueError):
    pass


@dataclass
class AuthorizationDecision:
    target: str
    allowed: bool
    reason: str


def normalize_target(target: str) -> str:
    t = (target or "").strip()
    if not t:
        raise TargetNotAllowed("Empty destination")
    if t.startswith("-"):
        raise TargetNotAllowed("Destination may not start with '-' (option injection)")
    try:
        return str(ipaddress.ip_address(t))
    except ValueError:
        pass
    if not _HOSTNAME.match(t):
        raise TargetNotAllowed(f"'{t}' is not a valid hostname or IP address")
    return t.lower().rstrip(".")


def load_policy(path: Path = AUTH_FILE) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def check_target(target: str, policy: dict | None = None) -> AuthorizationDecision:
    policy = policy or load_policy()
    try:
        t = normalize_target(target)
    except TargetNotAllowed as exc:
        return AuthorizationDecision(target, False, str(exc))
    if t in policy.get("reserved_test_targets", {}):
        return AuthorizationDecision(t, True, policy["reserved_test_targets"][t])
    if t in [h.lower() for h in policy.get("hosts", [])]:
        return AuthorizationDecision(t, True, "listed in config/authorized_targets.json")
    try:
        ip = ipaddress.ip_address(t)
        if ip.is_loopback and policy.get("allow_loopback", True):
            return AuthorizationDecision(t, True, "loopback address")
        if ip.is_private and policy.get("allow_private_networks", False) and not is_public_deployment():
            return AuthorizationDecision(t, True, "private (RFC 1918 / local) address - your own network")
    except ValueError:
        if t == "localhost" and policy.get("allow_loopback", True):
            return AuthorizationDecision(t, True, "loopback name")
    return AuthorizationDecision(
        t, False, "not in the authorised destination list; add it in config/authorized_targets.json "
        "(or the Diagnostics page) only if you are permitted to test it"
    )


def authorize(target: str, policy: dict | None = None) -> str:
    d = check_target(target, policy)
    if not d.allowed:
        raise TargetNotAllowed(f"{d.target}: {d.reason}")
    return d.target


def add_authorized_host(target: str, path: Path = AUTH_FILE) -> str:
    if is_public_deployment():
        raise TargetNotAllowed("Adding destinations is disabled on the public deployment")
    t = normalize_target(target)
    policy = load_policy(path)
    if t not in policy["hosts"]:
        policy["hosts"].append(t)
        path.write_text(json.dumps(policy, indent=2) + "\n", encoding="utf-8")
    return t


def authorized_list(policy: dict | None = None) -> list[str]:
    policy = policy or load_policy()
    return [*policy.get("hosts", []), *policy.get("reserved_test_targets", {}).keys(), "127.0.0.1"]
