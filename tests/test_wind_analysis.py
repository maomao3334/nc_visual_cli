from __future__ import annotations

import numpy as np

from nc_visual_cli.wind_analysis import (
    build_brief_lines,
    calculate_flow_direction,
    calculate_meteorological_direction,
    calculate_risk_sector,
    calculate_rolling_wind_rose,
    calculate_wind_speed,
    determine_quality,
)


def test_vector_math_uses_flow_direction():
    u = np.array([0.0, 1.0, 0.0, -1.0])
    v = np.array([1.0, 0.0, -1.0, 0.0])
    assert np.allclose(calculate_wind_speed(u, v), 1.0)
    assert np.allclose(calculate_flow_direction(u, v), [0.0, 90.0, 180.0, 270.0])
    assert np.allclose(calculate_meteorological_direction(u, v), [180.0, 270.0, 0.0, 90.0])


def test_quality_flag_is_authoritative_and_neighbors_are_fallback():
    valid = np.array([[True, True, False]])
    flag = np.array([[2, 1, 2]])
    neighbors = np.array([[1, 5, 5]])
    assert determine_quality(valid, flag, neighbors).tolist() == [[2, 1, 0]]
    assert determine_quality(valid, None, neighbors).tolist() == [[1, 2, 0]]
    assert determine_quality(valid, None, None) is None


def test_rolling_rose_requires_multiple_real_times_and_uses_window():
    frame = {
        "speed": [3.0, 4.0, 6.0],
        "flow_direction": [80.0, 90.0, 100.0],
    }
    frames = {"0:0": frame, "1:0": frame, "2:0": frame}
    times = [0, 30 * 60_000, 180 * 60_000]
    valid = calculate_rolling_wind_rose(frames, times, 1, 0, window_minutes=60)
    assert valid["valid"] is True
    assert valid["sample_count"] == 6
    separated = calculate_rolling_wind_rose(frames, times, 2, 0, window_minutes=60)
    assert separated["valid"] is False

    gap_frames = {f"{index}:0": frame for index in range(4)}
    gap_times = [0, 10 * 60_000, 20 * 60_000, 55 * 60_000]
    reset = calculate_rolling_wind_rose(
        gap_frames, gap_times, 3, 0, window_minutes=60
    )
    assert reset["valid"] is False
    assert reset["sample_count"] == 3


def test_risk_sector_refuses_missing_or_distant_support():
    event = {"id": "fire-1", "lon": 102.6, "lat": 24.9}
    valid = calculate_risk_sector(event, 10.0, 90.0, 2, 20, 1.0)
    assert valid["valid"] is True
    assert valid["radius_km"] == 12.0
    assert valid["angle_width"] == 30
    assert calculate_risk_sector(event, 10.0, 90.0, 0, 20, 1.0)["valid"] is False
    assert calculate_risk_sector(event, 10.0, 90.0, 2, 20, 11.0)["valid"] is False


def test_brief_never_claims_safety():
    frame = {
        "summary": {
            "flow_direction_mean": 45.0,
            "speed_p25": 3.0,
            "speed_p75": 6.0,
            "quality_low": 8,
            "quality_acceptable": 2,
        }
    }
    lines = build_brief_lines(frame, "10:00", "30 m AGL", "provided", True)
    combined = "".join(lines)
    assert "研判参考" in combined
    assert "不是扩散模型或安全边界" in combined
    assert "无风险" not in combined

    frame["summary"]["flow_direction_mean"] = None
    variable = "".join(build_brief_lines(frame, "10:00", "30 m AGL", "provided", False))
    assert "方向分散或静风" in variable
