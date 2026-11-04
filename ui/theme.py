"""RouteResQ design tokens and the single stylesheet.

Base colours, fonts and radii live in .streamlit/config.toml. This file adds only what
config cannot express: tiles, cards, the workflow rail, evidence blocks and the method
flowchart. Every rule targets either our own HTML classes or keyed containers
(``st-key-*``), never Streamlit's internal DOM structure.
"""
from __future__ import annotations

import streamlit as st

# ---- surfaces ----
BG = "#0a0f14"
PANEL = "#111922"
PANEL_2 = "#0e151c"
BORDER = "rgba(148,178,204,.14)"
BORDER_HI = "rgba(148,178,204,.28)"
GRID = "rgba(148,178,204,.09)"
TXT = "#e6edf3"
MUT = "#97a6b5"
DIM = "#66788a"

# ---- semantic accents (one meaning each, everywhere) ----
SIGNAL = "#4fb3c8"   # brand, live measurement, TCP
AMBER = "#e0a957"    # warning, latency, congestion, UDP
CLAY = "#e06b5d"     # failure, loss, unreachable
GREEN = "#58bd8c"    # healthy, recovered, verified
STEEL = "#6f9fe0"    # rerouting, reports
SAND = "#c8a978"     # simulation
SLATE = "#8a9bb0"    # neutral / not applicable
ALT_PATH = SAND      # traffic on the alternative (backup) path n1-n3-n4

HEAD = "'Space Grotesk','Inter',system-ui,sans-serif"
BODY = "'Inter','Segoe UI',system-ui,sans-serif"
MONO = "'JetBrains Mono','Consolas',monospace"

# scenario identity is fixed across every chart
SCENARIO_COLOR = {"healthy": GREEN, "link_failure_dv": STEEL, "link_failure_static": CLAY, "congestion": AMBER}
PROTOCOL_COLOR = {"TCP": SIGNAL, "UDP": AMBER}
PHASE_COLOR = {"before": SLATE, "during": CLAY, "after": GREEN}

CATEGORY_COLOR = {
    "Healthy / Reachable": GREEN,
    "DNS Resolution Failure": CLAY,
    "Unreachable Destination": CLAY,
    "High Latency": AMBER,
    "Packet Loss": AMBER,
    "Possible Routing Issue": STEEL,
    "Possible Congestion": AMBER,
    "Inconclusive / Insufficient Evidence": SLATE,
}
LEVEL_COLOR = {"confirmed": GREEN, "likely": SIGNAL, "possible": AMBER, "insufficient_evidence": SLATE}
LEVEL_LABEL = {"confirmed": "Confirmed observation", "likely": "Likely explanation",
               "possible": "Possible explanation", "insufficient_evidence": "Insufficient evidence"}

