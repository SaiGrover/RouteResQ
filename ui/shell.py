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

LAB = "CN Lab · JIIT Noida"
REPO = "SaiGrover/RouteResQ"
_GH = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path fill="{T.MUT}" d="M8 0C3.58 0 0 3.58 0 8c0 '
       '3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82'
       '-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-'
       '.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 '
       '2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54'
       '.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>')
GH_ICON = '<img alt="" width="15" height="15" src="data:image/svg+xml;base64,' + base64.b64encode(_GH.encode()).decode() + '">'


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
        left, mid, right = st.columns([2.5, 2.3, 1.7], vertical_alignment="center")
        left.html(f"""<div class="rr-brand"><div class="rr-mark">{MARK}</div><div>
          <div class="rr-wm">Route<b>ResQ</b></div>
          <div class="rr-tag">Network failure detection · root cause · recovery analytics</div></div></div>""")
        with mid.container(horizontal=True, horizontal_alignment="right", vertical_alignment="center", gap="small"):
            st.html(f'<div class="rr-env">{chip_html}</div>')
            if demo_page is not None:
                # page_link navigates client-side: no rerun of the page being left
                with st.container(key="demo_link"):
                    st.page_link(demo_page, label="Guided demo", icon=":material/play_circle:")
        right.html(f"""<div class="rr-who"><div class="rr-lab">{e(LAB)}</div>
          <a class="rr-repo" href="https://github.com/{REPO}" target="_blank" rel="noopener noreferrer">{GH_ICON}<span>{e(REPO)}</span></a>
          </div>""")


def _headlines() -> dict[str, str]:
    recs = data.diag_records()
    last = recs[-1] if recs else None
    sims = data.latest_all()
    out = {
        "overview": f"{len(recs)} checks · {len(sims)} sims",
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


def _css_str(text: str) -> str:
    """Quote text for a CSS ``content:`` value."""
    clean = " ".join(str(text).split())
    return '"' + clean.replace("\\", "\\\\").replace('"', '\\"') + '"'


def rail(nav: list[tuple[str, str, str, object]], current_title: str) -> None:
    """nav: (key, stage label, title, st.Page).

    Each node is an st.page_link, so navigation happens in the browser without re-running the
    page being left (buttons + switch_page re-ran the whole current page first, which felt laggy).
    The stage label and the live headline are drawn with CSS pseudo-elements around the link text.
    """
    heads = _headlines()
    accents = {"overview": T.SLATE, "detect": T.SIGNAL, "diagnose": T.AMBER, "impact": T.CLAY,
               "recovery": T.GREEN, "transport": T.STEEL, "report": T.SAND, "demo": T.SIGNAL}
    css = []
    for key, stage, _title, page in nav:
        c = accents[key]
        sel = f".st-key-nav_{key} a"
        css.append(f"{sel}::before {{ content:{_css_str(stage)}; }}"
                   f"{sel}::after {{ content:{_css_str(heads.get(key, '')[:32])}; }}"
                   f"{sel} {{ box-shadow: inset 0 2px 0 0 {c}; }}"
                   f"{sel}:hover {{ border-color:{c}aa !important; }}")
        if page.title == current_title:
            css.append(f"{sel} {{ border-color:{c} !important; background:color-mix(in srgb,{c} 12%,{T.PANEL}) !important;"
                       f" box-shadow: inset 0 3px 0 0 {c}, 0 10px 26px -16px {c} !important; }}"
                       f"{sel} p, {sel} span {{ color:{c} !important; }}")
    # The row is a CSS grid with one equal track per node (see theme.py): it never wraps, every node
    # has the same width and height, and the arrows are drawn in the gaps, so the rail reads as one
    # evenly spaced journey. Below 1180 px (too tight for seven readable nodes) it becomes a
    # horizontal scroll strip of fixed-width nodes instead of squeezing or wrapping them.
    css.append(f"@media (min-width: 1181px) {{ .st-key-rail [data-testid='stHorizontalBlock'] "
               f"{{ grid-template-columns:repeat({len(nav)}, minmax(0, 1fr)) !important; }} }}")
    st.html("<style>" + "".join(css) + "</style>")
    with st.container(key="rail"):
        for col, (key, _stage, title, page) in zip(st.columns(len(nav), gap="small"), nav):
            with col, st.container(key=f"nav_{key}"):
                st.page_link(page, label=title, width="stretch")
