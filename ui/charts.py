"""One Plotly chart system for the whole app. Every figure is built from backend results
passed in by the caller; nothing is synthesised here."""
from __future__ import annotations

import plotly.graph_objects as go

from simulation.scenario import LINKS, NODE_ROLES
from ui import theme as T

AXIS = dict(gridcolor=T.GRID, zerolinecolor=T.GRID, linecolor=T.GRID, tickfont=dict(color=T.DIM, size=11),
            title_font=dict(color=T.MUT, size=11.5))


def style(fig: go.Figure, h: int = 320, legend: bool = True, margin_t: int | None = None) -> go.Figure:
    fig.update_layout(
        height=h, template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, Segoe UI, system-ui, sans-serif", size=12, color=T.MUT),
        margin=dict(l=6, r=10, b=6, t=margin_t if margin_t is not None else (34 if legend else 10)),
        hoverlabel=dict(bgcolor="#16212c", bordercolor=T.BORDER_HI, font=dict(color=T.TXT, size=12, family="Inter")),
        showlegend=legend,
        legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0, bgcolor="rgba(0,0,0,0)",
                    font=dict(size=11, color=T.MUT), title_text=""),
        colorway=[T.SIGNAL, T.AMBER, T.GREEN, T.CLAY, T.STEEL, T.SLATE],
    )
    fig.update_xaxes(**AXIS)
    fig.update_yaxes(**AXIS)
    return fig


def _events(fig: go.Figure, scenario: dict) -> None:
    """Shade the configured event window and mark its edges (from the scenario config)."""
    p = scenario["effective_params"]
    if str(p.get("fail_link", "none")) != "none":
        t0, t1 = float(p["fail_at"]), float(p["restore_at"]) if float(p["restore_at"]) >= 0 else None
        label, c = f"link {p['fail_link']} down", T.CLAY
    elif str(p.get("cross_rate", "0")) != "0":
        t0, t1 = float(p["cross_start"]), float(p["cross_stop"])
        label, c = "competing flow active", T.AMBER
    else:
        return
    fig.add_vrect(x0=t0, x1=t1 if t1 else float(p["stop"]), fillcolor=c, opacity=.07, line_width=0, layer="below")
    fig.add_vline(x=t0, line=dict(color=c, width=1.2, dash="dot"))
    if t1:
        fig.add_vline(x=t1, line=dict(color=T.GREEN, width=1.2, dash="dot"))
    fig.add_annotation(x=t0, y=0, yref="paper", text=label, showarrow=False, xanchor="left", yanchor="bottom",
                       font=dict(size=10.5, color=c), xshift=4, yshift=4, bgcolor="rgba(10,15,20,.75)")


# ------------------------------------------------------------------ topology
POS = {0: (0, 0), 1: (1.15, 0), 2: (2.3, .62), 3: (2.3, -.62), 4: (3.45, 0), 5: (4.6, 0)}


