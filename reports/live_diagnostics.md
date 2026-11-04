# RouteResQ live diagnostics report

Generated 2026-11-04T12:40:29+00:00. All values are live measurements from commands executed on this machine.

## Live diagnostics: 8.8.8.8

*Live network measurement - run ded760c92aea, 2026-11-04T12:40:29+00:00, Windows 11, label 'report run'*

**Classification:** Healthy / Reachable

**Conclusion:** 8.8.8.8 is reachable and no problem was detected with the configured thresholds.

### Root cause

**Cause status: No failure detected.** No failure to explain.

### What was observed (confirmed)

- Destination given as IP address 8.8.8.8; no DNS lookup needed.
- Default gateway 192.168.1.1: 4/4 echo replies.
- Ping: 4/4 replies (0.0% loss), RTT min/avg/max 4.0/8.75/23.0 ms, std-dev 8.227 ms.
- Traceroute: 9 hop(s) listed; destination reached; last responding hop is TTL 9 (8.8.8.8), followed by 0 silent hop(s).
- TCP connect to port 53: succeeded in 5.83 ms.

### Traceroute

| TTL | Address | RTTs (ms) |
|---|---|---|
| 1 | 192.168.1.1 | 1, 5, 0 |
| 2 | 10.240.12.49 | 6, 3, 3 |
| 3 | * | *, *, * |
| 4 | 61.246.101.45 | 4, 4, 4 |
| 5 | 116.119.164.57 | 4, 4, 4 |
| 6 | 72.14.217.194 | 5, 4, 4 |
| 7 | 142.251.193.131 | 4, 4, 4 |
| 8 | 142.251.52.199 | 6, 6, 5 |
| 9 | 8.8.8.8 | 5, 5, 4 |

### What can and cannot be concluded

- Can: the observations above, which come directly from command output.
- Cannot: the precise cause, unless an explanation is marked *likely* and its checks are done. ICMP-based tools only show what devices choose to answer.

## Live diagnostics: nonexistent.invalid

*Live network measurement - run 66577883a127, 2026-11-04T12:40:46+00:00, Windows 11, label 'report run'*

**Classification:** DNS Resolution Failure

**Conclusion:** The name nonexistent.invalid could not be resolved, so no connection was attempted. The local network appears to work (gateway reachable), which points to a naming/DNS problem. The exact cause is not confirmed.

### Root cause

**Cause status: Likely.** The name does not exist in DNS or is misspelt (NXDOMAIN / host not found)

Rated likely because it is the only explanation consistent with all collected evidence.

Evidence:

- resolver returned 'host not found' ([11001] getaddrinfo failed)
- default gateway 192.168.1.1 answered ping

Checks needed to confirm: Check the spelling of the name; Query another resolver, e.g. 'nslookup <name> 1.1.1.1'.

### What was observed (confirmed)

- DNS lookup for nonexistent.invalid failed (nxdomain: [11001] getaddrinfo failed).
- Default gateway 192.168.1.1: 4/4 echo replies.
- TCP connect to port 53: failed (dns).

### Findings

| Rule | Level | Category | Finding | Evidence |
|---|---|---|---|---|
| R-DNS-01 | confirmed | DNS Resolution Failure | Destination name could not be resolved | resolver error: [11001] getaddrinfo failed |

### Possible root causes

**The name does not exist in DNS or is misspelt (NXDOMAIN / host not found)** (likely)

- Supporting evidence: resolver returned 'host not found' ([11001] getaddrinfo failed); default gateway 192.168.1.1 answered ping
- Checks to confirm: Check the spelling of the name; Query another resolver, e.g. 'nslookup <name> 1.1.1.1'
- Recommended actions: Correct the host name; Ask the domain owner whether the record exists

### What can and cannot be concluded

- Can: the observations above, which come directly from command output.
- Cannot: the precise cause, unless an explanation is marked *likely* and its checks are done. ICMP-based tools only show what devices choose to answer.

## Live diagnostics: 192.0.2.1

*Live network measurement - run 0faf716a4bb5, 2026-11-04T12:40:49+00:00, Windows 11, label 'report run'*

