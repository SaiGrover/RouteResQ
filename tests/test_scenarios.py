"""Scenario configuration validation (no NS2 needed)."""
import pytest

from simulation.scenario import ScenarioError, load_all_scenarios, parse_bandwidth, parse_delay, scenario_from_dict


def base(**params):
    return {
        "id": "t", "name": "t", "category": "healthy", "description": "d", "known_cause": "c",
        "params": params, "phases": {"before": [1, 3], "during": [3, 6], "after": [6, 9]},
    }


def test_bundled_scenarios_load_and_are_ordered():
    sc = load_all_scenarios()
    assert list(sc) == ["healthy", "link_failure_dv", "link_failure_static", "congestion"]
    assert sc["link_failure_dv"].failed_link == (1, 2) and sc["link_failure_dv"].restore_at == 6.0
    assert sc["link_failure_static"].routing == "Static"
    assert [f.fid for f in sc["congestion"].flows] == [1, 2]
    assert sc["healthy"].packet_interval == pytest.approx(0.008)


def test_ns_args():
    args = load_all_scenarios()["link_failure_dv"].ns_args("out.tr", "events.log")
    assert args[:2] == ["trace=out.tr", "events=events.log"]
    assert "fail_link=1-2" in args and "routing=DV" in args


@pytest.mark.parametrize("params", [
    {"rate": "1Mb; exit"}, {"rate": "[exec rm]"}, {"routing": "OSPF"}, {"unknown_key": 1},
    {"fail_link": "1-5", "fail_at": 3.0}, {"queue_limit": "-1"}, {"core_delay": "10 ms"},
])
def test_invalid_parameters_rejected(params):
    with pytest.raises(ScenarioError):
        scenario_from_dict(base(**params))


def test_restore_must_follow_failure_and_category_consistency():
    d = base(fail_link="1-2", fail_at=5.0, restore_at=4.0)
    with pytest.raises(ScenarioError):
        scenario_from_dict(d)
    d = base()
    d["category"] = "link_failure"
    with pytest.raises(ScenarioError):
        scenario_from_dict(d)
    d = base()
    d["phases"]["during"] = [6, 3]
    with pytest.raises(ScenarioError):
        scenario_from_dict(d)


def test_units():
    assert parse_bandwidth("1.5Mb") == 1.5e6 and parse_bandwidth("10Kb") == 1e4
    assert parse_delay("10ms") == pytest.approx(0.01)
