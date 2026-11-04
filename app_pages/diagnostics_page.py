import altair as alt
import pandas as pd
import streamlit as st

from common.deployment import is_public_deployment
from diagnostics.authorization import add_authorized_host, authorized_list, check_target
from diagnostics.engine import run_diagnostics
from diagnostics.history import DiagnosticHistory, compare_runs, summary_row
from diagnostics.models import run_from_dict
from failure_analysis.rules import CATEGORIES, Thresholds, analyze_run
from ui.components import bullet, category_badges, level_badge, live_badge

history = DiagnosticHistory()
PUBLIC = is_public_deployment()
if "diag_last_run" not in st.session_state:
    st.session_state.diag_last_run = None

st.title("Diagnostics & root-cause analysis")
live_badge()
st.caption("Every measurement comes from a command executed on the machine running RouteResQ. Only destinations "
           "in the authorised list can be probed.")
if PUBLIC:
    st.info("This is the hosted demo: probes run from the hosting server, not from your computer, and only the "
            "listed destinations are allowed. Run RouteResQ locally to diagnose your own network.",
            icon=":material/cloud:")

mode = st.segmented_control(
    "View", ["Run diagnostics", "History & comparison", "Authorised destinations"],
    default="Run diagnostics", key="diag_mode", label_visibility="collapsed", required=True,
)

