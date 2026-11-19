"""Reusable presentation components. Every value shown comes from the caller - these
functions only lay it out. Text from measurements is HTML-escaped."""
from __future__ import annotations

import itertools
from html import escape
from pathlib import Path

import streamlit as st

from ui import theme as T

_KEY = itertools.count()


def e(x) -> str:
    return escape("" if x is None else str(x))


def code(text: str) -> str:
    """Escape text, then render `backticked` spans as inline code."""
    import re

    return re.sub(r"`([^`]+)`", lambda m: f"<code>{m.group(1)}</code>", e(text))


def fmt(x, unit: str = "", nd: int = 2) -> str:
    if x is None:
        return "n/a"
    if isinstance(x, float):
        return f"{x:,.{nd}f}{unit}"
    if isinstance(x, int):
        return f"{x:,}{unit}"
    return f"{x}{unit}"


# ------------------------------------------------------------------ headers / tiles
def page_header(kicker: str, title: str, text: str, color: str = T.SIGNAL) -> None:
    st.html(f'<div class="rr-ph" style="--c:{color}"><div class="k">{e(kicker)}</div>'
            f'<h1>{e(title)}</h1><p>{text}</p></div>')


def tiles(items: list[tuple[str, str, str, str]]) -> None:
    """items: (label, value, note, colour). ``value`` may contain a <small> unit."""
    body = "".join(
        f'<div class="rr-tile" style="--c:{c}"><div class="l">{e(label)}</div>'
        f'<div class="v">{value}</div><div class="n">{e(note)}</div></div>'
        for label, value, note, c in items)
    st.html(f'<div class="rr-tiles">{body}</div>')


def eyebrow(title: str, sub: str = "", color: str = T.SIGNAL) -> None:
    st.html(f'<div class="rr-eb" style="--c:{color}"><h3>{e(title)}</h3><span>{e(sub)}</span></div>')


# ------------------------------------------------------------------ badges
def pill(text: str, color: str = T.SLATE, dot: bool = True) -> str:
    return f'<span class="rr-pill" style="--c:{color}">{"<i></i>" if dot else ""}{e(text)}</span>'


def pills(items: list[tuple[str, str]]) -> None:
    st.html("<div>" + "".join(pill(t, c) for t, c in items) + "</div>")


def source_badge(kind: str) -> str:
    label, c = {"live": ("Live measurement", T.SIGNAL), "sim": ("NS2 simulation", T.SAND),
                "loopback": ("Real sockets - loopback", T.STEEL), "stored": ("Stored NS2 run", T.SAND),
                "netlab": ("Real TCP upload - isolated test network", T.UPLOAD),
                "recorded": ("Recorded run (captured locally)", T.SLATE)}[kind]
    return f'<span class="rr-src" style="--c:{c}">{label}</span>'


def badge_row(*kinds: str) -> None:
    st.html('<div style="display:flex;gap:.4rem;margin:-.4rem 0 .8rem 0">' + "".join(source_badge(k) for k in kinds) + "</div>")


def verdict(kicker: str, text: str, color: str) -> None:
    st.html(f'<div class="rr-verdict" style="--c:{color}"><div class="dot"></div><div>'
            f'<div class="k">{e(kicker)}</div><div class="t">{e(text)}</div></div></div>')


def note(text_html: str, color: str = T.AMBER) -> None:
    st.html(f'<div class="rr-note" style="--c:{color}">{text_html}</div>')


def empty(title: str, body: str) -> None:
    st.html(f'<div class="rr-empty"><div class="t">{e(title)}</div><div class="b">{body}</div></div>')


# ------------------------------------------------------------------ cards / charts
def card(name: str = ""):
    """A keyed container that the stylesheet turns into the standard card."""
    return st.container(key=f"card_{name}_{next(_KEY)}")


def card_title(title: str, sub: str = "") -> None:
    st.html(f'<div class="rr-ctitle">{e(title)}</div>' + (f'<div class="rr-csub">{e(sub)}</div>' if sub else ""))


def chart(fig, title: str = "", sub: str = "", what: str = "", why: str = "", key: str | None = None) -> None:
    with card("chart"):
        if title:
            card_title(title, sub)
        st.plotly_chart(fig, width="stretch", key=key, config={"displayModeBar": False, "responsive": True})
        if what:
            with st.expander("Interpretation"):
                st.markdown(f"**What this shows.** {what}")
                if why:
                    st.markdown(f"**Why it matters.** {why}")


