# Scenario C - congestion from competing traffic

*Simulated condition (NS2 2.35+dfsg-3.1, backend: docker, run C:\Users\Aditya\AppData\Local\Claude-Data\claude_pzs8sxrjxfjjc\scratch-workspaces\cd6a4156-9f3b-47f6-9837-f1cc0711a291\bd2a9cd6-7d84-4284-b93a-7971c0f98a00\scratch-2026-11-04-50bf27\results\simulation\congestion\20261104-164425). These are simulation results, not live-network measurements.*

The monitored 1 Mb/s flow (fid 1) runs as in the baseline. From t = 3.0 s to t = 6.0 s a competing 1.5 Mb/s CBR flow (fid 2) is added on the same path, so 2.5 Mb/s is offered to the 2 Mb/s core link n1-n2.

## What failed?

No component failed. Offered load exceeded the capacity of the core link, degrading service between t=3s and t=6s.

## Why did it fail?

Competing traffic (flow 2, 1.5 Mb/s) was deliberately injected between t = 3.0 s and t = 6.0 s. Offered load on link n1-n2 is 2.5 Mb/s against 2 Mb/s capacity.

## What happened next?

- Offered load on the core path during t=3-6s: 2.50 Mb/s vs 2.00 Mb/s capacity (125% utilisation demand).
- Queue at link 1->2 peaked at 20 packets (limit 20) at t=3.301s.
- Monitored flow average delay: 33.60 ms before -> 102.75 ms during -> 35.24 ms after.
- Monitored flow throughput: 984.0 kb/s before -> 682.7 kb/s during -> 1005.3 kb/s after.
- Congestion loss confirmed: 170 queue-overflow drops ('d' events on an up link) - flow 1: 117, flow 2: 53.

**Routing behaviour:** No route change was observed (NS2 DV routing is not load-aware).

## How did performance change? (monitored flow 1)

| Phase | Window (s) | Sent | Delivered | Loss % | Avg delay (ms) | Max delay (ms) | Jitter (ms) | Throughput (kb/s) |
|---|---|---|---|---|---|---|---|---|
| before | 1.00-3.00 | 250 | 250 | 0.00 | 33.60 | 33.60 | 0.000 | 984.0 |
| during | 3.00-6.00 | 375 | 259 | 30.93 | 102.75 | 109.65 | 0.326 | 682.7 |
| after | 6.00-9.00 | 375 | 374 | 0.27 | 35.24 | 101.65 | 0.182 | 1005.3 |

Loss and delay are assigned to a phase by **send time**; throughput by **receive time**.

## Was recovery observed?

**recovered - delay and loss returned to baseline once the queue drained**

- Bottleneck queue drained to 0 at t=6.1428s (0.1428 s after competing traffic stopped).
- After-phase loss 0.27%, delay 35.24 ms (before-phase delay 33.60 ms).
- Packets sent after the queue drained (t=6.143-9s): 357 sent, 0.00% loss, 33.60 ms average delay.
- 1 monitored packet(s) sent just after t=6s were still dropped by the full queue before it drained (transient).

## Timeline

| t (s) | Source | Event | Description |
|---|---|---|---|
| 0.0000 | configured | SIM_START | Simulation starts (routing=DV). |
| 1.0000 | configured | TRAFFIC_START | Monitored CBR traffic starts (flow 1, n0 -> n5). |
| 1.0336 | trace | FIRST_DELIVERY | First monitored packet delivered (seq 0, path 0-1-2-4-5, delay 33.6 ms). |
| 3.0000 | configured | CROSS_TRAFFIC_START | Configured load increase: competing flow 2 starts. |
| 3.3015 | trace | QUEUE_FULL | Queue of link 1->2 reaches its limit (20 packets). |
| 4.1468 | trace | FIRST_LOSS | First monitored packet lost (seq 393): d event at queue of link 1->2 at t=4.1468s (link up -> DropTail overflow). |
| 4.1468 | trace | FIRST_QUEUE_DROP | First queue-overflow drop of a monitored packet at link 1->2. |
| 6.0000 | configured | CROSS_TRAFFIC_STOP | Competing flow 2 stops. |
| 6.0028 | trace | LAST_QUEUE_DROP | Last queue-overflow drop of a monitored packet (117 in total). |
| 6.1428 | trace | QUEUE_DRAINED | Queue of link 1->2 has drained to 0 after the competing flow stopped. |
| 9.0000 | configured | TRAFFIC_STOP | Monitored CBR traffic stops. |
| 9.0336 | trace | LAST_DELIVERY | Last monitored packet delivered (seq 1000). |
| 10.0000 | configured | SIM_END | Simulation ends. |

## Technical explanation

Between t=3s and t=6s the core link 1->2 was offered more traffic than it can carry, so its DropTail queue filled. Queueing added delay, and once the queue was full new arrivals were dropped. Packet loss was caused by queue overflow at the bottleneck (confirmed by d events).

## What can and cannot be concluded

- Can: Queue build-up, delay increase and drop counts at the bottleneck (from the trace).
- Cannot: How a TCP flow would react (both flows are CBR/UDP and do not back off).
- Cannot: NS2 results describe this configured model, not any real network.

Trace quality: 17839 lines, 0 malformed.