def topology(scenario: dict | None, result: dict | None = None, phase: str = "during", h: int = 300,
             labels: bool = True) -> go.Figure:
    """Topology with link state from the scenario and, if a result is given, the paths that
    delivered packets actually took in the chosen phase (reconstructed from the trace)."""
    p = (scenario or {}).get("effective_params", {})
    failed = set(map(int, str(p.get("fail_link", "none")).split("-"))) if str(p.get("fail_link", "none")) != "none" else None
    used: dict[frozenset, int] = {}
    if result:
        for path, n in result["path_usage"].get(phase, {}).items():
            nodes = [int(x) for x in path.split("-")]
            for a, b in zip(nodes, nodes[1:]):
                used[frozenset((a, b))] = used.get(frozenset((a, b)), 0) + n
    bottleneck = None
    if result and result.get("bottleneck_link") and scenario and scenario["category"] == "congestion":
        a, b = result["bottleneck_link"].split("->")
        bottleneck = frozenset((int(a), int(b)))
    fail_window = None
    if failed and p:
        fail_window = (float(p["fail_at"]), float(p["restore_at"]) if float(p["restore_at"]) >= 0 else float(p["stop"]))
    phase_window = tuple((scenario or {}).get("phases", {}).get(phase, (0, 0)))
    link_down_now = bool(failed and fail_window and phase_window and phase_window[0] < fail_window[1] and phase_window[1] > fail_window[0])

    fig = go.Figure()
    maxn = max(used.values()) if used else 1
    for a, b, kind in LINKS:
        (x0, y0), (x1, y1) = POS[a], POS[b]
        key = frozenset((a, b))
        bw = p.get("access_bw" if kind == "access" else "core_bw", "")
        dl = p.get("access_delay" if kind == "access" else "core_delay" if kind == "core" else "alt_delay", "")
        n = used.get(key, 0)
        if failed and key == frozenset(failed) and link_down_now:
            color, width, dash = T.CLAY, 3, "dash"
        elif bottleneck and key == bottleneck:
            color, width, dash = T.AMBER, 3 + 4 * n / maxn, "solid"
        elif n:
            color, width, dash = (T.ALT_PATH if kind == "alt" else T.SIGNAL), 2 + 5 * n / maxn, "solid"
        else:
            color, width, dash = "rgba(148,178,204,.28)", 1.6, "dot" if kind == "alt" else "solid"
        hover = f"n{a} - n{b}<br>{bw}, {dl}" + (f", cost {p.get('alt_cost')}" if kind == "alt" else "") + \
                (f"<br>{n} delivered packets in '{phase}'" if result else "")
        fig.add_trace(go.Scatter(x=[x0, x1], y=[y0, y1], mode="lines", line=dict(color=color, width=width, dash=dash),
                                 hoverinfo="skip", showlegend=False))
        fig.add_trace(go.Scatter(x=[(x0 + x1) / 2], y=[(y0 + y1) / 2], mode="markers", marker=dict(size=14, opacity=0),
                                 hovertemplate=hover + "<extra></extra>", showlegend=False))
        # label offset along the edge normal, pointing away from the centre line
        dx, dy = x1 - x0, y1 - y0
        ln = (dx * dx + dy * dy) ** .5
        nx, ny = -dy / ln, dx / ln
        my = (y0 + y1) / 2
        if (my < 0 < ny) or (my > 0 > ny):
            nx, ny = -nx, -ny
        if labels:
            fig.add_annotation(x=(x0 + x1) / 2 + nx * .16, y=my + ny * .16, text=f"{bw} · {dl}", showarrow=False,
                               font=dict(size=9.5, color=T.DIM))
        if failed and key == frozenset(failed) and link_down_now:
            fig.add_trace(go.Scatter(x=[(x0 + x1) / 2], y=[(y0 + y1) / 2], mode="markers+text", text=["DOWN"],
                                     textposition="bottom right", textfont=dict(color=T.CLAY, size=10),
                                     marker=dict(symbol="x-thin", size=16, line=dict(color=T.CLAY, width=3)),
                                     hoverinfo="skip", showlegend=False))
    xs = [POS[n][0] for n in NODE_ROLES]
    ys = [POS[n][1] for n in NODE_ROLES]
    colors = [T.SIGNAL if n in (0, 5) else "#1a2632" for n in NODE_ROLES]
    fig.add_trace(go.Scatter(
        x=xs, y=ys, mode="markers+text", text=[f"n{n}" for n in NODE_ROLES], textposition="middle center",
        textfont=dict(color=[T.BG if n in (0, 5) else T.TXT for n in NODE_ROLES], size=12, family="JetBrains Mono"),
        marker=dict(size=38, color=colors, line=dict(color=[T.SIGNAL] * 6, width=1.5)),
        customdata=list(NODE_ROLES.values()), hovertemplate="%{text}<br>%{customdata}<extra></extra>",
        showlegend=False))
    for n, label in ((0, "source"), (5, "destination")):
        fig.add_annotation(x=POS[n][0], y=POS[n][1] - .3, text=label, showarrow=False, font=dict(size=10, color=T.MUT))
    style(fig, h=h, legend=False, margin_t=6)
    fig.update_xaxes(visible=False, range=[-.4, 5.0])
    fig.update_yaxes(visible=False, range=[-1.0, 1.0], scaleanchor=None)
    fig.update_layout(dragmode=False)
    return fig


# ------------------------------------------------------------------ simulation series
def throughput(result: dict, h: int = 300) -> go.Figure:
    ts = result["timeseries"]
    fig = go.Figure()
    t = [r["t"] for r in ts]
    fig.add_trace(go.Scatter(x=t, y=[r["throughput_kbps"] for r in ts], name="flow 1 (monitored)", mode="lines",
                             line=dict(color=T.SIGNAL, width=2, shape="hv"), fill="tozeroy", fillcolor="rgba(79,179,200,.10)",
                             hovertemplate="t=%{x:.1f}s<br>%{y:.0f} kb/s<extra>flow 1</extra>"))
    if ts and "cross_throughput_kbps" in ts[0]:
        fig.add_trace(go.Scatter(x=t, y=[r["cross_throughput_kbps"] for r in ts], name="flow 2 (competing)", mode="lines",
                                 line=dict(color=T.AMBER, width=1.6, shape="hv"),
                                 hovertemplate="t=%{x:.1f}s<br>%{y:.0f} kb/s<extra>flow 2</extra>"))
    _events(fig, result["scenario"])
    style(fig, h)
    fig.update_xaxes(title="simulation time (s)")
    fig.update_yaxes(title="kb/s received (100 ms bins)", rangemode="tozero")
    return fig


