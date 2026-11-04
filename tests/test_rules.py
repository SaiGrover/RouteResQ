"""Root-cause engine tests using mocked (deterministic) diagnostic measurements."""
from failure_analysis.rules import (
    CONGESTION, DNS_FAILURE, HEALTHY, HIGH_LATENCY, INCONCLUSIVE, PACKET_LOSS, ROUTING, UNREACHABLE,
    Thresholds, analyze_run,
)
from tests.helpers import make_run

TH = Thresholds()  # defaults, independent of config/thresholds.json edits


def fired(report):
    return {t.rule_id for t in report.rule_trace if t.fired}


def test_reachable_destination_is_healthy():
    r = analyze_run(make_run(tr_hops=[("192.168.1.1", [1, 1, 1]), ("93.184.216.34", [10, 11, 10])]), th=TH)
    assert r.classifications == [HEALTHY]
    assert not r.findings and not r.contradictions
    assert "reachable" in r.conclusion


def test_dns_nxdomain_with_working_gateway():
    r = analyze_run(make_run(dns_ok=False, dns_kind="nxdomain"), th=TH)
    assert r.classifications == [DNS_FAILURE]
    assert r.explanations[0].level == "likely" and "does not exist" in r.explanations[0].cause
    assert "gateway reachable" in r.conclusion


def test_dns_temporary_failure_with_dead_gateway_mentions_local_network():
    r = analyze_run(make_run(dns_ok=False, dns_kind="temporary", gateway_replies=0), th=TH)
    causes = [e.cause for e in r.explanations]
    assert DNS_FAILURE in r.classifications
    assert any("DNS server" in c for c in causes) and any("local network" in c for c in causes)


def test_timeout_unreachable_with_traceroute_stopping():
    run = make_run(rtts=[], tr_hops=[("192.168.1.1", [1, 1, 1]), ("10.0.0.1", [5, 5, 5]),
                                     (None, [None] * 3), (None, [None] * 3)], tcp=(False, "timeout"))
    r = analyze_run(run, th=TH)
    assert UNREACHABLE in r.classifications and ROUTING in r.classifications and PACKET_LOSS in r.classifications
    assert {"R-REACH-01", "R-LOSS-02", "R-ROUTE-01", "R-TCP-01"} <= fired(r)
    levels = {e.cause: e.level for e in r.explanations}
    assert all(lv == "possible" for lv in levels.values())  # cause cannot be pinned down
    assert "not confirmed" in r.conclusion


def test_router_reported_unreachable_is_likely_no_route():
    run = make_run(rtts=[], unreachable=["Destination host unreachable (reported by 192.168.1.1)"] * 4)
    r = analyze_run(run, th=TH)
    assert "R-REACH-02" in fired(r)
    assert r.explanations[0].level == "likely" and "no route" in r.explanations[0].cause
    assert "explicitly reported" in r.conclusion


def test_dead_gateway_and_dead_destination_points_to_local_problem():
    r = analyze_run(make_run(rtts=[], gateway_replies=0), th=TH)
    assert any("Local network" in e.cause and e.level == "likely" for e in r.explanations)


def test_high_latency_with_enough_samples():
    r = analyze_run(make_run(rtts=[210, 220, 205, 215]), th=TH)
    assert HEALTHY in r.classifications and HIGH_LATENCY in r.classifications
    assert CONGESTION not in r.classifications  # a single symptom never implies congestion
    cong = next(t for t in r.rule_trace if t.rule_id == "R-CONG-01")
    assert not cong.fired and "single indicator" in cong.reason


def test_high_latency_single_sample_is_insufficient_evidence():
    r = analyze_run(make_run(sent=4, rtts=[300.0]), th=TH)
    assert HIGH_LATENCY not in r.classifications
    assert any(f.level == "insufficient_evidence" for f in r.findings)


def test_jitter_detected():
    r = analyze_run(make_run(rtts=[10, 120, 15, 130]), th=TH)
    assert "R-LAT-02" in fired(r) and HIGH_LATENCY in r.classifications


def test_partial_packet_loss_above_threshold():
    r = analyze_run(make_run(sent=10, rtts=[10.0] * 8), th=TH)
    assert PACKET_LOSS in r.classifications and HEALTHY in r.classifications
    assert any("Intermittent loss" in e.cause for e in r.explanations)


def test_partial_loss_below_threshold_is_only_observed():
    r = analyze_run(make_run(sent=50, rtts=[10.0] * 49), th=TH)
    assert PACKET_LOSS not in r.classifications
    assert "below the" in next(t for t in r.rule_trace if t.rule_id == "R-LOSS-01").reason


def test_complete_packet_loss():
    r = analyze_run(make_run(rtts=[]), th=TH)
    assert "R-LOSS-02" in fired(r) and PACKET_LOSS in r.classifications and UNREACHABLE in r.classifications


