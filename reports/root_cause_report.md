# RouteResQ root-cause report

*Generated 2026-11-19T18:02:28+00:00 from stored results. Live rows are measurements from the machine running RouteResQ; NS2 rows are simulations whose cause was injected; transport rows are drills on the loopback interface.*

## Cause status

- **Confirmed (injected)** - the cause was introduced on purpose in a controlled experiment and its effect is visible in the evidence.
- **Likely** - live network: one explanation is consistent with all collected evidence.
- **Not confirmed** - live network: several explanations fit; the next checks would separate them.

## Summary

| Source | Subject | Failure | Cause status | Root cause |
|---|---|---|---|---|
| Live diagnostics | nonexistent.invalid | DNS Resolution Failure | **Likely** | The name does not exist in DNS or is misspelt (NXDOMAIN / host not found) |
| Live diagnostics | 192.0.2.1 | Unreachable Destination, Packet Loss, Possible Routing Issue | **Not confirmed** | Not determined - possible causes: The destination host is down or offline; A downstream part of the path (beyond the last responding hop) is inaccessible; ICMP / traceroute probes are filtered by a firewall. |
| Live diagnostics | 8.8.8.8 | none | **No failure detected** | No failure to explain. |
| NS2 simulation | B1 link_failure_dv | link failure - n1-n2 | **Confirmed (injected)** | Link n1-n2 was deliberately disabled with `$ns rtmodel-at 3.0 down $n1 $n2` and re-enabled at t = 6.0 s. This is the experimental condition. |
| NS2 simulation | B2 link_failure_static | link failure - n1-n2 | **Confirmed (injected)** | Link n1-n2 was deliberately disabled with `$ns rtmodel-at 3.0 down $n1 $n2` and re-enabled at t = 6.0 s. Static routing is the second controlled condition. |
| NS2 simulation | C congestion | congestion (increased traffic load) - n1-n2 | **Confirmed (injected)** | Competing traffic (flow 2, 1.5 Mb/s) was deliberately injected between t = 3.0 s and t = 6.0 s. Offered load on link n1-n2 is 2.5 Mb/s against 2 Mb/s capacity. |
| NS2 simulation | A healthy | none (control) | **No failure detected** | No fault introduced. |
| Transport drill | Connection timeout | timeout | **Confirmed (injected)** | Server accepts the TCP connection but never replies; client read timeout 1.5s |
| Transport drill | Interrupted TCP transfer | reset | **Confirmed (injected)** | Server resets the connection (RST) after receiving about 300000 of 2000000 bytes |
| Transport drill | Invalid TLS certificate (host name mismatch) | tls_certificate | **Confirmed (injected)** | Server presents a lab-CA certificate issued for 'wrong-host.example' while the client connects to 'localhost' |
| Transport drill | Invalid TLS certificate (untrusted issuer) | tls_certificate | **Confirmed (injected)** | Server presents a certificate signed by a CA the client does not trust |
| Transport drill | Missing UDP datagrams | missing_datagrams | **Confirmed (injected)** | Sender deliberately skipped sequence numbers [50, 51, 52, 53, 54, 120, 199] (injected loss) |
| Transport drill | Server unavailable | refused | **Confirmed (injected)** | No process listening on 127.0.0.1:60931 |
| Upload under link failure | Link failure · backup route (recorded run) | Continued on the backup path (same TCP connection) | **Confirmed (injected)** | Primary link taken down after 30% of the upload had reached the server, for 3 s; a backup route was installed. |
| Upload under link failure | Link failure · static forwarding (recorded run) | Stalled until the link returned, then resumed (same TCP connection) | **Confirmed (injected)** | Primary link taken down after 30% of the upload had reached the server, for 3 s; no route to the backup path. |
| Upload under link failure | Healthy baseline (recorded run) | none (control) | **No failure detected** | No fault introduced. |

13 failure(s) explained out of 16 subject(s).

## Details

### Live diagnostics: nonexistent.invalid

- **Failure:** DNS Resolution Failure
- **Root cause (Likely):** The name does not exist in DNS or is misspelt (NXDOMAIN / host not found)
- **How it caused the failure:** Rated likely because it is the only explanation consistent with all collected evidence.
- **Evidence:**
  - resolver returned 'host not found' ([11001] getaddrinfo failed)
  - default gateway 192.168.1.1 answered ping
- **Checks needed to confirm:** Check the spelling of the name; Query another resolver, e.g. 'nslookup <name> 1.1.1.1'
- **Outcome:** The name nonexistent.invalid could not be resolved, so no connection was attempted. The local network appears to work (gateway reachable), which points to a naming/DNS problem. The exact cause is not confirmed.

### Live diagnostics: 192.0.2.1