# ------------------------------------------------------------------ timeline / method
def timeline(events: list[dict], max_items: int | None = None) -> None:
    color = {"configured": T.SAND, "trace": T.SIGNAL}
    special = {"LINK_DOWN": T.CLAY, "LINK_DOWN_TRACED": T.CLAY, "FIRST_LOSS_AFTER_FAILURE": T.CLAY,
               "DELIVERY_GAP_START": T.CLAY, "DELIVERY_STOPPED": T.CLAY, "QUEUE_FULL": T.AMBER,
               "FIRST_QUEUE_DROP": T.AMBER, "ROUTE_CHANGE": T.STEEL, "LINK_UP": T.GREEN,
               "LINK_UP_TRACED": T.GREEN, "DELIVERY_RESUMED": T.GREEN, "QUEUE_DRAINED": T.GREEN,
               "CROSS_TRAFFIC_START": T.AMBER, "ROUTING_UPDATES": T.STEEL}
    rows = events[:max_items] if max_items else events
    html = "".join(
        f'<div class="rr-ev" style="--c:{special.get(ev["event"], color.get(ev["source"], T.SLATE))}">'
        f'<span class="tm">t = {ev["time"]:.4f} s</span><span class="src">{e(ev["source"])}</span>'
        f'<div class="d">{e(ev["description"])}</div></div>'
        for ev in rows)
    st.html(f'<div class="rr-tl">{html}</div>')


def size_of(p: Path) -> str:
    if not p.exists():
        return "missing"
    n = p.stat().st_size
    for unit, div in (("MB", 1 << 20), ("KB", 1 << 10)):
        if n >= div:
            return f"{n / div:.1f} {unit}"
    return f"{n} B"


def method(steps: list[tuple[str, str]], engine: str, inputs: list[tuple[str, Path | str]],
           outputs: list[tuple[str, Path | str]], color: str = T.SIGNAL, sub: str = "") -> None:
    """Method flowchart beside an artefact panel. Path sizes are read from disk now."""
    eyebrow("Method", sub, color)
    left, right = st.columns([1.35, 1], gap="large")
    n = len(steps)
    with left:
        st.html('<div class="rr-flow">' + "".join(
            f'<div class="step" style="--c:{T.GREEN if i == n - 1 else color}"><div class="node">{i + 1:02d}</div>'
            f'<div class="body"><h5>{e(t)}</h5><p>{b}</p></div></div>'
            for i, (t, b) in enumerate(steps)) + "</div>")

    def rows(items):
        return "".join(f'<div class="row"><span>{e(lbl)}</span><span>{size_of(p) if isinstance(p, Path) else e(p)}</span></div>'
                       for lbl, p in items)

    with right:
        st.html(f'<div class="rr-io"><div class="h">Artefacts</div>'
                f'<div class="k" style="--c:{color}">Consumed</div>{rows(inputs)}'
                f'<div class="eng" style="--c:{color}">{e(engine)}</div>'
                f'<div class="k" style="--c:{T.GREEN}">Produced</div>{rows(outputs)}'
                f'<div style="color:{T.DIM};font-size:.66rem;margin-top:.5rem">Sizes read from disk on this page load.</div></div>')


def chain(stages: list[tuple[str, str, str]]) -> None:
    """stages: (title, state, detail) with state ok | fail | skip. Only backend-verified states are passed in."""
    look = {"ok": (T.GREEN, "&#10003;"), "fail": (T.CLAY, "&#10005;"), "skip": ("#3a4856", "&middot;")}
    st.html('<div class="rr-chain">' + "".join(
        f'<div class="s" style="--c:{look[s][0]}"><div class="t"><i>{look[s][1]}</i>{e(t)}</div><div class="d">{e(d)}</div></div>'
        for t, s, d in stages) + "</div>")


STATUS_COLOR = {"Confirmed (injected)": T.GREEN, "Likely": T.SIGNAL, "Not confirmed": T.AMBER, "No failure detected": T.SLATE}


def cause_register(rows: list[dict], show_healthy: bool = True) -> None:
    """Compact root-cause register: source, subject, failure, cause status and the cause itself."""
    rows = [r for r in rows if show_healthy or r["status"] != "No failure detected"]
    if not rows:
        empty("No failures to explain", "Nothing in the stored results needs a root cause.")
        return
    head = ('<div class="rr-reg"><div class="rr-reg-h"><span>Source</span><span>Subject</span><span>Failure</span>'
            '<span>Cause status</span><span>Root cause</span></div>')
    body = "".join(
        f'<div class="rr-reg-r"><span class="src">{e(r["source"])}</span><span class="sub">{e(r["subject"])}</span>'
        f'<span>{e(r["failure"])}</span><span>{pill(r["status"], STATUS_COLOR[r["status"]])}</span>'
        f'<span class="cause">{code(r["cause"])}</span></div>' for r in rows)
    st.html(head + body + "</div>")
