import pandas as pd
import streamlit as st

from common.deployment import is_public_deployment
from common.paths import CONFIG_DIR, DIAG_RESULTS_DIR
from diagnostics.authorization import AUTH_FILE, add_authorized_host, authorized_list, check_target
from diagnostics.engine import run_diagnostics
from diagnostics.history import DiagnosticHistory, compare_runs, summary_row
from failure_analysis.rules import Thresholds, analyze_run
from ui import charts
from ui import theme as T
from analysis.cause_report import NO_FAILURE, live_cause
from ui.components import (STATUS_COLOR, badge_row, card, card_title, chart, e, empty, eyebrow, fmt, method, note, page_header,
                           pill, tiles, verdict)

PUBLIC = is_public_deployment()
history = DiagnosticHistory()
TH = Thresholds.load()
st.session_state.setdefault("diag_run_id", None)

page_header("Stage 01 · Detect", "Live network diagnostics",
            "Real <code>ping</code>, <code>traceroute</code>/<code>tracert</code>, DNS lookups and TCP connects, "
            "executed on the machine running RouteResQ against authorised destinations only.", T.SIGNAL)
badge_row("live")
if PUBLIC:
    note("<b>Hosted demo.</b> Probes run from the hosting server, not from your computer, and only the listed "
         "destinations can be tested. Run RouteResQ locally to diagnose your own network.", T.AMBER)

# ------------------------------------------------------------------ run form
with st.container(key="card_form"):
    with st.form("diag_form", border=False):
        c1, c2 = st.columns([2, 1.2])
        options = authorized_list()
        target = c1.selectbox("Destination", options, index=options.index("8.8.8.8") if "8.8.8.8" in options else 0,
                              accept_new_options=not PUBLIC,
                              help="nonexistent.invalid always fails DNS (RFC 6761); 192.0.2.1 has no host (RFC 5737).")
        label = c2.text_input("Label (optional)", placeholder="e.g. lab Wi-Fi, before change")
        c3, c4, c5, c6, c7 = st.columns([1, 1, 1, 1, 1.1], vertical_alignment="bottom")
        count = c3.number_input("Ping probes", 1, 50, 4)
        timeout = c4.number_input("Timeout / probe (s)", 0.2, 10.0, 1.0, step=0.5)
        hops = c5.number_input("Max hops", 1, 30, 15)
        port = c6.number_input("TCP port (0 = off)", 0, 65535, 0)
        do_tr = c7.toggle("Traceroute", value=True)
        go = st.form_submit_button("Run diagnostics", type="primary", icon=":material/radar:", width="stretch")

if go:
    decision = check_target(str(target))
    if not decision.allowed:
        st.error(decision.reason, title=f"{decision.target} is not authorised")
    else:
        baseline, previous = history.baseline(decision.target), history.previous(decision.target)
        with st.status(f"Probing {decision.target}", expanded=True) as status:
            st.write("Reading routing table and DNS configuration, resolving the name, pinging the gateway and "
                     "destination" + (", tracing the path" if do_tr else "") + " ...")
            run = run_diagnostics(decision.target, ping_count=int(count), timeout_s=float(timeout), do_traceroute=do_tr,
                                  max_hops=int(hops), tcp_port=int(port) or None, label=label)
            rep = analyze_run(run, baseline=baseline, previous=previous)
            history.save(run, rep)
            status.update(label=f"Finished probing {decision.target}", state="complete", expanded=False)
        st.session_state.diag_run_id = run.run_id

# ------------------------------------------------------------------ result
recs = history.records()
rec = history.get_record(st.session_state.diag_run_id) if st.session_state.diag_run_id else (recs[-1] if recs else None)
if rec is None:
    empty("No measurements yet", "Choose a destination and run the diagnostics. Try <code>nonexistent.invalid</code> "
          "or <code>192.0.2.1</code> to see how failures are detected.")
