# NS2 scenario comparison

*All values come from real NS2 traces of the four configured scenarios.*

| Scenario | Routing | Sent | Delivered | Loss % | Avg delay ms | Max delay ms | Throughput kb/s | During-phase kb/s | Route changes | Longest gap s | Max queue | Recovery |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | DV | 1001 | 1001 | 0.00 | 33.60 | 33.60 | 996.81 | 1000.00 | 0 | 0.00 | 1 | not applicable |
| B1 | DV | 1001 | 999 | 0.20 | 37.36 | 43.60 | 994.82 | 992.00 | 2 | 0.00 | 1 | rerouted - delivery continued over an alternative path |
| B2 | Static | 1001 | 624 | 37.66 | 33.60 | 33.60 | 621.39 | 5.33 | 0 | 3.02 | 1 | interrupted - delivery resumed only after the link was restored |
| C | DV | 1001 | 884 | 11.69 | 54.55 | 109.65 | 880.30 | 682.67 | 0 | 0.00 | 20 | recovered - delay and loss returned to baseline once the queue drained |

## Root cause of each scenario

The cause of every NS2 failure is known because it was injected; the mechanism is what the trace shows.

| Scenario | Cause status | Root cause | How it affected traffic |
|---|---|---|---|
| A healthy | No failure (control) | No fault is introduced. All links stay up for the whole simulation. | With all links up and an offered load of 1 Mb/s on 2 Mb/s core links, every packet followed the lowest-cost path. No packets were lost. These numbers are the baseline for the other scenarios. |
| B1 link_failure_dv | Confirmed (injected) | Link n1-n2 was deliberately disabled with `$ns rtmodel-at 3.0 down $n1 $n2` and re-enabled at t = 6.0 s. This is the experimental condition. | Link 1-2 failed at t=3 s. When link 1-2 went down, NS2's distance-vector agents at the adjacent routers were notified and sent triggered updates; node 1 already had a route via the alternative path, so forwarding switched almost immediately. Only packets that were already queued on or in transit over the failed link were lost. Average delay changed from 33.60 ms before the failure to 43.60 ms during it because the alternative path is longer. |
| B2 link_failure_static | Confirmed (injected) | Link n1-n2 was deliberately disabled with `$ns rtmodel-at 3.0 down $n1 $n2` and re-enabled at t = 6.0 s. Static routing is the second controlled condition. | Link 1-2 failed at t=3 s. With static routing the forwarding table still pointed at link 1-2, so node 1 received the packets but could not forward them. NS2 discarded them without writing 'd' events; their loss was detected because they were never seen again after arriving at node 1. Delivery resumed only when the link came back. No packet sent during the failure was delivered, so no delay can be measured for that phase. |
| C congestion | Confirmed (injected) | Competing traffic (flow 2, 1.5 Mb/s) was deliberately injected between t = 3.0 s and t = 6.0 s. Offered load on link n1-n2 is 2.5 Mb/s against 2 Mb/s capacity. | Between t=3s and t=6s the core link 1->2 was offered more traffic than it can carry, so its DropTail queue filled. Queueing added delay, and once the queue was full new arrivals were dropped. Packet loss was caused by queue overflow at the bottleneck (confirmed by d events). |
