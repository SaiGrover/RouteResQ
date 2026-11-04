# Scenario B2 - link n1-n2 failure, static routing

*Simulated condition (NS2 2.35+dfsg-3.1, backend: docker, run C:\Users\Aditya\AppData\Local\Claude-Data\claude_pzs8sxrjxfjjc\scratch-workspaces\cd6a4156-9f3b-47f6-9837-f1cc0711a291\bd2a9cd6-7d84-4284-b93a-7971c0f98a00\scratch-2026-11-04-50bf27\results\simulation\link_failure_static\20261104-164425). These are simulation results, not live-network measurements.*

Identical failure to B1 (link n1-n2 down from t = 3.0 s to t = 6.0 s), but routes are computed once at start-up (rtProto Static). This shows what happens when routing does not react to the failure.

## What failed?

Link n1-n2 failed at t=3 s. Confirmed by the trace: link-down event at t=3 s.

## Why did it fail?

Link n1-n2 was deliberately disabled with `$ns rtmodel-at 3.0 down $n1 $n2` and re-enabled at t = 6.0 s. Static routing is the second controlled condition.

## What happened next?

- 377 monitored packet(s) were lost from the failure until t=6s (dropped_link_down: 2, lost_at_node: 375).
- Of 375 packets sent while the link was down, 0 were delivered.
- Delivery gap at the destination from t=3.010s to t=6.034s (3.024 s).

**Routing behaviour:** No route change was observed for delivered packets after the failure. Static routing computes routes once; no routing-protocol messages exist in this run.

## How did performance change? (monitored flow 1)

| Phase | Window (s) | Sent | Delivered | Loss % | Avg delay (ms) | Max delay (ms) | Jitter (ms) | Throughput (kb/s) |
|---|---|---|---|---|---|---|---|---|
| before | 1.00-3.00 | 250 | 248 | 0.80 | 33.60 | 33.60 | 0.000 | 984.0 |
| during | 3.00-6.00 | 375 | 0 | 100.00 | n/a | n/a | n/a | 5.3 |
| after | 6.00-9.00 | 375 | 375 | 0.00 | 33.60 | 33.60 | 0.000 | 989.3 |

Loss and delay are assigned to a phase by **send time**; throughput by **receive time**.

## Was recovery observed?

**interrupted - delivery resumed only after the link was restored**

- No packet sent during the failure was delivered; first delivery after restoration at t=6.0336s (0.0336 s after link-up, 3.034 s after the failure).
- After-phase throughput is 100.5% of the before-phase value with 0.00% loss and 33.60 ms average delay.
- Trace records link 1-2 up again at t=6s.

## Timeline

| t (s) | Source | Event | Description |
|---|---|---|---|
| 0.0000 | configured | SIM_START | Simulation starts (routing=Static). |
| 1.0000 | configured | TRAFFIC_START | Monitored CBR traffic starts (flow 1, n0 -> n5). |
| 1.0336 | trace | FIRST_DELIVERY | First monitored packet delivered (seq 0, path 0-1-2-4-5, delay 33.6 ms). |
| 3.0000 | configured | LINK_DOWN | Configured failure: link 1-2 is taken down (rtmodel-at down). |
| 3.0000 | trace | LINK_DOWN_TRACED | Trace records link 1-2 down (NS2 'v link-down' event). |
| 3.0000 | trace | FIRST_LOSS_AFTER_FAILURE | First monitored packet lost after the failure (seq 248): d event on link 1->2 at t=3.0000s while link 1-2 was down. |
| 3.0096 | trace | DELIVERY_GAP_START | Delivery gap begins: no packets reach n5 for 3.024 s. |
| 6.0000 | configured | LINK_UP | Configured restoration: link 1-2 is brought back up (rtmodel-at up). |
| 6.0000 | trace | LINK_UP_TRACED | Trace records link 1-2 up (NS2 'v link-up' event). |
| 6.0000 | trace | LOSS_TOTAL_DURING_FAILURE | 377 monitored packet(s) were lost between the failure and t=6.00s. |
| 6.0336 | trace | DELIVERY_RESUMED | Delivery resumes at the destination after a 3.024 s gap. |
| 9.0000 | configured | TRAFFIC_STOP | Monitored CBR traffic stops. |
| 9.0336 | trace | LAST_DELIVERY | Last monitored packet delivered (seq 1000). |
| 10.0000 | configured | SIM_END | Simulation ends. |

## Technical explanation

Link 1-2 failed at t=3 s. With static routing the forwarding table still pointed at link 1-2, so node 1 received the packets but could not forward them. NS2 discarded them without writing 'd' events; their loss was detected because they were never seen again after arriving at node 1. Delivery resumed only when the link came back. No packet sent during the failure was delivered, so no delay can be measured for that phase.

## What can and cannot be concluded

- Can: Which packets were lost and where (from the trace).
- Can: Whether and when the forwarding path changed (from per-packet paths).
- Cannot: Results describe NS2's model of DV/static routing on this topology; real routing protocols (e.g. RIP with hold-down timers) can converge much more slowly.
- Cannot: NS2 2.35 does not write 'd' events for some of these losses; their location is inferred from the last traced event of each packet.

Trace quality: 8633 lines, 0 malformed.