else:
    run, a = rec["run"], rec["analysis"]
    p, tr, dns, gw = run.get("ping") or {}, run.get("traceroute"), run.get("dns") or {}, run.get("gateway_ping")
    eyebrow(f"Result · {run['target']}", f"run {run['run_id']} · {run['timestamp']} · {run['platform']}", T.SIGNAL)
    cats = a["classifications"]
    bad = [c for c in cats if c != "Healthy / Reachable"]
    col = T.CLAY if any(c in cats for c in ("DNS Resolution Failure", "Unreachable Destination")) else T.AMBER if bad else T.GREEN
    verdict(" · ".join(cats), a["conclusion"], col)
    rc = live_cause(run, a)
    if rc["status"] != NO_FAILURE:
        st.html(f'<div class="rr-note" style="--c:{STATUS_COLOR[rc["status"]]}"><b>Root cause · {e(rc["status"])}.</b> '
                f'{e(rc["cause"])}' + (f' Other possibilities: {e("; ".join(rc["alternatives"]))}.' if rc["alternatives"] else "")
                + ' The Root cause page shows the full evidence chain.</div>')

    jitter = p.get("stdev_ms")
    tiles([
        ("DNS", "IP literal" if dns.get("is_ip_literal") else ("resolved" if dns.get("success") else "failed"),
         ", ".join(dns.get("addresses", [])[:2]) or (dns.get("error_kind") or ""), T.GREEN if dns.get("success") else T.CLAY),
        ("Echo replies", f"{p.get('received', 0)}<small>/{p.get('sent', 0)}</small>", f"{p.get('timeouts', 0)} timed out",
         T.GREEN if p.get("received") else T.CLAY),
        ("Packet loss", f"{fmt(p.get('loss_pct'), '', 0)}<small>%</small>" if p.get("loss_pct") is not None else "n/a",
         f"threshold {TH.loss_threshold_pct:g}%", T.CLAY if (p.get("loss_pct") or 0) >= TH.loss_threshold_pct else T.GREEN),
        ("Average RTT", f"{fmt(p.get('avg_ms'))}<small>ms</small>" if p.get("avg_ms") is not None else "n/a",
         f"min {fmt(p.get('min_ms'))} · max {fmt(p.get('max_ms'))}", T.AMBER if (p.get("avg_ms") or 0) > TH.high_rtt_ms else T.SIGNAL),
        ("RTT std-dev", f"{fmt(jitter)}<small>ms</small>" if jitter is not None else "n/a", f"jitter threshold {TH.high_jitter_ms:g} ms",
         T.AMBER if (jitter or 0) > TH.high_jitter_ms else T.SIGNAL),
        ("Path", ("reached" if tr["reached_destination"] else "incomplete") if tr else "skipped",
         f"{len(tr['hops'])} hops listed" if tr else "", T.GREEN if tr and tr["reached_destination"] else T.AMBER if tr else T.SLATE),
        ("Gateway", (f"{gw['received']}<small>/{gw['sent']}</small>" if gw else "n/a"),
         (run.get("config") or {}).get("default_gateway") or "not found", T.GREEN if gw and gw.get("received") else T.AMBER),
    ])

    c1, c2 = st.columns(2, gap="medium")
    with c1:
        if p.get("sent"):
            chart(charts.rtt_probes(p, TH.high_rtt_ms), "Round-trip time per probe", "ICMP echo, in send order",
                  what="Each bar is one echo reply's RTT; a red cross marks a probe that got no reply. The dotted line "
                       "is the average and the dashed line the high-latency threshold.",
                  why="Spread between bars is jitter; missing bars are loss. Both feed the rule engine.")
        else:
            empty("No ping result", e("; ".join(p.get("parse_warnings", [])) or "The destination name could not be resolved, so no probe was sent."))
    with c2:
        if tr and tr.get("hops"):
            chart(charts.hops(tr), "Path to destination", f"traceroute, max {run['options'].get('max_hops')} hops",
                  what="Median RTT at each hop that answered, with min-max whiskers. Red crosses are hops that sent "
                       "no reply within the timeout.",
                  why="Where replies stop, or where RTT jumps, is where to look first. Silent hops alone do not prove "
                      "a fault: many routers ignore traceroute probes.")
        else:
            empty("No traceroute", "Traceroute was skipped or the destination name could not be resolved.")

    c3, c4 = st.columns([1, 1], gap="medium")
    with c3, card("hops"):
        card_title("Hop table", "as reported by the tool")
        if tr and tr.get("hops"):
            st.dataframe(pd.DataFrame([{"TTL": h["ttl"], "address": h["address"] or "*",
                                        "RTTs (ms)": ", ".join("*" if v is None else f"{v:g}" for v in h["rtts_ms"]),
                                        "notes": "; ".join(h["annotations"])} for h in tr["hops"]]),
                         hide_index=True, height=260, alt="Traceroute hops")
        else:
            st.caption("No hops recorded.")
    with c4, card("cfg"):
        cfg = run.get("config") or {}
        card_title("Network configuration", "read from the OS of the probing machine")
        st.dataframe(pd.DataFrame([
            {"item": "host", "value": cfg.get("hostname")}, {"item": "platform", "value": cfg.get("platform")},
            {"item": "source IP", "value": cfg.get("primary_source_ip")},
            {"item": "default gateway", "value": cfg.get("default_gateway") or "not found"},
            {"item": "DNS servers", "value": ", ".join(cfg.get("dns_servers", [])) or "not found"},
            {"item": "TCP check", "value": (f"port {run['tcp_check']['port']}: " + ("connected" if run["tcp_check"]["success"]
                                            else run["tcp_check"]["error_kind"])) if run.get("tcp_check") else "off"},
        ]), hide_index=True, height=260, alt="Network configuration")

    b1, b2, _ = st.columns([1.2, 1.2, 2])
    if b1.button("Open root-cause analysis", icon=":material/psychology:", type="primary", width="stretch"):
        st.session_state.diag_run_id = run["run_id"]
        st.switch_page("app_pages/diagnose_page.py")
    if b2.button("Use as baseline", icon=":material/flag:", width="stretch", disabled=not p.get("received")):
        history.set_baseline(run["target"], run["run_id"])
        st.toast(f"Baseline for {run['target']} set to run {run['run_id']}")
    with st.expander("Raw command output"):
        cmds = [("gateway ping", (gw or {}).get("command")), ("ping", p.get("command")), ("traceroute", (tr or {}).get("command"))]
        cmds += [(" ".join(c["argv"]), c) for c in (run.get("config") or {}).get("commands", [])]
        for name, c in cmds:
            if c:
                st.markdown(f"**{name}** · `{' '.join(c['argv'])}` · exit {c['returncode']} · {c['duration_s']} s")
                st.code((c.get("stdout") or c.get("error") or "")[-4000:], language=None)

