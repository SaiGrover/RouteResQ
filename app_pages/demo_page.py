"""Guided demo: one walkthrough of every RouteResQ capability, running the real backend at
each step. Nothing is pre-recorded except where a stored NS2 run is used because NS2 is
unavailable - and that is labelled."""
from pathlib import Path

import pandas as pd
import streamlit as st

from common.storage import utc_now_iso
from communication.experiments import run_comparison
from communication.failures import run_all
from diagnostics.engine import run_diagnostics
from diagnostics.history import DiagnosticHistory
from failure_analysis.rules import analyze_run
from security.tls import run_secure_transfer
from simulation.experiments import run_and_analyze
from ui import charts, data
from ui import theme as T
from ui.components import (card, card_title, chain, chart, e, empty, eyebrow, fmt, note, page_header, pill, tiles,
                           verdict)

STEPS = [("Detect", "live probes", T.SIGNAL), ("Diagnose", "rule engine", T.AMBER), ("Analyse impact", "NS2", T.CLAY),
         ("Observe recovery", "trace evidence", T.GREEN), ("Transport", "TCP · UDP · TLS", T.STEEL), ("Report", "summary", T.SAND)]
TARGETS = [("8.8.8.8", "a reachable public resolver"), ("nonexistent.invalid", "a name that can never resolve (RFC 6761)"),
           ("192.0.2.1", "an address with no host behind it (RFC 5737)")]

history = DiagnosticHistory()
st.session_state.setdefault("demo", {"step": 0, "done": []})
D = st.session_state.demo

page_header("Showcase", "Guided demo",
            "Six steps that exercise every part of RouteResQ with real measurements: probe three destinations, explain "
            "what failed, inject failures in NS2, check whether the network recovered, drill transport-layer failures, "
            "and assemble a report. Run one step at a time or the whole sequence.", T.SIGNAL)


# ------------------------------------------------------------------ actions (each calls the real backend)
def do_detect():
    ids = []
    for t, _ in TARGETS:
        run = run_diagnostics(t, ping_count=3, timeout_s=0.6, max_hops=8, label="guided demo")
        rep = analyze_run(run, baseline=history.baseline(t), previous=history.previous(t))
        history.save(run, rep)
        ids.append(run.run_id)
    D["detect"] = ids


def do_impact():
    status = data.ns2_status()
    if status["available"]:
        D["sim"] = {sid: run_and_analyze(sc)["run"]["run_dir"] for sid, sc in data.scenarios().items()}
        D["sim_source"] = f"fresh runs on {status['kind']} ns2 {status['version']}"
    else:
        D["sim"] = {sid: str(data.runs(sid)[0]) for sid in data.scenarios() if data.runs(sid)}
        D["sim_source"] = "stored runs (NS2 unavailable here)"


def do_transport():
    D["tcpudp"] = run_comparison(total_bytes=400_000, datagram_payload=1024, trials=1)
    D["tls"] = run_secure_transfer(data=None, message="guided demo")
    D["fails"] = run_all()


ACTIONS = {0: ("Probe 3 destinations", do_detect), 2: ("Run the 4 NS2 scenarios", do_impact),
           4: ("Run transport experiments", do_transport)}


def mark(i):
    if i not in D["done"]:
        D["done"].append(i)


# ------------------------------------------------------------------ stepper
step = D["step"]
st.html('<div class="rr-steps">' + "".join(
    f'<div class="{"on" if i == step else "done" if i in D["done"] else ""}" style="--c:{c}"><b>{i + 1:02d} · {n}</b>{s}</div>'
    for i, (n, s, c) in enumerate(STEPS)) + "</div>")
b = st.columns([1, 1, 1.3, 3], vertical_alignment="center")
if b[0].button("Back", icon=":material/arrow_back:", disabled=step == 0, width="stretch"):
    D["step"] -= 1
    st.rerun()
if b[1].button("Next", icon=":material/arrow_forward:", disabled=step == len(STEPS) - 1, width="stretch"):
    D["step"] += 1
    st.rerun()
if b[2].button("Run the full demo", type="primary", icon=":material/play_circle:", width="stretch"):
    with st.status("Running every stage with the real backend", expanded=True) as stt:
        st.write("Detect · probing 8.8.8.8, nonexistent.invalid and 192.0.2.1 ...")
        do_detect()
        mark(0)
        mark(1)
        st.write("Analyse impact · simulating four NS2 scenarios ...")
        do_impact()
        mark(2)
        mark(3)
        st.write("Transport · TCP vs UDP, TLS transfer, six failure drills ...")
        do_transport()
        mark(4)
        mark(5)
        stt.update(label="Demo complete - every step below now shows its results", state="complete", expanded=False)
    D["step"] = 5
    st.rerun()
