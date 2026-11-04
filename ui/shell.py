"""Application shell: brand bar and the workflow rail that doubles as navigation."""
from __future__ import annotations

import base64

import streamlit as st

from common.deployment import is_public_deployment
from ui import data
from ui import theme as T
from ui.components import e

_SVG = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48">
<circle cx="10" cy="24" r="4" fill="{T.SIGNAL}"/><circle cx="38" cy="24" r="4" fill="{T.SIGNAL}"/>
<circle cx="24" cy="12" r="3.2" fill="none" stroke="{T.MUT}" stroke-width="1.6"/>
<circle cx="24" cy="36" r="3.2" fill="none" stroke="{T.MUT}" stroke-width="1.6"/>
<path d="M13.5 22.2 L21 13.6 M27 13.6 L34.5 22.2" stroke="{T.CLAY}" stroke-width="2" stroke-linecap="round" stroke-dasharray="2.5 2.5"/>
<path d="M13.5 25.8 L21 34.4 M27 34.4 L34.5 25.8" stroke="{T.GREEN}" stroke-width="2.4" stroke-linecap="round"/>
</svg>"""
# st.html sanitises inline SVG away, so the mark is embedded as a data-URI image
MARK = '<img alt="" width="30" height="30" src="data:image/svg+xml;base64,' + base64.b64encode(_SVG.encode()).decode() + '">'


def brand_bar(demo_page=None) -> None:
    ns2 = data.ns2_status()
    tools = data.tools_status()
    chips = [
        ("NS2 " + (ns2["version"] or "") if ns2["available"] else "NS2 unavailable", T.GREEN if ns2["available"] else T.CLAY),
        ("ping · " + tools["traceroute_cmd"] if tools["ping"] else "ping missing", T.GREEN if tools["ping"] else T.CLAY),
        ("hosted demo · restricted probes" if is_public_deployment() else "local mode", T.AMBER if is_public_deployment() else T.SIGNAL),
    ]
    chip_html = "".join(f'<span class="rr-chip" style="--c:{c}"><i></i>{e(t)}</span>' for t, c in chips)
    with st.container(key="topbar"):
        left, right = st.columns([3, 2.4], vertical_alignment="center")
        left.html(f"""<div class="rr-brand"><div class="rr-mark">{MARK}</div><div>
          <div class="rr-wm">Route<b>ResQ</b></div>
          <div class="rr-tag">Network failure detection · root cause · recovery analytics</div></div></div>""")
        with right.container(horizontal=True, horizontal_alignment="right", vertical_alignment="center", gap="small"):
            st.html(f'<div class="rr-env">{chip_html}</div>')
            if demo_page is not None and st.button("Guided demo", key="nav_demo", type="primary",
                                                   icon=":material/play_circle:"):
                st.switch_page(demo_page)


def _headlines() -> dict[str, str]:
    recs = data.diag_records()
    last = recs[-1] if recs else None
    sims = data.latest_all()
    out = {
        "overview": f"{len(recs)} checks · {len(sims)} scenarios",
        "detect": (f"{last['run']['target']} · {(last['run'].get('ping') or {}).get('loss_pct', 'n/a')}% loss"
                   if last else "no checks yet"),
        "diagnose": (", ".join(last["analysis"]["classifications"])[:34] if last and last.get("analysis") else "awaiting evidence"),
        "impact": f"{len(sims)}/4 NS2 runs stored",
        "recovery": "no failure run yet",
        "transport": "TCP · UDP · TLS",
        "report": f"{len(data.reports())} reports",
        "demo": "end-to-end walkthrough",
    }
    b1 = sims.get("link_failure_dv")
    if b1:
        t = b1["findings"]["recovery"].get("time_to_recovery_s")
        out["recovery"] = f"DV reroute in {t * 1000:.1f} ms" if t is not None else b1["findings"]["recovery"]["outcome"][:30]
    tls = data.latest_comm("failure_demo")
    if tls:
        ok = sum(1 for r in tls["records"] if r["resumed"])
        out["transport"] = f"{ok}/{len(tls['records'])} failures recovered"
    return out


def rail(nav: list[tuple[str, str, str, object]], current_title: str) -> None:
    """nav: (key, stage label, title, st.Page). The workflow stages are joined by arrows."""
    heads = _headlines()
    accents = {"overview": T.SLATE, "detect": T.SIGNAL, "diagnose": T.AMBER, "impact": T.CLAY,
               "recovery": T.GREEN, "transport": T.STEEL, "report": T.SAND, "demo": T.SIGNAL}
    css = []
    for key, _stage, _title, page in nav:
        c = accents[key]
        css.append(f".st-key-nav_{key} button:hover {{ border-color:{c}aa !important; box-shadow:0 8px 22px -14px {c} !important; }}"
                   f".st-key-nav_{key} button:before {{ content:''; position:absolute; top:0; left:0; right:0; height:2px;"
                   f" background:linear-gradient(90deg,{c},transparent); }}")
        if page.title == current_title:
            css.append(f".st-key-nav_{key} button {{ border-color:{c} !important; background:color-mix(in srgb,{c} 11%,{T.PANEL}) !important;"
                       f" box-shadow:0 0 0 1px {c}55, 0 10px 26px -16px {c} !important; }}"
                       f".st-key-nav_{key} button strong {{ color:{c} !important; }}"
                       f".st-key-nav_{key} button:before {{ height:3px !important; }}")
    st.html("<style>" + "".join(css) + "</style>")
    arrow_after = {"detect", "diagnose", "impact"}  # arrows only inside the workflow
    with st.container(key="rail"):
        widths = []
        for key, *_r in nav:
            widths.append(4)
            if key in arrow_after:
                widths.append(.45)
        cols = iter(st.columns(widths, gap="small", vertical_alignment="center"))
        for key, stage, title, page in nav:
            with next(cols):
                label = f"{stage}  \n**{title}**  \n*{heads.get(key, '')[:30]}*"
                if st.button(label, key=f"nav_{key}", width="stretch", help=f"Open {title}"):
                    st.switch_page(page)
            if key in arrow_after:
                next(cols).html('<div class="rr-arrow">&#10230;</div>')
