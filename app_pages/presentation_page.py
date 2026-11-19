"""The project's slide deck (presentation/index.html), shown inside the app.

Streamlit cannot serve an HTML file as a page of its own, so the deck is embedded here. Its one
image is inlined as a data URI, which also makes the downloadable copy a single self-contained file.
"""
import base64

import streamlit as st
import streamlit.components.v1 as components

from common.paths import PROJECT_ROOT
from ui import theme as T
from ui.components import empty, page_header

DECK = PROJECT_ROOT / "presentation" / "index.html"
ASSETS = PROJECT_ROOT / "presentation" / "assets"


@st.cache_data(show_spinner=False)
def _deck(mtime: float) -> str:
    html = DECK.read_text(encoding="utf-8")
    bg = ASSETS / "bg.webp"
    if bg.exists():
        uri = "data:image/webp;base64," + base64.b64encode(bg.read_bytes()).decode()
        html = html.replace("url(assets/bg.webp)", f"url({uri})")
    return html


n_slides = DECK.read_text(encoding="utf-8").count('<section class="slide') if DECK.exists() else 0
page_header("Presentation", f"The project in {n_slides} slides",
            "The demo deck. Click inside it, then use the arrow keys (or click the right / left side) to move between "
            "slides. Download it to present full screen: open the file in a browser and press F.", T.SIGNAL)

if not DECK.exists():
    empty("Deck not found", "presentation/index.html is missing from this deployment.")
    st.stop()

html = _deck(DECK.stat().st_mtime)
st.download_button("Download the presentation (single HTML file)", html, file_name="RouteResQ_presentation.html",
                   mime="text/html", icon=":material/download:")
components.html(html, height=700, scrolling=False)
