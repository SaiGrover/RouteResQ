"""Guided demo: one network-failure story told with the real backend. Stage logic, verification
and error handling live in walkthrough/flow.py; this page only presents them."""
import pandas as pd
import streamlit as st

from analysis import cause_report
from diagnostics.authorization import authorized_list
from ui import charts, data
from ui import theme as T
from ui.components import (card, card_title, cause_register, chain, chart, code, e, empty, eyebrow, fmt, note, page_header,
                           pill, tiles, verdict)
from walkthrough import flow

LOOK = {flow.SUCCESS: ("verified", T.GREEN, "✓"), flow.PARTIAL: ("partial", T.AMBER, "◐"),
        flow.FAILED: ("failed", T.CLAY, "✕"), flow.STORED: ("stored data", T.SAND, "◆"),
        flow.NOT_STARTED: ("not run", T.SLATE, "○")}
SC = data.scenarios()
st.session_state.setdefault("wt", flow.new_state())
W = st.session_state.wt

page_header("Showcase", "Guided demo: one network failure, end to end",
            "Detect a problem on the live network, work out its cause, then reproduce known failures in NS2 to see "
            "their impact and whether the network recovers, test the transport layer, and report. Every stage runs "
            "the real backend and checks its own results; stored data is always labelled as such.", T.SIGNAL)


def status_of(key: str) -> str:
    return flow.step_status(W, key)


def show_errors(items: dict) -> None:
    for name, v in items.items():
        if v.get("error"):
            st.html(f'<div class="rr-note" style="--c:{T.CLAY}"><b>{e(name)}:</b> {e(v["error"])}</div>')


# ------------------------------------------------------------------ stepper (clickable, per-stage status)
css = []
for i, (key, _name) in enumerate(flow.STEPS):
    label, col, _ = LOOK[status_of(key)]
    css.append(f".st-key-wt_step_{i} button {{ box-shadow: inset 0 3px 0 0 {col} !important; min-height:64px; }}")
    if i == W["step"]:
        css.append(f".st-key-wt_step_{i} button {{ border-color:{T.SIGNAL} !important; background:color-mix(in srgb,{T.SIGNAL} 10%,{T.PANEL}) !important; }}")
st.html("<style>" + "".join(css) + "</style>")
cols = st.columns(len(flow.STEPS), gap="small")
for i, ((key, name), col) in enumerate(zip(flow.STEPS, cols)):
    label, _c, icon = LOOK[status_of(key)]
    with col, st.container(key=f"wt_step_{i}"):
        if st.button(f"{i + 1:02d} · **{name}**  \n{icon} {label}", key=f"wt_btn_{i}", width="stretch"):
            W["step"] = i
            st.rerun()

b = st.columns([1, 1, 1.5, 1, 2.6], vertical_alignment="center")
if b[0].button("Back", icon=":material/arrow_back:", disabled=W["step"] == 0, width="stretch"):
    W["step"] -= 1
    st.rerun()
if b[1].button("Next", icon=":material/arrow_forward:", disabled=W["step"] == len(flow.STEPS) - 1, width="stretch"):
    W["step"] += 1
    st.rerun()
run_all = b[2].button("Run the full demo", type="primary", icon=":material/play_circle:", width="stretch")
if b[3].button("Reset", icon=":material/restart_alt:", width="stretch"):
    st.session_state.wt = flow.new_state()
    st.rerun()
b[4].caption("About a minute: three live probes, the selected NS2 scenarios, and the transport experiments.")

if run_all:
    with st.status("Running every stage with the real backend", expanded=True) as stt:
        for key, label, fn in [("detect", "Detect · probing the selected destinations", lambda: flow.run_detect(W)),
                               ("impact", "Analyse impact · NS2 scenarios", lambda: flow.run_impact(W, W["scenarios"], data.ns2_status())),
                               ("transport", "Transport · TCP/UDP, TLS, failure drills", lambda: flow.run_transport(W))]:
            st.write(f"{label} ...")
            try:
                fn()
            except Exception as exc:  # noqa: BLE001 - flow already guards; this is a last resort
                W[key] = {"status": flow.FAILED, "error": str(exc), "per_target": {}, "per_scenario": {}, "parts": {}}
            s = status_of(key)
            st.write(f"→ {LOOK[s][2]} {LOOK[s][0]}")
        final = [status_of(k) for k, _ in flow.STEPS]
        all_ok = all(s == flow.SUCCESS for s in final)
        stt.update(label="Demo complete - every stage verified" if all_ok else "Demo finished - some stages need attention",
                   state="complete" if all_ok else "error", expanded=False)
    W["step"] = len(flow.STEPS) - 1
    st.rerun()

