# NS2 scenario comparison

*All values come from real NS2 traces of the four configured scenarios.*

| Scenario | Routing | Sent | Delivered | Loss % | Avg delay ms | Max delay ms | Throughput kb/s | During-phase kb/s | Route changes | Longest gap s | Max queue | Recovery |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | DV | 1001 | 1001 | 0.00 | 33.60 | 33.60 | 996.81 | 1000.00 | 0 | 0.00 | 1 | not applicable |
| B1 | DV | 1001 | 999 | 0.20 | 37.36 | 43.60 | 994.82 | 992.00 | 2 | 0.00 | 1 | rerouted - delivery continued over an alternative path |
| B2 | Static | 1001 | 624 | 37.66 | 33.60 | 33.60 | 621.39 | 5.33 | 0 | 3.02 | 1 | interrupted - delivery resumed only after the link was restored |
| C | DV | 1001 | 884 | 11.69 | 54.55 | 109.65 | 880.30 | 682.67 | 0 | 0.00 | 20 | recovered - delay and loss returned to baseline once the queue drained |