- **Failure:** Unreachable Destination, Packet Loss, Possible Routing Issue
- **Root cause (Not confirmed):** Not determined - possible causes: The destination host is down or offline; A downstream part of the path (beyond the last responding hop) is inaccessible; ICMP / traceroute probes are filtered by a firewall.
- **How it caused the failure:** Several explanations fit the evidence equally well; the checks listed would separate them.
- **Evidence:**
  - default gateway 192.168.1.1 answered ping
  - traceroute: last responding hop is TTL 2 (10.240.12.49), followed by 6 silent hop(s)
- **Other possible causes:** The destination host is down or offline; A downstream part of the path (beyond the last responding hop) is inaccessible; ICMP / traceroute probes are filtered by a firewall
- **Checks needed to confirm:** Try a TCP connection to a known service port; Ask the host owner whether it is running; Re-run traceroute later and compare the last responding hop; Traceroute to a different host behind the same network; Test reachability with TCP to a port the host is expected to serve
- **Outcome:** 192.0.2.1 could not be reached using the available diagnostic methods. No device reported an explicit error, so the precise cause is not confirmed.

### NS2 simulation: B1 link_failure_dv

- **Failure:** link failure - n1-n2
- **Root cause (Confirmed (injected)):** Link n1-n2 was deliberately disabled with `$ns rtmodel-at 3.0 down $n1 $n2` and re-enabled at t = 6.0 s. This is the experimental condition.
- **How it caused the failure:** Link 1-2 failed at t=3 s. When link 1-2 went down, NS2's distance-vector agents at the adjacent routers were notified and sent triggered updates; node 1 already had a route via the alternative path, so forwarding switched almost immediately. Only packets that were already queued on or in transit over the failed link were lost. Average delay changed from 33.60 ms before the failure to 43.60 ms during it because the alternative path is longer.
- **Evidence:**
  - Link n1-n2 failed at t=3 s. Confirmed by the trace: link-down event at t=3 s.
  - 2 monitored packet(s) were lost from the failure until t=6s (dropped_link_down: 2).
  - Of 375 packets sent while the link was down, 375 were delivered.
  - No delivery gap longer than the detection threshold was observed at the destination.
  - Recovery: rerouted - delivery continued over an alternative path
- **Outcome:** rerouted - delivery continued over an alternative path

### NS2 simulation: B2 link_failure_static

- **Failure:** link failure - n1-n2
- **Root cause (Confirmed (injected)):** Link n1-n2 was deliberately disabled with `$ns rtmodel-at 3.0 down $n1 $n2` and re-enabled at t = 6.0 s. Static routing is the second controlled condition.
- **How it caused the failure:** Link 1-2 failed at t=3 s. With static routing the forwarding table still pointed at link 1-2, so node 1 received the packets but could not forward them. NS2 discarded them without writing 'd' events; their loss was detected because they were never seen again after arriving at node 1. Delivery resumed only when the link came back. No packet sent during the failure was delivered, so no delay can be measured for that phase.
- **Evidence:**
  - Link n1-n2 failed at t=3 s. Confirmed by the trace: link-down event at t=3 s.
  - 377 monitored packet(s) were lost from the failure until t=6s (dropped_link_down: 2, lost_at_node: 375).
  - Of 375 packets sent while the link was down, 0 were delivered.
  - Delivery gap at the destination from t=3.010s to t=6.034s (3.024 s).
  - Recovery: interrupted - delivery resumed only after the link was restored
- **Outcome:** interrupted - delivery resumed only after the link was restored

### NS2 simulation: C congestion

- **Failure:** congestion (increased traffic load) - n1-n2
- **Root cause (Confirmed (injected)):** Competing traffic (flow 2, 1.5 Mb/s) was deliberately injected between t = 3.0 s and t = 6.0 s. Offered load on link n1-n2 is 2.5 Mb/s against 2 Mb/s capacity.
- **How it caused the failure:** Between t=3s and t=6s the core link 1->2 was offered more traffic than it can carry, so its DropTail queue filled. Queueing added delay, and once the queue was full new arrivals were dropped. Packet loss was caused by queue overflow at the bottleneck (confirmed by d events).
- **Evidence:**
  - No component failed. Offered load exceeded the capacity of the core link, degrading service between t=3s and t=6s.
  - Offered load on the core path during t=3-6s: 2.50 Mb/s vs 2.00 Mb/s capacity (125% utilisation demand).
  - Queue at link 1->2 peaked at 20 packets (limit 20) at t=3.301s.
  - Monitored flow average delay: 33.60 ms before -> 102.75 ms during -> 35.24 ms after.
  - Recovery: recovered - delay and loss returned to baseline once the queue drained
- **Outcome:** recovered - delay and loss returned to baseline once the queue drained

### Transport drill: Connection timeout