def test_traceroute_incomplete_but_ping_ok_is_contradiction_not_routing_issue():
    run = make_run(tr_hops=[("172.17.0.1", [0.3, 0.3, 0.3])] + [(None, [None] * 3)] * 7)
    r = analyze_run(run, th=TH)
    assert r.classifications == [HEALTHY]
    assert ROUTING not in r.classifications
    assert any("not evidence of a routing failure" in c for c in r.contradictions)


def test_ping_blocked_but_tcp_answers():
    r = analyze_run(make_run(rtts=[], tcp=(True, None)), th=TH)
    assert HEALTHY in r.classifications and UNREACHABLE not in r.classifications
    assert any("ICMP echo is probably filtered" in c for c in r.contradictions)
    assert any("ICMP echo is blocked" in e.cause for e in r.explanations)


def test_ping_fails_but_traceroute_reached_is_contradictory():
    run = make_run(rtts=[], tr_hops=[("192.168.1.1", [1, 1, 1]), ("93.184.216.34", [9, 9, 9])])
    r = analyze_run(run, th=TH)
    assert UNREACHABLE not in r.classifications
    assert any("traceroute reached the destination" in c for c in r.contradictions)


def test_silent_gateway_with_reachable_destination_is_noted_not_a_fault():
    r = analyze_run(make_run(gateway_replies=0), th=TH)
    assert r.classifications == [HEALTHY]
    assert any("ignores ICMP" in c for c in r.contradictions)


def test_unparseable_ping_is_inconclusive():
    r = analyze_run(make_run(rtts=[], ping_parsed=False), th=TH)
    assert INCONCLUSIVE in r.classifications
    assert "R-PING-00" in fired(r)


def test_baseline_rtt_increase_alone_is_not_congestion():
    base = make_run(rtts=[10, 11, 10, 11], run_id="base")
    cur = make_run(rtts=[60, 62, 61, 63], run_id="cur")
    r = analyze_run(cur, baseline=base, th=TH)
    assert "R-BASE-01" in fired(r) and HIGH_LATENCY in r.classifications
    assert CONGESTION not in r.classifications


def test_baseline_rtt_and_loss_increase_suggest_possible_congestion():
    base = make_run(sent=20, rtts=[10.0] * 20, run_id="base")
    cur = make_run(sent=20, rtts=[60, 70, 65, 80, 75, 60, 70, 65, 80, 75, 60, 70, 65, 80, 75, 60], run_id="cur")
    r = analyze_run(cur, baseline=base, th=TH)
    assert CONGESTION in r.classifications
    f = next(f for f in r.findings if f.category == CONGESTION)
    assert f.level == "possible" and len(f.evidence) >= 2


def test_throughput_drop_counts_as_congestion_indicator():
    base = make_run(rtts=[10, 10, 10, 10], throughput=10_000, run_id="b")
    cur = make_run(rtts=[50, 52, 51, 50], throughput=4_000, run_id="c")
    r = analyze_run(cur, baseline=base, th=TH)
    assert "R-BASE-04" in fired(r) and CONGESTION in r.classifications


def test_route_change_between_runs():
    prev = make_run(tr_hops=[("192.168.1.1", [1]), ("10.0.0.1", [5]), ("93.184.216.34", [9])], run_id="p")
    cur = make_run(tr_hops=[("192.168.1.1", [1]), ("10.0.0.7", [6]), ("93.184.216.34", [9])], run_id="c")
    r = analyze_run(cur, previous=prev, th=TH)
    assert "R-ROUTE-02" in fired(r) and ROUTING in r.classifications and HEALTHY in r.classifications


def test_every_rule_is_traced_with_a_reason():
    r = analyze_run(make_run(), th=TH)
    ids = {t.rule_id for t in r.rule_trace}
    assert {"R-DNS-01", "R-REACH-01", "R-LOSS-01", "R-LAT-01", "R-CONG-01", "R-ROUTE-01", "R-OK-01"} <= ids
    assert all(t.reason for t in r.rule_trace)


def test_no_confidence_percentages_in_output():
    r = analyze_run(make_run(rtts=[], tr_hops=[("192.168.1.1", [1]), (None, [None])]), th=TH)
    text = " ".join([r.conclusion] + [e.cause for e in r.explanations])
    assert "%" not in text.replace("% loss", "")


def test_levels_are_from_fixed_vocabulary():
    r = analyze_run(make_run(rtts=[]), th=TH)
    allowed = {"confirmed", "likely", "possible", "insufficient_evidence"}
    assert all(f.level in allowed for f in r.findings)
    assert all(e.level in allowed for e in r.explanations)


def test_shorter_hop_limit_is_not_a_route_change():
    prev = make_run(tr_hops=[("192.168.1.1", [1]), ("10.0.0.1", [5]), (None, [None]), ("93.184.216.34", [9])], run_id="p")
    cur = make_run(tr_hops=[("192.168.1.1", [1]), ("10.0.0.1", [5])], tr_reached=False, run_id="c")  # max hops 2
    r = analyze_run(cur, previous=prev, th=TH)
    assert "R-ROUTE-02" not in fired(r)
    assert "hop limit" in next(t for t in r.rule_trace if t.rule_id == "R-ROUTE-02").reason
