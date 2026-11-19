import json
from pathlib import Path

import pandas as pd
import streamlit as st

from netlab.config import (MAX_FILE_BYTES, MIN_FILE_BYTES, RUN_DESCRIPTIONS, RUN_LABELS, RUN_MODES, SAMPLE_BYTES,
                           SAMPLE_NAME, ConfigError, LabConfig, check_file_size, sample_bytes)
from netlab.report import BACKUP_DEFINITION, STALL_DEFINITION, rows as compare_rows, source_line
from ui import charts, data
from ui import theme as T
from ui.components import (badge_row, card, card_title, chart, e, empty, eyebrow, fmt, method, note, page_header, tiles,
                           verdict)

page_header("Lab · File upload under link failure", "What happens to an upload when a link fails?",
            "A real TCP upload of real file bytes across an isolated test network with a primary and a backup path. "
            "Halfway through, the primary link is taken down. Three runs answer one question: does the upload "
            "<b>continue on a backup route</b>, <b>stall until the link returns</b>, or <b>fail and need a retry</b>?",
            T.UPLOAD)

status = data.netlab_status()
runs = data.upload_runs()

# ------------------------------------------------------------------ set-up
with card("upl_setup"):
    a, b = st.columns([1.05, 1], gap="large")
    with a:
        card_title("The test network", "three Linux network namespaces inside the lab container; the host's network is untouched")
        st.plotly_chart(charts.upload_topology(), width="stretch", key="upl_topo_static",
                        config={"displayModeBar": False})
    with b:
        card_title("Three runs, same file, same settings", "only the forwarding behaviour differs")
        for mode in RUN_MODES:
            st.html(f'<div class="rr-note" style="--c:{T.RUN_COLOR[mode]};margin-bottom:.45rem">'
                    f'<b>{e(RUN_LABELS[mode])}.</b> {e(RUN_DESCRIPTIONS[mode])}</div>')
        st.caption("The fault is applied after a set share of the file has been **received by the server**. "
                   "The backup route is a pre-installed floating static route (controlled failover), not a routing "
                   "protocol. A retry is a new TCP connection that re-sends the file from byte 0.")

# ------------------------------------------------------------------ run form
eyebrow("Run the experiment", status["reason"], T.GREEN if status["available"] else T.SLATE)
with st.container(key="card_uplform"), st.form("upl_form", border=False):
    c1, c2 = st.columns([1.3, 1], vertical_alignment="bottom")
    up = c1.file_uploader(f"File to upload ({MIN_FILE_BYTES // 1024} KiB - {MAX_FILE_BYTES // 1048576} MiB)",
                          help="Leave empty to use the bundled sample.")
    use_sample = c2.toggle(f"Use the bundled sample ({SAMPLE_BYTES // 1048576} MiB)", value=True)
    d1, d2, d3, d4, d5 = st.columns(5, vertical_alignment="bottom")
    pct = d1.slider("Fail the link at (% received)", 10, 80, 30, step=5)
    outage = d2.number_input("Link down for (s)", 0.5, 30.0, 3.0, step=0.5)
    rate = d3.number_input("Upload pacing (KiB/s)", 64, 4096, 512, step=64)
    timeout = d4.number_input("Socket timeout (s)", 1.0, 30.0, 10.0, step=1.0)
    retries = d5.number_input("Retries allowed", 0, 3, 1)
    go = st.form_submit_button("Run all three uploads", type="primary", icon=":material/upload_file:",
                               disabled=not status["available"])
if not status["available"]:
    st.caption("Running needs Linux with root, or Docker with the `routeresq-netlab:1` image: "
               "`docker build -f docker/Dockerfile.netlab -t routeresq-netlab:1 docker`, then "
               "`python -m netlab.runner`. The results below come from stored runs.")
if go:
    try:
        if up is not None and not use_sample:
            payload, name = up.getvalue(), up.name
        else:
            payload, name = sample_bytes(), SAMPLE_NAME
        check_file_size(len(payload))
        cfg = LabConfig(fault_at_pct=float(pct), outage_s=float(outage), rate_kib_s=float(rate),
                        timeout_s=float(timeout), retries=int(retries)).validate()
        from netlab.runner import NetlabError, run_experiment

        with st.spinner("Building the test network and uploading three times ..."):
            new_dir = run_experiment(payload, name, cfg)
        st.session_state.upl_run = str(new_dir)
        st.rerun()
    except ConfigError as exc:
        st.error(str(exc))
    except Exception as exc:  # noqa: BLE001 - shown to the user
        st.error(f"The experiment could not run: {exc}")

