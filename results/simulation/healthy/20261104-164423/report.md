# Scenario A - healthy network (baseline)

*Simulated condition (NS2 2.35+dfsg-3.1, backend: docker, run C:\Users\Aditya\AppData\Local\Claude-Data\claude_pzs8sxrjxfjjc\scratch-workspaces\cd6a4156-9f3b-47f6-9837-f1cc0711a291\bd2a9cd6-7d84-4284-b93a-7971c0f98a00\scratch-2026-11-04-50bf27\results\simulation\healthy\20261104-164423). These are simulation results, not live-network measurements.*

All six links are up. A single 1 Mb/s CBR/UDP flow runs from n0 to n5 over the primary path n0-n1-n2-n4-n5. This run is the baseline for every comparison.

## What failed?

Nothing. No fault was introduced; this is the control experiment.

## Why did it fail?

No fault is introduced. All links stay up for the whole simulation.

## What happened next?

- 1001 packets sent, 1001 delivered, 0 lost (0.00% loss).
- Average end-to-end delay 33.60 ms, throughput 996.8 kb/s.
- Delivered packets used path(s): 0-1-2-4-5.

**Routing behaviour:** Only path 0-1-2-4-5 was used.

## How did performance change? (monitored flow 1)

| Phase | Window (s) | Sent | Delivered | Loss % | Avg delay (ms) | Max delay (ms) | Jitter (ms) | Throughput (kb/s) |
|---|---|---|---|---|---|---|---|---|
| before | 1.00-3.00 | 250 | 250 | 0.00 | 33.60 | 33.60 | 0.000 | 984.0 |
| during | 3.00-6.00 | 375 | 375 | 0.00 | 33.60 | 33.60 | 0.000 | 1000.0 |
| after | 6.00-9.00 | 375 | 375 | 0.00 | 33.60 | 33.60 | 0.000 | 1000.0 |

*There is no event in this scenario. The same three windows are used as reference windows so the results line up with scenarios B and C.*

Loss and delay are assigned to a phase by **send time**; throughput by **receive time**.

## Was recovery observed?

**not applicable**


## Timeline

| t (s) | Source | Event | Description |
|---|---|---|---|
| 0.0000 | configured | SIM_START | Simulation starts (routing=DV). |
| 1.0000 | configured | TRAFFIC_START | Monitored CBR traffic starts (flow 1, n0 -> n5). |
| 1.0336 | trace | FIRST_DELIVERY | First monitored packet delivered (seq 0, path 0-1-2-4-5, delay 33.6 ms). |
| 9.0000 | configured | TRAFFIC_STOP | Monitored CBR traffic stops. |
| 9.0336 | trace | LAST_DELIVERY | Last monitored packet delivered (seq 1000). |
| 10.0000 | configured | SIM_END | Simulation ends. |

## Technical explanation

With all links up and an offered load of 1 Mb/s on 2 Mb/s core links, every packet followed the lowest-cost path. No packets were lost. These numbers are the baseline for the other scenarios.

## What can and cannot be concluded

- Can: Baseline throughput, delay and loss of the configured model.
- Cannot: NS2 results describe this configured model, not any real network.

Trace quality: 12273 lines, 0 malformed.