def delay(result: dict, h: int = 260) -> go.Figure:
    ts = [r for r in result["timeseries"] if r["avg_delay_ms"] is not None]
    paths = sorted({r["path"] for r in ts})
    fig = go.Figure()
    for pth in paths:
        pts = [r for r in ts if r["path"] == pth]
        c = T.ALT_PATH if "3" in pth.split("-") else T.SIGNAL
        fig.add_trace(go.Scatter(x=[r["t"] for r in pts], y=[r["avg_delay_ms"] for r in pts], mode="markers",
                                 name=f"path {pth}", marker=dict(size=6, color=c),
                                 hovertemplate="sent t=%{x:.1f}s<br>%{y:.2f} ms<extra>" + pth + "</extra>"))
    _events(fig, result["scenario"])
    style(fig, h)
    fig.update_xaxes(title="send time (s)")
    fig.update_yaxes(title="end-to-end delay (ms)")
    return fig


def losses(result: dict, h: int = 220) -> go.Figure:
    ts = result["timeseries"]
    fig = go.Figure(go.Bar(x=[r["t"] for r in ts], y=[r["lost"] for r in ts], marker_color=T.CLAY, name="lost",
                           hovertemplate="sent t=%{x:.1f}s<br>%{y} lost<extra></extra>"))
    _events(fig, result["scenario"])
    style(fig, h, legend=False)
    fig.update_xaxes(title="send time (s)")
    fig.update_yaxes(title="packets lost per 100 ms", rangemode="tozero")
    return fig


def queue(result: dict, h: int = 240) -> go.Figure:
    ts = result["timeseries"]
    fig = go.Figure()
    if ts and "bottleneck_queue_pkts" in ts[0]:
        fig.add_trace(go.Scatter(x=[r["t"] for r in ts], y=[r["bottleneck_queue_pkts"] for r in ts], mode="lines",
                                 line=dict(color=T.AMBER, width=2, shape="hv"), fill="tozeroy",
                                 fillcolor="rgba(224,169,87,.12)", name=f"queue {result['bottleneck_link']}",
                                 hovertemplate="t=%{x:.1f}s<br>%{y} packets<extra></extra>"))
        lim = int(result["scenario"]["effective_params"]["queue_limit"])
        fig.add_hline(y=lim, line=dict(color=T.CLAY, dash="dot", width=1), annotation_text=f"queue limit {lim}",
                      annotation_font=dict(color=T.CLAY, size=10), annotation_position="top left")
    _events(fig, result["scenario"])
    style(fig, h, legend=False)
    fig.update_xaxes(title="time (s)")
    fig.update_yaxes(title="packets queued (max per 100 ms)", rangemode="tozero")
    return fig


def routing_messages(result: dict, h: int = 220) -> go.Figure:
    s = result["routing_control"]["series"]
    fig = go.Figure(go.Bar(x=[r["t"] for r in s], y=[r["messages"] for r in s], marker_color=T.STEEL,
                           hovertemplate="t=%{x:.1f}s<br>%{y} DV messages<extra></extra>"))
    _events(fig, result["scenario"])
    style(fig, h, legend=False)
    fig.update_xaxes(title="time (s)")
    fig.update_yaxes(title=f"DV messages / {result['routing_control']['bin_size']} s")
    return fig


def phases(result: dict, h: int = 280) -> go.Figure:
    from plotly.subplots import make_subplots

    ph = result["phases"]["1"]
    names = ["before", "during", "after"]
    metrics = [("throughput_kbps", "Throughput (kb/s)"), ("avg_delay_ms", "Avg delay (ms)"), ("loss_pct", "Loss (%)")]
    fig = make_subplots(rows=1, cols=3, subplot_titles=[m[1] for m in metrics], horizontal_spacing=.08)
    for i, (k, _) in enumerate(metrics, start=1):
        vals = [ph[n][k] for n in names]
        fig.add_trace(go.Bar(x=names, y=[v if v is not None else 0 for v in vals],
                             marker_color=[T.PHASE_COLOR[n] for n in names],
                             text=["n/a" if v is None else f"{v:,.1f}" for v in vals], textposition="outside",
                             textfont=dict(color=T.MUT, size=11), cliponaxis=False,
                             hovertemplate="%{x}: %{text}<extra></extra>", showlegend=False), row=1, col=i)
    style(fig, h, legend=False, margin_t=30)
    fig.update_annotations(font=dict(size=11.5, color=T.MUT, family="Inter"))
    fig.update_yaxes(rangemode="tozero")
    for ax in fig.layout:
        if ax.startswith("yaxis"):
            fig.layout[ax].update(range=[0, None])
    return fig


