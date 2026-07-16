from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np
import xarray as xr

from .errors import DataContractError, InputError
from .models import DatasetAnalysis, ScanResult
from .provenance import source_sha256
from .scanner import scan_folder

SPEED_FACTORS = {
    "m/s": 1.0,
    "m s-1": 1.0,
    "m s^-1": 1.0,
    "meter per second": 1.0,
    "metre per second": 1.0,
    "kt": 0.514444,
    "kts": 0.514444,
    "knot": 0.514444,
    "knots": 0.514444,
    "km/h": 1.0 / 3.6,
    "km h-1": 1.0 / 3.6,
}


def calculate_wind_speed(u: np.ndarray | float, v: np.ndarray | float) -> np.ndarray:
    return np.hypot(u, v)


def calculate_flow_direction(u: np.ndarray | float, v: np.ndarray | float) -> np.ndarray:
    return (np.degrees(np.arctan2(u, v)) + 360.0) % 360.0


def calculate_meteorological_direction(u: np.ndarray | float, v: np.ndarray | float) -> np.ndarray:
    return (calculate_flow_direction(u, v) + 180.0) % 360.0


def circular_difference(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    return np.abs((left - right + 180.0) % 360.0 - 180.0)


def determine_quality(
    valid: np.ndarray,
    quality_flag: np.ndarray | None,
    neighbor_count: np.ndarray | None,
) -> np.ndarray | None:
    if quality_flag is not None:
        values = np.asarray(quality_flag, dtype=np.float64)
        quality = np.zeros(valid.shape, dtype=np.int8)
        finite = np.isfinite(values)
        quality[finite] = np.clip(np.rint(values[finite]), 0, 2).astype(np.int8)
        return np.where(valid, quality, 0).astype(np.int8)
    if neighbor_count is not None:
        neighbor_count = np.asarray(neighbor_count, dtype=np.float64)
        quality = np.zeros(valid.shape, dtype=np.int8)
        quality[(neighbor_count >= 1) & valid] = 1
        quality[(neighbor_count >= 3) & valid] = 2
        return quality
    return None


def _speed_factor(units: Any, variable_name: str, warnings: list[str]) -> float:
    normalized = str(units or "").strip().casefold()
    if not normalized:
        warnings.append(f"{variable_name} 缺少单位，按 m/s 解释")
        return 1.0
    if normalized not in SPEED_FACTORS:
        raise DataContractError(f"{variable_name} 使用不支持的风速单位: {units!r}")
    return SPEED_FACTORS[normalized]


def _canonical_dataset(dataset: xr.Dataset, scan: ScanResult) -> xr.Dataset:
    rename: dict[str, str] = {}
    for canonical, actual in scan.coordinate_names.items():
        if canonical != actual and canonical not in dataset.variables and canonical not in dataset.dims:
            rename[actual] = canonical
    for canonical, actual in scan.variable_names.items():
        if canonical != actual and canonical not in dataset.data_vars:
            rename[actual] = canonical
    if rename:
        dataset = dataset.rename(rename)
    if "time" in dataset.dims and "time" in dataset.coords:
        try:
            dataset = dataset.sortby("time")
        except Exception as exc:
            raise DataContractError(f"time 坐标无法排序: {exc}") from exc
    if "height" in dataset.dims and "height" in dataset.coords:
        try:
            dataset = dataset.sortby("height")
        except Exception as exc:
            raise DataContractError(f"height 坐标无法排序: {exc}") from exc
    for coordinate in ("lat", "lon"):
        if coordinate not in dataset.coords:
            raise DataContractError(f"缺少 {coordinate} 坐标")
        values = np.asarray(dataset[coordinate].values, dtype=np.float64)
        if values.ndim != 1 or not np.all(np.isfinite(values)):
            raise DataContractError(f"{coordinate} 必须是一维有限数值坐标")
        differences = np.diff(values)
        if differences.size and not (np.all(differences > 0) or np.all(differences < 0)):
            raise DataContractError(f"{coordinate} 坐标必须严格单调")
    return dataset


def _slice_2d(variable: xr.DataArray, time_index: int, height_index: int) -> np.ndarray:
    indexers: dict[str, int] = {}
    if "time" in variable.dims:
        indexers["time"] = time_index
    if "height" in variable.dims:
        indexers["height"] = height_index
    selected = variable.isel(indexers)
    remaining = [dim for dim in selected.dims if dim not in {"lat", "lon"}]
    if remaining:
        raise DataContractError(
            f"变量 {variable.name} 含有未支持维度: {', '.join(remaining)}"
        )
    if "lat" not in selected.dims or "lon" not in selected.dims:
        raise DataContractError(f"变量 {variable.name} 必须包含 lat/lon 维度")
    return np.asarray(selected.transpose("lat", "lon").values)


def _slice_summary_value(
    variable: xr.DataArray | None,
    time_index: int,
    height_index: int,
) -> Any:
    if variable is None:
        return None
    indexers: dict[str, int] = {}
    if "time" in variable.dims:
        indexers["time"] = time_index
    if "height" in variable.dims:
        indexers["height"] = height_index
    selected = variable.isel(indexers).squeeze(drop=True)
    values = np.asarray(selected.values)
    if values.size == 0:
        return None
    if values.size == 1:
        return values.reshape(-1)[0].item()
    if np.issubdtype(values.dtype, np.number):
        finite = values[np.isfinite(values)]
        return float(np.sum(finite)) if finite.size else 0.0
    return str(values.reshape(-1)[0])


def _time_point(value: Any, timezone: ZoneInfo) -> dict[str, Any]:
    if isinstance(value, np.datetime64):
        if np.isnat(value):
            raise DataContractError("time 坐标包含 NaT")
        text = np.datetime_as_string(value, unit="s")
        parsed = datetime.fromisoformat(text)
    elif isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise DataContractError(f"无法解析 time 坐标值 {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone)
    else:
        parsed = parsed.astimezone(timezone)
    return {
        "iso": parsed.isoformat(),
        "label": parsed.strftime("%Y-%m-%d %H:%M"),
        "short_label": parsed.strftime("%H:%M"),
        "epoch_ms": int(parsed.timestamp() * 1000),
        "timezone": str(timezone),
    }


def _height_coordinates(dataset: xr.Dataset, warnings: list[str]) -> tuple[list[float], str]:
    if "height" not in dataset.dims:
        return [0.0], "UNKNOWN"
    coordinate = dataset["height"]
    values = np.asarray(coordinate.values, dtype=np.float64)
    units = str(coordinate.attrs.get("units", "m")).strip().casefold()
    if units in {"km", "kilometer", "kilometre"}:
        values = values * 1000.0
    elif units not in {"m", "meter", "metre", "meters", "metres", ""}:
        raise DataContractError(f"height 使用不支持的单位: {units!r}")
    if not str(coordinate.attrs.get("units", "")).strip():
        warnings.append("height 缺少单位，按米解释")
    description = " ".join(
        str(coordinate.attrs.get(key, "")) for key in ("long_name", "standard_name", "datum")
    ).casefold()
    if "above ground" in description or "agl" in description:
        datum = "AGL"
    elif "above sea" in description or "msl" in description or "sea level" in description:
        datum = "MSL"
    else:
        datum = "UNKNOWN"
        warnings.append("高度基准无法识别，报告将显示“高度基准未知”")
    return values.astype(float).tolist(), datum


def _float_list(values: np.ndarray, digits: int = 4) -> list[float]:
    return np.round(values.astype(np.float64), digits).tolist()


def _nullable_float_list(
    values: np.ndarray,
    digits: int,
    minimum: float | None = None,
) -> list[float | None]:
    result: list[float | None] = []
    for value in np.asarray(values, dtype=np.float64).reshape(-1):
        if not np.isfinite(value) or (minimum is not None and value < minimum):
            result.append(None)
        else:
            result.append(round(float(value), digits))
    return result


def _nullable_int_list(values: np.ndarray, minimum: int = 0) -> list[int | None]:
    result: list[int | None] = []
    for value in np.asarray(values, dtype=np.float64).reshape(-1):
        if not np.isfinite(value) or value < minimum:
            result.append(None)
        else:
            result.append(int(round(float(value))))
    return result


def _string_matrix(
    variable: xr.DataArray | None,
    time_count: int,
    height_count: int,
) -> list[list[str]]:
    return [
        [str(_slice_summary_value(variable, t, h) or "") for h in range(height_count)]
        for t in range(time_count)
    ]


def _find_scan(path: Path, supplied: ScanResult | None) -> ScanResult:
    if supplied is not None:
        return supplied
    resolved = path.resolve()
    for result in scan_folder(resolved.parent):
        if result.path == resolved:
            return result
    raise DataContractError(f"无法检查 NetCDF: {path}")


def analyze_dataset(
    path: str | Path,
    scan_result: ScanResult | None = None,
    timezone: str = "Asia/Shanghai",
    time_window_min: int = 60,
) -> DatasetAnalysis:
    source = Path(path).expanduser().resolve()
    scan = _find_scan(source, scan_result)
    if not scan.compatible:
        raise DataContractError(scan.error or f"不兼容的 NetCDF: {source}")
    try:
        timezone_info = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise InputError(f"未知时区: {timezone}") from exc

    warnings = list(scan.warnings)
    with xr.open_dataset(source, decode_times=True) as opened:
        dataset = _canonical_dataset(opened, scan)
        time_count = int(dataset.sizes.get("time", 1))
        height_count = int(dataset.sizes.get("height", 1))
        latitudes = np.asarray(dataset["lat"].values, dtype=np.float64)
        longitudes = np.asarray(dataset["lon"].values, dtype=np.float64)
        if "time" in dataset.dims:
            time_points = [_time_point(value, timezone_info) for value in dataset["time"].values]
            time_kind = "coordinate"
        else:
            time_points = [
                {
                    "iso": None,
                    "label": "无时间维（静态场）",
                    "short_label": "静态",
                    "epoch_ms": 0,
                    "timezone": timezone,
                }
            ]
            time_kind = "absent"
        heights_m, height_datum = _height_coordinates(dataset, warnings)

        u_variable = dataset["U_wind"]
        v_variable = dataset["V_wind"]
        u_factor = _speed_factor(u_variable.attrs.get("units"), "U_wind", warnings)
        v_factor = _speed_factor(v_variable.attrs.get("units"), "V_wind", warnings)
        speed_variable = dataset.get("wind_speed")
        speed_factor = (
            _speed_factor(speed_variable.attrs.get("units"), "wind_speed", warnings)
            if speed_variable is not None
            else 1.0
        )
        direction_variable = dataset.get("wind_direction")
        quality_variable = dataset.get("quality")
        neighbor_variable = dataset.get("neighbor_count")
        distance_variable = dataset.get("observation_distance")
        observation_count_variable = dataset.get("observation_count")
        source_mix_variable = dataset.get("source_mix")
        coord_status_variable = dataset.get("coord_status_mix")

        if quality_variable is not None:
            quality_status = "provided"
        elif neighbor_variable is not None:
            quality_status = "derived_from_neighbors"
            warnings.append("无质量等级字段，按有效邻点数推导质量等级")
        else:
            quality_status = "unavailable"

        speed_mean: list[list[float | None]] = [
            [None for _ in range(height_count)] for _ in range(time_count)
        ]
        speed_p25: list[list[float | None]] = [
            [None for _ in range(height_count)] for _ in range(time_count)
        ]
        speed_p75: list[list[float | None]] = [
            [None for _ in range(height_count)] for _ in range(time_count)
        ]
        coverage: list[list[int]] = [[0 for _ in range(height_count)] for _ in range(time_count)]
        low_quality_ratio: list[list[float | None]] = [
            [None for _ in range(height_count)] for _ in range(time_count)
        ]
        acceptable_quality_ratio: list[list[float | None]] = [
            [None for _ in range(height_count)] for _ in range(time_count)
        ]
        frames: dict[str, dict[str, Any]] = {}
        all_speeds: list[np.ndarray] = []
        speed_error_max = 0.0
        speed_error_count = 0
        direction_error_max = 0.0
        direction_error_count = 0
        unsupported_quality_points = 0
        observation_hint_mismatches = 0
        neighbor_metadata_missing = False
        distance_metadata_missing = False
        observation_count_warning = False

        for time_index in range(time_count):
            for height_index in range(height_count):
                observation_hint = _slice_summary_value(
                    observation_count_variable, time_index, height_index
                )
                observation_value: int | None = None
                if observation_hint is not None:
                    try:
                        numeric_hint = float(observation_hint)
                        if math.isfinite(numeric_hint) and numeric_hint > 0:
                            observation_value = max(1, int(round(numeric_hint)))
                    except (TypeError, ValueError):
                        if not observation_count_warning:
                            warnings.append("observation_count 含非数值，已改为逐切片检查")
                            observation_count_warning = True
                        observation_count_variable = None

                u = _slice_2d(u_variable, time_index, height_index).astype(np.float64) * u_factor
                v = _slice_2d(v_variable, time_index, height_index).astype(np.float64) * v_factor
                valid = np.isfinite(u) & np.isfinite(v)
                if not np.any(valid):
                    continue

                speed = calculate_wind_speed(u, v)
                flow_direction = calculate_flow_direction(u, v)
                quality_values = (
                    _slice_2d(quality_variable, time_index, height_index)
                    if quality_variable is not None
                    else None
                )
                neighbor_values = (
                    _slice_2d(neighbor_variable, time_index, height_index)
                    if neighbor_variable is not None
                    else None
                )
                distance_values = (
                    _slice_2d(distance_variable, time_index, height_index)
                    if distance_variable is not None
                    else None
                )
                quality = determine_quality(valid, quality_values, neighbor_values)
                supported = valid if quality is None else valid & (quality > 0)
                if quality is not None:
                    unsupported_quality_points += int(np.sum(valid & (quality == 0)))
                if not np.any(supported):
                    continue
                valid_flat = supported.reshape(-1)
                point_index = np.flatnonzero(valid_flat)
                u_valid = u.reshape(-1)[valid_flat]
                v_valid = v.reshape(-1)[valid_flat]
                speed_valid = speed.reshape(-1)[valid_flat]
                direction_valid = flow_direction.reshape(-1)[valid_flat]
                all_speeds.append(speed_valid)

                if speed_variable is not None:
                    supplied_speed = (
                        _slice_2d(speed_variable, time_index, height_index).astype(np.float64)
                        * speed_factor
                    )
                    comparison = supported & np.isfinite(supplied_speed)
                    if np.any(comparison):
                        errors = np.abs(supplied_speed[comparison] - speed[comparison])
                        speed_error_max = max(speed_error_max, float(np.max(errors)))
                        speed_error_count += int(np.sum(errors > 0.05))

                if direction_variable is not None:
                    supplied_direction = _slice_2d(
                        direction_variable, time_index, height_index
                    ).astype(np.float64)
                    comparison = supported & np.isfinite(supplied_direction)
                    if np.any(comparison):
                        expected = calculate_meteorological_direction(u[comparison], v[comparison])
                        errors = circular_difference(supplied_direction[comparison], expected)
                        direction_error_max = max(direction_error_max, float(np.max(errors)))
                        direction_error_count += int(np.sum(errors > 1.0))

                quality_valid = quality.reshape(-1)[valid_flat] if quality is not None else None
                neighbor_valid = (
                    neighbor_values.reshape(-1)[valid_flat] if neighbor_values is not None else None
                )
                distance_valid = (
                    distance_values.reshape(-1)[valid_flat] if distance_values is not None else None
                )
                mean_u = float(np.mean(u_valid))
                mean_v = float(np.mean(v_valid))
                mean_speed = float(np.mean(speed_valid))
                resultant_speed = float(np.hypot(mean_u, mean_v))
                direction_resultant_ratio = (
                    resultant_speed / mean_speed if mean_speed > 1e-9 else 0.0
                )
                mean_direction = (
                    round(float(calculate_flow_direction(mean_u, mean_v)), 2)
                    if direction_resultant_ratio >= 0.1
                    else None
                )
                frame_summary = {
                    "valid_points": int(point_index.size),
                    "speed_mean": round(mean_speed, 3),
                    "speed_p25": round(float(np.percentile(speed_valid, 25)), 3),
                    "speed_p75": round(float(np.percentile(speed_valid, 75)), 3),
                    "speed_min": round(float(np.min(speed_valid)), 3),
                    "speed_max": round(float(np.max(speed_valid)), 3),
                    "flow_direction_mean": mean_direction,
                    "direction_resultant_ratio": round(direction_resultant_ratio, 3),
                    "mean_u": round(mean_u, 4),
                    "mean_v": round(mean_v, 4),
                }
                if quality_valid is not None:
                    frame_summary["quality_missing"] = int(np.sum(quality_valid == 0))
                    frame_summary["quality_low"] = int(np.sum(quality_valid == 1))
                    frame_summary["quality_acceptable"] = int(np.sum(quality_valid == 2))
                frame = {
                    "time_index": time_index,
                    "height_index": height_index,
                    "point_index": point_index.astype(int).tolist(),
                    "u": _float_list(u_valid),
                    "v": _float_list(v_valid),
                    "speed": _float_list(speed_valid),
                    "flow_direction": _float_list(direction_valid, 2),
                    "summary": frame_summary,
                }
                if quality_valid is not None:
                    frame["quality"] = quality_valid.astype(int).tolist()
                if neighbor_valid is not None:
                    neighbor_list = _nullable_int_list(neighbor_valid)
                    neighbor_metadata_missing = neighbor_metadata_missing or any(
                        value is None for value in neighbor_list
                    )
                    frame["neighbor_count"] = neighbor_list
                if distance_valid is not None:
                    distance_list = _nullable_float_list(distance_valid, 6, minimum=0.0)
                    distance_metadata_missing = distance_metadata_missing or any(
                        value is None for value in distance_list
                    )
                    frame["observation_distance_deg"] = distance_list
                frames[f"{time_index}:{height_index}"] = frame

                speed_mean[time_index][height_index] = frame_summary["speed_mean"]
                speed_p25[time_index][height_index] = frame_summary["speed_p25"]
                speed_p75[time_index][height_index] = frame_summary["speed_p75"]
                if observation_value is None:
                    coverage_value = int(point_index.size)
                    if observation_hint is not None and observation_count_variable is not None:
                        observation_hint_mismatches += 1
                else:
                    coverage_value = observation_value
                coverage[time_index][height_index] = max(0, coverage_value)
                if quality_valid is not None and quality_valid.size:
                    low_quality_ratio[time_index][height_index] = round(
                        float(np.mean(quality_valid == 1)), 4
                    )
                    acceptable_quality_ratio[time_index][height_index] = round(
                        float(np.mean(quality_valid == 2)), 4
                    )

        if unsupported_quality_points:
            warnings.append(
                f"{unsupported_quality_points} 个有限 U/V 格点的质量等级为 0，已按无受支持风场排除"
            )
        if observation_hint_mismatches:
            warnings.append(
                f"{observation_hint_mismatches} 个切片的 observation_count 与有效 U/V 不一致，覆盖数改用受支持格点数"
            )
        if neighbor_metadata_missing:
            warnings.append("部分有效格点缺少有限邻点数，报告中保留为空值")
        if distance_metadata_missing:
            warnings.append("部分有效格点缺少有限最近观测距离，报告中保留为空值")

        if not frames:
            warnings.append("全部时间高度切片均无受支持 U/V 风矢量")
            global_stats = {
                "p50": 0.0,
                "p95": 1.0,
                "p99": 1.0,
                "max": 0.0,
                "valid_points": 0,
            }
            default_time_index = time_count - 1
            default_height_index = 0
        else:
            combined_speed = np.concatenate(all_speeds)
            global_stats = {
                "p50": round(float(np.percentile(combined_speed, 50)), 3),
                "p95": max(0.1, round(float(np.percentile(combined_speed, 95)), 3)),
                "p99": round(float(np.percentile(combined_speed, 99)), 3),
                "max": round(float(np.max(combined_speed)), 3),
                "valid_points": int(combined_speed.size),
            }
            default_time_index = max(int(key.split(":")[0]) for key in frames)
            default_height_index = int(np.argmax(coverage[default_time_index]))

        if speed_error_count:
            warnings.append(
                f"wind_speed 与 U/V 推导值不一致: {speed_error_count} 个格点超过 0.05 m/s，最大误差 {speed_error_max:.3f} m/s；报告采用 U/V 推导值"
            )
        if direction_error_count:
            warnings.append(
                f"wind_direction 与 U/V 气象来向不一致: {direction_error_count} 个格点超过 1°，最大误差 {direction_error_max:.2f}°；报告采用 U/V 推导值"
            )

        epochs = [point["epoch_ms"] for point in time_points]
        positive_deltas = [right - left for left, right in zip(epochs, epochs[1:]) if right > left]
        median_delta = float(np.median(positive_deltas)) if positive_deltas else 0.0
        gap_after_indices = [
            index
            for index, (left, right) in enumerate(zip(epochs, epochs[1:]))
            if median_delta > 0 and right - left > median_delta * 1.5
        ]
        coordinates = {
            "time": time_points,
            "height_m": heights_m,
            "lat": latitudes.astype(float).tolist(),
            "lon": longitudes.astype(float).tolist(),
            "gap_after_indices": gap_after_indices,
            "median_time_step_ms": int(median_delta),
        }
        mapping = {key: value for key, value in scan.variable_names.items()}
        units = {
            "U_wind": "m/s",
            "V_wind": "m/s",
            "wind_speed": "m/s",
            "flow_direction": "degree_clockwise_from_north",
            "height": "m",
            "lat": "degree_north",
            "lon": "degree_east",
        }
        time_height = {
            "speed_mean": speed_mean,
            "speed_p25": speed_p25,
            "speed_p75": speed_p75,
            "coverage": coverage,
            "low_quality_ratio": low_quality_ratio,
            "acceptable_quality_ratio": acceptable_quality_ratio,
        }
        source_summary = _string_matrix(source_mix_variable, time_count, height_count)
        coordinate_status_summary = _string_matrix(
            coord_status_variable, time_count, height_count
        )
        return DatasetAnalysis(
            source_path=source,
            source_sha256=source_sha256(source),
            dimensions={
                "time": time_count,
                "height": height_count,
                "lat": int(latitudes.size),
                "lon": int(longitudes.size),
            },
            coordinates=coordinates,
            variable_mapping=mapping,
            variable_units=units,
            height_datum=height_datum,
            time_kind=time_kind,
            quality_status=quality_status,
            global_stats=global_stats,
            frames=frames,
            time_height=time_height,
            default_time_index=default_time_index,
            default_height_index=default_height_index,
            source_summary=source_summary,
            coordinate_status_summary=coordinate_status_summary,
            warnings=warnings,
        )


def calculate_rolling_wind_rose(
    frames: dict[str, dict[str, Any]],
    times_epoch_ms: list[int],
    current_time_index: int,
    height_index: int,
    window_minutes: int = 60,
    direction_mode: str = "flow",
) -> dict[str, Any]:
    current_epoch = times_epoch_ms[current_time_index]
    window_ms = window_minutes * 60_000
    candidates = [
        index
        for index in range(current_time_index + 1)
        if 0 <= current_epoch - times_epoch_ms[index] <= window_ms
    ]
    if len(candidates) < 2:
        return {"valid": False, "reason": "样本时次不足", "sample_count": 0}
    positive_deltas = [
        right - left
        for left, right in zip(times_epoch_ms, times_epoch_ms[1:])
        if right > left
    ]
    median_delta = float(np.median(positive_deltas)) if positive_deltas else 0.0
    gap_limit = median_delta * 1.5 if median_delta > 0 else math.inf
    segment_start = 0
    for position in range(1, len(candidates)):
        left = times_epoch_ms[candidates[position - 1]]
        right = times_epoch_ms[candidates[position]]
        if right - left > gap_limit:
            segment_start = position
    candidates = candidates[segment_start:]
    directions: list[float] = []
    speeds: list[float] = []
    used_times = 0
    for time_index in candidates:
        frame = frames.get(f"{time_index}:{height_index}")
        if frame is None:
            continue
        frame_directions = frame["flow_direction"]
        if direction_mode == "meteorological":
            frame_directions = [(value + 180.0) % 360.0 for value in frame_directions]
        directions.extend(frame_directions)
        speeds.extend(frame["speed"])
        used_times += 1
    if used_times < 2 or len(directions) < 5:
        return {"valid": False, "reason": "有效样本不足", "sample_count": len(directions)}
    speed_bins = [0.0, 2.0, 5.0, 10.0, 15.0, math.inf]
    sectors = [[0 for _ in range(5)] for _ in range(16)]
    for direction, speed in zip(directions, speeds):
        sector = int(((direction + 11.25) % 360.0) // 22.5)
        for bin_index in range(5):
            if speed_bins[bin_index] <= speed < speed_bins[bin_index + 1]:
                sectors[sector][bin_index] += 1
                break
    return {
        "valid": True,
        "sectors": sectors,
        "sample_count": len(directions),
        "time_count": used_times,
        "window_minutes": window_minutes,
        "direction_mode": direction_mode,
    }


def haversine_km(left_lon: float, left_lat: float, right_lon: float, right_lat: float) -> float:
    radius_km = 6371.0088
    lat1 = math.radians(left_lat)
    lat2 = math.radians(right_lat)
    delta_lat = lat2 - lat1
    delta_lon = math.radians(right_lon - left_lon)
    value = (
        math.sin(delta_lat / 2.0) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2.0) ** 2
    )
    return radius_km * 2.0 * math.atan2(math.sqrt(value), math.sqrt(1.0 - value))


def calculate_risk_sector(
    event: dict[str, Any],
    wind_speed: float,
    flow_direction: float,
    quality_level: int,
    risk_horizon_min: int,
    support_distance_km: float,
    max_support_distance_km: float = 10.0,
) -> dict[str, Any]:
    if quality_level <= 0:
        return {"valid": False, "reason": "无受支持风场"}
    if support_distance_km > max_support_distance_km:
        return {"valid": False, "reason": "事件附近无受支持风场"}
    if not math.isfinite(wind_speed) or not math.isfinite(flow_direction):
        return {"valid": False, "reason": "风矢量无效"}
    return {
        "valid": True,
        "event_id": str(event["id"]),
        "center_lon": float(event["lon"]),
        "center_lat": float(event["lat"]),
        "direction": float(flow_direction % 360.0),
        "radius_km": float(wind_speed * risk_horizon_min * 60.0 / 1000.0),
        "angle_width": 30 if quality_level >= 2 else 60,
        "line_style": "solid" if quality_level >= 2 else "dashed",
        "quality_level": int(quality_level),
        "support_distance_km": float(support_distance_km),
        "label": "理论平流距离",
    }


def direction_name(direction: float) -> str:
    names = (
        "北",
        "北东北",
        "东北",
        "东东北",
        "东",
        "东东南",
        "东南",
        "南东南",
        "南",
        "南西南",
        "西南",
        "西西南",
        "西",
        "西西北",
        "西北",
        "北西北",
    )
    return names[int((direction + 11.25) // 22.5) % 16]


def build_brief_lines(
    frame: dict[str, Any] | None,
    time_label: str,
    height_label: str,
    quality_status: str,
    has_events: bool,
) -> list[str]:
    if frame is None:
        return [f"时刻：{time_label}，高度：{height_label}。", "当前层无有效风场数据。"]
    summary = frame["summary"]
    lines = [f"时刻：{time_label}，高度：{height_label}。"]
    mean_direction = summary.get("flow_direction_mean")
    if mean_direction is None or not math.isfinite(float(mean_direction)):
        lines.append(
            f"风向：方向分散或静风，风速：{summary['speed_p25']:.1f}–{summary['speed_p75']:.1f} m/s。"
        )
    else:
        lines.append(
            f"风向：向{direction_name(float(mean_direction))}扩散，风速：{summary['speed_p25']:.1f}–{summary['speed_p75']:.1f} m/s。"
        )
    if quality_status == "unavailable":
        lines.append("无逐格质量信息，请结合现场观测研判。")
    elif summary.get("quality_low", 0) > summary.get("quality_acceptable", 0):
        lines.append("当前层主要为低邻点支持，请结合现场观测研判。")
    if has_events:
        lines.append("下风向图层为理论平流研判参考，不是扩散模型或安全边界。")
    return lines
