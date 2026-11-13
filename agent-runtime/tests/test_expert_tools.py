import pytest

from app.expert_tools import (calculate_proportion_interval, frames_to_duration,
                              summarize_numeric_data, tools_for_role)


def test_summary_and_validation():
    result = summarize_numeric_data.invoke({"values": [1, 2, 3]})
    assert result["mean"] == 2 and result["median"] == 2
    assert result["sampleStandardDeviation"] == 1
    assert summarize_numeric_data.invoke({"values": [2]})["sampleStandardDeviation"] is None
    for values in ([], [float("nan")], [1] * 1001):
        with pytest.raises(ValueError):
            summarize_numeric_data.invoke({"values": values})


def test_wilson_interval_at_edges_and_invalid_counts():
    result = calculate_proportion_interval.invoke({"successes": 50, "trials": 100})
    assert result["lower"] == pytest.approx(0.4038315, abs=1e-6)
    assert result["upper"] == pytest.approx(0.5961685, abs=1e-6)
    assert calculate_proportion_interval.invoke({"successes": 0, "trials": 1})["lower"] == 0
    assert calculate_proportion_interval.invoke({"successes": 1, "trials": 1})["upper"] == 1
    with pytest.raises(ValueError):
        calculate_proportion_interval.invoke({"successes": 2, "trials": 1})


def test_fractional_frame_rate_and_roles():
    result = frames_to_duration.invoke({"frames": 30000, "fps_numerator": 30000, "fps_denominator": 1001})
    assert result["exactSeconds"] == "1001/1"
    with pytest.raises(ValueError):
        frames_to_duration.invoke({"frames": 10, "fps_numerator": 0})
    assert {t.name for t in tools_for_role("ANALYST")} == {"summarize_numeric_data", "calculate_proportion_interval"}
    assert [t.name for t in tools_for_role("EDITOR")] == ["frames_to_duration"]
    assert tools_for_role("FACT_CHECK") == []
    # 恢复旧快照时，以原授权清单为上限，不因升级增加工具。
    assert tools_for_role("ANALYST", ["read_inputs", "submit_candidate"]) == []
    assert [t.name for t in tools_for_role("ANALYST", ["calculate_proportion_interval"]) ] == ["calculate_proportion_interval"]


def test_external_tools_require_live_mode_enablement_and_snapshot(monkeypatch, tmp_path):
    monkeypatch.setenv("CREATOR_RESEARCH_ENABLED", "true")
    monkeypatch.setenv("CREATOR_RESEARCH_ALLOWED_HOSTS", "search.example")
    monkeypatch.setenv("CREATOR_RESEARCH_SEARCH_URL", "https://search.example/search")
    monkeypatch.setenv("CREATOR_LOCAL_MEDIA_ENABLED", "true")
    monkeypatch.setenv("CREATOR_LOCAL_MEDIA_ROOT", str(tmp_path))
    research = ["read_research_page", "search_research_sources"]
    local = ["local_sha256", "inspect_local_media"]
    assert tools_for_role("FACT_CHECK", research, mode="FIXTURE") == []
    assert tools_for_role("FACT_CHECK", [], mode="LIVE") == []
    assert {t.name for t in tools_for_role("FACT_CHECK", research, mode="LIVE")} == set(research)
    for role in ("PACKAGING", "PUBLISHER", "BUSINESS"):
        assert {t.name for t in tools_for_role(role, research, mode="LIVE")} == set(research)
    assert {t.name for t in tools_for_role("LIBRARIAN", local, mode="LIVE")} == set(local)
    assert tools_for_role("WRITER", research + local, mode="LIVE") == []
    monkeypatch.setenv("CREATOR_RESEARCH_ENABLED", "false")
    monkeypatch.setenv("CREATOR_LOCAL_MEDIA_ENABLED", "false")
    assert tools_for_role("FACT_CHECK", research, mode="LIVE") == []
    assert tools_for_role("LIBRARIAN", local, mode="LIVE") == []