def fates(result: dict, h: int = 240) -> go.Figure:
    ph = result["phases"]["1"]
    order = [("delivered", T.GREEN), ("dropped_queue", T.AMBER), ("dropped_link_down", T.CLAY),
             ("lost_at_node", "#b8564b"), ("lost_on_link", "#8f4a43"), ("in_flight", T.SLATE)]
    fig = go.Figure()
    for fate, c in order:
        ys = [ph[n]["fates"].get(fate, 0) for n in ("before", "during", "after")]
        if any(ys):
            fig.add_trace(go.Bar(x=["before", "during", "after"], y=ys, name=fate.replace("_", " "), marker_color=c,
                                 hovertemplate="%{x}: %{y} packets<extra>" + fate + "</extra>"))
    style(fig, h)
    fig.update_layout(barmode="stack")
    fig.update_yaxes(title="packets (by send time)")
    return fig


def scenario_compare(rows: list[dict], metric: str, label: str, h: int = 300) -> go.Figure:
    fig = go.Figure()
    for r in rows:
        ph = r["phases"]["1"]
        ys = [ph[n][metric] for n in ("before", "during", "after")]
        fig.add_trace(go.Bar(x=["before", "during", "after"], y=[y if y is not None else 0 for y in ys],
                             name=f"{r['scenario']['label']} {r['scenario']['id']}",
                             marker_color=T.SCENARIO_COLOR.get(r["scenario"]["id"], T.SLATE),
                             customdata=["n/a" if y is None else f"{y:,.2f}" for y in ys],
                             hovertemplate="%{x}: %{customdata}<extra>%{fullData.name}</extra>"))
    style(fig, h)
    fig.update_layout(barmode="group", bargap=.25, bargroupgap=.06)
    fig.update_yaxes(title=label, rangemode="tozero")
    return fig


def overlay_throughput(results: list[dict], h: int = 300) -> go.Figure:
    fig = go.Figure()
    for r in results:
        ts = r["timeseries"]
        sid = r["scenario"]["id"]
        fig.add_trace(go.Scatter(x=[x["t"] for x in ts], y=[x["throughput_kbps"] for x in ts], mode="lines",
                                 name=f"{r['scenario']['label']} {sid}", line=dict(color=T.SCENARIO_COLOR.get(sid), width=1.8, shape="hv"),
                                 hovertemplate="t=%{x:.1f}s %{y:.0f} kb/s<extra>%{fullData.name}</extra>"))
    fig.add_vrect(x0=3, x1=6, fillcolor=T.SLATE, opacity=.06, line_width=0, layer="below",
                  annotation_text="event window 3-6 s", annotation_position="top left",
                  annotation_font=dict(size=10, color=T.MUT))
    style(fig, h)
    fig.update_xaxes(title="simulation time (s)")
    fig.update_yaxes(title="flow 1 kb/s received", rangemode="tozero")
    return fig


# ------------------------------------------------------------------ live diagnostics
def rtt_probes(ping: dict, threshold: float, h: int = 240) -> go.Figure:
    rtts = ping.get("rtts_ms") or []
    sent = ping.get("sent") or len(rtts)
    xs = list(range(1, len(rtts) + 1))
    fig = go.Figure(go.Bar(x=xs, y=rtts, marker_color=T.SIGNAL, name="echo reply",
                           hovertemplate="reply %{x}: %{y:.2f} ms<extra></extra>"))
    lost = max(sent - len(rtts), 0)
    if lost:
        fig.add_trace(go.Bar(x=list(range(len(rtts) + 1, sent + 1)), y=[0] * lost, name="no reply",
                             marker=dict(color=T.CLAY, line=dict(color=T.CLAY, width=2)),
                             hovertemplate="probe %{x}: no reply<extra></extra>"))
        for x in range(len(rtts) + 1, sent + 1):
            fig.add_annotation(x=x, y=0, text="✕", showarrow=False, font=dict(color=T.CLAY, size=14), yshift=10)
    if rtts:
        avg = sum(rtts) / len(rtts)
        fig.add_hline(y=avg, line=dict(color=T.GREEN, dash="dot", width=1), annotation_text=f"avg {avg:.2f} ms",
                      annotation_font=dict(color=T.GREEN, size=10), annotation_position="top right")
    if rtts and max(rtts) > threshold * .5:
        fig.add_hline(y=threshold, line=dict(color=T.AMBER, dash="dash", width=1), annotation_text=f"threshold {threshold:g} ms",
                      annotation_font=dict(color=T.AMBER, size=10), annotation_position="bottom right")
    style(fig, h, legend=bool(lost))
    fig.update_xaxes(title="probe", dtick=1)
    fig.update_yaxes(title="RTT (ms)", rangemode="tozero")
    return fig


