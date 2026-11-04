"""NS2 trace parsing, packet matching and metric calculations on synthetic traces whose
correct answers are known exactly."""
import pytest

from analysis.metrics import queue_occupancy, queue_stats, time_series, window_summary
from analysis.packets import build_packet_records
from analysis.routing import delivery_gaps, path_usage, route_changes, routing_control_traffic
from simulation.trace_parser import LinkStateEvent, parse_line, parse_trace_lines
from tests.helpers import packet, trace_text

PRIMARY = [0, 1, 2, 4, 5]
ALT = [0, 1, 3, 4, 5]


def parse(text):
    return parse_trace_lines(text.splitlines())


def test_parse_line_fields():
    ev = parse_line("r 1.033600 4 5 cbr 1000 ------- 1 0.0 5.0 0 7")
    assert (ev.event, ev.time, ev.from_node, ev.to_node, ev.ptype, ev.size) == ("r", 1.0336, 4, 5, "cbr", 1000)
    assert (ev.fid, ev.src_node, ev.dst_node, ev.seq, ev.pkt_id) == (1, 0, 5, 0, 7)
    assert parse_line("v 3 link-down 1 2") == LinkStateEvent(3.0, "down", 1, 2)
    assert parse_line("v 0 eval {set sim_annotation x}") is None


def test_malformed_lines_counted_and_skipped():
    text = "+ 1.0 0 1 cbr 1000 ------- 1 0.0 5.0 0 0\n+ 1.0 0 1 cbr\nX junk\n- 1.0 0 1 cbr 1000 ------- 1 0.0 5.0 0 0\n"
    p = parse(text)
    assert p.malformed_lines == 2 and len(p.events) == 2 and len(p.malformed_examples) == 2


def test_duplicate_link_events_collapsed_and_intervals():
    p = parse("v 3 link-down 1 2\nv 3 link-down 1 2\nv 3 link-down 2 1\nv 6 link-up 1 2\nv 6 link-up 1 2\n")
    assert len(p.link_events) == 3
    assert p.link_down_intervals()[frozenset((1, 2))] == [(3.0, 6.0)]
    assert p.link_down_at(1, 2, 4.0) and not p.link_down_at(1, 2, 6.0) and not p.link_down_at(1, 2, 2.9)


@pytest.fixture()
def mixed_trace():
    """10 packets every 0.1 s from t=1.0 along the primary path (10 ms per hop -> 40 ms delay).

    seq 3: queue drop on 1->2 (link up)          -> dropped_queue
    seq 5: drop on 1->2 while link 1-2 is down   -> dropped_link_down
    seq 7: arrives at node 1, never forwarded    -> lost_at_node
    seq 8: transmitted on 2->4, never received   -> lost_on_link
    others delivered.
    """
    ev = []
    for seq in range(10):
        t0 = round(1.0 + 0.1 * seq, 6)
        kw = {}
        if seq in (3, 5):
            kw["drop_hop"] = 1
        if seq == 7:
            kw["stop"] = ("arrive", 0)
        if seq == 8:
            kw["stop"] = ("dequeue", 2)
        ev += packet(100 + seq, seq, t0, PRIMARY, **kw)
    ev += [(1.49, "v 1.49 link-down 1 2"), (1.55, "v 1.55 link-up 1 2")]
    ev += [(5.0, "+ 5.0 3 4 rtProtoDV 6 ------- 0 3.1 4.1 -1 999")]  # extends trace end, routing pkt
    return parse(trace_text(ev))


def test_no_double_counting_and_fates(mixed_trace):
    recs = build_packet_records(mixed_trace, {1})
    plus_events = sum(1 for e in mixed_trace.events if e.event == "+" and e.ptype == "cbr")
    assert plus_events > 10  # forwarding enqueues exist at every hop...
    s = window_summary(list(recs.values()))
    assert s["sent"] == 10  # ...but each packet is counted as sent exactly once
    assert s["delivered"] == 6 and s["lost"] == 4 and s["loss_pct"] == 40.0
    fates = {r.seq: r.fate for r in recs.values()}
    assert fates[3] == "dropped_queue" and fates[5] == "dropped_link_down"
    assert fates[7] == "lost_at_node" and fates[8] == "lost_on_link"
    assert sum(f == "delivered" for f in fates.values()) == 6


def test_delay_is_matched_by_packet_id(mixed_trace):
    recs = build_packet_records(mixed_trace, {1})
    delivered = [r for r in recs.values() if r.fate == "delivered"]
    assert all(r.delay == pytest.approx(0.04) for r in delivered)
    s = window_summary(list(recs.values()))
    assert s["avg_delay_ms"] == pytest.approx(40.0) and s["jitter_ms"] == pytest.approx(0.0)
    assert all(r.path == PRIMARY for r in delivered)


