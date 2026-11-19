"""The isolated test network: three Linux network namespaces joined by veth links.

::

                    primary link (direct)
        client  cp0 ------------------------ sp0  server
     10.98.0.1  cb0 ---- rc0 [router] rs0 ---- sb0  10.99.0.1
                     backup path (two hops)

* The client and the server each own a *service address* on their loopback interface
  (10.98.0.1 and 10.99.0.1). The TCP connection runs between these two addresses, so its
  four-tuple does not change when the packets change path.
* The primary link carries the upload while it is up (route metric 10).
* ``failover`` mode also installs a backup route through the router with metric 100 (a floating
  static route). When the primary link goes down, the kernel removes the routes that used it and
  forwarding falls back to the backup route on its own. No routing protocol runs here.
* ``static`` mode installs only the primary route. The backup path stays connected and the router
  keeps forwarding, but nothing routes traffic to it.
* Taking the link down = administratively downing both ends of the primary veth pair, inside the
  namespaces. Restoring = bringing both ends up and re-installing the primary route.

Nothing here touches the host's interfaces or routes. The commands need root (CAP_NET_ADMIN and
CAP_SYS_ADMIN), which the lab gets inside its own container.
"""
from __future__ import annotations

import os
import subprocess
import uuid

CLIENT_SVC = "10.98.0.1"
SERVER_SVC = "10.99.0.1"
PORT = 5050

# interface -> (namespace role, address/prefix)
IFACES = {
    "cp0": ("c", "10.0.1.1/30"), "sp0": ("s", "10.0.1.2/30"),     # primary link
    "cb0": ("c", "10.0.2.1/30"), "rc0": ("r", "10.0.2.2/30"),     # backup hop 1
    "rs0": ("r", "10.0.3.1/30"), "sb0": ("s", "10.0.3.2/30"),     # backup hop 2
}
PAIRS = [("cp0", "sp0"), ("cb0", "rc0"), ("rs0", "sb0")]
PRIMARY = ("cp0", "sp0")
BACKUP_IFACES = ("cb0", "rc0", "rs0", "sb0")

PRIMARY_ROUTES = {"c": f"{SERVER_SVC}/32 via 10.0.1.2 dev cp0 metric 10 src {CLIENT_SVC}",
                  "s": f"{CLIENT_SVC}/32 via 10.0.1.1 dev sp0 metric 10 src {SERVER_SVC}"}
BACKUP_ROUTES = {"c": f"{SERVER_SVC}/32 via 10.0.2.2 dev cb0 metric 100 src {CLIENT_SVC}",
                 "s": f"{CLIENT_SVC}/32 via 10.0.3.1 dev sb0 metric 100 src {SERVER_SVC}"}
ROUTER_ROUTES = [f"{SERVER_SVC}/32 via 10.0.3.2 dev rs0", f"{CLIENT_SVC}/32 via 10.0.2.1 dev rc0"]


class TopologyError(RuntimeError):
    pass


def _run(args: list[str]) -> str:
    p = subprocess.run(args, capture_output=True, text=True, timeout=15)
    if p.returncode != 0:
        raise TopologyError(f"{' '.join(args)} failed: {(p.stderr or p.stdout).strip()}")
    return p.stdout


