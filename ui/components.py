"""Small Streamlit rendering helpers shared by the pages (presentation only)."""
from __future__ import annotations

import streamlit as st

LEVEL_BADGE = {
    "confirmed": ("Confirmed observation", "green", ":material/check_circle:"),
    "likely": ("Likely explanation", "blue", ":material/lightbulb:"),
    "possible": ("Possible explanation", "orange", ":material/help:"),
    "insufficient_evidence": ("Insufficient evidence", "gray", ":material/block:"),
}

CATEGORY_COLOR = {
    "Healthy / Reachable": "green",
    "DNS Resolution Failure": "red",
    "Unreachable Destination": "red",
    "High Latency": "orange",
    "Packet Loss": "orange",
    "Possible Routing Issue": "violet",
    "Possible Congestion": "violet",
    "Inconclusive / Insufficient Evidence": "gray",
}


def live_badge() -> None:
    st.badge("Live network measurement", icon=":material/sensors:", color="green")


def sim_badge() -> None:
    st.badge("NS2 simulation (known, injected cause)", icon=":material/science:", color="violet")


def loopback_badge() -> None:
    st.badge("Real sockets on loopback", icon=":material/lan:", color="blue")


def level_badge(level: str) -> None:
    label, color, icon = LEVEL_BADGE.get(level, (level, "gray", None))
    st.badge(label, color=color, icon=icon)


def category_badges(categories: list[str]) -> None:
    with st.container(horizontal=True, gap="small"):
        for c in categories:
            st.badge(c, color=CATEGORY_COLOR.get(c, "gray"))


def bullet(items: list[str]) -> None:
    if items:
        st.markdown("\n".join(f"- {i}" for i in items))


def fmt(x, unit: str = "", nd: int = 2) -> str:
    if x is None:
        return "n/a"
    if isinstance(x, float):
        return f"{x:.{nd}f}{unit}"
    return f"{x}{unit}"


@st.cache_data(ttl=120, show_spinner="Checking NS2 installation...")
def cached_backend_status() -> dict:
    from simulation.runner import backend_status

    return backend_status()