b[3].caption("A full run takes roughly 30-60 seconds, mostly traceroute waiting on silent hops.")

name, sub, color = STEPS[step]
eyebrow(f"Step {step + 1} · {name}", sub, color)

if step in ACTIONS:
    label, fn = ACTIONS[step]
    if st.button(label, icon=":material/play_arrow:", key=f"act{step}"):
        with st.spinner(f"{label} ..."):
            fn()
        mark(step)
        if step in (0, 2):
            mark(step + 1)
        st.rerun()

# ================================================================== step bodies
if step == 0:
    st.markdown("RouteResQ first **detects** symptoms with real commands. The demo probes three deliberately different "
                "destinations so every kind of outcome appears:")
    st.html("".join(pill(f"{t} — {why}", T.SIGNAL, dot=False) for t, why in TARGETS))
    if D.get("detect"):
        cols = st.columns(3, gap="medium")
        for col, rid in zip(cols, D["detect"]):
            r = history.get_record(rid)
            p = r["run"].get("ping") or {}
            with col, card("d"):
                card_title(r["run"]["target"], ", ".join(r["analysis"]["classifications"]))
                if p.get("sent"):
                    st.plotly_chart(charts.rtt_probes(p, 150, h=190), width="stretch", config={"displayModeBar": False}, key=f"dp{rid}")
                else:
                    st.caption("No probe sent: the name could not be resolved.")
                tr = r["run"].get("traceroute")
                st.caption(f"replies {p.get('received', 0)}/{p.get('sent', 0)} · "
                           + (f"traceroute {'reached' if tr['reached_destination'] else 'stopped'} after {len(tr['hops'])} hops" if tr else "no traceroute"))
    else:
        empty("Not run yet", "Press <b>Probe 3 destinations</b>.")

elif step == 1:
    st.markdown("Next the rule engine **diagnoses** each run: observations, findings, candidate causes and what the "
                "evidence cannot tell us.")
    if not D.get("detect"):
        empty("Run step 1 first", "The diagnosis needs measurements.")
    else:
        cols = st.columns(3, gap="medium")
        for col, rid in zip(cols, D["detect"]):
            a = history.get_record(rid)["analysis"]
            with col, card("dx"):
                card_title(a["target"])
                st.html("".join(pill(c, T.CATEGORY_COLOR[c]) for c in a["classifications"]))
                st.markdown(f"_{a['conclusion']}_")
                for x in a["explanations"][:3]:
                    st.html(f'<div class="rr-csub">{pill(x["level"], T.LEVEL_COLOR[x["level"]], dot=False)} {e(x["cause"])}</div>')
                if a["contradictions"]:
                    st.caption("Contradiction: " + a["contradictions"][0][:160])
                if st.button("Full reasoning", key=f"open{rid}", icon=":material/psychology:"):
                    st.session_state.diag_run_id = rid
                    st.switch_page("app_pages/diagnose_page.py")

elif step == 2:
    st.markdown("Live diagnostics can only suggest causes. In **NS2** the cause is known because it is injected: a link "
                "failure under two routing protocols, and congestion.")
    sims = {sid: data.result_at(Path(p)) for sid, p in D.get("sim", {}).items()}
    if not sims:
        empty("Not run yet", "Press <b>Run the 4 NS2 scenarios</b>.")
    else:
        note(f"<b>Source:</b> {e(D.get('sim_source', ''))}.", T.SAND)
        tiles([(f"{data.scenarios()[s].label} delivered", f"{r['flows']['1']['summary']['delivered']}<small>/{r['flows']['1']['summary']['sent']}</small>",
                data.scenarios()[s].name.split(" - ", 1)[-1], T.SCENARIO_COLOR[s]) for s, r in sims.items()])
        chart(charts.overlay_throughput(list(sims.values())), "Throughput at the destination, every scenario",
              what="The shaded window is when the fault or extra load is applied.",
              why="Same failure, different routing, very different outcome.")

elif step == 3:
    st.markdown("RouteResQ then checks the trace for **recovery**: did traffic reroute, how long was delivery "
                "interrupted, and did performance return to its earlier level?")
    sims = {sid: data.result_at(Path(p)) for sid, p in D.get("sim", {}).items()}
    if not sims:
        empty("Run step 3 first", "Recovery is read from the NS2 traces.")
    else:
        cols = st.columns(3, gap="medium")
        for col, sid in zip(cols, [s for s in ("link_failure_dv", "link_failure_static", "congestion") if s in sims]):
            r = sims[sid]
            sc = data.scenarios()[sid]
            with col, card("rv"):
                card_title(f"{sc.label} · {sc.name.split(' - ', 1)[-1]}", r["findings"]["recovery"]["outcome"])
                st.plotly_chart(charts.topology(sc.to_dict(), r, "during", h=200, labels=False), width="stretch",
                                config={"displayModeBar": False}, key=f"rt{sid}")
                for x in r["findings"]["recovery"]["evidence"][:2]:
                    st.caption(x)
        if st.button("Open the full failure & recovery analysis", icon=":material/healing:"):
            st.switch_page("app_pages/recovery_page.py")