key, name = flow.STEPS[W["step"]]
s = status_of(key)
eyebrow(f"Step {W['step'] + 1} · {name}", LOOK[s][0], LOOK[s][1])

# ================================================================== 1 detect
if key == "detect":
    st.markdown("The story starts on the **live network**: probe destinations and record exactly what answered. "
                "The defaults cover a healthy host, a name that can never resolve and an address with no host.")
    opts = authorized_list()
    pick = st.multiselect("Destinations to probe", opts, default=[t for t in W["targets"] if t in opts], key="wt_targets")
    if st.button("Retry detection" if W["detect"] else "Run detection", icon=":material/radar:", disabled=not pick):
        with st.spinner("Pinging, tracing and resolving ..."):
            flow.run_detect(W, pick)
        st.rerun()
    if W["detect"]:
        show_errors(W["detect"]["per_target"])
        recs = {r["run"]["target"]: r for r in flow.detect_records(W)}
        cols = st.columns(max(1, len(recs)), gap="medium")
        for col, (t, v) in zip(cols, [(t, v) for t, v in W["detect"]["per_target"].items() if t in recs]):
            r = recs[t]
            p = r["run"].get("ping") or {}
            with col, card("wt_d"):
                card_title(t, ", ".join(r["analysis"]["classifications"]))
                st.html(pill("measurement verified" if v["ok"] else "measurement incomplete", T.GREEN if v["ok"] else T.AMBER)
                        + f'<div class="rr-csub">{e(v["verified"])}</div>')
                if p.get("sent"):
                    st.plotly_chart(charts.rtt_probes(p, 150, h=180), width="stretch", config={"displayModeBar": False},
                                    key=f"wt_rtt_{t}")
                else:
                    st.caption("No probe sent: the name could not be resolved.")
    else:
        empty("Not run yet", "Choose destinations and press <b>Run detection</b>.")

# ================================================================== 2 diagnose
elif key == "diagnose":
    st.markdown("For each destination the rule engine builds an **evidence chain**: what went wrong, the measurements "
                "that show it, the explanation they support, what the evidence cannot tell us, and the check that would "
                "settle it.")
    recs = flow.detect_records(W)
    if not recs:
        empty("Run step 1 first", "The diagnosis needs measurements.")
    else:
        names = [r["run"]["target"] for r in recs]
        sel = st.segmented_control("Destination", names, default=names[0], key="wt_dx", required=True)
        rec = recs[names.index(sel)]
        ch = flow.evidence_chain(rec)
        sc_col = {cause_report.CONFIRMED: T.GREEN, cause_report.LIKELY: T.SIGNAL, cause_report.NOT_CONFIRMED: T.AMBER,
                  cause_report.NO_FAILURE: T.SLATE}.get(ch["status"], T.SLATE)
        verdict(f"Root cause · {ch['status']}", ch["explanation"], sc_col)

        def rung(n, title, items, color):
            lis = "".join(f"<li>{e(i)}</li>" for i in items) or f'<li style="color:{T.DIM}">none</li>'
            return (f'<div class="rr-rung" style="--c:{color}"><div class="h"><div class="num">{n}</div>'
                    f'<div class="t">{e(title)}</div></div><ul>{lis}</ul></div>')

        if ch["status"] == cause_report.NOT_CONFIRMED:
            expl = ["No single cause is supported over the others. Possible:"] + ch["alternatives"]
        else:
            expl = [ch["explanation"]] + [f"also possible: {x}" for x in ch["alternatives"]]
        st.html('<div class="rr-ladder" style="grid-template-columns:repeat(5,minmax(0,1fr))">'
                + rung(1, "Observed symptom", ch["symptoms"], T.CLAY)
                + rung(2, "Measurement", ch["measurements"], T.SIGNAL)
                + rung(3, f"Explanation ({ch['status']})", expl, sc_col)
                + rung(4, "Limitations", ch["limitations"], T.SLATE)
                + rung(5, "Next check", ch["next_checks"], T.GREEN) + "</div>")
        if st.button("Open the full rule trace", icon=":material/psychology:"):
            st.session_state.diag_run_id = rec["run"]["run_id"]
            st.switch_page("app_pages/diagnose_page.py")