**Classification:** Unreachable Destination, Packet Loss, Possible Routing Issue

**Conclusion:** 192.0.2.1 could not be reached using the available diagnostic methods. No device reported an explicit error, so the precise cause is not confirmed.

### Root cause

**Cause status: Not confirmed.** Not determined - possible causes: The destination host is down or offline; A downstream part of the path (beyond the last responding hop) is inaccessible; ICMP / traceroute probes are filtered by a firewall.

Several explanations fit the evidence equally well; the checks listed would separate them.

Evidence:

- default gateway 192.168.1.1 answered ping
- traceroute: last responding hop is TTL 2 (10.240.12.49), followed by 8 silent hop(s)

Other possible causes: The destination host is down or offline; A downstream part of the path (beyond the last responding hop) is inaccessible; ICMP / traceroute probes are filtered by a firewall.

Checks needed to confirm: Try a TCP connection to a known service port; Ask the host owner whether it is running; Re-run traceroute later and compare the last responding hop; Traceroute to a different host behind the same network; Test reachability with TCP to a port the host is expected to serve.

### What was observed (confirmed)

- Destination given as IP address 192.0.2.1; no DNS lookup needed.
- Default gateway 192.168.1.1: 4/4 echo replies.
- Ping: 0/4 replies (100.0% loss).
- Traceroute: 10 hop(s) listed; destination NOT reached; last responding hop is TTL 2 (10.240.12.49), followed by 8 silent hop(s).
- TCP connect to port 53: failed (timeout).

### Findings

| Rule | Level | Category | Finding | Evidence |
|---|---|---|---|---|
| R-REACH-01 | confirmed | Unreachable Destination | Destination did not answer any ping (complete loss) | 4 echo requests, 0 replies; 4 request(s) timed out |
| R-TCP-01 | confirmed | Unreachable Destination | Connection timeout on TCP port 53 | no response within 3.0s (timed out) |
| R-LOSS-02 | confirmed | Packet Loss | Complete packet loss | 4/4 probes lost |
| R-ROUTE-01 | possible | Possible Routing Issue | Path stops responding before the destination | last responding hop is TTL 2 (10.240.12.49), followed by 8 silent hop(s) |

### Possible root causes

**The destination host is down or offline** (possible)

- Supporting evidence: default gateway 192.168.1.1 answered ping; traceroute: last responding hop is TTL 2 (10.240.12.49), followed by 8 silent hop(s)
- Checks to confirm: Try a TCP connection to a known service port; Ask the host owner whether it is running
- Recommended actions: Wait and re-run the diagnostics

**A downstream part of the path (beyond the last responding hop) is inaccessible** (possible)

- Supporting evidence: default gateway 192.168.1.1 answered ping; traceroute: last responding hop is TTL 2 (10.240.12.49), followed by 8 silent hop(s)
- Checks to confirm: Re-run traceroute later and compare the last responding hop; Traceroute to a different host behind the same network
- Recommended actions: Report the last responding hop to the network operator

**ICMP / traceroute probes are filtered by a firewall** (possible)

- Supporting evidence: default gateway 192.168.1.1 answered ping; traceroute: last responding hop is TTL 2 (10.240.12.49), followed by 8 silent hop(s); TCP connect timed out as well
- Checks to confirm: Test reachability with TCP to a port the host is expected to serve
- Recommended actions: Use a TCP-based check where ICMP is blocked

### Traceroute

| TTL | Address | RTTs (ms) |
|---|---|---|
| 1 | 192.168.1.1 | 1, 1, 1 |
| 2 | 10.240.12.49 | 27, 19, 28 |
| 3 | * | *, *, * |
| 4 | * | *, *, * |
| 5 | * | *, *, * |
| 6 | * | *, *, * |
| 7 | * | *, *, * |
| 8 | * | *, *, * |
| 9 | * | *, *, * |
| 10 | * | *, *, * |

### What can and cannot be concluded

- Can: the observations above, which come directly from command output.
- Cannot: the precise cause, unless an explanation is marked *likely* and its checks are done. ICMP-based tools only show what devices choose to answer.