if not runs:
    empty("No run yet", "Run the experiment, or add the recorded run in results/netlab/recorded.")
    st.stop()

labels = {str(d): (("Recorded run · " if d.name == "recorded" else "Live run · ") + d.name) for d in runs}
default = st.session_state.get("upl_run", str(runs[0]))
pick = st.selectbox("Run", list(labels), index=list(labels).index(default) if default in labels else 0,
                    format_func=labels.get, key="upl_pick")
run = data.upload_run(Path(pick))
if not run:
    empty("Run unreadable", "This run folder has no readable results.")
    st.stop()
recorded = run["meta"].get("source") == "recorded"
badge_row("netlab", *(["recorded"] if recorded else []))
st.caption(source_line(run))
rws = compare_rows(run)
by = {r["mode"]: r for r in rws}

# ------------------------------------------------------------------ verdicts
eyebrow("What happened", "measured outcome of each run, in plain words", T.UPLOAD)
for r in rws:
    color = {"completed": T.GREEN, "continued_on_backup": T.STEEL, "stalled_then_resumed": T.AMBER,
             "completed_after_retry": T.AMBER}.get(r["code"], T.CLAY)
    verdict(f"{r['run']} · {r['outcome']}", r["summary"], color)

fo, so = by.get("failover"), by.get("static")
tiles([
    ("Backup route · stall", f"{fmt(fo['stall_s'], '', 2)}<small>s</small>" if fo else "n/a", "longest pause at the server", T.STEEL),
    ("Static · stall", f"{fmt(so['stall_s'], '', 2)}<small>s</small>" if so else "n/a", "longest pause at the server", T.CLAY),
    ("Backup bytes (failover)", f"{fmt(fo['backup_bytes'] / 1048576, '', 2)}<small>MiB</small>"
     if fo and fo["backup_bytes"] is not None else "n/a", "client backup interface, during the outage", T.ALT_PATH),
    ("Retries needed", str(sum(1 for r in rws if r["retry_required"])), "new TCP connections across the runs", T.SLATE),
    ("SHA-256", "all match" if all(r["sha256_match"] for r in rws) else "see table", "client file = server file",
     T.GREEN if all(r["sha256_match"] for r in rws) else T.AMBER),
])

# ------------------------------------------------------------------ comparison
with card("upl_cmp"):
    card_title("Three-run comparison", "same file, pacing, timeout and topology; n/a = not measurable in that run")
    df = pd.DataFrame([{
        "Run": r["run"], "Outcome": r["outcome"], "Completed": "yes" if r["completed"] else "no",
        "Total time (s)": fmt(r["total_s"], "", 2), "Stall (s)": fmt(r["stall_s"], "", 3),
        "Retry required": "yes" if r["retry_required"] else "no",
        "Same TCP connection": "yes" if r["same_connection"] else "no",
        "Backup path used": ("n/a" if r["backup_used"] is None else ("yes" if r["backup_used"] else "no"))
        + (f" ({r['backup_bytes']:,} B)" if r["backup_bytes"] is not None else ""),
        "First backup traffic (s after link down)": fmt(r["first_backup_after_down_s"], "", 3),
        "Resumed after link up (s)": fmt(r["resumed_after_link_up_s"], "", 3),
        "SHA-256": "match" if r["sha256_match"] else ("n/a" if r["sha256_match"] is None else "MISMATCH"),
    } for r in rws])
    st.dataframe(df, hide_index=True, width="stretch")
    st.caption(STALL_DEFINITION + " " + BACKUP_DEFINITION)

chart(charts.upload_overlay(run), "Receiver progress, all three runs", "server-confirmed % of the file vs time",
      what="Share of the file the server had read, against time since the upload started. The shaded band is the outage "
           "of the fault runs.",
      why="A flat line is a stall: the server received nothing. A line that keeps rising during the outage means the "
          "upload found another path.", key="upl_overlay")

