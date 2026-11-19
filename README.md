# RouteResQ

**Network failure detection, root-cause analysis and recovery observation.** A Computer Networks lab project (24B15CS313, JIIT Noida).

RouteResQ answers four questions about a network problem, using evidence only:

1. **What failed?** Connectivity, DNS, latency, loss, routing or congestion symptoms.
2. **Why did it fail?** The causes the evidence supports, kept separate from what is only possible.
3. **What happened next?** Interruption, packet drops, route changes and recovery.
4. **How did performance change?** Throughput, delay and loss before, during and after the failure.

The workflow is **Detect → Diagnose → Analyse impact → Observe recovery → Report**.

| Component | Environment | What it does |
|---|---|---|
| Network diagnostics & failure analysis | **Live network** | Real `ping`, `tracert`/`traceroute`, DNS and TCP checks. A deterministic rule engine turns the evidence into findings and possible root causes. |
| NS2 failure simulation & recovery analysis | **NS2 simulation** | A real NS2 2.35 run of a 6-node wired topology: healthy baseline, link failure (DV and static routing) and congestion. A Python parser analyses the trace. |
| TCP/UDP communication & secure transfer | **Real sockets** (loopback or two lab PCs) | TCP and UDP client/server, a TCP vs UDP experiment, a TLS-encrypted transfer with SHA-256 integrity checks, and controlled failure demonstrations. |

Simulated results and live measurements are always labelled and kept apart. A failure seen on the live network is never assumed to have the same cause as a simulated one.

---

## 1. Architecture

```
streamlit_app.py            UI entry point: brand bar + workflow rail (the navigation), then the page
app_pages/                  overview, detect, diagnose, impact (NS2), recovery, transport, report, demo
ui/                         presentation only - theme.py (design tokens + stylesheet), components.py
                            (tiles, cards, evidence ladder, timeline, method flow), charts.py (one Plotly
                            chart system), shell.py (brand bar, workflow rail), data.py (cached readers)

diagnostics/                live measurements
  commands.py               allow-listed subprocess runner, OS-specific command builders
  parsers.py                ping / tracert / traceroute / tracepath / route / DNS-config parsers
  engine.py                 DNS lookup, gateway check, ping, traceroute, TCP connect, network inspection
  authorization.py          destination validation and allow-list (config/authorized_targets.json)
  history.py                JSON-lines history, baselines, run-to-run comparison
  cli.py                    command-line front end
failure_analysis/
  rules.py                  rule-based root-cause engine (no ML), thresholds, rule trace
  report.py                 Markdown report for a diagnostic run
simulation/
  tcl/routeresq.tcl         the NS2 topology and experiment script (parametrised)
  scenarios/*.json          scenario A, B1, B2, C definitions
  scenario.py               scenario loading and strict parameter validation
  runner.py                 runs NS2 (local `ns` or the Docker image)
  trace_parser.py           NS2 wired-trace and event-log parser
  experiments.py            simulate -> parse -> analyse -> save -> report (CLI)
analysis/
  packets.py                per-packet reconstruction and fate classification
  metrics.py                loss, delay, jitter, throughput, phases, time series, queue occupancy
  routing.py                paths, route changes, delivery gaps, routing-protocol traffic
  timeline.py               configured and observed failure timeline
  experiment.py             answers what / why / what next / how / recovery for one run
  comparison.py, report.py  scenario comparison and Markdown reports
communication/
  framing.py                length-prefixed framing (handles partial reads)
  tcp_server.py, tcp_client.py   message + file transfer, timing, error classification (also TLS)
  udp.py                    sequenced datagrams, loss / reorder / duplicate / timeout detection
  experiments.py            TCP vs UDP experiment
  failures.py               controlled failure demonstrations
  report.py                 runs everything and writes reports/communication.md
security/
  certs.py                  lab PKI (CA, valid server cert, untrusted cert, wrong-host cert)
  tls.py                    TLS server/client contexts and the secure-transfer demo
  integrity.py              SHA-256 helpers
config/                     authorised destinations, rule thresholds
results/                    generated JSON / CSV / trace files (simulation runs are kept in git)
reports/                    generated Markdown experiment reports
tests/                      pytest suite (+ real captured command outputs in tests/fixtures)
docker/Dockerfile.ns2       NS2 2.35 image for Windows/macOS
```

