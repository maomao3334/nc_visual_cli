from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import xarray as xr


def make_dataset(
    with_time: bool = True,
    with_height: bool = True,
    with_quality: bool = True,
    empty: bool = False,
) -> xr.Dataset:
    dimensions: list[str] = []
    coordinates: dict[str, object] = {
        "lat": np.array([25.0, 24.9], dtype=np.float32),
        "lon": np.array([102.5, 102.6, 102.7], dtype=np.float32),
    }
    shape: list[int] = []
    if with_time:
        dimensions.append("time")
        coordinates["time"] = np.array(
            ["2024-04-03T09:00:00", "2024-04-03T10:00:00"], dtype="datetime64[ns]"
        )
        shape.append(2)
    if with_height:
        dimensions.append("height")
        coordinates["height"] = xr.DataArray(
            np.array([10.0, 30.0], dtype=np.float32),
            dims=("height",),
            attrs={"units": "m", "long_name": "height above ground"},
        )
        shape.append(2)
    dimensions.extend(["lat", "lon"])
    shape.extend([2, 3])
    u = np.full(shape, np.nan, dtype=np.float32)
    v = np.full(shape, np.nan, dtype=np.float32)
    if not empty:
        populated = min(12, u.size)
        u.reshape(-1)[:populated] = np.linspace(1.0, 4.0, populated, dtype=np.float32)
        v.reshape(-1)[:populated] = np.linspace(0.5, 2.0, populated, dtype=np.float32)
    variables: dict[str, object] = {
        "U_wind": (tuple(dimensions), u, {"units": "m/s"}),
        "V_wind": (tuple(dimensions), v, {"units": "m/s"}),
        "wind_speed": (tuple(dimensions), np.hypot(u, v), {"units": "m/s"}),
        "wind_direction": (
            tuple(dimensions),
            (np.degrees(np.arctan2(-u, -v)) + 360.0) % 360.0,
            {"units": "degree"},
        ),
    }
    if with_quality:
        quality = np.where(np.isfinite(u), 2, 0).astype(np.int8)
        neighbor = np.where(np.isfinite(u), 4, 0).astype(np.int16)
        distance = np.where(np.isfinite(u), 0.01, np.nan).astype(np.float32)
        variables.update(
            {
                "wind_interpolation_quality": (tuple(dimensions), quality),
                "wind_effective_neighbor_count": (tuple(dimensions), neighbor),
                "wind_nearest_observation_distance_deg": (tuple(dimensions), distance),
            }
        )
    summary_dimensions = tuple(dim for dim in dimensions if dim in {"time", "height"})
    if summary_dimensions:
        summary_shape = tuple(len(coordinates[dim]) for dim in summary_dimensions)
        variables["observation_count"] = (
            summary_dimensions,
            np.full(summary_shape, 3 if not empty else 0, dtype=np.int32),
        )
        variables["source_mix"] = (
            summary_dimensions,
            np.full(summary_shape, "test_station", dtype="U20"),
        )
        variables["coord_status_mix"] = (
            summary_dimensions,
            np.full(summary_shape, "original", dtype="U20"),
        )
    return xr.Dataset(variables, coords=coordinates)


@pytest.fixture
def dataset_factory():
    return make_dataset


@pytest.fixture
def nc_folder(tmp_path: Path, dataset_factory) -> Path:
    folder = tmp_path / "nc"
    folder.mkdir()
    dataset_factory().to_netcdf(folder / "sample.nc")
    return folder
