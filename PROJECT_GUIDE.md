# RouteResQ: the complete project guide

This guide explains how RouteResQ works, from the first click to the last line of a report. It covers every module, every rule, every formula, every file the project writes, and why each design choice was made. Read it top to bottom once; after that, use the table of contents to jump to whatever you need before a demo or viva.

Where this guide quotes a number (43.6 ms, 3.024 s, 13 of 16 and so on), it comes from the results stored in this repository, not from memory.

---

## Contents

1. [RouteResQ in one minute](#1-routeresq-in-one-minute)
2. [The problem and the five questions](#2-the-problem-and-the-five-questions)
3. [The three evidence environments and the honesty rules](#3-the-three-evidence-environments-and-the-honesty-rules)
4. [Repository map: every folder and file](#4-repository-map-every-folder-and-file)
5. [How a request flows through the system](#5-how-a-request-flows-through-the-system)
6. [Module 1: live diagnostics](#6-module-1-live-diagnostics)
7. [Module 2: the root-cause rule engine](#7-module-2-the-root-cause-rule-engine)
8. [The root-cause register](#8-the-root-cause-register)
9. [Module 3: NS2 simulation and trace analysis](#9-module-3-ns2-simulation-and-trace-analysis)
10. [The NS2 results, explained number by number](#10-the-ns2-results-explained-number-by-number)
11. [Module 4: the transport lab (TCP, UDP, TLS)](#11-module-4-the-transport-lab-tcp-udp-tls)
11A. [File upload under link failure (isolated test network)](#11a-file-upload-under-link-failure-isolated-test-network)
12. [The guided demo](#12-the-guided-demo)
13. [The user interface](#13-the-user-interface)
14. [Files the project writes](#14-files-the-project-writes)
15. [Deployment](#15-deployment)
16. [Testing](#16-testing)
17. [Running everything: command reference](#17-running-everything-command-reference)
18. [Design decisions and why they were made](#18-design-decisions-and-why-they-were-made)
19. [Limitations](#19-limitations)
20. [Likely viva questions, with answers](#20-likely-viva-questions-with-answers)
21. [Glossary](#21-glossary)

---

## 1. RouteResQ in one minute

RouteResQ is a Computer Networks lab project (course 24B15CS313, JIIT Noida) that explains **why** a network failed, not only **that** it failed.

* It runs **real** network checks (DNS, ping, traceroute, TCP connect) on the machine it runs on, and a **deterministic rule engine** turns the output into findings and possible causes.
* It runs the **real NS2 2.35 simulator** on a six-node network, injects a link failure or congestion on purpose, and reconstructs every packet from the trace to measure loss, delay, throughput, route changes and recovery.
* It runs **real TCP, UDP and TLS sockets** on the loopback interface, compares TCP with UDP, verifies a TLS transfer with SHA-256, and breaks the connection in six controlled ways to show each failure and its recovery.
* A **root-cause register** joins all three: one row per failure, with the cause and an honest certainty status (*Confirmed (injected)*, *Likely*, *Not confirmed*, *No failure detected*).
* Everything is shown in a **Streamlit** web app (deployed at **https://routeresq.streamlit.app**) and written to JSON, CSV and Markdown files.

There is **no machine learning**, **no packet capture**, **no made-up data**, and **no confidence percentages**.

Team: Saanvi Grover (2408030010), Aditya Sharma (2408030019), Prankit Goel (2408030011), Aaradhya Shankar Kulashri (2408030026). Mentors: Dr. Kirti Aggarwal and Dr. Kapil Madan. Repository: https://github.com/SaiGrover/RouteResQ.

---

## 2. The problem and the five questions

A user sees "the site is timing out". That one symptom can come from many causes:

| Cause | What actually happens |
|---|---|
| DNS failure | The name never resolves, so no packet is ever sent. |
| Host or path down | Packets vanish somewhere beyond the last router that answers. |
| Congestion | Queues fill, delay climbs, routers drop packets. |
| Link failure | Routing must find another path, or traffic stops until the link returns. |
| Port closed or reset | The host is alive but the service refuses or drops the connection. |
| Bad certificate | TLS rejects an untrusted issuer or the wrong host name. |

Tools such as `ping`, `tracert` and `nslookup` show only symptoms, and they can mislead: routers ignore ICMP, firewalls block traceroute, and a working TCP connection can contradict a failed ping. People end up guessing one cause and stating it with false confidence.

RouteResQ answers five questions for every failure, and only with evidence:

| Stage | Question | Where it is answered |
|---|---|---|
| 01 Detect | What failed? | live diagnostics (`diagnostics/`) |
| 02 Diagnose | Why, and how sure are we? | rule engine (`failure_analysis/`) and cause register (`analysis/cause_report.py`) |
| 03 Analyse impact | What did it do to the traffic? | NS2 trace analysis (`simulation/`, `analysis/`) |
| 04 Observe recovery | Did service come back, and how? | recovery logic in `analysis/experiment.py` |
| 05 Report | Can we prove it? | Markdown reports, stored JSON/CSV, the Reports page |

These five stages are also the navigation rail at the top of the app, so the demo follows the same order.

---

## 3. The three evidence environments and the honesty rules

### The three environments

| Environment | What it is | Can the cause be known? | Best possible status |
|---|---|---|---|
| **Live measurement** | Real commands on the machine running RouteResQ | No. The tool only sees what devices answer. | *Likely* |
| **NS2 simulation** | Real ns-2.35 runs with a fault we inject | Yes. We created the fault. | *Confirmed (injected)* |
| **Real sockets on loopback** | Real TCP/UDP/TLS between two local sockets, with faults we inject | Yes. We created the fault. | *Confirmed (injected)* |

They are deliberately kept apart. Every page carries a source label, and every row in a report says which environment it came from. **A simulated cause is never presented as the cause of a live problem.**

### The honesty rules (built into the code)

1. **No confidence percentages.** There is no calibrated probability for these inferences, so the project uses words: *confirmed*, *likely*, *possible*, *insufficient evidence*.
2. **No fabricated data.** Every chart and number is read from a stored result produced by the backend. If something could not be measured, the UI says "n/a".
3. **Contradictions are reported, not hidden.** For example, "ping failed but TCP connected" is shown as a note.
4. **Recovery is claimed only when the trace shows it.**
5. **Stored results are labelled as stored.** If NS2 is unavailable, the guided demo uses earlier runs and says so.
6. **Probing is restricted** to authorised destinations, so the tool cannot be turned against other people's networks.

---

## 4. Repository map: every folder and file

```
streamlit_app.py          Entry point of the web app (navigation, module refresh, brand bar, rail)
app_pages/                One file per page of the app
  overview_page.py          Command centre: KPIs, cause register, throughput of all scenarios, recent checks
  detect_page.py            Stage 01: run live diagnostics, charts, hop table, history, baselines
  diagnose_page.py          Stage 02: evidence ladder, candidate causes, findings, rule trace
  impact_page.py            Stage 03: NS2 scenario picker, topology, throughput/delay/fate/queue charts
  recovery_page.py          Stage 04: recovery verdict, before/during/after topology, timeline, comparison
  transport_page.py         Lab: TCP message/file, TCP vs UDP, TLS transfer, failure drills
  report_page.py            Stage 05: root-cause register, reports, history, files and ZIP export, log
  demo_page.py              Guided demo: the whole story in seven verified steps
  upload_page.py            Lab: file upload under link failure (three runs, progress, path evidence)
  about_page.py             Problem & solution: one page for first-time visitors
  presentation_page.py      The slide deck embedded in the app
ui/                       Presentation only (no networking logic)
  theme.py                  Colour tokens, fonts and the stylesheet
  shell.py                  Brand bar (logo, NS2/tool chips, CN Lab badge, team, repo link) and the rail
  components.py             Tiles, cards, pills, timeline, method flowchart, cause register table
  charts.py                 Every Plotly chart (topology, throughput, delay, queue, RTT, hops, ...)
  data.py                   Cached readers for stored results
diagnostics/              Live measurements
  authorization.py          Which destinations may be probed
  commands.py               Allow-listed command runner and OS-specific command builders
  engine.py                 DNS, gateway ping, ping, traceroute, TCP connect, network inspection
  parsers.py                Parsers for ping, tracert/traceroute/tracepath, route table, DNS config
  models.py                 Data classes for every measurement
  history.py                history.jsonl, baselines, run-to-run comparison, CSV export
  cli.py                    Command-line front end
failure_analysis/
  rules.py                  The 17-rule root-cause engine
  report.py                 Markdown report for one diagnostic run
simulation/
  tcl/routeresq.tcl         The NS2 script: topology, traffic, failures, event log
  scenarios/*.json          Scenarios A (healthy), B1 (link failure, DV), B2 (link failure, static), C (congestion)
  scenario.py               Scenario loading and strict validation
  runner.py                 Runs NS2 locally or in Docker
  trace_parser.py           Parses the NS2 trace and the event log
  experiments.py            simulate -> parse -> analyse -> save -> report (CLI)
analysis/
  packets.py                Rebuilds every packet from the trace and gives it a fate
  metrics.py                Loss, delay, jitter, throughput, phases, time series, queue occupancy
  routing.py                Paths used, route changes, delivery gaps, routing messages
  timeline.py               Configured and observed events merged into one timeline
  experiment.py             Answers what / why / impact / recovery for one NS2 run
  comparison.py             Cross-scenario comparison
  report.py                 Markdown reports for NS2 runs
  cause_report.py           The root-cause register across all three environments
communication/
  framing.py                Length-prefixed frames over TCP
  tcp_server.py             Threaded TCP/TLS server (also injects faults for the drills)
  tcp_client.py             TCP/TLS client with timing and error classification
  udp.py                    Sequenced UDP sender and receiver
  experiments.py            TCP vs UDP experiment
  failures.py               The six controlled failure drills
  report.py                 Runs all transport experiments and writes reports/communication.md
security/
  certs.py                  Lab PKI (CA, valid server cert, rogue cert, wrong-host cert)
  tls.py                    TLS contexts and the secure-transfer demo
  integrity.py              SHA-256 helpers
walkthrough/
  flow.py                   Guided-demo logic (independent of Streamlit)
common/                   Paths, JSON/CSV storage, logging, public-deployment detection
config/
  authorized_targets.json   Allowed destinations
  thresholds.json           Rule thresholds
results/                  Generated JSON, CSV and NS2 traces (the four NS2 runs are committed)
reports/                  Generated Markdown reports
netlab/                   Upload under link failure: test network, lab, analysis, runner, report
tests/                    186 pytest tests, with real captured command outputs in tests/fixtures
docker/Dockerfile.ns2     Ubuntu 22.04 image with ns2 2.35, for Windows/macOS
packages.txt              apt packages for Streamlit Cloud (ns2, tcl8.6, iputils-ping, traceroute, iproute2)
requirements.txt          Python packages (streamlit, pandas, plotly, cryptography, pytest)
.streamlit/config.toml    Locked dark theme, fonts, static file serving
static/bg.webp            Background artwork
report/                   The final project report (LaTeX source, screenshots, PDF)
presentation/             The 12-slide HTML demo deck
```

---

## 5. How a request flows through the system

```
             Streamlit UI (app_pages/, ui/)          or         command line (python -m ...)
                          |                                              |
        +-----------------+-------------------+------------------------+-+
        |                                     |                          |
  diagnostics/engine.py              simulation/runner.py        communication/*, security/*
  (real commands, sockets)           (real ns-2.35)               (real sockets on 127.0.0.1)
        |                                     |                          |
  diagnostics/parsers.py             simulation/trace_parser.py   TransferResult, UDP reports,
        |                            analysis/packets, metrics,   FailureRecord
  failure_analysis/rules.py          routing, timeline,                  |
  (17 rules, rule trace)             experiment.py                       |
        |                                     |                          |
  results/diagnostics/history.jsonl  results/simulation/<id>/<run>/   results/communication/*.json
        \                                     |                          /
         \------------------> analysis/cause_report.py <----------------/
                               (root-cause register)
                                          |
                     reports/*.md, the Reports page, the Overview, the guided demo
```

The key design idea: **the UI never contains networking logic.** Pages call backend functions, the backend writes results to disk, and pages read those results back. That is why the same thing can be done from the command line, from the test suite and from the web app, with identical numbers.

---

## 6. Module 1: live diagnostics

Files: `diagnostics/authorization.py`, `commands.py`, `engine.py`, `parsers.py`, `models.py`, `history.py`, `cli.py`.

### 6.1 Step 1: is the destination allowed? (`authorization.py`)

Before any packet is sent, the destination goes through `authorize()`:

1. **Normalise.** Empty input is rejected. Input starting with `-` is rejected, because `-n 100 host` would be read by `ping` as an option (this is called *option injection*). An IP address is kept as is; otherwise the text must match a strict host-name pattern (letters, digits, hyphens, dots, at most 253 characters). Names are lower-cased and a trailing dot is removed.
2. **Check the policy** in `config/authorized_targets.json`, in this order:
   * **Reserved test targets** are always allowed:
     * `nonexistent.invalid`: the `.invalid` top-level domain can never resolve (RFC 6761), so it demonstrates a DNS failure;
     * `192.0.2.1`: an RFC 5737 documentation address with no real host, so it demonstrates a timeout or unreachable destination.
   * **Listed hosts:** `localhost`, `8.8.8.8`, `1.1.1.1`, `9.9.9.9`, `dns.google`, `one.one.one.one`, `example.com`, `github.com`.
   * **Loopback** addresses (127.x) and the name `localhost`, because `allow_loopback` is true.
   * **Private addresses** (RFC 1918, your own LAN), because `allow_private_networks` is true, **except in public mode** (see below).
   * Everything else is refused with the message "not in the authorised destination list".
3. **Adding a host:** on a local install, the Diagnostics page lets you add a destination after confirming you are allowed to test it (`add_authorized_host`). On the public deployment this is disabled.

**Public mode** (`common/deployment.py`): when the app runs on Streamlit Community Cloud (the project folder starts with `/mount/src`) or `ROUTERESQ_PUBLIC=1` is set, private addresses are refused (they would be the hosting provider's internal network) and visitors cannot add destinations.

### 6.2 Step 2: how commands are run (`commands.py`)

* Only seven executables can ever run: `ping`, `tracert`, `traceroute`, `tracepath`, `route`, `ip`, `ipconfig`. Anything else raises `PermissionError`.
* Commands are passed as **argument lists** with `shell=False`. There is no shell, so shell syntax such as `; rm -rf` has no effect.
* Every command has a timeout. If it expires, the partial output is kept and the record says `timed_out=True`.
* Output is decoded leniently (`errors="replace"`) because Windows console tools use the OEM code page.
* If a tool is missing, the record carries an error ("'traceroute' is not installed or not on PATH") instead of crashing.

`CommandRunner` is a **protocol** (an interface). `SubprocessRunner` is the real implementation. The tests pass a fake runner that replays captured Windows and Linux output, so every parser and rule is tested without a network.

The exact commands built:

| Step | Windows | Linux |
|---|---|---|
| Routing table | `route print -4` | `ip route` |
| DNS servers | `ipconfig /all` | read `/etc/resolv.conf` |
| Ping | `ping -n <count> -w <timeout ms> <ip>` | `ping -c <count> -W <timeout s> -i 0.5 <ip>` |
| Path | `tracert -d -h <max hops> -w <timeout ms> <ip>` | `traceroute -n -m <max hops> -w <s> -q 3 <ip>`, or `tracepath -n -m <max hops> <ip>` if traceroute is missing |

`-d` / `-n` means "do not look up names for each hop", which keeps the output fast and parseable.

### 6.3 Step 3: the diagnostic sequence (`engine.run_diagnostics`)

Inputs are validated first: ping count 1–50, max hops 1–30, timeout 0.2–10 s. Then:

1. **Create a run** with a random 12-character `run_id`, the UTC timestamp, the OS, and the options used.
2. **Inspect the network** (`inspect_network`): host name, local addresses, the primary source IP (found by "connecting" a UDP socket to 192.0.2.1, which sends no packet), the **default gateway** (the `0.0.0.0` route with the lowest metric on Windows, the `default via` line with the lowest metric on Linux), and the DNS servers. A failure here is recorded but does not stop the run.
3. **DNS lookup** (`resolve`): if the destination is already an IP address, no lookup is needed. Otherwise `socket.getaddrinfo` is called and timed. Errors are sorted into kinds: `nxdomain` (the name does not exist), `temporary` (the resolver did not answer in time), `no_data` (the name exists but has no address), `other`. IPv4 addresses are preferred so ping and traceroute use the same family on every OS.
4. **Gateway ping** (if a gateway was found): up to 4 probes. This tells "my local network is broken" apart from "the far end is broken".
5. **Destination ping** with the chosen count and timeout. If DNS failed, the original name is pinged so the OS's own error is captured.
6. **Traceroute**, only if DNS succeeded (otherwise "traceroute skipped" is recorded).
7. **TCP connect** (optional, if a port is given), with a timeout of max(3 × the ping timeout, 2 s). Outcomes: connected (with connect time), `refused` (something answered with RST, so the host is up), `timeout`, `unreachable`, `dns`, `other`.

### 6.4 Step 4: parsing the output (`parsers.py`)

The parsers **never invent values**: a line that cannot be understood is skipped and a parse warning is recorded.

**Ping**

* Each individual echo reply line is matched (`Reply from ... time=12ms` on Windows, `bytes from ... icmp_seq=1 ... time=12.3 ms` on Linux). **Received = the number of genuine echo replies.**
* Windows prints `time<1ms` for very fast replies. RouteResQ records these as **0 ms** and adds a warning.
* ICMP error replies ("Destination host unreachable", "TTL expired") are collected as `unreachable_reports`, together with the address that sent them. Linux `From x icmp_seq=... Destination Host Unreachable` lines are collected too, and so are "Network is unreachable" / "No route to host" from the local OS.
* "Request timed out." lines are counted (Windows).
* The tool's own summary line (`Packets: Sent = 4, Received = 4` or `4 packets transmitted, 4 received`) gives `sent`. If the summary's "received" differs from the number of real echo replies, a warning explains why: **Windows counts ICMP error replies as "Received"; RouteResQ does not.**
* If there is no summary line, `sent` is rebuilt from the probe lines.
* Then: `loss % = (sent − received) / sent × 100`, and min/avg/max RTT and the **population standard deviation** of RTT (used as the jitter measure).
* A DNS failure inside ping output ("could not find host", "Name or service not known") sets `dns_failure`.

**Traceroute**

* Windows `tracert` lines are parsed into a hop number, up to three RTTs (or `*` for a timeout), and the hop address. "Request timed out" hops have no address. Text after "reports:" (for example "Destination host unreachable") becomes an annotation.
* Linux `traceroute` lines are read token by token: `*` is a timeout, an IP is the hop address (a second, different IP is noted as "also answered by"), a number followed by `ms` is an RTT, and `!H`, `!N`, `!X` are kept as annotations (these are routers saying "host / network / administratively unreachable").
* `tracepath` lines (`1: 192.168.1.1 1.2ms` and `2: no reply`) are also understood. `tracepath` prints some TTLs twice, so duplicates are collapsed, keeping the line that answered.
* `reached_destination` is true if any hop's address equals the resolved destination IP.
* Two helper properties: `last_responding_hop` (the last hop that answered) and `trailing_timeouts` (how many silent hops follow it).

### 6.5 The data model (`models.py`)

Every result is a Python data class:

* `CommandRecord`: argv, return code, duration, stdout, stderr, timed_out, error. Kept so the UI and reports can show the raw output.
* `DNSResult`: query, whether it was an IP literal, addresses, success, error kind, error text, duration.
* `PingResult`: sent, received, every RTT, loss %, min/avg/max/stdev, OS-reported conditions (DNS failure, timeouts, unreachable reports, general failure), parse quality (parsed_ok, summary counts, warnings), and the command.
* `Hop` and `TracerouteResult`: hops, reached_destination, max_hops, parse quality.
* `TCPCheckResult`: host, port, success, connect time, error kind.
* `NetworkConfig`: host name, platform, local addresses, default gateway, DNS servers, primary source IP, notes, commands.
* `DiagnosticRun` composes all of the above, plus `run_id`, target, timestamp, options, label and errors.

Functions such as `run_from_dict` rebuild these objects from stored JSON, so old runs can be re-analysed with the current rules.

### 6.6 History, baselines and comparison (`history.py`)

* Every run (and its analysis) is appended as one JSON line to `results/diagnostics/history.jsonl`. JSON Lines means one record per line, so a half-written last line never corrupts the file (the reader skips it).
* **Previous run:** the latest earlier run against the same destination, used to detect route changes.
* **Baseline:** any healthy run can be marked as the baseline for its destination (`results/diagnostics/baselines.json`). Later runs are compared with it (see rules R-BASE-01 to 04).
* **`compare_runs(old, new)`** compares two runs field by field: DNS resolved, echo replies, loss, average/max RTT, RTT std-dev, traceroute reached, the hop paths, and whether the path changed.
* **CSV export:** `history.csv` with one summary row per run.

### 6.7 Command line (`cli.py`)

```bash
python -m diagnostics.cli 8.8.8.8 nonexistent.invalid 192.0.2.1 --report reports/live_diagnostics.md
python -m diagnostics.cli 8.8.8.8 --set-baseline
```

Options: `--count`, `--timeout`, `--max-hops`, `--no-traceroute`, `--tcp-port`, `--label`, `--set-baseline`, `--report`. Refused targets print `[refused]` and the exit code becomes 2.

---

## 7. Module 2: the root-cause rule engine

File: `failure_analysis/rules.py`. Function: `analyze_run(run, baseline=None, previous=None, thresholds=None)`.

### 7.1 Evidence levels

Every finding and explanation carries exactly one level:

| Level | Meaning |
|---|---|
| `confirmed` | Directly observed in command output. An **observation**, not a cause. |
| `likely` | The explanation most consistent with **all** the evidence. |
| `possible` | Consistent with the evidence, but alternatives cannot be ruled out. |
| `insufficient_evidence` | The data cannot support a conclusion (for example, too few RTT samples). |

### 7.2 Thresholds (`config/thresholds.json`)

| Setting | Default | Used by |
|---|---|---|
| `high_rtt_ms` | 150 | R-LAT-01 |
| `high_jitter_ms` | 30 | R-LAT-02 (RTT standard deviation) |
| `loss_threshold_pct` | 5 | R-LOSS-01 |
| `min_rtt_samples` | 3 | R-LAT-01, R-LAT-02 (need at least 3 replies to judge latency) |
| `baseline_rtt_factor` | 1.5 | R-BASE-01 (RTT must be 1.5 × baseline ...) |
| `baseline_rtt_min_increase_ms` | 20 | R-BASE-01 (... and at least 20 ms higher) |
| `baseline_loss_increase_pct` | 10 | R-BASE-02 |
| `baseline_jitter_factor` | 2 | R-BASE-03 |
| `throughput_drop_pct` | 30 | R-BASE-04 |

### 7.3 The facts

First the run is turned into a set of plain facts (`_Facts`): did DNS succeed or fail and with what error kind; is the ping usable (parsed and at least one probe sent); sent, received, loss, avg, stdev, number of samples; OS unreachable reports; is a gateway known, tested and reachable; is the traceroute usable and did it reach the destination; traceroute annotations such as `!H`; did TCP connect, get refused or time out.

One important derived fact: **`host_responds`** is true if any echo reply came back, **or** TCP connected, **or** TCP was refused (a refusal means the host is up), **or** traceroute reached the destination.

### 7.4 Observations

Plain confirmed facts, written as sentences, for example "DNS resolved 8.8.8.8 ...", "Default gateway 192.168.1.1: 4/4 echo replies", "Ping: 0/4 replies (100.0% loss)", "Traceroute: 10 hop(s) listed; destination NOT reached; last responding hop is TTL 2 (10.240.12.49), followed by 8 silent hop(s)", "TCP connect to port 80: failed (timeout)".

### 7.5 The 17 rules, in the order they run

Every rule is recorded in the **rule trace** with whether it fired and why.

| Rule | Fires when | Produces |
|---|---|---|
| **R-DNS-01** | A host-name lookup failed | Finding *DNS Resolution Failure* (confirmed) |
| **R-PING-00** | Ping output is missing or unparseable (and DNS did not fail) | Trace entry only; may lead to *Inconclusive* |
| **R-REACH-01** | Ping was usable, 0 replies, and DNS did not fail | If TCP connected/refused or traceroute reached the host: **contradiction** instead ("the host is up and ICMP echo is probably filtered"). Otherwise finding *Unreachable Destination* (confirmed). |
| **R-REACH-02** | The OS or a router explicitly reported unreachable / no route (or traceroute shows `!H`, `!N`...), and 0 replies | *Unreachable Destination* (confirmed), with the reports as evidence |
| **R-TCP-01** | The TCP connect timed out | *Unreachable Destination* (confirmed): connection timeout on the port |
| **R-LOSS-01** | 0 % < loss < 100 % and loss ≥ 5 % | *Packet Loss* (confirmed). If fewer than 20 probes were sent, the evidence adds "one lost probe changes loss by N points" (with 4 probes, one loss is 25 points). Below 5 %, the loss is kept as an observation only. |
| **R-LOSS-02** | 100 % loss with no contradictions | *Packet Loss* (confirmed): complete loss |
| **R-LAT-01** | Average RTT > 150 ms with at least 3 samples | *High Latency* (confirmed). With fewer samples: *Inconclusive*, level insufficient_evidence. |
| **R-LAT-02** | RTT standard deviation > 30 ms with at least 3 samples | *High Latency* (confirmed): large RTT variation (jitter) |
| **R-BASE-01** | RTT > 1.5 × baseline **and** at least 20 ms higher | *High Latency* (confirmed): RTT increased compared with the baseline |
| **R-BASE-02** | Loss rose by at least 10 points over the baseline (and is below 100 %) | Trace entry; counts as a congestion indicator |
| **R-BASE-03** | RTT std-dev > max(2 × baseline std-dev, 10 ms) | Trace entry; congestion indicator |
| **R-BASE-04** | Throughput is more than 30 % below the baseline (only when a throughput was measured) | Trace entry; congestion indicator |
| **R-CONG-01** | **Two or more** congestion indicators together, and at least one reply | *Possible Congestion* (possible). One indicator alone is explicitly *not* enough. |
| **R-ROUTE-01** | Traceroute did not reach the destination **and** ping got 0 replies **and** TCP did not answer | *Possible Routing Issue* (possible): path stops responding before the destination |
| **R-ROUTE-02** | A TTL that answered in both this run and the previous run answered from a **different address** | *Possible Routing Issue* family, level confirmed: "Route changed since the previous run" |
| **R-OK-01** | DNS is fine (or an IP was given), the host responds, and there is no DNS or Unreachable finding | Classification *Healthy / Reachable* |

The **congestion indicators** counted by R-CONG-01 are: RTT above the baseline (or above 150 ms when no baseline exists); loss above the baseline (or any partial loss); increased RTT variation; throughput below the baseline.

R-ROUTE-02 compares **per TTL**, so a different hop limit or a hop that stayed silent in one run is never mistaken for a route change.

### 7.6 Contradictions (reported, never hidden)

* **Ping fails but TCP answers** (connected or refused): the host is up; ICMP echo is probably filtered.
* **Ping fails but traceroute reached the destination:** ICMP echo may be filtered, or the loss was transient.
* **Traceroute stops but ping works:** routers or a firewall/NAT are not answering traceroute probes, or the hop limit is too small. This is explicitly **not** treated as a routing failure.
* **The gateway ignores ping but the destination answers:** the gateway probably ignores ICMP; gateway silence alone is not a fault.

### 7.7 Classifications

The run gets one or more of eight labels: *Healthy / Reachable*, *DNS Resolution Failure*, *Unreachable Destination*, *High Latency*, *Packet Loss*, *Possible Routing Issue*, *Possible Congestion*, *Inconclusive / Insufficient Evidence*. They come from the findings (skipping insufficient-evidence ones). *Healthy* is added first when R-OK-01 holds. *Inconclusive* is added when nothing usable was measured, or when there are contradictions but no findings and the host is not confirmed reachable.

### 7.8 Explanations (candidate causes)

Each explanation has a cause, a level, supporting evidence, contrary evidence, **checks to confirm** and recommended actions.

* **DNS failure, error kind `nxdomain`:** "The name does not exist in DNS or is misspelt" — **likely**. Checks: check the spelling; query another resolver (`nslookup <name> 1.1.1.1`).
* **DNS failure, other kinds:** "The configured DNS server is unreachable or not answering" — likely if the gateway answered, otherwise possible. If the gateway also failed: "There is no working local network connection" — possible.
* **Unreachable / routing:**
  * A router reported unreachable: "A router on the path has no route to the destination" — **likely**.
  * The gateway failed too: "Local network or default-gateway problem".
  * The gateway answered (or traceroute got some hops): three **possible** explanations — the host is down or offline; a downstream part of the path beyond the last responding hop is inaccessible; ICMP/traceroute probes are filtered by a firewall.
* **Healthy but ICMP blocked** (TCP answered, ping did not): "ICMP echo is blocked, but the host is reachable" — likely.
* **Partial loss:** intermittent loss on a link (congestion, Wi-Fi, faulty link), or routers rate-limiting ICMP — both possible.
* **High latency:** long or slow path — possible, with the largest RTT jump between consecutive traceroute hops quoted as evidence.
* **Congestion:** queues filling at a bottleneck — possible.

### 7.9 Conclusion sentence

* DNS failure: "The name X could not be resolved, so no connection was attempted. [The local network appears to work (gateway reachable), which points to a naming/DNS problem.] The exact cause is not confirmed."
* Unreachable: "X could not be reached using the available diagnostic methods." followed by either "A router explicitly reported that the destination is unreachable." or "No device reported an explicit error, so the precise cause is not confirmed."
* Healthy: "X is reachable and no problem was detected with the configured thresholds." (or "... but the following conditions were observed: ...").
* Inconclusive: "The collected evidence is insufficient or contradictory; no conclusion can be drawn."

### 7.10 Worked examples (real runs)

The last three rows are the live runs stored in `reports/root_cause_report.md`; the `localhost` run is the one shown in the report's screenshots.

| Destination | What was measured | Classification | Cause status |
|---|---|---|---|
| `localhost` | DNS resolved, 4/4 replies, 0 % loss, one hop | Healthy / Reachable | No failure detected |
| `8.8.8.8` | replies received | Healthy / Reachable | No failure detected |
| `nonexistent.invalid` | resolver said "host not found" ([11001] getaddrinfo failed); gateway 192.168.1.1 answered | DNS Resolution Failure | **Likely**: the name does not exist in DNS or is misspelt |
| `192.0.2.1` | gateway answered 4/4; destination 0/4; traceroute's last responding hop TTL 2 (10.240.12.49) then 8 silent hops; TCP connect timed out | Unreachable Destination, Packet Loss, Possible Routing Issue | **Not confirmed**: host down, path beyond hop 2 inaccessible, or ICMP filtered |

---

## 8. The root-cause register

File: `analysis/cause_report.py`. Command: `python -m analysis.cause_report` (writes `reports/root_cause_report.md`).

This is the output that answers the project's main question: **what caused each failure, and how sure are we?**

### 8.1 The four cause statuses

| Status | When | Meaning |
|---|---|---|
| **Confirmed (injected)** | NS2 scenarios with a fault, and transport drills that produced an error | We caused it on purpose, and its effect is visible in the trace or the error. |
| **Likely** | Live run where the engine rated exactly one explanation *likely* | One explanation fits all the evidence. |
| **Not confirmed** | Live run with only *possible* explanations (or none) | Several explanations fit; the register lists them with the checks that would separate them. |
| **No failure detected** | Healthy live runs, scenario A, drills with no error | Nothing to explain. |

A live failure can never be *Confirmed*, because the tool cannot know the true cause of a live failure.

### 8.2 How each row is built

* **Live rows (`live_cause`)**: problems = classifications other than Healthy. No problems → No failure detected. A *likely* explanation → Likely, with its evidence, the alternatives and the next checks. Only *possible* explanations → Not confirmed, cause "Not determined - possible causes: ...". Symptoms but no explanation → Not confirmed with "Repeat the measurement with more probes / Record a baseline".
* **NS2 rows (`sim_cause`)**: scenario A → No failure detected. Others → Confirmed (injected), the cause is the scenario's `known_cause` text, the mechanism is the analysis's explanation, and the evidence is "what failed", the first three impact lines and the recovery outcome.
* **Transport rows (`transport_cause`)**: an observed error → Confirmed (injected); the cause is the condition the drill created; the conclusion says whether communication resumed.

### 8.3 How the register is collected (`collect`)

* **Latest run per destination** by default (the Reports page has a toggle to include every run).
* **Live runs are re-analysed with the current rules** (`_current_analysis`), using the run's previous run and its baseline, so the register never shows a verdict from an older version of the rules. A run is never compared with itself as its own baseline.
* Rows are sorted by source (live, NS2, transport), then status, then subject.

### 8.4 The stored register

16 subjects: 3 live (8.8.8.8, nonexistent.invalid, 192.0.2.1), 4 NS2 (A, B1, B2, C), 6 transport drills and 3 upload runs. **13 failures have a stated cause**; the other 3 (8.8.8.8, scenario A and the upload baseline) are healthy.

---

## 9. Module 3: NS2 simulation and trace analysis

### 9.1 What NS2 is and why we use it

NS2 (Network Simulator 2, version 2.35) is a discrete-event network simulator widely used in networking courses. A Tcl script describes the nodes, links, traffic and events; NS2 runs the simulation and writes a **trace file** with one line per packet event. We use it because a link failure or congestion can be **injected at an exact time**, so the cause is known, and the effect can be measured packet by packet. RouteResQ runs the **real** simulator; there is no mock.

### 9.2 The topology and the Tcl script (`simulation/tcl/routeresq.tcl`)

```
                 n2
      (primary) /  \ (primary)
   n0 ---- n1          n4 ---- n5
  source        \  /         destination
                 n3   (alternative path)
```

| Node | Role |
|---|---|
| n0 | source host |
| n1 | edge router (ingress) |
| n2 | core router, primary path |
| n3 | core router, alternative/backup path |
| n4 | edge router (egress) |
| n5 | destination host |

| Link | Bandwidth | Delay | Queue | Routing cost |
|---|---|---|---|---|
| n0–n1, n4–n5 (access) | 10 Mb/s | 2 ms | DropTail, 20 packets | 1 |
| n1–n2, n2–n4 (primary core) | 2 Mb/s | 10 ms | DropTail, 20 packets | 1 |
| n1–n3, n3–n4 (alternative) | 2 Mb/s | 15 ms | DropTail, 20 packets | 3 |

The alternative links cost 3 each, so while everything is up the routing protocol prefers n1–n2–n4 (cost 2) over n1–n3–n4 (cost 6).

What the script does, in order:

1. **Default parameters** in a Tcl array (`trace`, `events`, `stop` 10 s, `routing` DV, bandwidths, delays, `queue_limit` 20, `alt_cost` 3, `pkt_size` 1000, `rate` 1Mb, traffic 1–9 s, no failure, no cross traffic, `dv_advert` 2 s).
2. **Reads `key=value` arguments** from the command line. An unknown key stops the script with exit code 2.
3. **Routing:** `DV` sets `Agent/rtProto/DV advertInterval` to 2 s and calls `$ns rtproto DV` (distance-vector, reacts to link changes). `Static` computes routes once at start-up and never changes them.
4. Opens the **trace file** (`$ns trace-all`) and the **event log**, and defines `log_event`, which writes "time KIND detail" lines.
5. Creates 6 nodes and the 6 duplex links, sets every queue limit in both directions, and sets the cost 3 on the alternative links.
6. **Flow 1 (monitored):** a UDP agent on n0 (flow id 1) to a Null sink on n5, driven by a CBR (constant bit rate) application: 1000-byte packets at 1 Mb/s, `random_ 0` (perfectly regular), from `traffic_start` to `traffic_stop`.
7. **Flow 2 (competing, only if `cross_rate` is not 0):** a second CBR/UDP flow n0→n5 (flow id 2) between `cross_start` and `cross_stop`.
8. **Controlled link failure** (if `fail_link` is set): `$ns rtmodel-at <fail_at> down $n1 $n2` and `... up` at `restore_at`, each also logged as `LINK_DOWN 1-2` / `LINK_UP 1-2`.
9. `finish` at `stop`: logs `SIM_END`, flushes and closes the files, exits 0.

At 1 Mb/s with 1000-byte (8000-bit) packets, one packet leaves every **8 ms** (125 packets per second). From 1.0 s to 9.0 s that is **1001 packets**.

### 9.3 The four scenarios (`simulation/scenarios/*.json`)

| Label | id | Routing | Injected condition (known cause) |
|---|---|---|---|
| A | `healthy` | DV | None. The control experiment and the baseline for every comparison. |
| B1 | `link_failure_dv` | DV | Link n1–n2 down at 3.0 s, back up at 6.0 s. |
| B2 | `link_failure_static` | Static | Exactly the same failure, but routing never reacts. |
| C | `congestion` | DV | Competing 1.5 Mb/s CBR flow from 3.0 to 6.0 s, so 2.5 Mb/s is offered to a 2 Mb/s core link. |

All four use the same **phase windows**: **before 1–3 s, during 3–6 s, after 6–9 s**. In scenario A these are reference windows only, so results line up with B and C.

Each scenario file holds an `id`, `label`, `name`, `category` (`healthy`, `link_failure` or `congestion`), a `description`, the `known_cause` text, the NS2 `params`, the `phases`, and (for A) a `phase_note`.

### 9.4 Strict validation (`simulation/scenario.py`)

Scenario values are passed to NS2 as `key=value` and end up inside Tcl strings, so they are validated strictly to prevent **Tcl injection**:

* every key must be one of the 20 known parameters;
* bandwidths must look like `1.5Mb` (units b, Kb, Mb, Gb), delays like `10ms` (s, ms, us), integers and floats are plain numbers, the link is `a-b` with nodes 0–5, routing is `DV` or `Static`;
* no spaces, brackets, braces, semicolons or `$` can get through.

Then logical checks: traffic must start before it stops and stop before the simulation ends; a failed link must exist in the topology; `fail_at` must be set; `restore_at` must come after `fail_at`; a `link_failure` scenario must have a failure; a `congestion` scenario must have cross traffic; all three phase windows must exist and be non-empty.

The `Scenario` class also provides derived values: `has_failure`, `failed_link`, `fail_at`, `restore_at`, `has_cross_traffic`, `routing`, the `flows` list, `packet_interval` (8 ms here), and `ns_args()` which builds the validated argument list.

### 9.5 Running NS2 (`simulation/runner.py`)

**Backend detection** (`detect_backend`):

1. An `ns` binary on PATH → the **local** backend (typical on Linux after `sudo apt install ns2`, and on Streamlit Cloud via `packages.txt`). The version comes from running a tiny script that prints `[ns-version]`.
2. Otherwise, if Docker is running and the image `routeresq-ns2:2.35` exists → the **docker** backend (used on Windows). The version comes from `dpkg-query` inside the image: `2.35+dfsg-3.1`.
3. Docker without the image → an error explaining how to build it. Neither → "NS2 was not found".

**One run** (`run_scenario`):

1. Creates `results/simulation/<scenario id>/<timestamp>/` (adds `-1`, `-2` if the folder exists).
2. Copies `routeresq.tcl` into that folder.
3. Runs `ns routeresq.tcl trace=out.tr events=events.log <params...>` there, or `docker run --rm -v <run dir>:/work -w /work routeresq-ns2:2.35 routeresq.tcl ...`. Always as an argument list, with a 300 s timeout.
4. Writes `scenario.json` and `run.json` (backend, version, exact command, start time, wall time, return code, last 5000 characters of stdout/stderr).
5. Raises `NS2ExecutionError` if NS2 failed or the trace is missing or empty.

`list_runs` returns run folders newest first, ordered by the UTC start time stored in `run.json` (folder names use the local clock of whichever machine ran NS2, so they are not comparable across machines).

### 9.6 The trace format and parser (`simulation/trace_parser.py`)

A wired trace line has 12 fields:

```
event time  from to  type size flags   fid src  dst  seq pkt_id
+     1.0   0    1   cbr  1000 ------- 1   0.0  5.0  0   0
```

* `event`: `+` enqueued on a link's queue, `-` dequeued (transmission starts), `r` received at `to`, `d` dropped.
* `src`/`dst` are `node.port`; `pkt_id` is NS2's **globally unique packet id**, used to follow one packet across hops.
* Link changes appear as `v 3 link-down 1 2` and `v 6 link-up 1 2`. NS2 2.35 prints each one twice, so duplicates are removed.

The parser keeps packet events, link events, the number of malformed lines (with up to 5 examples), the total number of lines and the end time. `link_down_intervals()` turns link events into "down from t0 to t1" intervals, and `link_down_at(a, b, t)` answers "was this link down at time t?". `parse_events_log` reads the event log written by `log_event`.

### 9.7 Rebuilding every packet (`analysis/packets.py`)

Each data packet (types `cbr`, `udp`, `tcp`, `exp`, `pareto`) becomes a `PacketRecord`. The **counting rules prevent double counting at routers**:

* **Sent:** the first `+` event **at the packet's source node**. `+` events at routers are forwarding, not new packets.
* **Received:** an `r` event **at the destination node**. `r` events at routers only extend the packet's path.
* **Path:** the source followed by every node the packet was received at, e.g. `0-1-2-4-5`.
* **Delay:** receive time − send time (includes queueing, transmission and propagation).

Every sent packet ends with exactly **one fate**:

| Fate | How it is decided |
|---|---|
| `delivered` | received at the destination |
| `dropped_queue` | a `d` event on a link that was **up** → DropTail queue overflow |
| `dropped_link_down` | a `d` event on a link that the trace shows as **down** |
| `lost_at_node` | **no `d` event**; the last event is arrival at a router that never forwarded it |
| `lost_on_link` | no `d` event; the last event is `+`/`-` on a link |
| `in_flight` | last seen within 0.5 s of the end of the trace (it could not have arrived yet) |

**Why `lost_at_node` matters:** NS2 2.35 silently discards packets that reach a router whose route uses a down link. It writes **no `d` line** for them. This happens in scenario B2. RouteResQ still finds these losses because the packet is never seen again, and reports where it was last seen and which adjacent links were down.

### 9.8 Metrics (`analysis/metrics.py`)

For a window (the whole run, or one phase), with S = packets sent in the window, R = those delivered, D = those lost, F = those in flight:

* **Loss %** = |D| ÷ (|S| − |F|) × 100
* **Average delay** = mean of (receive time − send time) over R; min and max are kept too
* **Jitter** = mean of |dₖ − dₖ₋₁| over consecutive delivered packets in send order (a simplified form of RFC 3550)
* **Throughput** = bits received at the destination in the window ÷ window length; for the whole flow the window is [first send, last receive]
* **Phase assignment:** loss and delay go to the phase of the **send** time; throughput goes by **receive** time
* Also: delivery ratio, reordered count and fate counts

**Time series:** 0.1 s bins with throughput, packets sent, packets lost, average delay and the dominant path in each bin (used for the charts).

**Queue occupancy:** rebuilt per directed link from `+` (join the queue), `-` (start transmission, leave the queue) and `d` (dropped from the queue). A `d` for a packet already being transmitted does not change the queue length. `queue_stats` gives the maximum and when it happened; the **bottleneck** is the link with the largest queue.

**Drops by location:** counts each loss fate per link or node.

### 9.9 Routing evidence (`analysis/routing.py`)

* **Path usage:** delivered packets per complete path, per phase.
* **Route changes:** delivered packets are sorted by send time and grouped into runs on the same path. A change is reported only if the new path then holds for **at least 3 consecutive packets**, so one stray packet is never called a route change. Each change records its time, old and new path, and the last/first packet on each.
* **Delivery gaps (interruptions):** periods with no arrivals at the destination longer than max(5 × packet interval, 50 ms). Here 5 × 8 ms = 40 ms, so the threshold is **50 ms**. An "open" gap means delivery never resumed before traffic stopped.
* **Routing control traffic:** distance-vector messages (`rtProtoDV`) originated per 0.5 s, and the count in the 0.5 s after the failure versus the average before it.

### 9.10 Timeline (`analysis/timeline.py`)

One list of events, each tagged as **configured** (from the event log: SIM_START, TRAFFIC_START, LINK_DOWN, LINK_UP, CROSS_TRAFFIC_START/STOP, SIM_END) or **trace** (observed): link down/up traced, first delivery, first loss after the failure, total losses during the failure, routing updates after the failure, each route change, delivery gap start and resume, queue full, queue drained, first and last queue-overflow drop, last delivery. Sorted by time, with configured events before observed ones at the same time.

### 9.11 Interpreting one experiment (`analysis/experiment.py`)

`analyze_experiment` parses the trace and the event log, rebuilds packets for each flow, computes everything above, and then answers the questions according to the scenario's category:

* **Healthy:** packets sent/delivered/lost, delay, throughput, the path used. Any loss is flagged as "Unexpected".
* **Link failure:**
  * checks the trace really contains the link-down event ("Confirmed by the trace ...");
  * counts packets lost from the failure until restoration, split by fate;
  * counts how many packets sent while the link was down were delivered;
  * reports delivery gaps, route changes during the failure and after restoration, and the DV messages after the failure;
  * **recovery classification:**
    * **rerouted**, if packets sent during the failure arrived over a path that avoids the failed link; the recovery time is the first such arrival minus the failure time;
    * **interrupted until restored**, if delivery resumed only after link-up;
    * **not recovered within the simulation** otherwise;
  * also the after-phase throughput as a percentage of the before phase;
  * explains the mechanism (DV triggered updates and an existing alternative route, or static routes still pointing at the failed link).
* **Congestion:**
  * offered load vs capacity;
  * the bottleneck queue's peak;
  * delay and throughput before/during/after;
  * queue-overflow drops per flow;
  * when the queue drained after the competing flow stopped;
  * **recovered** only if packets sent **after the queue drained** show **0 % loss** and average delay **within 10 % of the before phase**. Otherwise **partially recovered**, or **not recovered** if the queue never drained. Packets caught in the draining queue are reported as a transient, not as non-recovery.

Each result also lists what **can** and **cannot** be concluded (for example, "NS2 results describe this configured model, not any real network").

### 9.12 What one NS2 run folder contains

`results/simulation/<id>/<timestamp>/`:

| File | Contents |
|---|---|
| `routeresq.tcl` | the exact script that ran |
| `out.tr` | the raw NS2 trace |
| `events.log` | configured events written by `log_event` |
| `scenario.json` | the scenario with its effective parameters |
| `run.json` | backend, version, command, timing, return code |
| `results.json` | the full analysis (everything above) |
| `timeline.csv`, `timeseries.csv`, `phase_metrics.csv`, `lost_packets.csv` | tables for each part of the analysis |
| `report.md` | the Markdown report for this run |

`python -m simulation.experiments` also writes `results/simulation/scenario_comparison.json` and `.csv` and the reports `reports/<scenario>.md` and `reports/scenario_comparison.md`. `--reanalyze` re-analyses the newest stored traces without simulating again.

---

## 10. The NS2 results, explained number by number

All four runs used ns-2.35 (`2.35+dfsg-3.1`) in Docker. NS2 is deterministic, so re-running gives the same numbers.

| Scenario | Delivered | Loss % | Avg delay | Throughput | Route changes | Longest gap | Outcome |
|---|---|---|---|---|---|---|---|
| A healthy | 1001/1001 | 0.00 | 33.60 ms | 996.81 kb/s | 0 | none | baseline |
| B1 DV | 999/1001 | 0.20 | 37.36 ms | 994.82 kb/s | 2 | none | rerouted |
| B2 static | 624/1001 | 37.66 | 33.60 ms | 621.39 kb/s | 0 | 3.024 s | interrupted until restored |
| C congestion | 884/1001 | 11.69 | 54.55 ms | 880.30 kb/s | 0 | none | recovered |

### A: why the delay is exactly 33.6 ms

Propagation: 2 + 10 + 10 + 2 = 24 ms. Transmission of one 8000-bit packet: 0.8 ms on each 10 Mb/s link and 4 ms on each 2 Mb/s link, so 0.8 + 4 + 4 + 0.8 = 9.6 ms. Total 33.6 ms, with no queueing because 1 Mb/s fits easily in 2 Mb/s. Every packet used path 0-1-2-4-5. The before-phase throughput is 984 kb/s rather than 1000 only because the first packet arrives 33.6 ms after traffic starts.

### B1: rerouting in 43.6 ms

* At 3.0 s link n1–n2 goes down. NS2's DV agents are told immediately and send triggered updates: **14 DV messages in the 0.5 s after the failure, against 2.4 per 0.5 s on average before**.
* n1 already had a route through n3, so forwarding switched at once: route change at **3.000 s** from 0-1-2-4-5 to 0-1-3-4-5, and back at **6.008 s** after the link returned.
* The first packet over the alternative path arrived at 3.0436 s: **43.6 ms after the failure**. That is also exactly the alternative path's delay: propagation 2 + 15 + 15 + 2 = 34 ms plus 9.6 ms transmission = 43.6 ms.
* **Only 2 packets were lost** (fate `dropped_link_down`): they were already on the n1–n2 link when it failed. All **375 packets sent while the link was down were delivered**. (375 = 3 s × 125 packets per second.)
* During-phase delay rose to 43.6 ms because of the longer path; after-phase throughput was **101.9 %** of the before phase.

### B2: the same failure with static routing

* Static routes are computed once, so n1 kept forwarding towards the dead link. **No packet sent during the failure was delivered (0 of 375)**.
* **377 packets lost:** 375 of fate `lost_at_node` (silently discarded at n1, no `d` line, found because they were never seen again) and 2 `dropped_link_down` (already on the link).
* A delivery gap from 3.0096 s to 6.0336 s: **3.024 s**. The first delivery after restoration came 33.6 ms after link-up, 3.034 s after the failure.
* No routing messages exist in this run, and there were no route changes.

### C: congestion

* From 3 to 6 s, 1 + 1.5 = **2.5 Mb/s** is offered to the **2 Mb/s** link n1→n2 (125 % of capacity).
* The queue at n1→n2 reached its **20-packet limit** at 3.30 s.
* Delay of the monitored flow: 33.6 ms before → **102.75 ms during** → 35.24 ms after (max 109.6 ms). A full queue of 20 packets, each taking 4 ms to transmit on the 2 Mb/s link, adds up to about 80 ms of waiting.
* **170 queue-overflow drops** (`d` events on an up link): **117 from flow 1** and 53 from flow 2. During-phase loss 30.93 %.
* The queue **drained 0.143 s** after the competing flow stopped. The 357 packets sent after it drained had 0 % loss and 33.6 ms delay, so the outcome is **recovered**. One packet sent just after 6 s was still dropped by the full queue (reported as a transient).
* No route changes: NS2's DV routing is not load-aware.

---

## 11. Module 4: the transport lab (TCP, UDP, TLS)

All of this uses real sockets on `127.0.0.1`. The standalone tools also work between two lab PCs.

### 11.1 Framing (`communication/framing.py`)

TCP delivers a **byte stream**, not messages: one `send` may arrive in several `recv` calls, and several sends may arrive together. So every message is wrapped in a frame:

```
| type: 1 byte | payload length: 4 bytes, big endian | payload |
```

* Frame types: `MSG`, `FILE_META`, `FILE_CHUNK`, `FILE_END`, `ACK`, `ERROR`, `BYE`.
* `recv_exact(sock, n)` loops until exactly n bytes arrive, which handles **partial reads**. If the peer closes mid-frame it raises `ConnectionClosed`.
* Frames larger than 16 MiB and unknown types raise `ProtocolError`.
* JSON payloads (metadata and acknowledgements) are encoded with `send_json` / `decode_json`.

### 11.2 The server (`communication/tcp_server.py`)

`TCPTransferServer` listens on a port (0 means "pick a free one") and handles each client in its own thread. It is a **context manager**, so `with TCPTransferServer(...) as srv:` always closes the socket. Every step is recorded as an event (LISTEN, CONNECTED, TLS_HANDSHAKE_OK/FAILED, MSG, FILE_START, FILE_DONE, BYE, CONNECTION_ENDED, ...).

* **TLS:** if an SSL context is given, each accepted connection is wrapped server-side.
* **Message:** replies with an ACK holding the byte count, the SHA-256 of what it received and an echo of up to 200 characters.
* **File:** reads the metadata (name, size, SHA-256), sanitises the name, refuses sizes above 200 MB, receives chunks while hashing them (optionally saving them), and replies with an ACK containing the received bytes, its own SHA-256, `integrity_ok` (size and digest both match) and its duration.
* **Fault injection, used only by the drills:**
  * `silent=True` accepts the connection but never replies, which provokes a read timeout;
  * `abort_after_bytes=N` resets the connection after N bytes. It sets `SO_LINGER` to (on, 0 seconds) before closing, which makes the OS send a **TCP RST** instead of a normal FIN.

### 11.3 The client (`communication/tcp_client.py`)

`send_message` and `send_bytes` / `send_file` return a `TransferResult`. It holds: ok, operation, host, port, tls, bytes sent, payload size, connect time, TLS handshake time, duration, throughput, local SHA-256, the server's ACK, integrity_ok, error kind and message, TLS details, and a list of **steps** that actually happened (for example "TCP connection established in 0.37 ms (3-way handshake)"). The UI builds its connection-state chain only from these completed steps.

* Files are sent in 64 KiB chunk frames; throughput = bytes × 8 ÷ duration.
* TLS details: protocol version, cipher suite and its bits, the peer certificate's subject, issuer, expiry and SHA-256 fingerprint.
* **Error classification** (`classify_error`):

| Exception | Kind |
|---|---|
| `ssl.SSLCertVerificationError` | `tls_certificate` |
| other `ssl.SSLError` | `tls_error` |
| `ConnectionRefusedError` | `refused` |
| `socket.timeout` / `TimeoutError` | `timeout` |
| `ConnectionResetError`, `ConnectionAbortedError`, `BrokenPipeError` | `reset` |
| `ConnectionClosed` | `closed_by_peer` |
| `ProtocolError` | `protocol` |
| `socket.gaierror` | `dns` |
| network/host unreachable errors | `unreachable` |
| anything else | `other` |

### 11.4 UDP (`communication/udp.py`)

UDP has no delivery, ordering or duplicate guarantees, and RouteResQ deliberately **adds none**. It only measures what arrived.

* **Datagram header:** magic `RRQU`, run id, sequence number, total count, send timestamp (struct `!4sIIId`), then the payload.
* **Sender (`send_datagrams`):** sends `count` datagrams, optionally paced at a rate, and can **deliberately skip** chosen sequence numbers (`omit`). This is used only to inject a known, labelled loss in a drill.
* **Receiver (`UDPReceiver`):** runs in a thread and ends when all datagrams have arrived, on `stop()`, or after an **idle timeout** (default 1.5 s) with nothing arriving. That idle timeout is how a missing tail is detected. It reports: received, unique, **duplicates**, **out-of-order** arrivals, **missing sequence numbers as ranges** (for example "50-54, 120, 199"), loss %, bytes, duration, throughput, whether it timed out, malformed datagrams and average one-way delay.

### 11.5 TCP vs UDP experiment (`communication/experiments.py`)

The same amount of data (1,000,000 bytes by default, 3 trials each) is sent over TCP and over UDP (1024-byte datagrams). The explanation is **generated from the measured numbers** and never claims that one protocol is always faster:

* TCP spends time on the SYN, SYN-ACK, ACK handshake; UDP sends immediately;
* TCP delivered 100 % and SHA-256 matched (retransmission and ordering);
* UDP either lost datagrams that were never resent, or delivered everything "in these trials", which is not a guarantee;
* any reordering;
* which was faster in this run, and why that depends on datagram size, pacing, buffers and the host.

Stored result: TCP connection setup 1.785 ms on average; every trial delivered 100 % with matching SHA-256; mean throughput **TCP 3067.1 Mb/s** (until acknowledged) vs **UDP 840.4 Mb/s** (at the receiver); all UDP datagrams arrived. These are loopback numbers on one host, not a ranking of the protocols.

### 11.6 Security: the lab PKI and TLS (`security/`)

**Certificates (`certs.py`)**, generated with the `cryptography` library into `results/certs/` (not committed):

| File | What it is |
|---|---|
| `lab-ca.pem` | "RouteResQ Lab CA", the CA the client trusts |
| `server.pem` / `server.key` | certificate for `localhost` and `127.0.0.1`, signed by the lab CA (**valid**) |
| `rogue-ca.pem`, `rogue-server.pem` / `.key` | the same names, but signed by "Untrusted Rogue CA" (**untrusted issuer**) |
| `wrong-host.pem` / `.key` | signed by the lab CA but issued for `wrong-host.example` (**name mismatch**) |

Details: elliptic-curve keys on P-256 (SECP256R1), SHA-256 signatures, 30-day validity, back-dated 5 minutes to avoid clock-skew problems, Subject Alternative Names, CA basic constraints and key usage, server-auth extended key usage. `ensure_lab_pki` reuses existing certificates and regenerates all of them if any file is missing or the server certificate expires within a day.

**TLS contexts (`tls.py`):** the server context requires TLS 1.2 or newer and loads the certificate and key. The client context trusts only the lab CA, requires TLS 1.2+, sets `check_hostname = True` and `verify_mode = CERT_REQUIRED`, so **both the certificate chain and the host name are checked**.

**Secure transfer demo:** a local TLS server; the client sends a message and a 262,144-byte random file; SHA-256 is compared on both ends. Stored result: **TLSv1.3, TLS_AES_256_GCM_SHA384 (256-bit)**, certificate chained to the lab CA and matched `localhost`, client and server SHA-256 equal.

**Integrity (`integrity.py`):** SHA-256 of bytes or of a file, and a verify helper.

No custom cryptography is used anywhere.

### 11.7 The six failure drills (`communication/failures.py`)

Each drill (1) creates a known failure, (2) records the error the application actually saw, (3) restores the condition and (4) checks that communication works again.

| Drill | How the fault is created | What the client observes | Restoration |
|---|---|---|---|
| Server unavailable | Connect to a free port with nothing listening | `refused` (the OS answers the SYN with RST; Windows retries for about 2 s first) | Start a server on that port; the message is acknowledged |
| Connection timeout | A `silent` server accepts but never replies | `timeout` after 1.5 s (a timeout alone cannot tell a slow server from a dead one) | Replace it with a responsive server |
| Interrupted transfer | The server resets after about 300,000 of 2,000,000 bytes | `reset`; no final acknowledgement, so the client cannot know how much was kept | Restart and resend the whole file; SHA-256 matches |
| Missing UDP datagrams | The sender skips sequence numbers 50–54, 120 and 199 | The receiver reports exactly "50-54, 120, 199" and an idle timeout; detection matches injection | Send again without skipping; 200/200 received |
| Untrusted certificate | The server presents the rogue-CA certificate | `tls_certificate` (CERTIFICATE_VERIFY_FAILED); no data sent | Switch to the valid lab certificate |
| Host-name mismatch | The server presents the `wrong-host.example` certificate | `tls_certificate` (host-name mismatch); no data sent | Present the valid `localhost` certificate |

An optional seventh drill connects to 192.0.2.1:80, where no host exists, to show a connect timeout (no SYN-ACK). It is not restorable by design.

`python -m communication.report` runs the comparison, the TLS demo and all drills, and writes `reports/communication.md`.

---

## 11A. File upload under link failure (isolated test network)

**The question:** if a network link goes down halfway through a file upload, does the upload continue on a backup route, stall until the link returns, or fail and need a retry?

**Code:** `netlab/` (`config.py` bounds, `topology.py` test network, `lab.py` one run, `analysis.py` outcomes, `runner.py` backends and stored runs, `report.py`). Page: **Lab · Link failure → Upload test** (`app_pages/upload_page.py`). Image: `docker/Dockerfile.netlab`.

**Test network.** Three Linux network namespaces (client, router, server) inside a container, joined by veth links. The client and server are joined directly by the **primary link** (5 ms each end); the **backup path** runs through the router in two hops (10 ms each). The TCP connection runs between service addresses on loopback (`10.98.0.1` → `10.99.0.1`), so it survives a change of path. The host's network is never touched; namespaces are deleted after every run.

**The fault.** When the **server** has received 30% of the file (receiver-confirmed), both ends of the primary link are taken down for 3 s, then brought back and the primary route re-installed.

| Run | What differs |
|---|---|
| Healthy baseline | the primary link stays up |
| Link failure · backup route | a backup route (metric 100, a floating static route) is pre-installed, so forwarding can fall back to it — **controlled failover**, no routing protocol |
| Link failure · static forwarding | the same fault; the backup path is connected but no route points to it |

Same file (bundled 2 MiB sample, or your own 64 KiB–8 MiB), pacing (512 KiB/s, 8 KiB chunks), 10 s socket timeout, 1 retry and topology in all three runs. Uploads use RouteResQ's framing (FILE_META, FILE_CHUNK, FILE_END) and the server's SHA-256 acknowledgement.

**Measured (recorded run, 2026-11-19, Docker backend):**

| Run | Outcome | Total | Stall | Retry | Same TCP connection | Backup path | SHA-256 |
|---|---|---|---|---|---|---|---|
| Healthy baseline | completed normally | 4.04 s | 0.017 s | no | yes | not used (336 B) | match |
| Backup route | continued on the backup path | 4.07 s | 0.071 s | no | yes | used (1.43 MiB during the outage; first bytes 0.134 s after link down) | match |
| Static forwarding | stalled until the link returned, then resumed | 4.72 s | 3.29 s | no | yes | not used (250 B); `ip route get` = *Network is unreachable* | match |

* **Stall** = the longest time the server's received byte count did not grow (after the link went down; whole transfer for the baseline).
* **Backup path used** = ≥ 16 KiB more left the client's backup interface during the outage (interface counters every 50 ms). A completed upload alone is never taken as proof of the path.
* In the static run progress resumed 0.29 s after the link came back (the next TCP retransmission); the total time grew less than the stall because the paced client catches up at link speed afterwards.
* A **retry** is a new TCP connection that re-sends the whole file; resuming from a byte offset is not implemented. With a 12 s outage and a 5 s timeout the first connection timed out and the retry (started while the link was still down) timed out too: classified *failed*.

**Running it:** `python -m netlab.runner` (bundled sample) or `python -m netlab.runner --file my.bin`; `--record --report` also refreshes `results/netlab/recorded` and `reports/file_upload_link_failure.md`. Needs Linux with root, or Docker with the image built once: `docker build -f docker/Dockerfile.netlab -t routeresq-netlab:1 docker`. The hosted app has neither, so it shows the **recorded run**, labelled as recorded.

---

## 12. The guided demo

Logic: `walkthrough/flow.py` (independent of Streamlit). Page: `app_pages/demo_page.py`. Open it with the **Guided demo** button in the top bar.

The demo tells one failure story in seven steps: **Detect → Diagnose → Analyse impact → Observe recovery → Transport → Upload under link failure → Report**. Every step runs the real backend and shows a **verified status**: `not_started`, `success`, `partial`, `failed` or `stored`.

| Step | What runs | How it is verified |
|---|---|---|
| Detect | `run_diagnostics` on the chosen destinations (default 8.8.8.8, nonexistent.invalid, 192.0.2.1) with 3 probes, 0.6 s timeout, 8 hops; each run is analysed and saved to history | `verify_run`: a DNS failure with a recorded reason, or ping output parsed into probe counts. Each destination is guarded separately, so one failure does not lose the others. |
| Diagnose | Builds the evidence chain for each run: symptom → measurement → explanation (with status) → limitations → next check | success if the detected runs can be read back from history |
| Analyse impact | Runs the chosen NS2 scenarios fresh if NS2 is available | `verify_sim`: return code 0, packet events present, no malformed lines, the monitored flow sent packets. If a fresh run fails or NS2 is missing, the newest stored run is used and **labelled `stored`**. |
| Observe recovery | Compares the baseline with the chosen failure scenario | success if all failure scenarios are fresh, `stored` if all are stored, `partial` if mixed |
| Transport | TCP vs UDP (400 kB, one trial), the TLS secure transfer, and all drills | TCP integrity verified; TLS file transfer OK with SHA-256 match; every drill observed an error **and** resumed |
| Upload under link failure | The three uploads (section 11A) with the bundled sample, if a test-network backend exists | `verify_upload`: all three runs present, the fault hit the upload in progress, every completed upload matched its SHA-256. Without a backend (or if the run fails) the recorded run is used and **labelled `stored`**. |
| Report | Builds a Markdown report | It states exactly which results are fresh, stored or failed, includes the root-cause register for this demo, the evidence chains, the mechanism of each injected failure, and any errors |

Stages keep their successful parts when a sibling fails, and each stage can be retried. The report never claims fresh results when stored ones were used.

---

## 13. The user interface

### 13.1 The entry point (`streamlit_app.py`)

1. **Module refresh:** Streamlit keeps already-imported modules in memory, so after a `git pull` on Streamlit Cloud (or an edit while running locally) old code would stay active until a reboot. Before importing anything from the project, `_drop_stale_project_modules()` checks whether any project file changed since it was loaded and, if so, drops the project's modules so this run imports the current code.
2. Creates the results folders and logging, and sets the page config (wide layout, title "RouteResQ").
3. Declares the 8 pages with `st.Page` and calls `st.navigation(..., position="hidden")`, so Streamlit's own sidebar menu is hidden.
4. Injects the theme, draws the **brand bar** and the **workflow rail**, then runs the current page.

### 13.2 The shell (`ui/shell.py`)

* **Brand bar:**
  * the logo (an inline SVG of a failed link and its reroute, embedded as a data URI because `st.html` strips inline SVG);
  * the RouteResQ word mark and tagline;
  * status chips: the NS2 version or "NS2 unavailable", the ping/traceroute tools, and "local mode" or "hosted demo · restricted probes";
  * the **Guided demo** button;
  * the **CN Lab · JIIT Noida** badge, the team names and a GitHub link to SaiGrover/RouteResQ.
* **Workflow rail:** seven equal cards with an arrow between each: Overview, 01 Detect, 02 Diagnose, 03 Impact, 04 Recovery, Lab (TCP · UDP · TLS), 05 Report.
  * Each card is an `st.page_link`, so navigation happens in the browser without re-running the page being left (buttons with `switch_page` felt laggy).
  * The stage label and a **live headline** from stored results (for example "DV reroute in 43.6 ms", "6/6 failures recovered", "4/4 NS2 runs stored") are drawn with CSS pseudo-elements.
  * The current page is lit in its own accent colour.

### 13.3 Theme, components, charts and data

* **Theme (`ui/theme.py` and `.streamlit/config.toml`):** a locked graphite dark theme. Fonts: Space Grotesk (headings and values), Inter (text), JetBrains Mono (addresses and timings). One colour per meaning everywhere:

| Colour | Meaning |
|---|---|
| cyan | live measurement, TCP, brand |
| amber | latency, congestion, UDP, warnings |
| clay (red) | failure, loss, unreachable |
| green | healthy, recovered, verified |
| steel blue | rerouting, reports |
| sand | simulation, the alternative path |
| slate | neutral, not applicable |

  Each NS2 scenario also has a fixed colour (A green, B1 blue, B2 clay, C amber). The background artwork `static/bg.webp` sits behind a dark overlay; cards stay opaque so text never sits on the texture.
* **Components (`ui/components.py`):** page headers, KPI tiles, cards, pills, source badges, verdict boxes, notes, empty states, charts with an **Interpretation** note (what it shows and why it matters), the event timeline, the **Method** section (a step flowchart beside an artefact panel whose file sizes are read from disk on every load), the connection-state chain, and the cause register table.
* **Charts (`ui/charts.py`):** one Plotly style for the whole app. Charts include:
  * the topology, drawn with the paths delivered packets actually took in each phase;
  * throughput, delay and packet fates;
  * the bottleneck queue and DV routing messages;
  * phase bars, the scenario comparison and all scenarios' throughput overlaid;
  * per-probe RTT with threshold lines, per-hop traceroute RTT, and the history trend;
  * protocol bars for TCP vs UDP.

  Configured event windows are shaded.
* **Data (`ui/data.py`):** cached readers. Result files are cached by path **and modification time**, so a new run shows up immediately. The NS2 status is cached for an hour because Docker calls are slow.

### 13.4 The pages

| Page | What you see |
|---|---|
| **Overview** (Command centre) | KPI tiles (last live check, live checks recorded, NS2 scenarios analysed, DV reroute time, static-route outage, transport failures recovered), the **root-cause register**, every scenario's throughput on one chart, recovery verdicts, recent live checks, links onward |
| **Diagnostics** (01) | The run form (destination, label, probes, timeout, hops, TCP port, traceroute switch), a result header, KPI tiles, the per-probe RTT chart with thresholds, the per-hop traceroute chart and hop table, network configuration, raw command output, history trend, run-to-run comparison, baselines, adding an authorised destination (local only) |
| **Root cause** (02) | The reasoning ladder (detected symptoms → supporting measurements → possible explanations → evidence limitations), candidate causes with evidence for and against plus next checks, findings with evidence levels, contradictory evidence, the full rule trace, re-analysis against any earlier run |
| **NS2 simulation** (03) | A scenario picker (A, B1, B2, C), the NS2 status, an interactive topology with a before/during/after switch, scenario configuration, KPI tiles, throughput / delay / packet-fate / queue / DV-message charts, downloads |
| **Failure & recovery** (04) | The recovery verdict, the five questions answered, a before/during/after topology triptych (edge width = delivered packets that used the link), the timeline of configured and observed events, phase comparison, cross-scenario comparison |
| **TCP · UDP · TLS** (Lab) | Four sections: Connection (send a real TCP message or file), TCP vs UDP, Secure transfer (TLS handshake, certificate and SHA-256 details), Failure drills (fault → error → restore → resumed) |
| **Reports** (05) | Five views: Root-cause report (the default), Reports (every generated Markdown report), Experiment history, Files & export (file browser and a ZIP of all results and reports), Log |
| **Upload test** (Lab · Link failure) | Section 11A: the set-up, a run form (file, fault point, outage, pacing, timeout, retries), plain-language verdicts, the three-run comparison, progress and path-evidence charts, `ip route get` snapshots, the event log |
| **Problem & solution** | One page that states the problem and the solution, with links to every stage |
| **Presentation** | The slide deck, embedded and downloadable |
| **Guided demo** | The seven-step story with verified statuses (section 12) |

---

## 14. Files the project writes

| Path | Written by | Contents |
|---|---|---|
| `results/diagnostics/history.jsonl` | every live run | one JSON line per run with its analysis |
| `results/diagnostics/baselines.json` | "set baseline" | destination → baseline run id |
| `results/diagnostics/history.csv` | CSV export | one summary row per run |
| `results/simulation/<id>/<run>/` | each NS2 run | see section 9.12 |
| `results/simulation/scenario_comparison.json` / `.csv` | `simulation.experiments` | one comparison row per scenario |
| `results/communication/tcp_vs_udp_<time>.json` | TCP vs UDP experiment | all trials and the generated explanation |
| `results/communication/failure_demo_<time>.json` | the drills | one record per drill |
| `results/certs/` | lab PKI | certificates and private keys (not committed) |
| `results/logs/routeresq.log` | everything | rotating log (2 MB × 3) |
| `reports/healthy.md`, `link_failure_dv.md`, `link_failure_static.md`, `congestion.md` | NS2 | one report per scenario |
| `reports/scenario_comparison.md` | NS2 | the comparison |
| `reports/live_diagnostics.md` | diagnostics CLI | live runs |
| `reports/communication.md` | `communication.report` | TCP/UDP, TLS, drills |
| `reports/root_cause_report.md` | `analysis.cause_report` | the root-cause register |

There is no database: everything is JSON, JSON Lines, CSV, Markdown or raw trace files, so every result can be opened and checked by hand.

---

## 15. Deployment

* **Live app:** https://routeresq.streamlit.app on Streamlit Community Cloud, deployed from `streamlit_app.py` on the `main` branch (Python 3.12, Debian).
* **`packages.txt`** installs `ns2`, `tcl8.6`, `iputils-ping`, `traceroute` and `iproute2` with apt, so the hosted app runs **real NS2 without Docker**.
* **Public mode** is detected automatically there (section 6.1). Live diagnostics on the hosted app measure the **hosting server's** network, not the visitor's.
* **Updates:** pushing to `main` updates the app; the module refresh in `streamlit_app.py` makes the new code take effect without a reboot.
* **Locally on Windows:** install the Python packages, install Docker Desktop and build the NS2 image once:

```bash
pip install -r requirements.txt
docker build -f docker/Dockerfile.ns2 -t routeresq-ns2:2.35 docker
streamlit run streamlit_app.py
```

* **Locally on Linux:** `sudo apt install ns2 traceroute`, then the same `pip install` and `streamlit run`.
* **GitHub Codespaces / dev container:** `.devcontainer/devcontainer.json` installs `packages.txt` and `requirements.txt` and starts the app on port 8501.

---

## 16. Testing

```bash
pytest                                  # everything (186 tests)
pytest -m netlab                        # real upload under link failure (skipped without a backend)
pytest -m "not ns2 and not network"     # offline only
pytest -m ns2                           # real NS2 runs
pytest -m network                       # real ping / traceroute / DNS (loopback and reserved targets only)
pytest -m ui                            # Streamlit AppTest
```

NS2 tests are skipped automatically when NS2 is not available.

| File | Kind | What it checks |
|---|---|---|
| `test_parsers.py` | real captured outputs (Windows 11, Ubuntu 24.04) + edge cases | reachable, DNS failure, timeouts, partial/complete loss, `<1ms`, unreachable replies, truncated/garbage output, traceroute formats |
| `test_rules.py` | mocked measurements | every classification, evidence levels, contradictions, one indicator is not congestion, baseline comparison, route change |
| `test_diagnostics_engine.py` | mocked command runner | the full pipeline, authorisation and injection rejection, allow-listed executables, history and baselines |
| `test_trace_analysis.py` | synthetic traces with known answers | parsing, packet matching, no double counting, every loss fate, delay/throughput/jitter, queue occupancy, route changes, gaps |
| `test_scenarios.py` | unit | scenario validation, including rejecting Tcl injection and invalid links or times |
| `test_ns2_integration.py` | **real NS2** | the script runs, the expected behaviour of all four scenarios, timeline events, comparison, reports |
| `test_communication.py` | **real sockets** | framing with partial reads, TCP/UDP/TLS transfers, integrity, certificate rejection, every drill |
| `test_live_network.py` | **real commands** | loopback health, reserved-name DNS failure, documentation-address unreachability, a refused port |
| `test_walkthrough.py` | demo logic with mocked backends + UI | stage statuses, per-target/per-scenario isolation, retry, unparseable measurements, NS2 unavailable → labelled stored runs, report wording, evidence chains, the register (including re-analysis of stale results), a full demo through the UI |
| `test_streamlit_ui.py` | UI | every page through the real entry point, scenario/phase switching, a real TCP send, the authorisation guard, the demo's transport step |

---

## 17. Running everything: command reference

| Task | Command |
|---|---|
| Start the app | `streamlit run streamlit_app.py` |
| Upload under link failure | `python -m netlab.runner [--file my.bin] [--record --report]` |
| All four NS2 experiments + reports | `python -m simulation.experiments` |
| Selected experiments | `python -m simulation.experiments healthy congestion` |
| Re-analyse stored traces only | `python -m simulation.experiments --reanalyze` |
| Live diagnostics + report | `python -m diagnostics.cli 8.8.8.8 nonexistent.invalid 192.0.2.1 --report reports/live_diagnostics.md` |
| Record a baseline | `python -m diagnostics.cli 8.8.8.8 --set-baseline` |
| Root-cause register | `python -m analysis.cause_report` |
| Transport experiments + report | `python -m communication.report` |
| TCP server and client on two PCs | `python -m communication.tcp_server --host 0.0.0.0 --port 5050` and `python -m communication.tcp_client --host <server-ip> --port 5050 --file data.bin` |
| TLS server and client | add `--tls` to both (copy `results/certs/lab-ca.pem` to the client PC) |
| UDP receiver and sender | `python -m communication.udp receive --host 0.0.0.0 --port 5051` and `python -m communication.udp send --host <ip> --port 5051 --count 1000 --size 1024` |
| Build the report PDF | in `report/`: `xelatex RouteResQ_Mini_Project_Report.tex` (twice) |
| Present the deck | open `presentation/index.html` in a browser (arrows to move, F for fullscreen) |

---

## 18. Design decisions and why they were made

| Decision | Why |
|---|---|
| Rule engine instead of machine learning | There is no labelled data of real network failures to train on, and rules can be audited: every conclusion points to the rule and evidence behind it. |
| Words instead of percentages | No calibrated probability exists for these inferences; a "73 % confident" figure would be invented. |
| Three separate environments | Only in simulation and in the drills is the true cause known. Mixing them would let a simulated cause be read as a live diagnosis. |
| Real NS2, no mock | Results must come from the actual simulator the course uses; the brief forbids mock replacements. |
| Counting packets by NS2's unique id, sent at source and received at destination | Prevents double counting at routers, which would otherwise inflate sent/received numbers. |
| Detecting losses with no `d` line | NS2 2.35 does not trace packets discarded at a router with no usable route; without this, B2's 375 losses would be invisible. |
| Route change needs 3 packets on the new path | One stray packet must not be reported as a routing change. |
| Congestion needs 2 indicators | A single high RTT has many other explanations (distance, a slow hop, a busy server). |
| Commands as argument lists from an allow-list | Prevents shell injection and option injection; the tool cannot run arbitrary programs. |
| Authorised destinations only | Probing networks you do not own can be unlawful; the public app is restricted further. |
| Backend independent of Streamlit | The same code is used by the CLI, the tests and the UI, so the numbers are identical everywhere and the logic is testable. |
| JSON/CSV/Markdown instead of a database | Every result is a file a person (or an examiner) can open and check. |
| Standard TLS library and a labelled lab PKI | Custom cryptography is unsafe and out of scope; the lab CA makes certificate errors reproducible. |
| `page_link` navigation | Buttons with `switch_page` re-ran the whole page being left, which made the top bar feel laggy. |

### How object-oriented design helps (asked in the report format)

* **Encapsulation and composition:** each measurement is a data class, composed into one `DiagnosticRun`; the analysis is one `AnalysisReport` of `Finding`, `Explanation` and `RuleTrace` objects. Evidence travels as one consistent, serialisable object from measurement to report.
* **Abstraction and polymorphism:** the `CommandRunner` protocol hides how commands run; the real `SubprocessRunner` and the tests' fake runner are interchangeable.
* **Inheritance:** domain errors specialise built-in exceptions: `TargetNotAllowed(ValueError)`, `ScenarioError(ValueError)`, `NS2UnavailableError(RuntimeError)`, `NS2ExecutionError(RuntimeError)`, `ConnectionClosed(ConnectionError)`, `ProtocolError(ValueError)`.
* **Validation inside objects:** a `Scenario` validates itself in `__post_init__`; `TCPTransferServer` is a context manager that always releases its socket.
* **Single responsibility:** parsers, rules, scenario execution, trace analysis, socket transfer, PKI and reporting are separate classes and modules, which made 186 targeted tests possible.

---

## 19. Limitations

* **Live diagnostics only see what devices choose to answer.** Routers rate-limit or drop ICMP, firewalls block traceroute, and NAT hides hops, so live causes are at best *Likely*.
* With 4 probes, loss has a 25-point resolution; use more probes for loss studies.
* Windows reports sub-millisecond RTTs as `<1ms`, recorded as 0 ms. Command output is parsed in **English** only.
* **NS2 results describe the configured model**, not a real network. NS2's DV agents learn about a failure immediately and send triggered updates, so rerouting in B1 is almost instant; real protocols with hold-down timers (for example RIP) converge more slowly.
* Both CBR flows use UDP and never back off, so scenario C does not show TCP congestion control.
* Loopback communication has no propagation delay and almost no loss, and throughput depends on the host; use two lab PCs for path effects.
* The upload test network is one Linux kernel with emulated delays; its failover is a pre-installed floating static route, not a routing protocol; a retry re-sends the whole file (no resume from an offset); the hosted app can only show the recorded run.
* The lab PKI is for local demonstration only.
* RouteResQ **explains** recovery; it does not repair live networks.
* **Out of scope by design:** packet capture (Wireshark), intrusion detection, machine learning, automatic repair, custom cryptography, mock NS2.

**Future scope:** larger topologies; link-state routing with configurable convergence timers; two-computer lab experiments; trend analysis of repeated live runs; DNS and MTU drills; controlled bandwidth limits; signed experiment manifests.

---

## 20. Likely viva questions, with answers

**What does RouteResQ do, in one sentence?**
It finds out why a network failed, what the failure did to the traffic and whether service recovered, and it states how certain each answer is, using only evidence.

**Why not just use ping?**
Ping shows a symptom (no reply), not a cause. The same 100 % loss can mean the host is down, the path is broken, or ICMP is filtered. RouteResQ combines DNS, gateway, ping, traceroute and TCP checks so the explanations can be told apart, and it reports contradictions.

**How do you decide the cause of a live failure?**
Seventeen deterministic rules turn the measurements into findings, and the engine lists candidate explanations with evidence for and against. If exactly one explanation fits all the evidence, it is *Likely*; if several fit, the status is *Not confirmed*, and the checks that would separate them are listed.

**Why is a live cause never "Confirmed"?**
Because we did not cause it. Only in NS2 and in the drills do we know the true cause, since we injected it.

**Why no machine learning?**
There is no labelled dataset of real failures to train on, and the brief excludes it. Rules are explainable and auditable: every conclusion has a rule trace.

**Why do B1 and B2 behave so differently for the same failure?**
In B1, distance-vector routing reacts: the routers send triggered updates and n1 switches to the n3 path within 43.6 ms, losing only 2 packets that were already on the failed link. In B2, static routes never change, so n1 keeps sending into the dead link and every packet sent during the 3 s outage is lost, which gives a 3.024 s delivery gap.

**Why is the baseline delay exactly 33.6 ms?**
24 ms of propagation (2 + 10 + 10 + 2) plus 9.6 ms of transmission for an 8000-bit packet (0.8 + 4 + 4 + 0.8), with no queueing.

**How do you know packets were lost in B2 if NS2 wrote no drop lines?**
Each packet is followed by its unique id. These 375 packets arrived at n1 and were never seen again, while the trace shows link n1–n2 was down, so they are classified `lost_at_node`.

**How do you avoid counting a packet several times as it crosses routers?**
A packet is "sent" only at its first enqueue at the source node and "received" only at the destination node; events at routers only extend its path.

**How is congestion proven in scenario C?**
2.5 Mb/s is offered to a 2 Mb/s link; the trace shows the n1→n2 queue at its 20-packet limit and 170 `d` events on a link that was up (queue overflow), 117 of them from the monitored flow; delay rose from 33.6 to 102.75 ms. Recovery is claimed because packets sent after the queue drained had 0 % loss and baseline delay.

**Why does TCP look faster than UDP in your results?**
The test hands TCP 64 KiB frames at a time, while the UDP test sends 1024-byte datagrams one by one, and UDP's figure counts only what reached the receiver. These are loopback numbers on one host. The app itself states that the result depends on the host, datagram size, pacing and buffers, and that neither protocol is faster in general.

**What does the TLS check prove?**
The certificate chains to the trusted lab CA, the certificate's name matches `localhost`, TLS 1.3 with AES-256-GCM was negotiated, and the SHA-256 of the file is equal on both ends, so it arrived unaltered.

**How do you stop the tool being misused to probe other networks?**
Only listed, loopback, private (local only) or reserved test destinations can be probed; input starting with `-` or with shell syntax is rejected; only seven executables can run, never through a shell; and the public deployment refuses private addresses and new destinations.

**What happens in the guided demo if NS2 isn't installed?**
The demo uses the newest stored NS2 runs, marks them `stored`, and the final report says that some NS2 results are stored runs rather than fresh simulations.

**What would you add next?**
Larger topologies, link-state routing with realistic convergence timers, experiments between two real lab PCs, trend analysis of repeated live runs, and DNS/MTU failure drills.

---

## 21. Glossary

| Term | Meaning |
|---|---|
| **CBR** | Constant Bit Rate: an application that sends packets at a fixed rate (here 1 Mb/s, one 1000-byte packet every 8 ms). |
| **DropTail** | A queue that drops new arrivals when it is full. |
| **DV (distance vector)** | A routing protocol where routers exchange distances to destinations with neighbours and pick the lowest-cost path. NS2's `rtProto DV`. |
| **Static routing** | Routes computed once and never updated. |
| **`rtmodel-at`** | The NS2 command that takes a link down or up at a given time. |
| **Trace file** | NS2's log of every packet event (`+`, `-`, `r`, `d`). |
| **Fate** | What finally happened to a packet: delivered, dropped at a queue, dropped on a down link, lost at a node, lost on a link, or in flight. |
| **Phase** | A time window: before (1–3 s), during (3–6 s), after (6–9 s). |
| **Delivery gap** | A period with no arrivals longer than 50 ms while traffic was flowing. |
| **Jitter** | Variation in delay: here, the mean absolute difference between consecutive packets' delays (NS2), or the RTT standard deviation (live). |
| **RTT** | Round-trip time: how long a ping takes to come back. |
| **TTL / hop** | Traceroute sends probes with increasing TTL; each router that answers is one hop. |
| **NXDOMAIN** | The DNS answer "this name does not exist". |
| **RST** | A TCP reset: the receiver refuses or aborts the connection. |
| **SYN / SYN-ACK / ACK** | The TCP three-way handshake. |
| **PKI / CA** | Public Key Infrastructure / Certificate Authority: the trusted issuer of certificates. |
| **SAN** | Subject Alternative Name: the host names or IPs a certificate is valid for. |
| **SHA-256** | A cryptographic hash; equal hashes on both ends mean the data arrived unaltered. |
| **Loopback** | The 127.0.0.1 interface: traffic that never leaves the computer. |
| **RFC 5737 / RFC 6761** | Standards that reserve 192.0.2.0/24 for documentation and `.invalid` as a name that never resolves. |
| **Public mode** | The restricted behaviour of the hosted app (no private addresses, no new destinations). |
| **Rule trace** | The list of every rule, whether it fired and why. |
| **Root-cause register** | The table of every detected failure, its cause and its certainty status. |
