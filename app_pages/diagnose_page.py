import pandas as pd
import streamlit as st

from common.paths import CONFIG_DIR
from diagnostics.history import DiagnosticHistory
from diagnostics.models import run_from_dict
from failure_analysis.rules import Thresholds, analyze_run
from ui import theme as T
from ui.components import badge_row, card, card_title, e, empty, eyebrow, method, page_header, pill, tiles, verdict

history = DiagnosticHistory()
recs = history.records()

page_header("Stage 02 · Diagnose", "Root-cause analysis",
            "Deterministic rules turn measurements into findings and candidate causes. Observations, explanations "
            "and gaps in the evidence are kept apart, and every rule records why it did or did not fire. "
            "No machine learning and no confidence percentages.", T.AMBER)
badge_row("live")

if not recs:
    empty("Nothing to diagnose yet", "Run a measurement on the <b>Diagnostics</b> page (or the guided demo); its "
          "analysis appears here.")
    st.stop()

ids = [r["run"]["run_id"] for r in reversed(recs)]
by_id = {r["run"]["run_id"]: r for r in recs}
labels = {i: f"{by_id[i]['run']['target']}  ·  {by_id[i]['run']['timestamp'][5:19].replace('T', ' ')}  ·  "
             f"{', '.join(by_id[i]['analysis']['classifications'])}" for i in ids}
default = st.session_state.get("diag_run_id")
c1, c2 = st.columns([2.2, 1], vertical_alignment="bottom")
sel = c1.selectbox("Diagnostic run", ids, index=ids.index(default) if default in ids else 0, format_func=labels.get)
st.session_state.diag_run_id = sel
rec = by_id[sel]
run = run_from_dict(rec["run"])
base_choices = ["stored analysis"] + [i for i in ids if by_id[i]["run"]["target"] == run.target and i != sel]
base_sel = c2.selectbox("Compare against", base_choices,
                        format_func=lambda i: i if i == "stored analysis" else f"baseline: {labels[i][:40]}")
if base_sel == "stored analysis":
    a = rec["analysis"]
else:
    other = run_from_dict(by_id[base_sel]["run"])
    a = analyze_run(run, baseline=other, previous=other, th=Thresholds.load()).to_dict()

cats = a["classifications"]
bad = [c for c in cats if c != "Healthy / Reachable"]
col = T.CLAY if any(c in cats for c in ("DNS Resolution Failure", "Unreachable Destination")) else T.AMBER if bad else T.GREEN
verdict("Conclusion", a["conclusion"], col)
st.html("<div>" + "".join(pill(c, T.CATEGORY_COLOR[c]) for c in cats) + "</div>")

fired = [t for t in a["rule_trace"] if t["fired"]]
levels = [f["level"] for f in a["findings"]] + [x["level"] for x in a["explanations"]]
tiles([
    ("Observations", f"{len(a['observations'])}", "facts read from command output", T.SIGNAL),
    ("Rules fired", f"{len(fired)}<small>/{len(a['rule_trace'])}</small>", "each with a recorded reason", T.AMBER),
    ("Findings", f"{len(a['findings'])}", f"{sum(1 for f in a['findings'] if f['level'] == 'confirmed')} confirmed", T.CLAY if a["findings"] else T.GREEN),
    ("Candidate causes", f"{len(a['explanations'])}", f"{levels.count('likely')} likely · {levels.count('possible')} possible", T.STEEL),
    ("Contradictions", f"{len(a['contradictions'])}", "evidence that disagrees", T.AMBER if a["contradictions"] else T.SLATE),
    ("Compared with", "baseline" if a.get("baseline_run_id") else "thresholds", a.get("baseline_run_id") or "no baseline", T.SLATE),
])

# ------------------------------------------------------------------ reasoning ladder
eyebrow("Diagnostic reasoning", "symptom → evidence → explanation → limits", T.AMBER)


def rung(n, title, items, color):
    lis = "".join(f"<li>{e(i)}</li>" for i in items) or f'<li style="color:{T.DIM}">none</li>'
    return (f'<div class="rr-rung" style="--c:{color}"><div class="h"><div class="num">{n}</div>'
            f'<div class="t">{e(title)}</div></div><ul>{lis}</ul></div>')


symptoms = [f"{f['title']} ({T.LEVEL_LABEL[f['level']].lower()})" for f in a["findings"]] or ["No problem symptom detected"]
causes = [f"{x['cause']} - {x['level']}" for x in a["explanations"]] or ["No cause needed: destination healthy"]
limits = list(a["contradictions"]) + [f["title"] + ": " + "; ".join(f["evidence"]) for f in a["findings"] if f["level"] == "insufficient_evidence"]
if not any(x["level"] == "likely" for x in a["explanations"]) and a["explanations"]:
    limits.append("No single explanation is better supported than the others; the precise cause is not confirmed.")