class Topology:
    """Build, change and remove one instance of the test network."""

    def __init__(self, mode: str, primary_delay_ms: float = 5.0, backup_delay_ms: float = 10.0):
        self.mode = mode
        self.primary_delay_ms = primary_delay_ms
        self.backup_delay_ms = backup_delay_ms
        tag = uuid.uuid4().hex[:6]
        self.ns = {"c": f"rrq{tag}c", "s": f"rrq{tag}s", "r": f"rrq{tag}r"}
        self.built = False
        self.commands: list[str] = []      # every command issued, kept for the run record

    # ---------------------------------------------------------------- helpers
    def ip(self, role: str, *args: str) -> str:
        cmd = ["ip", "-n", self.ns[role], *args]
        self.commands.append(" ".join(cmd))
        return _run(cmd)

    def sh(self, role: str, script: str) -> str:
        cmd = ["ip", "netns", "exec", self.ns[role], "sh", "-c", script]
        self.commands.append(" ".join(cmd[:4]) + f" sh -c '{script}'")
        return _run(cmd)

    def ns_path(self, role: str) -> str:
        return f"/run/netns/{self.ns[role]}"

    # ---------------------------------------------------------------- lifecycle
    def build(self) -> None:
        for name in self.ns.values():
            _run(["ip", "netns", "add", name])
            self.commands.append(f"ip netns add {name}")
        self.built = True
        for role in self.ns:
            self.ip(role, "link", "set", "lo", "up")
            self.sh(role, "for f in /proc/sys/net/ipv4/conf/*/rp_filter; do echo 0 > $f; done")
        self.ip("c", "addr", "add", f"{CLIENT_SVC}/32", "dev", "lo")
        self.ip("s", "addr", "add", f"{SERVER_SVC}/32", "dev", "lo")
        self.sh("r", "echo 1 > /proc/sys/net/ipv4/ip_forward")
        for a, b in PAIRS:
            _run(["ip", "link", "add", a, "type", "veth", "peer", "name", b])
            self.commands.append(f"ip link add {a} type veth peer name {b}")
            for ifc in (a, b):
                role, addr = IFACES[ifc]
                _run(["ip", "link", "set", ifc, "netns", self.ns[role]])
                self.ip(role, "addr", "add", addr, "dev", ifc)
                self.sh(role, f"echo 0 > /proc/sys/net/ipv4/conf/{ifc}/rp_filter")
                self.ip(role, "link", "set", ifc, "up")
                delay = self.primary_delay_ms if ifc in PRIMARY else self.backup_delay_ms
                if delay > 0:
                    self.sh(role, f"tc qdisc add dev {ifc} root netem delay {delay}ms limit 10000")
        self.ip("c", "route", "add", *PRIMARY_ROUTES["c"].split())
        self.ip("s", "route", "add", *PRIMARY_ROUTES["s"].split())
        if self.mode in ("failover", "baseline"):
            self.ip("c", "route", "add", *BACKUP_ROUTES["c"].split())
            self.ip("s", "route", "add", *BACKUP_ROUTES["s"].split())
        for r in ROUTER_ROUTES:
            self.ip("r", "route", "add", *r.split())

    def teardown(self) -> None:
        """Remove the namespaces (and with them every veth, address and route). Never raises."""
        for name in self.ns.values():
            subprocess.run(["ip", "netns", "del", name], capture_output=True, timeout=15)
        self.built = False

    # ---------------------------------------------------------------- the fault
    def link_down(self) -> None:
        self.ip("c", "link", "set", PRIMARY[0], "down")
        self.ip("s", "link", "set", PRIMARY[1], "down")

    def link_up(self) -> None:
        self.ip("c", "link", "set", PRIMARY[0], "up")
        self.ip("s", "link", "set", PRIMARY[1], "up")
        # downing an interface flushes the routes through it, so the primary routes are re-installed
        self.ip("c", "route", "replace", *PRIMARY_ROUTES["c"].split())
        self.ip("s", "route", "replace", *PRIMARY_ROUTES["s"].split())

    # ---------------------------------------------------------------- evidence
    def route_get(self) -> dict:
        """The kernel's forwarding decision for the upload, in both directions."""
        out = {}
        for role, dst, src in (("c", SERVER_SVC, CLIENT_SVC), ("s", CLIENT_SVC, SERVER_SVC)):
            try:
                out[role] = " ".join(_run(["ip", "-n", self.ns[role], "route", "get", dst, "from", src]).split())
            except TopologyError as exc:
                out[role] = f"no route ({str(exc).split('failed: ')[-1]})"
        return out


def read_counters() -> dict[str, tuple[int, int]]:
    """{iface: (rx_bytes, tx_bytes)} for the namespace of the *calling thread*."""
    out = {}
    with open("/proc/thread-self/net/dev") as f:
        for line in f.read().splitlines()[2:]:
            name, rest = line.split(":", 1)
            v = rest.split()
            out[name.strip()] = (int(v[0]), int(v[8]))
    return out


def enter_netns(path: str) -> None:
    """Move the calling thread (only) into the network namespace at ``path``."""
    fd = os.open(path, os.O_RDONLY)
    try:
        os.setns(fd, os.CLONE_NEWNET)
    finally:
        os.close(fd)