# ================================================================== 3 impact
elif key == "impact":
    st.markdown("A live diagnosis can only suggest causes. In **NS2** the cause is known because it is injected, so "
                "we can watch what it does to traffic. Pick the experiments; the healthy baseline is needed for comparison.")
    ns2 = data.ns2_status()
    if not ns2["available"]:
        note(f"<b>NS2 is not available here</b> ({e(ns2['detail'][:160])}). The demo will use <b>stored runs</b> and label them.", T.SAND)
    labels = {sid: f"{sc.label} · {sc.name.split(' - ', 1)[-1]}" for sid, sc in SC.items()}
    pick = st.multiselect("Experiments", list(SC), default=W["scenarios"] or list(SC), format_func=labels.get, key="wt_sc")
    if pick and "healthy" not in pick:
        st.caption("Tip: include A (healthy) so the failure can be compared against a baseline.")
    if st.button("Retry experiments" if W["impact"] else "Run experiments", icon=":material/science:", disabled=not pick):
        with st.spinner("Simulating and analysing ..."):
            flow.run_impact(W, pick, ns2)
        st.rerun()
    if W["impact"]:
        per = W["impact"]["per_scenario"]
        show_errors({sid: v for sid, v in per.items() if not v["ok"] or v["source"] == "stored"})
        st.html("".join(pill(f"{SC[sid].label} · {v['source'] or 'no result'}", T.GREEN if v["source"] == "fresh" else
                             T.SAND if v["source"] == "stored" else T.CLAY) for sid, v in per.items()))
        sims = flow.sim_results(W)
        if sims:
            tiles([(f"{SC[sid].label} delivered", f"{r['flows']['1']['summary']['delivered']}<small>/{r['flows']['1']['summary']['sent']}</small>",
                    ("fresh run" if per[sid]["source"] == "fresh" else "stored run") + " · " + SC[sid].name.split(" - ", 1)[-1],
                    T.SCENARIO_COLOR[sid]) for sid, r in sims.items()])
            chart(charts.overlay_throughput(list(sims.values())), "Throughput at the destination",
                  what="Shaded: the 3-6 s window in which the fault or extra load is applied.",
                  why="Same network, different injected cause, different impact.")
    else:
        empty("Not run yet", "Choose experiments and press <b>Run experiments</b>.")

# ================================================================== 4 recovery
elif key == "recovery":
    st.markdown("Now compare a failure against the healthy **baseline**: what changed, why, and did the network recover?")
    sims = flow.sim_results(W)
    avail = [s for s in flow.FAILURE_SCENARIOS if s in sims]
    if not avail:
        empty("No failure experiment available", "Run at least one of B1, B2 or C in step 3.")
    else:
        sid = st.segmented_control("Failure to examine", avail, format_func=lambda s: f"{SC[s].label} · {SC[s].name.split(' - ', 1)[-1]}",
                                   default=avail[0], key="wt_rec", required=True)
        r, base = sims[sid], sims.get("healthy")
        f = r["findings"]
        src = W["impact"]["per_scenario"][sid]["source"]
        oc = T.GREEN if f["recovery"]["outcome"].startswith(("rerouted", "recovered")) else T.AMBER
        verdict(f"Recovery · {'fresh run' if src == 'fresh' else 'stored run'}", f["recovery"]["outcome"], oc)
        st.html(f'<div class="rr-note" style="--c:{T.GREEN}"><b>Root cause (confirmed - injected).</b> {code(SC[sid].known_cause)}'
                f'<br><b>Mechanism seen in the trace.</b> {e(f["explanation"])}</div>')
        left, right = st.columns([1, 1.25], gap="medium")
        with left, card("wt_cmp"):
            card_title("Baseline vs failure, during 3-6 s", "monitored flow 1")
            rows = []
            for label, res in [("A baseline", base), (f"{SC[sid].label} failure", r)]:
                if res:
                    d = res["phases"]["1"]["during"]
                    rows.append({"run": label, "delivered": f"{d['delivered']}/{d['sent']}", "loss %": d["loss_pct"],
                                 "avg delay ms": d["avg_delay_ms"], "kb/s": d["throughput_kbps"]})
            st.dataframe(pd.DataFrame(rows), hide_index=True, alt="Baseline versus failure")
            if not base:
                st.caption("A (healthy) was not run, so there is no baseline row.")
            st.plotly_chart(charts.topology(SC[sid].to_dict(), r, "during", h=220, labels=False), width="stretch",
                            config={"displayModeBar": False}, key=f"wt_topo_{sid}")
        with right:
            chart(charts.overlay_throughput([x for x in (base, r) if x], h=320), "Throughput: baseline vs failure",
                  what="Both runs use identical traffic; only the injected condition differs.",
                  why="The gap between the curves is the impact of the failure; where they meet again is recovery.")

