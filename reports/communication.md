# RouteResQ communication experiments

*Generated 2026-11-04T12:41:36+00:00. Real sockets on the loopback interface (127.0.0.1); failures are injected locally and labelled as such.*

## TCP vs UDP

Parameters: {'total_bytes': 1000000, 'datagram_payload': 1024, 'trials': 3, 'udp_rate_pps': None, 'udp_rcvbuf': None}

| Protocol | Trial | Setup (ms) | Delivered % | Duration (s) | Throughput (Mb/s) | Integrity | Missing |
|---|---|---|---|---|---|---|---|
| TCP | 1 | 4.729 | 100.0 | 0.002038 | 3925.417 | True | - |
| TCP | 2 | 0.328 | 100.0 | 0.014607 | 547.683 | True | - |
| TCP | 3 | 0.298 | 100.0 | 0.001692 | 4728.132 | True | - |
| UDP | 1 | 0.0 | 100.0 | 0.009043 | 905.852 | None | none |
| UDP | 2 | 0.0 | 100.0 | 0.009827 | 833.546 | None | none |
| UDP | 3 | 0.0 | 100.0 | 0.010478 | 781.783 | None | none |

**Interpretation (generated from the measurements):**

- TCP spent 1.785 ms on average establishing a connection (SYN, SYN-ACK, ACK) before any data; UDP sends its first datagram immediately because it is connectionless.
- Every TCP trial delivered 100% of the bytes, and the SHA-256 check matched: TCP retransmits lost segments and delivers bytes in order.
- All UDP datagrams arrived in these trials. UDP does not guarantee this; on a congested or lossy path (or with a small receive buffer) datagrams would be lost without notice.
- Measured throughput: TCP 3067.1 Mb/s (until acknowledged) vs UDP 840.4 Mb/s (at the receiver). TCP was faster in this run, but this depends on datagram size, pacing, buffers and the host. Neither protocol is faster in general, and UDP's figure counts only what arrived.

## TLS secure transfer

- TLS version / cipher: TLSv1.3 / TLS_AES_256_GCM_SHA384 (256 bits)
- Server certificate: organizationName=RouteResQ Lab, commonName=localhost issued by organizationName=RouteResQ Lab, commonName=RouteResQ Lab CA
- File: 262144 bytes, client SHA-256 `22ac89270c9b9c161a522cfbca9ea515d125b637142c59701b2245a6dce7afa7`
- Server SHA-256 `22ac89270c9b9c161a522cfbca9ea515d125b637142c59701b2245a6dce7afa7` -> integrity verified: True

  1. TCP connection established in 0.37 ms (3-way handshake)
  2. TLS handshake completed in 1.299 ms (TLSv1.3, TLS_AES_256_GCM_SHA384)
  3. Server certificate validated against the trusted CA and host name
  4. Sent 262144 bytes in 4 chunk frame(s)
  5. Server acknowledged 262144 bytes; SHA-256 matches

## Communication failure demonstrations

| Failure | Root cause (injected) | Observed error | Resumed after restore |
|---|---|---|---|
| Server unavailable | No process listening on 127.0.0.1:51984 | refused: ConnectionRefusedError: [WinError 10061] No connection could be made because the target ma | yes |
| Connection timeout | Server accepts the TCP connection but never replies; client read timeout 1.5s | timeout: TimeoutError: timed out | yes |
| Interrupted TCP transfer | Server resets the connection (RST) after receiving about 300000 of 2000000 bytes | reset: ConnectionResetError: [WinError 10054] An existing connection was forcibly closed by the r | yes |
| Missing UDP datagrams | Sender deliberately skipped sequence numbers [50, 51, 52, 53, 54, 120, 199] (injected loss) | missing_datagrams: receiver detected missing seq 50-54, 120, 199; idle timeout after 1.0s | yes |
| Invalid TLS certificate (untrusted issuer) | Server presents a certificate signed by a CA the client does not trust | tls_certificate: SSLCertVerificationError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unab | yes |
| Invalid TLS certificate (host name mismatch) | Server presents a lab-CA certificate issued for 'wrong-host.example' while the client connects to 'localhost' | tls_certificate: SSLCertVerificationError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: Host | yes |

### Server unavailable

- **Root cause (confirmed - injected):** No process listening on 127.0.0.1:51984
- **Observed error:** `ConnectionRefusedError: [WinError 10061] No connection could be made because the target machine actively refused it`
- **Impact (what happened next):** The connection was refused after 2.05 s: the OS answered the SYN with a TCP RST (Windows retries a refused SYN for about 2 s before reporting it). No data was sent.
- **Restoration:** Started the server on port 51984
- **Recovery observed:** yes - Message sent and acknowledged in 0.72 ms; Connection closed (BYE + FIN)

### Connection timeout

- **Root cause (confirmed - injected):** Server accepts the TCP connection but never replies; client read timeout 1.5s
- **Observed error:** `TimeoutError: timed out`
- **Impact (what happened next):** TCP connected (0.318 ms) but no reply arrived within 1.5s, so the client gave up. A timeout alone cannot tell a slow server from a dead one.
- **Restoration:** Replaced the silent server with a responsive one
- **Recovery observed:** yes - reply received in 0.47 ms

### Interrupted TCP transfer

- **Root cause (confirmed - injected):** Server resets the connection (RST) after receiving about 300000 of 2000000 bytes
- **Observed error:** `ConnectionResetError: [WinError 10054] An existing connection was forcibly closed by the remote host`
- **Impact (what happened next):** The transfer stopped: the client had written 589824 bytes when the error was raised and got no acknowledgement, so it cannot know how much the server kept.
- **Restoration:** Restarted a normal server and re-sent the whole file (no partial resume)
- **Recovery observed:** yes - 2000000 bytes received, SHA-256 match = True

### Missing UDP datagrams

- **Root cause (confirmed - injected):** Sender deliberately skipped sequence numbers [50, 51, 52, 53, 54, 120, 199] (injected loss)
- **Observed error:** `receiver detected missing seq 50-54, 120, 199; idle timeout after 1.0s`
- **Impact (what happened next):** 193/200 datagrams arrived. UDP did not notice or recover the loss; only the sequence numbers revealed it.
- **Restoration:** Sent the run again without skipping
- **Recovery observed:** yes - 200/200 received, missing: none

### Invalid TLS certificate (untrusted issuer)

- **Root cause (confirmed - injected):** Server presents a certificate signed by a CA the client does not trust
- **Observed error:** `SSLCertVerificationError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate (_ssl.c:1032)`
- **Impact (what happened next):** The client aborted the TLS handshake, so no application data was sent. This is the intended protection against impersonation.
- **Restoration:** Server switched to the valid lab certificate for 'localhost'
- **Recovery observed:** yes - TLSv1.3 TLS_AES_256_GCM_SHA384

### Invalid TLS certificate (host name mismatch)

- **Root cause (confirmed - injected):** Server presents a lab-CA certificate issued for 'wrong-host.example' while the client connects to 'localhost'
- **Observed error:** `SSLCertVerificationError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: Hostname mismatch, certificate is not valid for 'localhost'. (_ssl.c:1032)`
- **Impact (what happened next):** The client aborted the TLS handshake, so no application data was sent. This is the intended protection against impersonation.
- **Restoration:** Server switched to the valid lab certificate for 'localhost'
- **Recovery observed:** yes - TLSv1.3 TLS_AES_256_GCM_SHA384

## What can and cannot be concluded

- Can: how each protocol behaved on this host and how the application detected each failure.
- Cannot: performance on a real network path; loopback has no propagation delay and almost no loss.
