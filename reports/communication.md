# RouteResQ communication experiments

*Generated 2026-11-04T11:12:25+00:00. Real sockets on the loopback interface (127.0.0.1); failures are injected locally and labelled as such.*

## TCP vs UDP

Parameters: {'total_bytes': 1000000, 'datagram_payload': 1024, 'trials': 3, 'udp_rate_pps': None, 'udp_rcvbuf': None}

| Protocol | Trial | Setup (ms) | Delivered % | Duration (s) | Throughput (Mb/s) | Integrity | Missing |
|---|---|---|---|---|---|---|---|
| TCP | 1 | 3.762 | 100.0 | 0.001813 | 4412.576 | True | - |
| TCP | 2 | 0.284 | 100.0 | 0.001997 | 4006.009 | True | - |
| TCP | 3 | 13.807 | 100.0 | 0.001635 | 4892.966 | True | - |
| UDP | 1 | 0.0 | 100.0 | 0.00856 | 956.892 | None | none |
| UDP | 2 | 0.0 | 100.0 | 0.008708 | 940.623 | None | none |
| UDP | 3 | 0.0 | 100.0 | 0.008874 | 923.009 | None | none |

**Interpretation (generated from the measurements):**

- TCP spent 5.951 ms on average establishing a connection (SYN, SYN-ACK, ACK) before any data; UDP sends its first datagram immediately because it is connectionless.
- Every TCP trial delivered 100% of the bytes, and the SHA-256 check matched: TCP retransmits lost segments and delivers bytes in order.
- All UDP datagrams arrived in these trials. UDP does not guarantee this; on a congested or lossy path (or with a small receive buffer) datagrams would be lost without notice.
- Measured throughput: TCP 4437.2 Mb/s (until acknowledged) vs UDP 940.2 Mb/s (at the receiver). TCP was faster in this run, but this depends on datagram size, pacing, buffers and the host. Neither protocol is faster in general, and UDP's figure counts only what arrived.

## TLS secure transfer

- TLS version / cipher: TLSv1.3 / TLS_AES_256_GCM_SHA384 (256 bits)
- Server certificate: organizationName=RouteResQ Lab, commonName=localhost issued by organizationName=RouteResQ Lab, commonName=RouteResQ Lab CA
- File: 262144 bytes, client SHA-256 `91dd6fb150521a9145d901debb70dd23a8d6d6a95efb568b31be0b788f1e0022`
- Server SHA-256 `91dd6fb150521a9145d901debb70dd23a8d6d6a95efb568b31be0b788f1e0022` -> integrity verified: True

  1. TCP connection established in 0.203 ms (3-way handshake)
  2. TLS handshake completed in 1.025 ms (TLSv1.3, TLS_AES_256_GCM_SHA384)
  3. Server certificate validated against the trusted CA and host name
  4. Sent 262144 bytes in 4 chunk frame(s)
  5. Server acknowledged 262144 bytes; SHA-256 matches

## Communication failure demonstrations

| Failure | Observed error | Resumed after restore |
|---|---|---|
| Server unavailable | refused: ConnectionRefusedError: [WinError 10061] No connection could be made because the target ma | yes |
| Connection timeout | timeout: TimeoutError: timed out | yes |
| Interrupted TCP transfer | reset: ConnectionResetError: [WinError 10054] An existing connection was forcibly closed by the r | yes |
| Missing UDP datagrams | missing_datagrams: receiver detected missing seq 50-54, 120, 199; idle timeout after 1.0s | yes |
| Invalid TLS certificate (untrusted issuer) | tls_certificate: SSLCertVerificationError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unab | yes |
| Invalid TLS certificate (host name mismatch) | tls_certificate: SSLCertVerificationError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: Host | yes |

### Server unavailable

- **Condition (what failed / why):** No process listening on 127.0.0.1:62671
- **Observed error:** `ConnectionRefusedError: [WinError 10061] No connection could be made because the target machine actively refused it`
- **Impact (what happened next):** The connection was refused after 2.05 s: the OS answered the SYN with a TCP RST (Windows retries a refused SYN for about 2 s before reporting it). No data was sent.
- **Restoration:** Started the server on port 62671
- **Recovery observed:** yes - Message sent and acknowledged in 0.35 ms; Connection closed (BYE + FIN)

### Connection timeout

- **Condition (what failed / why):** Server accepts the TCP connection but never replies; client read timeout 1.5s
- **Observed error:** `TimeoutError: timed out`
- **Impact (what happened next):** TCP connected (0.259 ms) but no reply arrived within 1.5s, so the client gave up. A timeout alone cannot tell a slow server from a dead one.
- **Restoration:** Replaced the silent server with a responsive one
- **Recovery observed:** yes - reply received in 0.39 ms

### Interrupted TCP transfer

- **Condition (what failed / why):** Server resets the connection (RST) after receiving about 300000 of 2000000 bytes
- **Observed error:** `ConnectionResetError: [WinError 10054] An existing connection was forcibly closed by the remote host`
- **Impact (what happened next):** The transfer stopped: the client had written 458752 bytes when the error was raised and got no acknowledgement, so it cannot know how much the server kept.
- **Restoration:** Restarted a normal server and re-sent the whole file (no partial resume)
- **Recovery observed:** yes - 2000000 bytes received, SHA-256 match = True

### Missing UDP datagrams

- **Condition (what failed / why):** Sender deliberately skipped sequence numbers [50, 51, 52, 53, 54, 120, 199] (injected loss)
- **Observed error:** `receiver detected missing seq 50-54, 120, 199; idle timeout after 1.0s`
- **Impact (what happened next):** 193/200 datagrams arrived. UDP did not notice or recover the loss; only the sequence numbers revealed it.
- **Restoration:** Sent the run again without skipping
- **Recovery observed:** yes - 200/200 received, missing: none

### Invalid TLS certificate (untrusted issuer)

- **Condition (what failed / why):** Server presents a certificate signed by a CA the client does not trust
- **Observed error:** `SSLCertVerificationError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate (_ssl.c:1032)`
- **Impact (what happened next):** The client aborted the TLS handshake, so no application data was sent. This is the intended protection against impersonation.
- **Restoration:** Server switched to the valid lab certificate for 'localhost'
- **Recovery observed:** yes - TLSv1.3 TLS_AES_256_GCM_SHA384

### Invalid TLS certificate (host name mismatch)

- **Condition (what failed / why):** Server presents a lab-CA certificate issued for 'wrong-host.example' while the client connects to 'localhost'
- **Observed error:** `SSLCertVerificationError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: Hostname mismatch, certificate is not valid for 'localhost'. (_ssl.c:1032)`
- **Impact (what happened next):** The client aborted the TLS handshake, so no application data was sent. This is the intended protection against impersonation.
- **Restoration:** Server switched to the valid lab certificate for 'localhost'
- **Recovery observed:** yes - TLSv1.3 TLS_AES_256_GCM_SHA384

## What can and cannot be concluded

- Can: how each protocol behaved on this host and how the application detected each failure.
- Cannot: performance on a real network path; loopback has no propagation delay and almost no loss.