# ------------------------------------------------------------------ one run in detail
eyebrow("One run in detail", "progress, path evidence and the forwarding decision", T.UPLOAD)
mode = st.segmented_control("Run detail", [m for m in RUN_MODES if m in run["runs"]], default="failover"
                            if "failover" in run["runs"] else RUN_MODES[0], format_func=RUN_LABELS.get,
                            required=True, key="upl_mode", label_visibility="collapsed")
res = run["runs"][mode]
o = res["outcome"]
l1, l2 = st.columns([1.5, 1], gap="medium")
with l1:
    chart(charts.upload_progress(res), "Receiver progress", res["label"],
          what="Bytes the server had received, as % of the file, per TCP connection. Markers: link down / up, first "
               "upload bytes on the backup interface, progress resumed, upload complete or attempt failed.",
          why="Progress is measured at the receiver; bytes the client handed to its socket may still have been buffered.",
          key=f"upl_prog_{mode}")
with l2:
    win = st.segmented_control("Window", ["before", "outage", "after"], default="outage", required=True,
                               key=f"upl_win_{mode}") if o.get("link_down_t") is not None else "all"
    with card("upl_paths"):
        card_title("Bytes the client sent on each path", f"window: {win}")
        st.plotly_chart(charts.upload_topology(res, win), width="stretch", key=f"upl_topo_{mode}_{win}",
                        config={"displayModeBar": False})
chart(charts.path_bytes(res), "Path evidence: interface byte counters", "client primary vs backup interface",
      what="Cumulative bytes sent by the client's primary and backup interfaces, sampled every 50 ms.",
      why="This is the direct evidence of which path carried the upload. A completed upload alone does not show the path.",
      key=f"upl_paths_{mode}")
c1, c2 = st.columns(2, gap="medium")
with c1, card("upl_routes"):
    card_title("Forwarding decision", "ip route get, in the client and server namespaces")
    if res.get("routes"):
        st.dataframe(pd.DataFrame([{"When": x["label"], "Client → server": x["c"], "Server → client": x["s"]}
                                   for x in res["routes"]]), hide_index=True, width="stretch")
    else:
        st.caption("n/a")
with c2, card("upl_events"):
    card_title("Event log", "one clock for the server, the client and the fault controller")
    keep = ("transfer_start", "client_connected", "link_down", "first_backup_traffic", "link_up", "progress_resumed",
            "server_complete", "client_ack", "client_failed", "retry_started", "server_timeout", "run_limit", "cleanup")
    st.dataframe(pd.DataFrame([{"t (s)": f"{ev['t']:.3f}", "event": ev["kind"], "detail": ev["detail"]}
                               for ev in res["events"] if ev["kind"] in keep]), hide_index=True, width="stretch")
note("<b>How to read the outcome.</b> <i>Same TCP connection</i> means the upload finished on the connection it "
     "started on (the server accepted exactly one connection). A <i>retry</i> is a new connection that re-sends the "
     "whole file; RouteResQ does not resume from a byte offset. Recovery is only claimed when the server's own byte "
     "count shows it.", T.UPLOAD)

method([
    ("Build the test network", "Three namespaces (client, router, server), veth links with emulated delay, "
     "service addresses on loopback so the TCP connection survives a path change."),
    ("Upload", "The client sends the real file bytes with RouteResQ's framing (FILE_META, FILE_CHUNK, FILE_END), paced "
     "so the upload is still running at the fault."),
    ("Inject the fault", "When the server has received the configured share of the file, both ends of the primary link "
     "are taken down; they come back after the configured outage."),
    ("Measure", "Server progress, interface counters (every 50 ms) and ip route get snapshots on one clock."),
    ("Verify", "The server's SHA-256 must equal the client's; outcomes are classified from the recorded events."),
], "netlab.lab (real sockets, Linux namespaces)",
    [("Uploaded file (deleted after the run)", "in memory"), ("Run settings", json.dumps(run["meta"]["config"])[:60] + "...")],
    [(f"{m}.json", Path(pick) / f"{m}.json") for m in run["runs"]] + [("meta.json", Path(pick) / "meta.json")],
    T.UPLOAD, "how one run is produced")

st.download_button("Download this run (JSON)", json.dumps(run, indent=1), file_name=f"upload_run_{Path(pick).name}.json",
                   mime="application/json", icon=":material/download:")