def test_throughput_and_windows(mixed_trace):
    recs = list(build_packet_records(mixed_trace, {1}).values())
    # delivered seq 0,1,2,4,6,9 -> received at 1.04,1.14,1.24,1.44,1.64,1.94
    w = window_summary(recs, 1.0, 2.0)
    assert w["throughput_kbps"] == pytest.approx(6 * 8000 / 1.0 / 1000)
    first_half = window_summary(recs, 1.0, 1.5)
    assert first_half["sent"] == 5 and first_half["delivered"] == 4 and first_half["loss_pct"] == 20.0
    whole = window_summary(recs)
    assert whole["window_start"] == 1.0 and whole["window_end"] == pytest.approx(1.94)
    assert whole["throughput_kbps"] == pytest.approx(6 * 8000 / 0.94 / 1000, rel=1e-3)


def test_in_flight_packets_excluded_from_loss():
    ev = packet(1, 0, 1.0, PRIMARY) + packet(2, 1, 1.98, PRIMARY, stop=("dequeue", 1))
    p = parse(trace_text(ev))
    recs = build_packet_records(p, {1}, in_flight_grace=0.5)
    assert {r.seq: r.fate for r in recs.values()} == {0: "delivered", 1: "in_flight"}
    s = window_summary(list(recs.values()))
    assert s["in_flight"] == 1 and s["loss_pct"] == 0.0


def test_queue_occupancy_from_events():
    lines = [
        "+ 1.0 1 2 cbr 1000 ------- 1 0.0 5.0 0 1",
        "+ 1.0 1 2 cbr 1000 ------- 1 0.0 5.0 1 2",
        "+ 1.0 1 2 cbr 1000 ------- 1 0.0 5.0 2 3",
        "d 1.0 1 2 cbr 1000 ------- 1 0.0 5.0 2 3",
        "- 1.1 1 2 cbr 1000 ------- 1 0.0 5.0 0 1",
        "- 1.2 1 2 cbr 1000 ------- 1 0.0 5.0 1 2",
        "d 1.25 1 2 cbr 1000 ------- 1 0.0 5.0 1 2",  # dropped AFTER dequeue: must not go negative
    ]
    q = queue_occupancy(parse("\n".join(lines)))
    assert [n for _t, n in q["1->2"]] == [1, 2, 3, 2, 1, 0]
    assert queue_stats(q)["1->2"]["max_queue_pkts"] == 3


def test_route_change_detection_and_path_usage():
    ev = []
    for seq in range(20):
        ev += packet(seq, seq, round(1.0 + 0.1 * seq, 6), PRIMARY if seq < 10 else ALT)
    ev += packet(99, 20, 3.1, PRIMARY)  # a single stray packet must not count as a route change
    ev += packet(100, 21, 3.2, ALT)
    recs = list(build_packet_records(parse(trace_text(ev)), {1}).values())
    ch = route_changes(recs)
    assert len(ch) == 1 and ch[0]["from_path"] == "0-1-2-4-5" and ch[0]["to_path"] == "0-1-3-4-5"
    assert ch[0]["time"] == pytest.approx(2.0)
    usage = path_usage(recs, {"before": (1.0, 2.0), "during": (2.0, 3.5)})
    assert usage["before"] == {"0-1-2-4-5": 10} and usage["during"]["0-1-3-4-5"] == 11


def test_delivery_gap_detection():
    ev = []
    for seq in range(30):
        t0 = round(1.0 + 0.01 * seq, 6) if seq < 10 else round(2.0 + 0.01 * seq, 6)
        ev += packet(seq, seq, t0, PRIMARY)
    recs = list(build_packet_records(parse(trace_text(ev)), {1}).values())
    gaps = delivery_gaps(recs, expected_interval=0.01, active=(1.0, 2.29))
    assert len(gaps) == 1
    assert gaps[0]["start"] == pytest.approx(1.13) and gaps[0]["end"] == pytest.approx(2.14)


def test_time_series_bins_and_routing_messages():
    ev = packet(1, 0, 1.0, PRIMARY) + packet(2, 1, 1.05, PRIMARY, drop_hop=0)
    ev += [(0.2, "+ 0.2 1 2 rtProtoDV 6 ------- 0 1.1 2.1 -1 50"), (0.2, "- 0.2 1 2 rtProtoDV 6 ------- 0 1.1 2.1 -1 50"),
           (0.21, "r 0.21 1 2 rtProtoDV 6 ------- 0 1.1 2.1 -1 50")]
    p = parse(trace_text(ev))
    ts = time_series(list(build_packet_records(p, {1}).values()), p.end_time, 0.1)
    row = next(r for r in ts if r["t"] == 1.0)
    assert row["sent"] == 2 and row["lost"] == 1 and row["avg_delay_ms"] == pytest.approx(40.0)
    ctrl = routing_control_traffic(p)
    assert ctrl["total_messages"] == 1  # forwarding/receive events of the same message not counted
