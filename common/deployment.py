"""Detect a public (hosted) deployment, where the app must not become an open probing tool."""
from __future__ import annotations

import os

from common.paths import PROJECT_ROOT


def is_public_deployment() -> bool:
    """True on Streamlit Community Cloud (apps are mounted under /mount/src) or when
    ROUTERESQ_PUBLIC=1 is set. In public mode:

    * only the destinations listed in config/authorized_targets.json and loopback can be probed
      (private RFC 1918 ranges would be the hosting provider's internal network);
    * visitors cannot add destinations to the allow-list.
    """
    flag = os.environ.get("ROUTERESQ_PUBLIC", "").strip().lower()
    if flag in ("1", "true", "yes"):
        return True
    if flag in ("0", "false", "no"):
        return False
    return str(PROJECT_ROOT).replace("\\", "/").startswith("/mount/src")