The networking logic does not depend on Streamlit. Every module can be used from Python or from its command line.

## 2. Installation

Requires Python 3.11 or newer (developed and tested on 3.13).

```bash
pip install -r requirements.txt
```

### NS2

RouteResQ runs the **real** NS2 simulator. It uses an `ns` binary on `PATH` if there is one; otherwise it uses Docker.

**Linux (verified on Ubuntu 22.04; the `ns2` package is in the universe repository):**

```bash
sudo apt install ns2
```

**Windows / macOS, or Linux without an `ns2` package:** install Docker Desktop, then build the image once. It is Ubuntu 22.04 with the distribution's `ns2 2.35+dfsg-3.1` package:

```bash
docker build -f docker/Dockerfile.ns2 -t routeresq-ns2:2.35 docker
```

The Overview page shows which back end was detected. The test suite skips NS2 tests when neither is available.

### Diagnostic tools

* **Windows:** `ping`, `tracert`, `route` and `ipconfig` are built in.
* **Linux:** `ping` (iputils), `ip` (iproute2) and `traceroute` (`sudo apt install traceroute`). If `traceroute` is missing, `tracepath` is used instead.

## 3. The interface

RouteResQ is laid out as a network-operations console with a locked graphite dark theme. The workflow is the navigation: a rail of connected nodes sits under the brand bar:

**Overview → 01 Detect → 02 Diagnose → 03 Analyse impact → 04 Observe recovery** · **Lab: TCP/UDP/TLS** · **05 Report**

Each node shows a live headline read from stored results, for example "DV reroute in 43.6 ms" or "6/6 failures recovered". The current stage is lit in its own accent colour. A **Guided demo** button in the brand bar starts the walkthrough.

The design adapts the strongest patterns of the team's Data Vortex Round 4 dashboard to network analysis:

* **Same structure on every page:** a KPI tile strip, then charts in one card shape, then a *Method* section. The method section is a step flowchart beside an artefact panel whose file sizes are read from disk on each page load.
* **Interpretation under every chart:** each chart has an *Interpretation* note saying what it shows and why it matters.
* **One semantic palette.** Each colour has a single meaning everywhere:

  | Colour | Meaning |
  |---|---|
  | cyan | live measurement, TCP |
  | amber | latency, congestion, UDP |
  | clay | failure, loss |
  | green | healthy, recovered |
  | blue | rerouting |
  | sand | simulation, alternative path |

  Each NS2 scenario also keeps a fixed colour on every chart.
* **Background artwork:** `static/bg.webp` is a network-topology image showing a failed link and its reroute. It is served by Streamlit's static file serving and fixed behind a dark overlay that deepens down the page; cards stay opaque, so text never sits on the texture.
* **One type scale:** Space Grotesk (headings, values), Inter (text) and JetBrains Mono (addresses, timings).
* **Clear source labels:** every page is labelled *Live measurement*, *NS2 simulation* or *Real sockets – loopback*.

