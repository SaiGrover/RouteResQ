# Scenario B1 - link n1-n2 failure, distance-vector routing

*Simulated condition (NS2 2.35+dfsg-3.1, backend: docker, run C:\Users\Aditya\AppData\Local\Claude-Data\claude_pzs8sxrjxfjjc\scratch-workspaces\cd6a4156-9f3b-47f6-9837-f1cc0711a291\bd2a9cd6-7d84-4284-b93a-7971c0f98a00\scratch-2026-11-04-50bf27\results\simulation\link_failure_dv\20261104-164424). These are simulation results, not live-network measurements.*

Same traffic as the baseline. Link n1-n2 on the primary path is taken down at t = 3.0 s and restored at t = 6.0 s. Nodes run NS2's distance-vector routing (rtProto DV), which reacts to link-state changes.

## What failed?

Link n1-n2 failed at t=3 s. Confirmed by the trace: link-down event at t=3 s.

## Root cause

**Cause status: Confirmed - the cause was injected deliberately in this experiment.**

- **Cause:** Link n1-n2 was deliberately disabled with `$ns rtmodel-at 3.0 down $n1 $n2` and re-enabled at t = 6.0 s. This is the experimental condition.
- **How it caused the failure (from the trace):** Link 1-2 failed at t=3 s. When link 1-2 went down, NS2's distance-vector agents at the adjacent routers were notified and sent triggered updates; node 1 already had a route via the alternative path, so forwarding switched almost immediately. Only packets that were already queued on or in transit over the failed link were lost. Average delay changed from 33.60 ms before the failure to 43.60 ms during it because the alternative path is longer.

## What happened next?

- 2 monitored packet(s) were lost from the failure until t=6s (dropped_link_down: 2).
- Of 375 packets sent while the link was down, 375 were delivered.
- No delivery gap longer than the detection threshold was observed at the destination.

**Routing behaviour:** Route changed at t=3.0000s from 0-1-2-4-5 to 0-1-3-4-5. During the failure, packets were delivered over 0-1-3-4-5, which avoids link 1-2. After restoration, route changed at t=6.0080s from 0-1-3-4-5 to 0-1-2-4-5. 14 distance-vector update(s) were originated in the 0.5 s after the failure (vs. 2.4 per 0.5 s on average before it).

## How did performance change? (monitored flow 1)

| Phase | Window (s) | Sent | Delivered | Loss % | Avg delay (ms) | Max delay (ms) | Jitter (ms) | Throughput (kb/s) |
|---|---|---|---|---|---|---|---|---|
| before | 1.00-3.00 | 250 | 248 | 0.80 | 33.60 | 33.60 | 0.000 | 984.0 |
| during | 3.00-6.00 | 375 | 375 | 0.00 | 43.60 | 43.60 | 0.000 | 992.0 |
| after | 6.00-9.00 | 375 | 375 | 0.00 | 33.63 | 43.60 | 0.027 | 1002.7 |

Loss and delay are assigned to a phase by **send time**; throughput by **receive time**.

## Was recovery observed?

**rerouted - delivery continued over an alternative path**

- First packet delivered via 0-1-3-4-5 arrived at t=3.0436s (43.6 ms after the failure).
- After-phase throughput is 101.9% of the before-phase value with 0.00% loss and 33.63 ms average delay.
- Trace records link 1-2 up again at t=6s.

## Timeline

| t (s) | Source | Event | Description |
|---|---|---|---|
| 0.0000 | configured | SIM_START | Simulation starts (routing=DV). |
| 1.0000 | configured | TRAFFIC_START | Monitored CBR traffic starts (flow 1, n0 -> n5). |
| 1.0336 | trace | FIRST_DELIVERY | First monitored packet delivered (seq 0, path 0-1-2-4-5, delay 33.6 ms). |
| 3.0000 | configured | LINK_DOWN | Configured failure: link 1-2 is taken down (rtmodel-at down). |
| 3.0000 | trace | LINK_DOWN_TRACED | Trace records link 1-2 down (NS2 'v link-down' event). |
| 3.0000 | trace | FIRST_LOSS_AFTER_FAILURE | First monitored packet lost after the failure (seq 248): d event on link 1->2 at t=3.0000s while link 1-2 was down. |
| 3.0000 | trace | ROUTING_UPDATES | 14 distance-vector routing message(s) were originated in the 0.5 s after the failure. |
| 3.0000 | trace | ROUTE_CHANGE | Delivered packets switch from path 0-1-2-4-5 to 0-1-3-4-5 (first packet on new path: seq 250). |
| 6.0000 | configured | LINK_UP | Configured restoration: link 1-2 is brought back up (rtmodel-at up). |
| 6.0000 | trace | LINK_UP_TRACED | Trace records link 1-2 up (NS2 'v link-up' event). |
| 6.0000 | trace | LOSS_TOTAL_DURING_FAILURE | 2 monitored packet(s) were lost between the failure and t=6.00s. |
| 6.0080 | trace | ROUTE_CHANGE | Delivered packets switch from path 0-1-3-4-5 to 0-1-2-4-5 (first packet on new path: seq 626). |
| 9.0000 | configured | TRAFFIC_STOP | Monitored CBR traffic stops. |
| 9.0336 | trace | LAST_DELIVERY | Last monitored packet delivered (seq 1000). |
| 10.0000 | configured | SIM_END | Simulation ends. |

## What can and cannot be concluded

- Can: Which packets were lost and where (from the trace).
- Can: Whether and when the forwarding path changed (from per-packet paths).
- Cannot: Results describe NS2's model of DV/static routing on this topology; real routing protocols (e.g. RIP with hold-down timers) can converge much more slowly.

Trace quality: 12365 lines, 0 malformed.