# ------------------------------------------------------------------ history
eyebrow("History & baselines", "compare runs against the same destination", T.SIGNAL)
targets = history.targets()
if not targets:
    empty("No history yet", "Each run is appended to <code>results/diagnostics/history.jsonl</code>.")
else:
    tsel = st.selectbox("Destination history", targets, index=targets.index(rec["run"]["target"]) if rec and rec["run"]["target"] in targets else 0)
    trecs = history.records(tsel)
    rows = [summary_row(r["run"], r.get("analysis")) for r in trecs]
    base = history.baseline(tsel)
    h1, h2 = st.columns([1.4, 1], gap="medium")
    with h1:
        chart(charts.history_trend(rows), "RTT and loss over time", f"{len(rows)} run(s) · baseline {base.run_id if base else 'not set'}",
              what="Average RTT (line, left axis) and packet loss (bars, right axis) for every run against this destination.",
              why="A baseline turns fixed thresholds into a comparison with this destination's own normal behaviour.")
    with h2, card("cmp"):
        card_title("Compare two runs")
        if len(trecs) >= 2:
            ids = [r["run"]["run_id"] for r in trecs]
            lbl = {r["run"]["run_id"]: f"{r['run']['timestamp'][5:16]} {r['run'].get('label', '')}".strip() for r in trecs}
            a1, a2 = st.columns(2)
            old_id = a1.selectbox("Earlier", ids, index=ids.index(base.run_id) if base and base.run_id in ids else len(ids) - 2, format_func=lbl.get)
            new_id = a2.selectbox("Current", ids, index=len(ids) - 1, format_func=lbl.get)
            cmp = compare_runs(history.get(old_id), history.get(new_id))
            st.html(pill(f"earlier: {cmp['status_earlier']}", T.SLATE) + pill(f"current: {cmp['status_current']}",
                    T.GREEN if cmp["status_current"] == "reachable" else T.CLAY) +
                    pill("path changed" if cmp["path_changed"] else "path unchanged", T.STEEL if cmp["path_changed"] else T.SLATE))
            st.dataframe(pd.DataFrame(cmp["metrics"]).astype(str), hide_index=True, alt="Run comparison")
        else:
            st.caption("Run this destination at least twice to compare.")
        cc1, cc2 = st.columns(2)
        if cc1.button("Export history CSV", icon=":material/download:", width="stretch"):
            st.toast(f"Saved {history.export_csv()}")
        if base and cc2.button("Clear baseline", icon=":material/flag:", width="stretch"):
            history.clear_baseline(tsel)
            st.rerun()

with st.expander("Authorised destinations"):
    st.html("".join(pill(t, T.SIGNAL, dot=False) for t in authorized_list()))
    if PUBLIC:
        st.caption("Adding destinations is disabled on the hosted demo.")
    else:
        with st.form("add_host", border=False):
            host = st.text_input("Add a destination")
            ok = st.checkbox("I am authorised to run network tests against this destination")
            if st.form_submit_button("Add", icon=":material/add:"):
                if not ok:
                    st.error("Confirm that you are authorised to test this destination.")
                else:
                    try:
                        st.success(f"Added {add_authorized_host(host)}")
                    except ValueError as exc:
                        st.error(str(exc))

method([
    ("Validate the destination", "Syntax check and allow-list check (<code>config/authorized_targets.json</code>). Option "
     "injection and shell syntax are rejected; commands run as argument lists, never through a shell."),
    ("Inspect local configuration", "Default gateway from <code>route print</code> / <code>ip route</code>, DNS servers "
     "from <code>ipconfig /all</code> / <code>resolv.conf</code>."),
    ("Resolve and probe", "DNS via <code>getaddrinfo</code> (error kind recorded), gateway ping, destination ping, "
     "traceroute and an optional TCP connect."),
    ("Parse, never estimate", "Counts are taken from individual reply lines and cross-checked with the tool's summary; "
     "disagreements are recorded as parser notes."),
    ("Store", "Run and analysis appended to the history; any healthy run can become the baseline."),
], "diagnostics.engine", [("authorized_targets.json", AUTH_FILE), ("thresholds.json", CONFIG_DIR / "thresholds.json")],
   [("history.jsonl", DIAG_RESULTS_DIR / "history.jsonl"), ("baselines.json", DIAG_RESULTS_DIR / "baselines.json")],
   T.SIGNAL, "how a live measurement is made")