# ================================================================== 5 transport
elif key == "transport":
    st.markdown("Failures also happen between applications. This stage compares **TCP and UDP**, sends a file over "
                "**TLS** with certificate and SHA-256 checks, and runs six controlled **failure drills**.")
    if st.button("Retry transport experiments" if W["transport"] else "Run transport experiments", icon=":material/swap_horiz:"):
        with st.spinner("Running real sockets on loopback ..."):
            flow.run_transport(W)
        st.rerun()
    if not W["transport"]:
        empty("Not run yet", "Press <b>Run transport experiments</b>.")
    else:
        parts = W["transport"]["parts"]
        show_errors(parts)
        c = st.columns(3, gap="medium")
        for col, (k, title) in zip(c, [("tcpudp", "TCP vs UDP"), ("tls", "TLS secure transfer"), ("drills", "Failure drills")]):
            v = parts[k]
            with col, card("wt_t"):
                card_title(title)
                st.html(pill("verified" if v["ok"] else "not verified", T.GREEN if v["ok"] else T.CLAY)
                        + f'<div class="rr-csub">{e(v["verified"] or v["error"] or "")}</div>')
        tls = (parts["tls"].get("result") or {}).get("file")
        if tls:
            ti = tls.get("tls_info") or {}
            chain([("TCP connect", "ok" if tls["connect_ms"] is not None else "fail", fmt(tls["connect_ms"], " ms", 3)),
                   ("TLS handshake", "ok" if ti else "fail", f"{ti.get('version', '')} {ti.get('cipher', '')}"),
                   ("Certificate", "ok" if ti else "fail", "lab CA · localhost"),
                   ("Encrypted transfer", "ok" if tls["server_ack"] else "fail", f"{tls['payload_bytes']:,} bytes"),
                   ("SHA-256", "ok" if tls["integrity_ok"] else "fail", "client = server")])
        drills = parts["drills"].get("result")
        if drills:
            st.dataframe(pd.DataFrame([{"drill": x["failure_type"], "root cause (injected)": x["condition_created"],
                                        "observed": x["observed_error_kind"], "resumed": x["resumed"]} for x in drills["records"]]),
                         hide_index=True, alt="Failure drills", column_config={"resumed": st.column_config.CheckboxColumn()})

# ================================================================== 6 report
else:
    statuses = {k: status_of(k) for k, _ in flow.STEPS}
    if all(v == flow.NOT_STARTED for k, v in statuses.items() if k != "report"):
        empty("Nothing to report yet", "Run the earlier steps or <b>Run the full demo</b>.")
    else:
        all_ok = all(v == flow.SUCCESS for v in statuses.values())
        verdict("Demo status", "Every stage completed with fresh, verified measurements." if all_ok else
                "Not every stage produced fresh, verified results - see the stage table and labels below.",
                T.GREEN if all_ok else T.AMBER)
        st.dataframe(pd.DataFrame([{"stage": n, "status": LOOK[statuses[k]][0]} for k, n in flow.STEPS]),
                     hide_index=True, alt="Stage status")
        eyebrow("Root causes identified in this demo", "", T.AMBER)
        rows = cause_report.collect(flow.detect_records(W), flow.sim_results(W),
                                    ((W.get("transport") or {}).get("parts", {}).get("drills") or {}).get("result"))
        cause_register(rows)
        md = flow.build_report(W)
        with st.expander("Full demo report"):
            st.markdown(md)
        st.download_button("Download demo report", md.encode(), "routeresq_demo_report.md", "text/markdown",
                           icon=":material/download:", type="primary")