limits.append("ICMP-based tools only see what devices choose to answer.")
st.html('<div class="rr-ladder">' + rung(1, "Detected symptoms", symptoms, T.CLAY if a["findings"] else T.GREEN)
        + rung(2, "Supporting measurements", a["observations"], T.SIGNAL)
        + rung(3, "Possible explanations", causes, T.STEEL)
        + rung(4, "Evidence limitations", limits, T.SLATE) + "</div>")

# ------------------------------------------------------------------ explanations
left, right = st.columns([1.5, 1], gap="medium")
with left:
    eyebrow("Candidate causes", "what each needs before it can be confirmed", T.STEEL)
    if not a["explanations"]:
        empty("No explanation required", "Every rule that indicates a fault stayed silent for this run.")
    for x in a["explanations"]:
        c = T.LEVEL_COLOR[x["level"]]

        def row(k, v):
            return f'<div class="row"><b>{k}</b><span>{"<br>".join(e(i) for i in v) if v else "—"}</span></div>'

        st.html(f'<div class="rr-cause" style="--c:{c}"><div class="c">{e(x["cause"])} {pill(T.LEVEL_LABEL[x["level"]], c)}</div>'
                + row("Supporting", x["supporting_evidence"]) + row("Against", x["contrary_evidence"])
                + row("Next checks", x["checks_to_confirm"]) + row("Actions", x["recommended_actions"]) + "</div>")
with right:
    eyebrow("Findings", "rule outputs", T.CLAY)
    if not a["findings"]:
        empty("No findings", "No rule produced a problem finding.")
    for f in a["findings"]:
        with card("finding"):
            c = T.LEVEL_COLOR[f["level"]]
            st.html(f'<div style="display:flex;gap:.4rem;flex-wrap:wrap">{pill(T.LEVEL_LABEL[f["level"]], c)}'
                    f'{pill(f["category"], T.CATEGORY_COLOR.get(f["category"], T.SLATE))}'
                    f'<span class="rr-src" style="--c:{T.DIM}">{e(f["rule_id"])}</span></div>'
                    f'<div class="rr-ctitle" style="margin-top:.35rem">{e(f["title"])}</div>'
                    + "".join(f'<div class="rr-csub">• {e(ev)}</div>' for ev in f["evidence"]))
    if a["contradictions"]:
        eyebrow("Contradictory evidence", "reported, never hidden", T.AMBER)
        for c in a["contradictions"]:
            st.html(f'<div class="rr-note" style="--c:{T.AMBER}">{e(c)}</div>')

# ------------------------------------------------------------------ rule map
eyebrow("Rule trace", "every rule evaluated for this run", T.SLATE)
st.html("<div>" + "".join(pill(t["rule_id"], T.AMBER if t["fired"] else "#3a4856") for t in a["rule_trace"]) + "</div>")
with card("trace"):
    card_title("Why each rule did or did not fire")
    st.dataframe(pd.DataFrame(a["rule_trace"])[["rule_id", "fired", "description", "reason"]], hide_index=True,
                 alt="Rule trace", column_config={"fired": st.column_config.CheckboxColumn("fired"),
                                                  "reason": st.column_config.TextColumn(width="large")})
with st.expander("Thresholds used"):
    st.json(a["thresholds"])

method([
    ("Normalise the evidence", "DNS result, gateway reachability, echo replies, RTT statistics, OS-reported errors, "
     "traceroute completeness and the TCP check become one set of facts."),
    ("Evaluate every rule", "R-DNS, R-REACH, R-TCP, R-LOSS, R-LAT, R-BASE, R-CONG, R-ROUTE, R-OK. Each records whether it "
     "fired and why. Congestion needs two independent indicators; one high RTT is never enough."),
    ("Detect contradictions", "Ping failing while TCP connects, traceroute stopping while ping succeeds, or a silent "
     "gateway with a reachable destination are reported instead of being forced into a category."),
    ("Rank explanations", "Each candidate cause is labelled likely or possible with the evidence for and against it, "
     "and the checks that would confirm it."),
    ("Conclude conservatively", "The conclusion states only what the evidence supports; otherwise it says the precise "
     "cause is not confirmed."),
], "failure_analysis.rules", [("history.jsonl (run)", "measurements"), ("thresholds.json", CONFIG_DIR / "thresholds.json")],
   [("classification", f"{len(cats)} label(s)"), ("explanations", f"{len(a['explanations'])}"), ("rule trace", f"{len(a['rule_trace'])} rules")],
   T.AMBER, "how the engine reasons")