elif step == 4:
    st.markdown("Failures happen at the transport layer too. This step compares **TCP and UDP**, sends a file over "
                "**TLS** with certificate and SHA-256 checks, and runs six controlled **failure drills**.")
    if not D.get("fails"):
        empty("Not run yet", "Press <b>Run transport experiments</b>.")
    else:
        tu, tls, fl = D["tcpudp"], D["tls"], D["fails"]
        f = tls.file
        tiles([("TCP delivered", f"{tu['tcp'][0]['delivered_pct']:g}<small>%</small>", "SHA-256 verified" if tu["tcp"][0]["integrity_ok"] else "check failed", T.SIGNAL),
               ("UDP delivered", f"{tu['udp'][0]['delivered_pct']:g}<small>%</small>", f"missing: {tu['udp'][0]['missing']}", T.AMBER),
               ("TLS", e(f.tls_info.version) if f.tls_info else "failed", "chain + host name validated" if f.ok else (f.error_kind or ""), T.GREEN if f.ok else T.CLAY),
               ("Drills recovered", f"{sum(x['resumed'] for x in fl['records'])}<small>/{len(fl['records'])}</small>", "after restoring each condition", T.GREEN)])
        chain([("TCP connect", "ok" if f.connect_ms is not None else "fail", f"{fmt(f.connect_ms, ' ms', 3)}"),
               ("TLS handshake", "ok" if f.tls_info else "fail", f"{f.tls_info.version} {f.tls_info.cipher}" if f.tls_info else ""),
               ("Certificate", "ok" if f.tls_info else "fail", "lab CA · localhost"),
               ("Encrypted transfer", "ok" if f.server_ack else "fail", f"{f.payload_bytes:,} bytes"),
               ("SHA-256", "ok" if f.integrity_ok else "fail", "client = server")])
        st.dataframe(pd.DataFrame([{"drill": x["failure_type"], "observed": x["observed_error_kind"], "resumed": x["resumed"],
                                    "detail": x["resume_detail"]} for x in fl["records"]]), hide_index=True,
                     alt="Failure drills", column_config={"resumed": st.column_config.CheckboxColumn()})

else:
    st.markdown("Finally everything is **reported**. Below is a summary of what this demo produced; the same results "
                "are stored as JSON/CSV and appear on the Reports page.")
    lines = [f"# RouteResQ guided demo\n\nGenerated {utc_now_iso()}.\n"]
    if D.get("detect"):
        lines.append("## Live diagnostics\n")
        for rid in D["detect"]:
            a = history.get_record(rid)["analysis"]
            lines.append(f"- **{a['target']}**: {', '.join(a['classifications'])}. {a['conclusion']}")
    sims = {sid: data.result_at(Path(p)) for sid, p in D.get("sim", {}).items()}
    if sims:
        lines.append(f"\n## NS2 ({D.get('sim_source')})\n")
        for sid, r in sims.items():
            s = r["flows"]["1"]["summary"]
            lines.append(f"- **{r['scenario']['label']} {sid}**: {s['delivered']}/{s['sent']} delivered, "
                         f"{s['loss_pct']}% loss, {s['avg_delay_ms']} ms mean delay - {r['findings']['recovery']['outcome']}.")
    if D.get("fails"):
        lines.append("\n## Transport\n")
        tu = D["tcpudp"]
        lines.append(f"- TCP delivered {tu['tcp'][0]['delivered_pct']}%, UDP {tu['udp'][0]['delivered_pct']}%.")
        f = D["tls"].file
        lines.append(f"- TLS: {'verified' if f.ok else 'failed'}" + (f" ({f.tls_info.version}, {f.tls_info.cipher})" if f.tls_info else ""))
        for x in D["fails"]["records"]:
            lines.append(f"- {x['failure_type']}: observed `{x['observed_error_kind']}`, resumed: {x['resumed']}")
    md = "\n".join(lines)
    if len(lines) == 1:
        empty("Nothing to report yet", "Run the earlier steps or <b>Run the full demo</b>.")
    else:
        done_all = all(i in D["done"] for i in range(5))
        verdict("Demo summary", "All stages completed with real measurements." if done_all else "Some stages have not been run yet.",
                T.GREEN if done_all else T.AMBER)
        with card("sum"):
            st.markdown(md)
        st.download_button("Download demo report", md.encode(), "routeresq_demo_report.md", "text/markdown",
                           icon=":material/download:", type="primary")
        st.page_link("app_pages/report_page.py", label="Open all reports", icon=":material/description:")