# ------------------------------------------------------------------ run diagnostics
if mode == "Run diagnostics":
    with st.form("diag_form", border=True):
        c1, c2 = st.columns([2, 1])
        options = authorized_list()
        target = c1.selectbox("Destination", options, index=options.index("8.8.8.8") if "8.8.8.8" in options else 0,
                              accept_new_options=not PUBLIC,
                              help="Pick an authorised destination" + ("." if PUBLIC else
                                   " or type one (private/loopback addresses are allowed)."))
        label = c2.text_input("Label (optional)", placeholder="e.g. lab Wi-Fi, before change")
        c3, c4, c5, c6 = st.columns(4)
        count = c3.number_input("Ping probes", 1, 50, 4)
        timeout = c4.number_input("Timeout per probe (s)", 0.2, 10.0, 1.0, step=0.5)
        hops = c5.number_input("Traceroute max hops", 1, 30, 15)
        port = c6.number_input("TCP port check (0 = off)", 0, 65535, 0)
        do_tr = st.toggle("Run traceroute", value=True)
        submitted = st.form_submit_button("Run diagnostics", type="primary", icon=":material/play_arrow:")

    if submitted:
        decision = check_target(str(target))
        if not decision.allowed:
            st.error(decision.reason, title=f"{decision.target} is not authorised")
        else:
            baseline = history.baseline(decision.target)
            previous = history.previous(decision.target)
            with st.status(f"Diagnosing {decision.target}...", expanded=True) as status:
                st.write("Inspecting network configuration, resolving name, pinging gateway and destination"
                         + (", running traceroute" if do_tr else "") + "...")
                run = run_diagnostics(decision.target, ping_count=int(count), timeout_s=float(timeout),
                                      do_traceroute=do_tr, max_hops=int(hops), tcp_port=int(port) or None,
                                      label=label)
                report = analyze_run(run, baseline=baseline, previous=previous)
                history.save(run, report)
                status.update(label=f"Diagnostics finished for {decision.target}", state="complete", expanded=False)
            st.session_state.diag_last_run = run.run_id

    rec = history.get_record(st.session_state.diag_last_run) if st.session_state.diag_last_run else None
    if rec:
        run = run_from_dict(rec["run"])
        a = rec["analysis"]
        st.subheader(f"Result for {run.target}")
        st.caption(f"Run {run.run_id} at {run.timestamp} on {run.platform}"
                   + (f" - label '{run.label}'" if run.label else "")
                   + (f" - compared with baseline {a['baseline_run_id']}" if a.get("baseline_run_id") else " - no baseline set"))
        category_badges(a["classifications"])
        headline = st.error if any(c in a["classifications"] for c in CATEGORIES[1:3]) else \
            st.warning if len(a["classifications"]) > 1 or "Inconclusive / Insufficient Evidence" in a["classifications"] else st.success
        headline(a["conclusion"], title="Conclusion")

        p = run.ping
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("DNS", "IP literal" if run.dns and run.dns.is_ip_literal else ("resolved" if run.dns and run.dns.success else "failed"), border=True)
        m2.metric("Echo replies", f"{p.received}/{p.sent}" if p else "n/a", border=True)
        m3.metric("Packet loss", f"{p.loss_pct}%" if p and p.loss_pct is not None else "n/a", border=True)
        m4.metric("Average RTT", f"{p.avg_ms} ms" if p and p.avg_ms is not None else "n/a", border=True)
        tr = run.traceroute
        m5.metric("Traceroute", ("reached" if tr.reached_destination else "not reached") if tr else "skipped", border=True)

        b1, _ = st.columns([1, 3])
        if b1.button("Use this run as the baseline", icon=":material/flag:", disabled=not (p and p.received)):
            history.set_baseline(run.target, run.run_id)
            st.toast(f"Baseline for {run.target} set to run {run.run_id}")

        left, right = st.columns([1, 1])
        with left:
            st.markdown("#### Observations")
            st.caption("Facts read directly from command output.")
            bullet(a["observations"])
            if a["contradictions"]:
                st.markdown("#### Contradictory evidence")
                for c in a["contradictions"]:
                    st.warning(c, icon=":material/rule:")
        with right:
            st.markdown("#### Findings")
            if not a["findings"]:
                st.write("No rule produced a problem finding.")
            for f in a["findings"]:
                with st.container(border=True):
                    with st.container(horizontal=True, gap="small"):
                        level_badge(f["level"])
                        st.badge(f["category"], color="gray")
                        st.caption(f["rule_id"])
                    st.markdown(f"**{f['title']}**")
                    bullet(f["evidence"])

        if a["explanations"]:
            st.markdown("#### Possible root causes")
            st.caption("Ordered as produced by the rules. 'Likely' means best supported by the evidence; "
                       "'possible' means consistent with it but not distinguishable from the alternatives.")
            for e in a["explanations"]:
                with st.expander(f"{e['cause']}  -  {e['level']}", expanded=e["level"] == "likely"):
                    level_badge(e["level"])
                    cols = st.columns(2)
                    with cols[0]:
                        st.markdown("**Supporting evidence**")
                        bullet(e["supporting_evidence"] or ["(none beyond the observed symptom)"])
                        if e["contrary_evidence"]:
                            st.markdown("**Evidence against**")
                            bullet(e["contrary_evidence"])
                    with cols[1]:
                        st.markdown("**Checks needed to confirm**")
                        bullet(e["checks_to_confirm"])
                        if e["recommended_actions"]:
                            st.markdown("**Recommended actions**")
                            bullet(e["recommended_actions"])

        with st.expander("Rule trace (why each conclusion was or was not produced)"):
            st.dataframe(pd.DataFrame(a["rule_trace"]), hide_index=True, alt="Every rule evaluated and its outcome",
                         column_config={"fired": st.column_config.CheckboxColumn("Fired")})
            st.json(a["thresholds"], expanded=False)

        if tr and tr.hops:
            with st.expander("Traceroute hops", expanded=not tr.reached_destination):
                st.dataframe(pd.DataFrame([{"TTL": h.ttl, "Address": h.address or "* (no reply)",
                                            "RTTs (ms)": ", ".join("*" if r is None else f"{r:g}" for r in h.rtts_ms),
                                            "Notes": "; ".join(h.annotations)} for h in tr.hops]),
                             hide_index=True, alt="Traceroute hop list")
        if run.config:
            with st.expander("Network configuration"):
                cfg = run.config
                st.dataframe(pd.DataFrame([
                    {"Item": "Host name", "Value": cfg.hostname},
                    {"Item": "Platform", "Value": cfg.platform},
                    {"Item": "Primary source IP", "Value": cfg.primary_source_ip or "n/a"},
                    {"Item": "Local addresses", "Value": ", ".join(cfg.local_addresses)},
                    {"Item": "Default gateway", "Value": cfg.default_gateway or "not found"},
                    {"Item": "DNS servers", "Value": ", ".join(cfg.dns_servers) or "not found"},
                ]), hide_index=True, alt="Local network configuration")
                bullet(cfg.notes)
        with st.expander("Raw command output"):
            cmds = [("Gateway ping", run.gateway_ping.command if run.gateway_ping else None),
                    ("Ping", p.command if p else None),
                    ("Traceroute", tr.command if tr else None)]
            if run.config:
                cmds += [(" ".join(c.argv), c) for c in run.config.commands]
            for name, c in cmds:
                if c is None:
                    continue
                st.markdown(f"**{name}** - `{' '.join(c.argv)}` (exit {c.returncode}, {c.duration_s}s)")
                st.code((c.stdout or c.error or "")[-4000:], language=None)
            warns = (p.parse_warnings if p else []) + (tr.parse_warnings if tr else [])
            if warns:
                st.markdown("**Parser notes**")
                bullet(warns)