- **Failure:** timeout
- **Root cause (Confirmed (injected)):** Server accepts the TCP connection but never replies; client read timeout 1.5s
- **How it caused the failure:** TCP connected (14.911 ms) but no reply arrived within 1.5s, so the client gave up. A timeout alone cannot tell a slow server from a dead one.
- **Evidence:**
  - Observed error: TimeoutError: timed out
- **Outcome:** Replaced the silent server with a responsive one -> communication resumed

### Transport drill: Interrupted TCP transfer

- **Failure:** reset
- **Root cause (Confirmed (injected)):** Server resets the connection (RST) after receiving about 300000 of 2000000 bytes
- **How it caused the failure:** The transfer stopped: the client had written 720896 bytes when the error was raised and got no acknowledgement, so it cannot know how much the server kept.
- **Evidence:**
  - Observed error: ConnectionResetError: [WinError 10054] An existing connection was forcibly closed by the remote host
- **Outcome:** Restarted a normal server and re-sent the whole file (no partial resume) -> communication resumed

### Transport drill: Invalid TLS certificate (host name mismatch)

- **Failure:** tls_certificate
- **Root cause (Confirmed (injected)):** Server presents a lab-CA certificate issued for 'wrong-host.example' while the client connects to 'localhost'
- **How it caused the failure:** The client aborted the TLS handshake, so no application data was sent. This is the intended protection against impersonation.
- **Evidence:**
  - Observed error: SSLCertVerificationError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: Hostname mismatch, certificate is not valid for 'localhost'. (_ssl.c:1032)
- **Outcome:** Server switched to the valid lab certificate for 'localhost' -> communication resumed

### Transport drill: Invalid TLS certificate (untrusted issuer)

- **Failure:** tls_certificate
- **Root cause (Confirmed (injected)):** Server presents a certificate signed by a CA the client does not trust
- **How it caused the failure:** The client aborted the TLS handshake, so no application data was sent. This is the intended protection against impersonation.
- **Evidence:**
  - Observed error: SSLCertVerificationError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate (_ssl.c:1032)
- **Outcome:** Server switched to the valid lab certificate for 'localhost' -> communication resumed

### Transport drill: Missing UDP datagrams

- **Failure:** missing_datagrams
- **Root cause (Confirmed (injected)):** Sender deliberately skipped sequence numbers [50, 51, 52, 53, 54, 120, 199] (injected loss)
- **How it caused the failure:** 193/200 datagrams arrived. UDP did not notice or recover the loss; only the sequence numbers revealed it.
- **Evidence:**
  - Observed error: receiver detected missing seq 50-54, 120, 199; idle timeout after 1.0s
- **Outcome:** Sent the run again without skipping -> communication resumed

### Transport drill: Server unavailable

- **Failure:** refused
- **Root cause (Confirmed (injected)):** No process listening on 127.0.0.1:60931
- **How it caused the failure:** The connection was refused after 2.04 s: the OS answered the SYN with a TCP RST (Windows retries a refused SYN for about 2 s before reporting it). No data was sent.
- **Evidence:**
  - Observed error: ConnectionRefusedError: [WinError 10061] No connection could be made because the target machine actively refused it
- **Outcome:** Started the server on port 60931 -> communication resumed

### Upload under link failure: Link failure · backup route (recorded run)

- **Failure:** Continued on the backup path (same TCP connection)
- **Root cause (Confirmed (injected)):** Primary link taken down after 30% of the upload had reached the server, for 3 s; a backup route was installed.
- **How it caused the failure:** The primary link went down after the server had received 30% of the file (0.60 MiB). The server stopped receiving bytes for 0.07 s. The same TCP connection then continued on the backup path (1.43 MiB left through the client's backup interface during the outage), and the file matched (SHA-256).
- **Evidence:**
  - Stall 0.07 s
  - Backup interface carried 1,496,468 bytes
  - 1 TCP connection(s)
  - SHA-256 match
- **Outcome:** Continued on the backup path (same TCP connection)

### Upload under link failure: Link failure · static forwarding (recorded run)

- **Failure:** Stalled until the link returned, then resumed (same TCP connection)
- **Root cause (Confirmed (injected)):** Primary link taken down after 30% of the upload had reached the server, for 3 s; no route to the backup path.
- **How it caused the failure:** The primary link went down after the server had received 30% of the file (0.60 MiB). The server stopped receiving bytes for 3.29 s. No upload traffic used the backup path, because forwarding had no route to it. The same TCP connection resumed 0.29 s after the link came back, and the file matched (SHA-256).
- **Evidence:**
  - Stall 3.29 s
  - Backup interface carried 250 bytes
  - 1 TCP connection(s)
  - SHA-256 match
- **Outcome:** Stalled until the link returned, then resumed (same TCP connection)

## Limits

- A live cause marked *Not confirmed* is reported as such: ICMP-based tools only see what devices answer, so the engine never guesses between equally supported explanations.
- NS2 causes are certain because they were configured; the mechanism is read from the simulator's trace.
