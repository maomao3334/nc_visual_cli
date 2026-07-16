from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from nc_visual_cli.offline_report import render_offline_report
from nc_visual_cli.report_contract import build_report_contract
from nc_visual_cli.scanner import scan_folder
from nc_visual_cli.wind_analysis import analyze_dataset


def test_analysis_builds_sparse_frames(nc_folder: Path):
    scan = scan_folder(nc_folder)[0]
    analysis = analyze_dataset(scan.path, scan)
    assert analysis.dimensions == {"time": 2, "height": 2, "lat": 2, "lon": 3}
    assert analysis.height_datum == "AGL"
    assert analysis.quality_status == "provided"
    assert analysis.frames
    assert len(analysis.frames["0:0"]["point_index"]) == 6
    assert analysis.global_stats["valid_points"] == 12
    assert analysis.default_time_index == 0


def test_no_time_height_or_quality_degrades_explicitly(tmp_path: Path, dataset_factory):
    folder = tmp_path / "static"
    folder.mkdir()
    path = folder / "static.nc"
    dataset_factory(with_time=False, with_height=False, with_quality=False).to_netcdf(path)
    scan = scan_folder(folder)[0]
    analysis = analyze_dataset(path, scan)
    assert analysis.time_kind == "absent"
    assert analysis.height_datum == "UNKNOWN"
    assert analysis.quality_status == "unavailable"
    assert analysis.coordinates["time"][0]["label"] == "无时间维（静态场）"
    assert any("无逐格质量" in warning for warning in analysis.warnings)


def test_render_single_and_script_chunk_modes(nc_folder: Path, tmp_path: Path):
    scan = scan_folder(nc_folder)[0]
    analysis = analyze_dataset(scan.path, scan)
    manifest = build_report_contract(analysis)
    single = render_offline_report(manifest, analysis, tmp_path / "single")
    assert single.mode == "single_file"
    assert single.html_path.is_file()
    assert "window.__NCV_BOOTSTRAP__" in single.html_path.read_text(encoding="utf-8")
    manifest = build_report_contract(analysis)
    chunked = render_offline_report(
        manifest, analysis, tmp_path / "chunked", split_threshold_mb=0.000001
    )
    assert chunked.mode == "script_chunks"
    assert chunked.html_path.is_file()
    assert list((chunked.html_path.parent / "chunks").glob("data_*.js"))
    document = json.loads(chunked.manifest_path.read_text(encoding="utf-8"))
    assert document["outputs"]["mode"] == "script_chunks"


def test_render_mode_switch_removes_stale_counterpart(nc_folder: Path, tmp_path: Path):
    scan = scan_folder(nc_folder)[0]
    analysis = analyze_dataset(scan.path, scan)
    output = tmp_path / "switch"

    chunked = render_offline_report(
        build_report_contract(analysis), analysis, output, split_threshold_mb=0.000001
    )
    single_path = output / "sample_report.html"
    report_dir = output / "sample_report"
    assert report_dir.is_dir()
    assert not single_path.exists()

    render_offline_report(build_report_contract(analysis), analysis, output)
    assert single_path.is_file()
    assert not report_dir.exists()

    render_offline_report(
        build_report_contract(analysis), analysis, output, split_threshold_mb=0.000001
    )
    assert report_dir.is_dir()
    assert not single_path.exists()


def test_zero_observation_hint_does_not_discard_supported_uv(
    tmp_path: Path, dataset_factory
):
    folder = tmp_path / "zero-hint"
    folder.mkdir()
    dataset = dataset_factory()
    dataset["observation_count"].values[:] = 0
    path = folder / "zero_hint.nc"
    dataset.to_netcdf(path)

    analysis = analyze_dataset(path, scan_folder(folder)[0])
    assert analysis.frames
    assert analysis.global_stats["valid_points"] == 12
    assert any("observation_count" in warning for warning in analysis.warnings)


def test_nonfinite_optional_metadata_serializes_as_null(tmp_path: Path, dataset_factory):
    folder = tmp_path / "optional-nan"
    folder.mkdir()
    dataset = dataset_factory()
    dataset["wind_effective_neighbor_count"] = dataset[
        "wind_effective_neighbor_count"
    ].astype(np.float64)
    dataset["wind_effective_neighbor_count"].values.reshape(-1)[0] = np.nan
    dataset["wind_nearest_observation_distance_deg"].values.reshape(-1)[0] = np.nan
    path = folder / "optional_nan.nc"
    dataset.to_netcdf(path)

    scan = scan_folder(folder)[0]
    analysis = analyze_dataset(path, scan)
    frame = analysis.frames["0:0"]
    assert frame["neighbor_count"][0] is None
    assert frame["observation_distance_deg"][0] is None
    report = render_offline_report(build_report_contract(analysis), analysis, tmp_path / "report")
    assert report.html_path.is_file()


def test_single_cell_grid_preserves_spatial_dimensions(tmp_path: Path, dataset_factory):
    folder = tmp_path / "single-cell"
    folder.mkdir()
    dataset = dataset_factory(with_time=False, with_height=False).isel(
        lat=slice(0, 1), lon=slice(0, 1)
    )
    path = folder / "single_cell.nc"
    dataset.to_netcdf(path)

    analysis = analyze_dataset(path, scan_folder(folder)[0])
    assert analysis.dimensions["lat"] == 1
    assert analysis.dimensions["lon"] == 1
    assert analysis.frames["0:0"]["summary"]["valid_points"] == 1


def test_quality_zero_is_excluded_and_opposing_flow_has_no_mean_direction(
    tmp_path: Path, dataset_factory
):
    quality_folder = tmp_path / "quality-zero"
    quality_folder.mkdir()
    quality_dataset = dataset_factory(with_time=False, with_height=False)
    quality_dataset["wind_interpolation_quality"].values[:] = 0
    quality_path = quality_folder / "quality_zero.nc"
    quality_dataset.to_netcdf(quality_path)
    quality_analysis = analyze_dataset(quality_path, scan_folder(quality_folder)[0])
    assert not quality_analysis.frames
    assert any("质量等级为 0" in warning for warning in quality_analysis.warnings)

    direction_folder = tmp_path / "opposing"
    direction_folder.mkdir()
    direction_dataset = dataset_factory(with_time=False, with_height=False)
    direction_dataset["U_wind"].values[:] = np.array(
        [[5.0, -5.0, 5.0], [-5.0, 5.0, -5.0]], dtype=np.float32
    )
    direction_dataset["V_wind"].values[:] = 0.0
    direction_path = direction_folder / "opposing.nc"
    direction_dataset.to_netcdf(direction_path)
    direction_analysis = analyze_dataset(direction_path, scan_folder(direction_folder)[0])
    assert direction_analysis.frames["0:0"]["summary"]["flow_direction_mean"] is None