CSS = f"""
<style>
.stApp {{
  background:
    radial-gradient(1200px 600px at 85% -10%, rgba(79,179,200,.07), transparent 60%),
    radial-gradient(900px 500px at -10% 10%, rgba(111,159,224,.05), transparent 60%),
    radial-gradient(rgba(148,178,204,.07) 1px, transparent 1px) 0 0 / 22px 22px,
    {BG};
}}
.block-container {{ padding-top: 3.6rem; padding-bottom: 4rem; max-width: 1560px; }}
.stMarkdown p, .stMarkdown li {{ line-height: 1.62; }}

/* ---------- brand bar ---------- */
.st-key-topbar {{ position:relative; padding-bottom:.85rem; }}
.st-key-topbar:after {{ content:""; position:absolute; left:0; right:0; bottom:0; height:1px;
  background:linear-gradient(90deg, transparent, {SIGNAL}88, {STEEL}66, {GREEN}55, transparent); }}
.rr-brand {{ display:flex; align-items:center; gap:.85rem; }}
.rr-mark {{ width:44px; height:44px; border-radius:12px; display:grid; place-items:center;
  border:1px solid {BORDER_HI}; background:{PANEL};
  box-shadow:0 0 28px -12px {SIGNAL}, inset 0 1px 0 rgba(255,255,255,.05); }}
.rr-mark svg {{ width:30px; height:30px; }}
.rr-mark .pulse {{ animation: rrpulse 2.8s ease-in-out infinite; }}
@keyframes rrpulse {{ 0%,100% {{ opacity:.55; }} 50% {{ opacity:1; }} }}
@media (prefers-reduced-motion: reduce) {{ .rr-mark .pulse {{ animation:none; }} }}
.rr-wm {{ font-family:{HEAD}; font-size:1.5rem; font-weight:700; letter-spacing:-.03em; color:{TXT}; line-height:1.1; }}
.rr-wm b {{ color:{SIGNAL}; font-weight:700; }}
.rr-tag {{ color:{MUT}; font-size:.68rem; letter-spacing:.18em; text-transform:uppercase; font-weight:600; margin-top:.2rem; }}
.rr-env {{ display:flex; gap:.45rem; flex-wrap:wrap; justify-content:flex-end; }}
.rr-chip {{ display:inline-flex; align-items:center; gap:.38rem; padding:.22rem .6rem; border-radius:999px;
  font-size:.68rem; font-weight:600; letter-spacing:.04em; color:{MUT}; border:1px solid {BORDER};
  background:rgba(255,255,255,.025); font-family:{MONO}; white-space:nowrap; }}
.rr-chip i {{ width:7px; height:7px; border-radius:50%; background:var(--c); box-shadow:0 0 8px var(--c); display:inline-block; }}

/* ---------- workflow rail (navigation) ---------- */
.st-key-rail {{ margin:.9rem 0 1.4rem 0; }}
div[class*="st-key-nav_"] a {{ display:flex !important; flex-direction:column; align-items:flex-start; justify-content:center;
  width:100%; min-height:82px; padding:.5rem .7rem !important; margin:0; background:{PANEL} !important;
  border:1px solid {BORDER}; border-radius:12px !important; text-decoration:none !important; overflow:hidden;
  transition:border-color .12s ease, transform .12s ease; }}
div[class*="st-key-nav_"] a:hover {{ transform:translateY(-1px); }}
div[class*="st-key-nav_"] a::before {{ font-size:.6rem; letter-spacing:.14em; text-transform:uppercase; color:{DIM}; line-height:1.5; }}
div[class*="st-key-nav_"] a::after {{ font-family:{MONO}; font-size:.68rem; color:{MUT}; line-height:1.5; white-space:nowrap;
  display:block; max-width:100%; overflow:hidden; text-overflow:ellipsis; }}
div[class*="st-key-nav_"] a p, div[class*="st-key-nav_"] a span {{ font-family:{HEAD} !important; font-size:.95rem !important;
  font-weight:600 !important; color:{TXT}; letter-spacing:-.01em; margin:0; }}
.st-key-demo_link {{ flex:0 0 auto; width:auto !important; }}
.st-key-demo_link a {{ background:{SIGNAL} !important; border-radius:10px !important; padding:.42rem .9rem !important;
  text-decoration:none !important; white-space:nowrap; min-width:9.6rem; justify-content:center; }}
.st-key-demo_link a p, .st-key-demo_link a span {{ color:{BG} !important; font-weight:700 !important; }}
.st-key-demo_link a:hover {{ filter:brightness(1.08); }}
.rr-arrow {{ text-align:center; color:{DIM}; font-size:1rem; line-height:82px; }}

@media (max-width: 640px) {{
  .rr-arrow {{ display:none; }}
  div[class*="st-key-nav_"] a {{ min-height:58px; }}
  .rr-ph h1 {{ font-size:1.55rem; }}
  .rr-steps {{ grid-template-columns:1fr 1fr; }}
}}

/* ---------- page header ---------- */
.rr-ph {{ margin:.2rem 0 1rem 0; }}
.rr-ph .k {{ font-size:.66rem; letter-spacing:.2em; text-transform:uppercase; font-weight:700; color:var(--c); }}
.rr-ph h1 {{ font-family:{HEAD}; font-size:2rem; margin:.15rem 0 .25rem 0; letter-spacing:-.035em; line-height:1.15; padding:0; }}
.rr-ph p {{ color:{MUT}; max-width:900px; margin:0; font-size:.95rem; line-height:1.6; }}

/* ---------- KPI tiles ---------- */
.rr-tiles {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:.7rem; margin:.4rem 0 1.2rem 0; }}
.rr-tile {{ background:linear-gradient(165deg, rgba(255,255,255,.045), rgba(255,255,255,.012)); border:1px solid {BORDER};
  border-radius:14px; padding:.8rem .95rem .75rem .95rem; position:relative; overflow:hidden; }}
.rr-tile:before {{ content:""; position:absolute; top:0; left:0; right:0; height:2px; background:linear-gradient(90deg,var(--c),transparent 85%); }}
.rr-tile .l {{ color:{MUT}; font-size:.62rem; letter-spacing:.15em; text-transform:uppercase; font-weight:700; }}
.rr-tile .v {{ font-family:{HEAD}; font-size:1.7rem; font-weight:700; color:var(--c); letter-spacing:-.03em;
  line-height:1.12; margin:.32rem 0 .15rem 0; font-variant-numeric:tabular-nums; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.rr-tile .v small {{ font-size:.9rem; color:{MUT}; font-weight:600; margin-left:.15rem; }}
.rr-tile .n {{ color:{DIM}; font-size:.74rem; line-height:1.4; }}

/* ---------- section eyebrow ---------- */
.rr-eb {{ display:flex; align-items:baseline; gap:.7rem; margin:1.7rem 0 .8rem 0; padding-left:.7rem;
  border-left:3px solid var(--c); }}
.rr-eb h3 {{ font-family:{HEAD}; margin:0; padding:0; font-size:1.15rem; font-weight:600; letter-spacing:-.02em; }}
.rr-eb span {{ color:{DIM}; font-size:.82rem; }}

/* ---------- one card shape ---------- */
div[class*="st-key-card"] {{ background:{PANEL}; border:1px solid {BORDER}; border-radius:16px; padding:.9rem 1rem .6rem 1rem; height:100%; }}
div[class*="st-key-card"] [data-testid="stExpander"] {{ border:0; border-top:1px solid {BORDER}; border-radius:0; background:transparent; }}
.rr-card {{ background:{PANEL}; border:1px solid {BORDER}; border-radius:16px; padding:1rem 1.1rem; margin-bottom:.8rem; }}
.rr-card h4 {{ font-family:{HEAD}; margin:0 0 .35rem 0; padding:0; font-size:1rem; font-weight:600; letter-spacing:-.015em; }}
.rr-card .sub {{ color:{MUT}; font-size:.84rem; line-height:1.6; }}
.rr-ctitle {{ font-family:{HEAD}; font-size:.98rem; font-weight:600; color:{TXT}; letter-spacing:-.015em; margin:0 0 .1rem 0; }}
.rr-csub {{ color:{DIM}; font-size:.76rem; margin-bottom:.35rem; }}

/* ---------- pills / badges ---------- */
.rr-pill {{ display:inline-flex; align-items:center; gap:.35rem; padding:.18rem .58rem; border-radius:999px; font-size:.7rem;
  font-weight:600; color:var(--c); background:color-mix(in srgb, var(--c) 13%, transparent);
  border:1px solid color-mix(in srgb, var(--c) 45%, transparent); white-space:nowrap; margin:0 .3rem .3rem 0; }}
.rr-pill i {{ width:6px; height:6px; border-radius:50%; background:var(--c); display:inline-block; }}
.rr-src {{ display:inline-block; font-size:.6rem; letter-spacing:.14em; text-transform:uppercase; font-weight:700;
  color:var(--c); border:1px solid color-mix(in srgb, var(--c) 50%, transparent); border-radius:6px; padding:.12rem .45rem; }}

/* ---------- evidence ladder (root cause) ---------- */
.rr-ladder {{ display:grid; grid-template-columns:repeat(4,1fr); gap:.7rem; }}
@media (max-width: 1100px) {{ .rr-ladder {{ grid-template-columns:1fr 1fr; }} }}
@media (max-width: 640px) {{ .rr-ladder {{ grid-template-columns:1fr; }} }}
.rr-rung {{ background:{PANEL}; border:1px solid {BORDER}; border-radius:14px; padding:.85rem .9rem; position:relative; }}
.rr-rung .h {{ display:flex; align-items:center; gap:.5rem; margin-bottom:.5rem; }}
.rr-rung .num {{ width:24px; height:24px; border-radius:7px; display:grid; place-items:center; font-family:{MONO};
  font-size:.72rem; font-weight:600; color:var(--c); border:1px solid var(--c); }}
.rr-rung .t {{ font-family:{HEAD}; font-weight:600; font-size:.92rem; }}
.rr-rung ul {{ margin:0; padding-left:1rem; }}
.rr-rung li {{ color:{MUT}; font-size:.8rem; line-height:1.55; margin-bottom:.2rem; }}
.rr-cause {{ border:1px solid {BORDER}; border-left:3px solid var(--c); border-radius:12px; padding:.75rem .9rem; margin-bottom:.6rem; background:{PANEL_2}; }}
.rr-cause .c {{ font-family:{HEAD}; font-weight:600; font-size:.95rem; margin-bottom:.35rem; }}
.rr-cause .row {{ display:grid; grid-template-columns:150px 1fr; gap:.6rem; font-size:.8rem; margin:.15rem 0; }}
.rr-cause .row b {{ color:{DIM}; font-weight:600; font-size:.66rem; letter-spacing:.12em; text-transform:uppercase; padding-top:.15rem; }}
.rr-cause .row span {{ color:{MUT}; line-height:1.5; }}

/* ---------- verdict banner ---------- */
.rr-verdict {{ border:1px solid color-mix(in srgb, var(--c) 45%, transparent); background:color-mix(in srgb, var(--c) 8%, {PANEL});
  border-radius:14px; padding:.9rem 1.1rem; margin:.3rem 0 1rem 0; display:flex; gap:.9rem; align-items:flex-start; }}
.rr-verdict .dot {{ width:12px; height:12px; border-radius:50%; background:var(--c); box-shadow:0 0 14px var(--c); margin-top:.35rem; flex:none; }}
.rr-verdict .k {{ font-size:.62rem; letter-spacing:.18em; text-transform:uppercase; font-weight:700; color:var(--c); }}
.rr-verdict .t {{ font-size:.98rem; color:{TXT}; line-height:1.55; margin-top:.15rem; }}

/* ---------- timeline ---------- */
.rr-tl {{ position:relative; padding-left:1.4rem; }}
.rr-tl:before {{ content:""; position:absolute; left:.42rem; top:.3rem; bottom:.3rem; width:2px; background:{BORDER}; }}
.rr-ev {{ position:relative; margin-bottom:.55rem; }}
.rr-ev:before {{ content:""; position:absolute; left:-1.18rem; top:.38rem; width:10px; height:10px; border-radius:50%;
  background:{BG}; border:2px solid var(--c); }}
.rr-ev .tm {{ font-family:{MONO}; font-size:.72rem; color:var(--c); font-weight:600; }}
.rr-ev .src {{ font-size:.58rem; letter-spacing:.14em; text-transform:uppercase; color:{DIM}; margin-left:.45rem; }}
.rr-ev .d {{ color:{MUT}; font-size:.82rem; line-height:1.5; }}

/* ---------- method flow + artefacts ---------- */
.rr-flow .step {{ position:relative; display:grid; grid-template-columns:40px 1fr; gap:.9rem; padding-bottom:.9rem; }}
.rr-flow .step:not(:last-child):after {{ content:""; position:absolute; left:19px; top:44px; bottom:0; width:2px;
  background:linear-gradient(180deg, var(--c), {BORDER}); }}
.rr-flow .node {{ width:40px; height:40px; border-radius:11px; display:grid; place-items:center; font-family:{MONO};
  font-size:.8rem; font-weight:600; color:var(--c); border:1.5px solid var(--c); background:rgba(255,255,255,.03); }}
.rr-flow .body {{ background:{PANEL}; border:1px solid {BORDER}; border-radius:12px; padding:.6rem .8rem; }}
.rr-flow h5 {{ font-family:{HEAD}; margin:0 0 .15rem 0; padding:0; font-size:.92rem; font-weight:600; }}
.rr-flow p {{ margin:0; color:{MUT}; font-size:.82rem; line-height:1.55; }}
.rr-flow code {{ font-size:.72rem; }}
.rr-io {{ background:{PANEL}; border:1px solid {BORDER}; border-radius:14px; padding:.9rem 1rem; }}
.rr-io .h {{ font-size:.62rem; letter-spacing:.16em; text-transform:uppercase; font-weight:700; color:{MUT}; margin-bottom:.6rem; }}
.rr-io .k {{ font-size:.6rem; letter-spacing:.14em; text-transform:uppercase; font-weight:700; color:var(--c); margin:.35rem 0 .3rem 0; }}
.rr-io .row {{ display:flex; justify-content:space-between; gap:.6rem; background:rgba(255,255,255,.03); border:1px solid {BORDER};
  border-radius:8px; padding:.32rem .55rem; margin-bottom:.28rem; font-size:.75rem; }}
.rr-io .row span:last-child {{ color:{DIM}; font-family:{MONO}; font-size:.68rem; white-space:nowrap; }}
.rr-io .eng {{ text-align:center; font-family:{HEAD}; font-weight:600; font-size:.88rem; color:var(--c);
  border:1.5px solid var(--c); border-radius:10px; padding:.5rem; margin:.5rem 0; }}

/* ---------- empty / note ---------- */
.rr-empty {{ border:1px dashed {BORDER_HI}; border-radius:14px; padding:1.1rem 1.2rem; background:rgba(255,255,255,.012); }}
.rr-empty .t {{ font-family:{HEAD}; font-weight:600; color:{MUT}; }}
.rr-empty .b {{ color:{DIM}; font-size:.82rem; line-height:1.6; margin-top:.25rem; max-width:640px; }}
.rr-note {{ border:1px solid color-mix(in srgb, var(--c) 35%, transparent); background:color-mix(in srgb, var(--c) 6%, transparent);
  border-radius:12px; padding:.6rem .85rem; color:{MUT}; font-size:.8rem; line-height:1.55; margin:.2rem 0 .9rem 0; }}
.rr-note b {{ color:var(--c); }}

/* ---------- demo stepper ---------- */
.rr-steps {{ display:grid; grid-template-columns:repeat(6,1fr); gap:.45rem; margin:.4rem 0 1.1rem 0; }}
.rr-steps div {{ border-radius:10px; padding:.5rem .6rem; border:1px solid {BORDER}; background:{PANEL}; font-size:.72rem; color:{DIM}; }}
.rr-steps div b {{ display:block; font-family:{HEAD}; font-size:.85rem; color:{MUT}; font-weight:600; }}
.rr-steps div.on {{ border-color:var(--c); box-shadow:0 0 0 1px var(--c) inset; }}
.rr-steps div.on b {{ color:{TXT}; }}
.rr-steps div.done {{ border-color:color-mix(in srgb, {GREEN} 50%, transparent); }}
.rr-steps div.done b {{ color:{GREEN}; }}

/* ---------- state chain (connection / handshake) ---------- */
.rr-chain {{ display:flex; align-items:stretch; gap:0; margin:.3rem 0 .9rem 0; flex-wrap:wrap; }}
.rr-chain .s {{ flex:1 1 140px; border:1px solid {BORDER}; background:{PANEL}; padding:.6rem .7rem; position:relative; min-width:130px; }}
.rr-chain .s:first-child {{ border-radius:12px 0 0 12px; }}
.rr-chain .s:last-child {{ border-radius:0 12px 12px 0; }}
.rr-chain .s + .s {{ border-left:0; }}
.rr-chain .s:before {{ content:""; position:absolute; top:0; left:0; right:0; height:3px; background:var(--c); }}
.rr-chain .s .t {{ font-family:{HEAD}; font-size:.85rem; font-weight:600; color:{TXT}; display:flex; gap:.35rem; align-items:center; }}
.rr-chain .s .t i {{ font-style:normal; color:var(--c); font-family:{MONO}; font-size:.8rem; }}
.rr-chain .s .d {{ color:{MUT}; font-size:.72rem; line-height:1.45; margin-top:.2rem; font-family:{MONO}; word-break:break-word; }}

/* ---------- root-cause register ---------- */
.rr-reg {{ border:1px solid {BORDER}; border-radius:14px; overflow:hidden; background:{PANEL}; }}
.rr-reg-h, .rr-reg-r {{ display:grid; grid-template-columns:130px 170px 1.1fr 170px 2.2fr; gap:.8rem; padding:.55rem .9rem; align-items:start; }}
.rr-reg-h {{ background:{PANEL_2}; border-bottom:1px solid {BORDER}; }}
.rr-reg-h span {{ font-size:.6rem; letter-spacing:.15em; text-transform:uppercase; font-weight:700; color:{DIM}; }}
.rr-reg-r {{ border-bottom:1px solid {BORDER}; font-size:.8rem; color:{MUT}; line-height:1.5; }}
.rr-reg-r:last-child {{ border-bottom:0; }}
.rr-reg-r .src {{ font-size:.66rem; letter-spacing:.1em; text-transform:uppercase; color:{DIM}; font-weight:600; padding-top:.15rem; }}
.rr-reg-r .sub {{ font-family:{MONO}; color:{TXT}; font-size:.76rem; word-break:break-word; }}
.rr-reg-r .cause {{ color:{TXT}; }}
@media (max-width: 900px) {{ .rr-reg-h {{ display:none; }} .rr-reg-r {{ grid-template-columns:1fr; gap:.25rem; }} }}

/* ---------- widgets ---------- */
div[data-testid="stWidgetLabel"] p {{ color:{MUT} !important; font-size:.68rem !important; letter-spacing:.12em;
  text-transform:uppercase; font-weight:600; }}
div[data-testid="stCaptionContainer"] p {{ color:{DIM}; font-size:.76rem; }}
.stTabs [data-baseweb="tab-list"] {{ gap:.25rem; border-bottom:1px solid {BORDER}; }}
.stTabs [data-baseweb="tab"] {{ border-radius:9px 9px 0 0; padding:.4rem .85rem; }}
.stTabs [aria-selected="true"] {{ background:rgba(79,179,200,.10); }}
</style>
"""


def inject() -> None:
    st.html(CSS)