# --------------------------------------------------------------- history / comparison
elif mode == "History & comparison":
    targets = history.targets()
    if not targets:
        st.info("No diagnostic runs recorded yet.")
        st.stop()
    target = st.selectbox("Destination", targets)
    recs = history.records(target)
    rows = [summary_row(r["run"], r.get("analysis")) for r in recs]
    df = pd.DataFrame(rows)
    base = history.baseline(target)
    st.caption(f"{len(rows)} run(s). Baseline: {base.run_id + ' (' + base.timestamp + ')' if base else 'not set'}")
    st.dataframe(df, hide_index=True, alt=f"Diagnostic history for {target}")

    if df["avg_rtt_ms"].notna().any():
        chart_df = df.assign(ts=pd.to_datetime(df["timestamp"]))
        rtt = alt.Chart(chart_df).mark_line(point=True).encode(
            x=alt.X("ts:T", title="Run time"), y=alt.Y("avg_rtt_ms:Q", title="Average RTT (ms)"),
            tooltip=["run_id", "label", "avg_rtt_ms", "loss_pct", "classifications"])
        loss = alt.Chart(chart_df).mark_bar(opacity=0.5, color="#c2410c").encode(
            x="ts:T", y=alt.Y("loss_pct:Q", title="Loss %"), tooltip=["run_id", "loss_pct"])
        c1, c2 = st.columns(2)
        c1.altair_chart(rtt, alt="Average RTT per run")
        c2.altair_chart(loss, alt="Packet loss per run")

    if len(recs) >= 2:
        st.subheader("Compare two runs")
        ids = [r["run"]["run_id"] for r in recs]
        fmt_id = {r["run"]["run_id"]: f"{r['run']['timestamp']}  {r['run'].get('label', '')}  ({r['run']['run_id']})" for r in recs}
        c1, c2 = st.columns(2)
        old_id = c1.selectbox("Earlier run", ids, index=(ids.index(base.run_id) if base and base.run_id in ids else len(ids) - 2),
                              format_func=fmt_id.get)
        new_id = c2.selectbox("Current run", ids, index=len(ids) - 1, format_func=fmt_id.get)
        old, new = history.get(old_id), history.get(new_id)
        cmp = compare_runs(old, new)
        st.markdown(f"Status: **{cmp['status_earlier']}** -> **{cmp['status_current']}**")
        st.dataframe(pd.DataFrame(cmp["metrics"]), hide_index=True, alt="Metric comparison between two runs")
        if cmp["path_earlier"] or cmp["path_current"]:
            st.markdown("**Traceroute path** (responding hops)" + (" - changed" if cmp["path_changed"] else " - unchanged"))
            n = max(len(cmp["path_earlier"]), len(cmp["path_current"]))
            st.dataframe(pd.DataFrame({"Earlier": cmp["path_earlier"] + [""] * (n - len(cmp["path_earlier"])),
                                       "Current": cmp["path_current"] + [""] * (n - len(cmp["path_current"]))}),
                         alt="Responding traceroute hops in both runs")
        if st.button("Re-analyse current run against the earlier run as baseline", icon=":material/refresh:"):
            rep = analyze_run(new, baseline=old, previous=old, th=Thresholds.load())
            category_badges(rep.classifications)
            st.write(rep.conclusion)
            for f in rep.findings:
                st.markdown(f"- **{f.title}** ({f.level}): {'; '.join(f.evidence)}")
            for c in rep.contradictions:
                st.warning(c)

    c1, c2 = st.columns(2)
    if c1.button("Export full history as CSV", icon=":material/download:"):
        path = history.export_csv()
        st.success(f"Saved {path}")
    if base and c2.button("Clear baseline for this destination", icon=":material/flag:"):
        history.clear_baseline(target)
        st.rerun()

# ----------------------------------------------------------------- authorisation
else:
    st.markdown("Active tests (ping, traceroute, TCP connect) are restricted to the destinations below, "
                "plus loopback and private addresses on your own network.")
    st.dataframe(pd.DataFrame({"Authorised destination": authorized_list()}), hide_index=True,
                 alt="Authorised destinations")
    if PUBLIC:
        st.caption("Adding destinations is disabled on the public deployment.")
        st.stop()
    with st.form("add_host"):
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