| Page | Highlights |
|---|---|
| Overview | KPIs across all modules, throughput of every scenario on one chart, recovery verdicts, recent live checks |
| Diagnostics | run form, per-probe RTT chart with thresholds, per-hop traceroute chart, hop table, network configuration, raw output, history trend, run-to-run comparison, baselines |
| Root cause | reasoning ladder (symptoms → measurements → explanations → evidence limits), candidate causes with evidence for and against plus next checks, findings with evidence levels, rule map and full rule trace, re-analysis against any earlier run |
| NS2 simulation | interactive topology showing the paths delivered packets actually took in each phase (from the trace), scenario configuration, throughput / delay / packet-fate / queue / DV-message charts, downloads |
| Failure & recovery | recovery verdict, the five questions answered, before/during/after topology triptych, timeline of configured and observed events, phase comparison, cross-scenario comparison |
| Upload test (Lab · Link failure) | real TCP upload across an isolated test network while the primary link fails: three-run comparison, receiver-progress charts with link down/up markers, interface-counter path evidence, `ip route get` snapshots, event log, plain-language verdicts |
| Problem & solution · Presentation | top-bar links: a one-page summary of the problem and the solution, and the slide deck embedded in the app (downloadable as one HTML file) |
| TCP · UDP · TLS | connection-state chain built only from stages the client actually completed, TCP vs UDP charts, TLS handshake / certificate / SHA-256 details, failure drills (fault → error → restore → resumed) |
| Reports | generated reports, full experiment history, file browser with ZIP export, log viewer |
| Guided demo | one failure story in seven steps, each running the real backend: detect (choose the destinations), diagnose (evidence chain: symptom → measurement → explanation → limitations → next check), analyse impact (choose the NS2 experiments), observe recovery (baseline vs the chosen failure), transport, upload under link failure (the recorded run, labelled *stored*, where no test-network backend exists), report. Every step shows its own **verified status** (verified / partial / failed / stored data / not run) and is clickable; each stage is error-guarded with a retry, keeps its successful parts, and verifies its own output (parsed measurements, a valid NS2 trace, TLS integrity, every drill detected and recovered). If NS2 fails or is missing, stored runs are used **and labelled as stored**, and the report never claims fresh results. |

Charts are Plotly and built only from backend results; nothing is drawn from made-up data.

## 4. Running

```bash
streamlit run streamlit_app.py
```

| Task | Command |
|---|---|
| All four NS2 experiments + reports | `python -m simulation.experiments` |
| Selected experiments | `python -m simulation.experiments healthy congestion` |
| Re-analyse stored traces only | `python -m simulation.experiments --reanalyze` |
| Live diagnostics + report | `python -m diagnostics.cli 8.8.8.8 nonexistent.invalid 192.0.2.1 --report reports/live_diagnostics.md` |
| Record a baseline | `python -m diagnostics.cli 8.8.8.8 --set-baseline` |
| Communication experiments + report | `python -m communication.report` |
| Upload under link failure (three runs) | `python -m netlab.runner` (needs Linux root or the `routeresq-netlab:1` Docker image) |
| TCP server / client (two lab PCs) | `python -m communication.tcp_server --host 0.0.0.0 --port 5050` and `python -m communication.tcp_client --host <server-ip> --port 5050 --file data.bin` |
| TLS server / client | add `--tls` to both (the client trusts `results/certs/lab-ca.pem`, so copy it to the client PC) |
| UDP receiver / sender | `python -m communication.udp receive --host 0.0.0.0 --port 5051` and `python -m communication.udp send --host <ip> --port 5051 --count 1000 --size 1024` |

### Hosted deployment (Streamlit Community Cloud)

Deploy `streamlit_app.py` from this repository. [packages.txt](packages.txt) installs Debian's `ns2`, `tcl8.6`, `iputils-ping`, `traceroute` and `iproute2`, so the hosted app runs real NS2 (no Docker needed).

On a hosted deployment (detected from the `/mount/src` path, or forced with `ROUTERESQ_PUBLIC=1`) RouteResQ runs in **public mode**:

* only the listed destinations and loopback can be probed (private address ranges would be the host's internal network);
* visitors cannot add destinations.

Live diagnostics there measure the *hosting server's* network, not the visitor's. The full test suite has been run in a container that mirrors this setup (Debian bookworm, Python 3.12, non-root user).

### Authorised destinations

Active probes (ping, traceroute, TCP connect) are only sent to destinations in [config/authorized_targets.json](config/authorized_targets.json), to loopback, and to private (RFC 1918) addresses. Two reserved targets are included for demonstrations:

* `nonexistent.invalid` can never resolve (RFC 6761), so it shows a DNS failure.
* `192.0.2.1` is a documentation address with no host (RFC 5737), so it shows a timeout or unreachable destination.

Add a destination only if you are allowed to test it. The Diagnostics page asks you to confirm this. Targets are validated, so option injection such as `-n …` or shell syntax is rejected, and commands are never run through a shell.

## 5. Module 1: diagnostics and root-cause analysis

### Measurements

| Step | Windows | Linux |
|---|---|---|
| Network configuration | `route print -4`, `ipconfig /all` | `ip route`, `/etc/resolv.conf` |
| DNS | `socket.getaddrinfo` (error kind: not-found / temporary / no-data) | same |
| Gateway reachability | `ping -n N -w ms <gateway>` | `ping -c N -W s <gateway>` |
| Destination RTT and loss | `ping -n N -w ms <ip>` | `ping -c N -W s -i 0.5 <ip>` |
| Path | `tracert -d -h H -w ms <ip>` | `traceroute -n -m H -w s -q 3 <ip>` (or `tracepath`) |
| Connection timeout / refusal | `socket.create_connection` to an optional TCP port | same |

Packet counts are computed from the individual echo-reply lines and cross-checked against the tool's own summary. Windows counts *"Destination host unreachable"* replies as "Received"; RouteResQ does not, and records a parser note when the two disagree.

### Classification

Each run gets one or more of: *Healthy / Reachable*, *DNS Resolution Failure*, *Unreachable Destination*, *High Latency*, *Packet Loss*, *Possible Routing Issue*, *Possible Congestion*, *Inconclusive / Insufficient Evidence*.

### Evidence levels

There are no confidence percentages. Every statement has exactly one of these levels:

* **confirmed**: directly observed in command output (an observation, not a cause)
* **likely**: the explanation most consistent with all the evidence
* **possible**: consistent with the evidence, but alternatives cannot be ruled out
* **insufficient_evidence**: the data cannot support a conclusion (for example, too few RTT samples)

### Rules ([failure_analysis/rules.py](failure_analysis/rules.py))

Thresholds are in [config/thresholds.json](config/thresholds.json).

| Rule | Condition | Produces |
|---|---|---|
| R-DNS-01 | name lookup fails | DNS Resolution Failure (confirmed); causes depend on the error kind and gateway reachability |
| R-PING-00 | ping output missing or unparseable | Inconclusive |
| R-REACH-01 | 0 echo replies and no TCP/traceroute contradiction | Unreachable Destination (confirmed) |
| R-REACH-02 | OS or a router reports *unreachable* / *no route* (`!H`, `!N`, …) | Unreachable; "no route at a router" is *likely* |
| R-TCP-01 | TCP connect times out | Connection timeout (confirmed) |
| R-LOSS-01 / 02 | partial loss ≥ threshold / 100 % loss | Packet Loss |
| R-LAT-01 | mean RTT > threshold with ≥ `min_rtt_samples` samples | High Latency; fewer samples gives *insufficient_evidence* |
| R-LAT-02 | RTT standard deviation > threshold | High Latency (jitter) |
| R-BASE-01..04 | RTT, loss, jitter or throughput clearly worse than the recorded baseline | baseline-relative findings |
| R-CONG-01 | **two or more** congestion indicators together | Possible Congestion. A single high-latency reading is never classified as congestion. |
| R-ROUTE-01 | traceroute stops before the destination **and** ping fails | Possible Routing Issue |
| R-ROUTE-02 | responding hop sequence differs from the previous run | route change (confirmed) |
| R-OK-01 | name resolves and the host answers | Healthy / Reachable |

**Contradictory evidence** is reported, not hidden. Examples:

* Ping fails but TCP connects: ICMP is probably filtered, and the host counts as reachable.
* Ping works but traceroute stops: probes are being filtered or NAT is in the way. This is *not* treated as a routing failure.
* The gateway ignores ping but the destination answers.

Every rule is listed in a **rule trace** with the reason it fired or did not.

Example from a real run against `192.0.2.1` (see [reports/live_diagnostics.md](reports/live_diagnostics.md)):

* The gateway answered 4/4 pings.
* Ping to the destination got 0/4 replies.
* Traceroute's last responding hop was TTL 2, followed by silent hops.
* A TCP connect timed out.

Possible explanations: the destination is down, a downstream path is inaccessible, or ICMP is filtered. Conclusion: *"192.0.2.1 could not be reached using the available diagnostic methods. No device reported an explicit error, so the precise cause is not confirmed."*

### Root-cause report

The main question RouteResQ answers is *why* a failure happened. [analysis/cause_report.py](analysis/cause_report.py) builds a **root-cause register**: one row per detected failure, across live diagnostics, NS2 experiments and transport drills. Each row gives the failure, its root cause, how certain that cause is, the evidence, other possible causes and the checks needed to confirm. Live runs are re-analysed with the current rules, so the register never shows a verdict from an older rule set.

| Cause status | Meaning |
|---|---|
| **Confirmed (injected)** | the cause was introduced on purpose (NS2 scenario or transport drill) and its effect is visible in the trace or error |
| **Likely** | live network: one explanation is consistent with all the evidence (for example NXDOMAIN → the name does not exist) |
| **Not confirmed** | live network: several explanations fit equally, so they are listed with the checks that would separate them |
| **No failure detected** | nothing to explain |

```bash
python -m analysis.cause_report          # writes reports/root_cause_report.md
```

The register is also shown on the Overview, as the default view of the Reports page, and in the guided demo's report. Every individual report has a *Root cause* section:
* each NS2 scenario report, giving the cause and how it produced the failure, as read from the trace;
* the scenario comparison;
* each live diagnostic run;
* the communication drills.

### History and baselines

Every run is appended to `results/diagnostics/history.jsonl`. You can mark any healthy run as the **baseline** for its destination (`baselines.json`). Later runs are judged against the baseline (factor + absolute margin) as well as the fixed thresholds. The UI and `compare_runs()` compare two runs: status, RTT, loss and traceroute path changes. History can be exported to CSV.

## 6. Module 2: NS2 simulation

### Topology ([simulation/tcl/routeresq.tcl](simulation/tcl/routeresq.tcl))

```
                 n2
      (primary) /  \ (primary)
   n0 ---- n1          n4 ---- n5
  source        \  /         destination
                 n3   (alternative path, cost 3 per link)
```

| Link | Bandwidth | Delay | Queue | Routing cost |
|---|---|---|---|---|
| n0–n1, n4–n5 (access) | 10 Mb/s | 2 ms | DropTail, 20 pkts | 1 |
| n1–n2, n2–n4 (primary core) | 2 Mb/s | 10 ms | DropTail, 20 pkts | 1 |
| n1–n3, n3–n4 (alternative) | 2 Mb/s | 15 ms | DropTail, 20 pkts | 3 |

* **Traffic:** monitored flow 1 is CBR over UDP, n0→n5, 1 Mb/s, 1000-byte packets, 1.0–9.0 s (1001 packets). The simulation stops at 10 s.
* **Routing:** `DV` (NS2 distance-vector, `rtProto DV`, advert interval 2 s) or `Static`.
* **Failures:** injected with `$ns rtmodel-at <t> down|up $n1 $n2`.

### Scenarios ([simulation/scenarios/](simulation/scenarios/))

| | Scenario | Injected condition (known cause) |
|---|---|---|
| A | healthy | none (baseline) |
| B1 | link_failure_dv | link n1–n2 down 3.0–6.0 s, DV routing |
| B2 | link_failure_static | same failure, static routing |
| C | congestion | competing 1.5 Mb/s CBR flow 2 from 3.0 to 6.0 s (2.5 Mb/s offered to a 2 Mb/s link) |

Phase windows are the same in every scenario: **before 1–3 s, during 3–6 s, after 6–9 s**. In scenario A they are reference windows only, since nothing happens at 3 s.

### Trace analysis and metric definitions

[analysis/packets.py](analysis/packets.py) rebuilds each data packet from its NS2 unique id (last trace column). The counting rules avoid double counting at routers:

* **Sent:** the packet's first `+` event at its *source* node. Forwarding `+` events at routers are ignored.
* **Received:** an `r` event at the *destination* node. `r` events at routers only extend the packet's path.
* **End-to-end delay:** receive time − send time of the same packet id. This includes queueing, transmission and propagation.
* **Packet loss %:** lost ÷ (sent − in-flight) × 100.
* **Jitter:** mean absolute difference between delays of consecutively sent packets (a simplified form of RFC 3550).
* **Throughput:** bits received at the destination in a window ÷ window length. For a whole flow the window is [first send, last receive].
* **Phase assignment:** loss and delay go to a phase by **send time**; throughput goes by **receive time**.
* **Queue occupancy:** rebuilt per link from `+`, `-` and `d` events. A `d` for a packet already being transmitted does not reduce the queue.
* **Route changes:** detected when consecutively sent, delivered packets switch path and the new path holds for at least 3 packets.
* **Delivery gaps (interruptions):** periods with no arrivals longer than max(5 × packet interval, 50 ms).
* **Recovery:**
  * Link failure: *rerouted* if packets sent during the failure arrived over a path that avoids the failed link. *Interrupted until restored* if delivery resumed only after link-up.
  * Congestion: *recovered* if packets sent after the bottleneck queue drained show 0 % loss and delay within 10 % of the before phase.

**Each lost packet gets one fate:**

* `dropped_queue`: a `d` event on a link that was up (DropTail overflow).
* `dropped_link_down`: a `d` event on a failed link.
* `lost_at_node` / `lost_on_link`: there is **no** `d` event. NS2 2.35 silently discards packets that reach a router whose only route uses a down link (this happens in scenario B2). RouteResQ finds these losses because the packet is never seen again, and gives its last traced location.

### Reference results (real NS2 2.35 runs, deterministic)

From [reports/scenario_comparison.md](reports/scenario_comparison.md). The per-scenario reports are in [reports/](reports/), and the raw traces and CSV/JSON are in `results/simulation/<scenario>/<run>/`.

| Scenario | Delivered | Loss % | Avg delay ms | During-phase throughput kb/s | Route changes | Longest gap | Outcome |
|---|---|---|---|---|---|---|---|
| A healthy | 1001/1001 | 0.00 | 33.60 | 1000.0 | 0 | none | baseline |
| B1 link failure, DV | 999/1001 | 0.20 | 37.36 | 992.0 | 2 (to n1-n3-n4 at 3.0 s, back at 6.008 s) | none | rerouted; first packet over the alternative path 43.6 ms after the failure; 2 packets lost (they were on the failed link) |
| B2 link failure, static | 624/1001 | 37.66 | 33.60 | 5.3 | 0 | 3.024 s | interrupted until the link was restored; 375 packets silently discarded at n1 |
| C congestion | 884/1001 | 11.69 | 54.55 | 682.7 | 0 | none | queue n1→n2 reached 20/20; 170 overflow drops (117 of flow 1); recovered 0.14 s after the load stopped |

The 33.6 ms baseline delay can be checked by hand: propagation is 2 + 10 + 10 + 2 ms, and transmission is 0.8 + 4 + 4 + 0.8 ms for a 1000-byte packet.

## 7. Module 3: TCP, UDP and TLS

### TCP

* **Framing:** 1-byte type + 4-byte length + payload. `recv_exact()` loops until the whole frame has arrived, so partial reads are handled.
* **Operations:** message echo with acknowledgement; file transfer in 64 KiB chunks with a SHA-256 check on the server.
* **Measurements:** connection set-up time, transfer time and throughput.
* **Errors** are classified as refused, timeout, reset, closed-by-peer, TLS certificate, TLS other, protocol, DNS or unreachable.

### UDP

* **Datagram header:** sequence number, run id, total count and send timestamp.
* **The receiver reports:** missing sequence numbers (as ranges), duplicates, out-of-order arrivals, loss %, throughput, and an idle-timeout flag.
* **No reliability layer is added:** UDP loss is measured, never repaired.

### TCP vs UDP

The same amount of data is sent over both protocols on loopback. The explanation is generated from the measured numbers and never claims one protocol is always faster.

### TLS

* Python's `ssl` module, TLS 1.2 minimum.
* The client requires a certificate chain to the RouteResQ lab CA **and** a matching host name.
* Messages and files go through the same framed protocol, with SHA-256 checked end to end.
* Certificates are generated with the `cryptography` package. No custom cryptography is used.

### Failure demonstrations

| Failure | How it is created | Observed by the client |
|---|---|---|
| Server unavailable | no listener on the port | `ConnectionRefusedError` (Windows retries ~2 s first) |
| Connection timeout | server accepts but never replies | read timeout |
| Interrupted transfer | server sends RST after ~300 kB of 2 MB | `ConnectionResetError` |
| Missing UDP datagrams | sender skips chosen sequence numbers (**injected**) | exact missing ranges + idle timeout |
| Invalid TLS certificate | untrusted issuer / wrong host name | `SSLCertVerificationError` |
| (optional) SYN timeout | connect to 192.0.2.1:80 | connect timeout |

Each demonstration then restores the condition and records whether communication resumed. See [reports/communication.md](reports/communication.md).

## 7A. File upload under link failure (isolated test network)

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

## 8. Testing

```bash
pytest                                  # everything (186 tests)
pytest -m "not ns2 and not network"     # mocked / offline only
pytest -m ns2                           # real NS2 runs
pytest -m network                       # real ping/traceroute/DNS (loopback + RFC-reserved targets only)
pytest -m ui                            # Streamlit AppTest smoke tests
pytest -m netlab                        # real upload under link failure (skipped without a backend)
```

| File | Kind | Covers |
|---|---|---|
| `test_parsers.py` | unit, **real captured outputs** (Windows 11, Ubuntu 24.04) + synthetic edge cases | reachable, DNS failure, timeouts, partial/complete loss, `<1ms`, unreachable replies, truncated/garbage output, traceroute formats |
| `test_rules.py` | unit, **mocked measurements** | every classification, evidence levels, contradictions, single-indicator ≠ congestion, baseline comparison, route change |
| `test_diagnostics_engine.py` | unit, mocked command runner | full pipeline, authorisation and injection rejection, allow-listed executables, history/baseline |
| `test_trace_analysis.py` | unit, synthetic traces with known answers | parsing, packet matching, no double counting, every loss fate, delay/throughput/jitter, queue occupancy, route changes, gaps |
| `test_scenarios.py` | unit | scenario validation (rejects Tcl injection and invalid links/times) |
| `test_ns2_integration.py` | **real NS2** | script execution, the expected behaviour of all four scenarios, timeline events, comparison, reports |
| `test_communication.py` | **real sockets** | framing with partial reads, TCP/UDP/TLS transfers, integrity, certificate rejection, every failure demonstration |
| `test_live_network.py` | **real commands** | loopback health, reserved-name DNS failure, documentation-address unreachability, refused port |
| `test_walkthrough.py` | demo logic with **mocked** backends + UI | stage statuses, per-target/per-scenario error isolation, retry, unparseable measurements, NS2 unavailable → labelled stored runs, fresh-run failure fallback, report wording, evidence chains, root-cause register (including re-analysis of stale results), full demo and reset through the UI |
| `test_streamlit_ui.py` | UI | every page and view through the real entry point, scenario/phase switching, real TCP send, authorisation guard, the guided demo's transport step |

## 9. Methodology notes and limitations

* **Live diagnostics only show what devices choose to answer.** Routers rate-limit or drop ICMP, firewalls block traceroute probes, and NAT (including Docker's) hides hops. RouteResQ therefore reports causes as *possible* unless the evidence singles one out. With only 4 probes, loss has 25-point resolution, so use more probes for loss studies.
* **Windows** reports sub-millisecond RTTs as `<1ms`, which RouteResQ records as 0 ms. Command output is parsed in English; other OS languages are not supported.
* **NS2 results describe the configured model**, not a real network.
  * NS2's DV agents learn about a link failure immediately and send triggered updates, so rerouting in B1 is almost instant. Real protocols with hold-down timers converge more slowly.
  * Both CBR flows use UDP and do not back off, so scenario C does not show TCP congestion control.
* **Communication experiments on loopback** have no propagation delay and almost no loss. Throughput depends on the host, so use two lab PCs for path effects.
* **The lab PKI is for local demonstration only.** Its private keys are generated into `results/certs/` and are not committed.

## 10. Scope

Included: the three components above, integrated in Streamlit.

Deliberately **not** included, as the project brief requires:

* Wireshark or packet capture
* intrusion detection
* machine learning
* automatic repair of real networks
* custom cryptography
* mock replacements for NS2