def hops(tr: dict, h: int = 300) -> go.Figure:
    xs, med, mn, mx, labels, silent = [], [], [], [], [], []
    for hp in tr.get("hops", []):
        vals = sorted(v for v in hp["rtts_ms"] if v is not None)
        if hp.get("address") and vals:
            xs.append(hp["ttl"])
            med.append(vals[len(vals) // 2])
            mn.append(vals[0])
            mx.append(vals[-1])
            labels.append(hp["address"])
        else:
            silent.append(hp["ttl"])
    fig = go.Figure()
    if xs:
        fig.add_trace(go.Scatter(x=xs, y=med, mode="lines+markers", name="median RTT", line=dict(color=T.SIGNAL, width=2),
                                 marker=dict(size=9, color=T.SIGNAL, line=dict(color=T.BG, width=1.5)),
                                 error_y=dict(type="data", symmetric=False, array=[b - m for b, m in zip(mx, med)],
                                              arrayminus=[m - a for a, m in zip(mn, med)], color="rgba(79,179,200,.4)", thickness=1),
                                 customdata=labels, hovertemplate="TTL %{x} · %{customdata}<br>median %{y:.1f} ms<extra></extra>"))
    if silent:
        fig.add_trace(go.Scatter(x=silent, y=[0] * len(silent), mode="markers", name="no reply (*)",
                                 marker=dict(symbol="x-thin", size=12, line=dict(color=T.CLAY, width=2.5)),
                                 hovertemplate="TTL %{x}: no reply<extra></extra>"))
    style(fig, h)
    fig.update_xaxes(title="hop (TTL)", dtick=1)
    fig.update_yaxes(title="RTT (ms)", rangemode="tozero")
    return fig


def history_trend(rows: list[dict], h: int = 280) -> go.Figure:
    fig = go.Figure()
    xs = [r["timestamp"] for r in rows]
    fig.add_trace(go.Scatter(x=xs, y=[r["avg_rtt_ms"] for r in rows], mode="lines+markers", name="avg RTT (ms)",
                             line=dict(color=T.SIGNAL, width=2), customdata=[r["run_id"] for r in rows],
                             hovertemplate="%{x}<br>%{y:.2f} ms<extra>run %{customdata}</extra>"))
    fig.add_trace(go.Bar(x=xs, y=[r["loss_pct"] for r in rows], name="loss (%)", marker_color="rgba(224,107,93,.55)",
                         yaxis="y2", hovertemplate="%{x}<br>%{y}% loss<extra></extra>"))
    style(fig, h)
    fig.update_layout(yaxis=dict(title="avg RTT (ms)", rangemode="tozero"),
                      yaxis2=dict(title="loss %", overlaying="y", side="right", range=[0, 100], showgrid=False,
                                  tickfont=dict(color=T.DIM, size=11), title_font=dict(color=T.MUT, size=11.5)))
    return fig


# ------------------------------------------------------------------ transport
def protocol_bars(rows: list[dict], key: str, label: str, h: int = 260, rng=None) -> go.Figure:
    fig = go.Figure()
    for proto in ("TCP", "UDP"):
        rs = [r for r in rows if r["protocol"] == proto]
        fig.add_trace(go.Bar(x=[f"trial {r['trial']}" for r in rs], y=[r.get(key) or 0 for r in rs], name=proto,
                             marker_color=T.PROTOCOL_COLOR[proto],
                             hovertemplate=f"{proto} %{{x}}: %{{y:,.3f}}<extra></extra>"))
    style(fig, h)
    fig.update_layout(barmode="group", bargap=.3)
    fig.update_yaxes(title=label, range=rng)
    return fig
