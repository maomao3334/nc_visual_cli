from __future__ import annotations

from datetime import datetime
from pathlib import Path

import xarray as xr

from .errors import InputError
from .models import ScanResult

COORDINATE_ALIASES: dict[str, tuple[str, ...]] = {
    "lat": ("lat", "latitude"),
    "lon": ("lon", "longitude"),
    "time": ("time", "datetime", "valid_time"),
    "height": ("height", "altitude", "level", "z"),
}

VARIABLE_ALIASES: dict[str, tuple[str, ...]] = {
    "U_wind": ("U_wind", "u_wind", "eastward_wind", "u"),
    "V_wind": ("V_wind", "v_wind", "northward_wind", "v"),
    "wind_speed": ("wind_speed", "windspeed", "speed"),
    "wind_direction": ("wind_direction", "wind_dir", "direction"),
    "quality": ("wind_interpolation_quality", "wind_quality", "quality"),
    "neighbor_count": ("wind_effective_neighbor_count", "neighbor_count"),
    "observation_distance": (
        "wind_nearest_observation_distance_deg",
        "nearest_observation_distance",
    ),
    "observation_count": ("observation_count", "obs_count"),
    "source_mix": ("source_mix",),
    "coord_status_mix": ("coord_status_mix",),
}


def _find_name(candidates: tuple[str, ...], available: set[str]) -> str | None:
    lowered = {name.casefold(): name for name in available}
    for candidate in candidates:
        match = lowered.get(candidate.casefold())
        if match is not None:
            return match
    return None


def _inspect_file(path: Path) -> ScanResult:
    result = ScanResult(
        path=path.resolve(),
        size_bytes=path.stat().st_size,
        modified_at=datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(),
    )
    try:
        with xr.open_dataset(path, decode_times=False) as dataset:
            available = set(dataset.variables) | set(dataset.dims)
            result.dimensions = {name: int(size) for name, size in dataset.sizes.items()}
            result.variables = sorted(dataset.data_vars)
            for canonical, aliases in COORDINATE_ALIASES.items():
                name = _find_name(aliases, available)
                if name:
                    result.coordinate_names[canonical] = name
            for canonical, aliases in VARIABLE_ALIASES.items():
                name = _find_name(aliases, set(dataset.data_vars))
                if name:
                    result.variable_names[canonical] = name

            required_coordinates = {"lat", "lon"}
            required_variables = {"U_wind", "V_wind"}
            missing_coordinates = required_coordinates - result.coordinate_names.keys()
            missing_variables = required_variables - result.variable_names.keys()
            if missing_coordinates:
                result.error = "缺少坐标: " + ", ".join(sorted(missing_coordinates))
                return result
            if missing_variables:
                result.error = "缺少风矢量变量: " + ", ".join(sorted(missing_variables))
                return result

            lat_name = result.coordinate_names["lat"]
            lon_name = result.coordinate_names["lon"]
            if dataset[lat_name].ndim != 1 or dataset[lon_name].ndim != 1:
                result.error = "首版仅支持一维规则 lat/lon 坐标"
                return result

            score = 100
            score += 15 if "time" in result.coordinate_names else 0
            score += 15 if "height" in result.coordinate_names else 0
            score += 10 if "wind_speed" in result.variable_names else 0
            score += 5 if "wind_direction" in result.variable_names else 0
            quality_keys = {"quality", "neighbor_count", "observation_distance"}
            quality_count = len(quality_keys & result.variable_names.keys())
            score += quality_count * 10
            score += 10 if "observation_count" in result.variable_names else 0
            score += 5 if "source_mix" in result.variable_names else 0
            score += 5 if "coord_status_mix" in result.variable_names else 0
            result.has_quality = quality_count > 0
            result.score = score
            result.compatible = True
            if "time" not in result.coordinate_names:
                result.warnings.append("无时间维，将生成单帧静态报告")
            if "height" not in result.coordinate_names:
                result.warnings.append("无高度维，将标记高度基准未知")
            if not result.has_quality:
                result.warnings.append("无逐格质量字段，不会默认标记为高可信")
    except Exception as exc:
        result.error = f"无法读取 NetCDF: {exc}"
    return result


def scan_folder(folder: str | Path) -> list[ScanResult]:
    path = Path(folder).expanduser()
    if not path.exists():
        raise InputError(f"输入文件夹不存在: {path}")
    if not path.is_dir():
        raise InputError(f"输入路径不是文件夹: {path}")
    nc_paths = sorted(
        (item for item in path.iterdir() if item.is_file() and item.suffix.casefold() == ".nc"),
        key=lambda item: item.name.casefold(),
    )
    if not nc_paths:
        raise InputError(f"输入文件夹第一层没有 .nc 文件: {path}")
    return [_inspect_file(item) for item in nc_paths]


def select_best(results: list[ScanResult]) -> ScanResult:
    compatible = [item for item in results if item.compatible]
    if not compatible:
        details = "; ".join(f"{item.path.name}: {item.error}" for item in results)
        raise InputError(f"没有兼容的 NetCDF 文件。{details}")
    return max(compatible, key=lambda item: (item.score, item.path.stat().st_mtime, item.path.name))
