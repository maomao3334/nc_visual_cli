from __future__ import annotations

import json
from pathlib import Path

import pytest

from nc_visual_cli.errors import InputError
from nc_visual_cli.provenance import load_boundary, load_points
from nc_visual_cli.scanner import scan_folder, select_best


def test_scanner_only_reads_first_level(nc_folder: Path, dataset_factory):
    nested = nc_folder / "nested"
    nested.mkdir()
    dataset_factory().to_netcdf(nested / "ignored.nc")
    (nc_folder / "broken.nc").write_text("not a netcdf", encoding="utf-8")
    results = scan_folder(nc_folder)
    assert {item.path.name for item in results} == {"sample.nc", "broken.nc"}
    assert select_best(results).path.name == "sample.nc"
    assert next(item for item in results if item.path.name == "broken.nc").compatible is False


def test_geojson_points_are_strict(tmp_path: Path):
    valid = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "id": "fire-1",
                    "name": "测试火点",
                    "type": "fire",
                    "start_time": "2024-04-03T09:00:00+08:00",
                },
                "geometry": {"type": "Point", "coordinates": [102.6, 24.9]},
            }
        ],
    }
    path = tmp_path / "events.geojson"
    path.write_text(json.dumps(valid, ensure_ascii=False), encoding="utf-8")
    assert load_points(path, "events")[0]["name"] == "测试火点"
    valid["features"][0]["properties"].pop("start_time")
    path.write_text(json.dumps(valid, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(InputError, match="start_time"):
        load_points(path, "events")


def test_boundary_rejects_point_geometry(tmp_path: Path):
    path = tmp_path / "boundary.geojson"
    path.write_text(json.dumps({"type": "Point", "coordinates": [0, 0]}), encoding="utf-8")
    with pytest.raises(InputError, match="不支持"):
        load_boundary(path)


def test_geojson_points_reject_malformed_coordinates_and_times(tmp_path: Path):
    document = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "id": "fire-1",
                    "name": "测试火点",
                    "type": "fire",
                    "start_time": "2024-04-03T09:00:00+08:00",
                },
                "geometry": {"type": "Point", "coordinates": "12"},
            }
        ],
    }
    path = tmp_path / "malformed.geojson"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(InputError, match="坐标必须"):
        load_points(path, "events")

    document["features"][0]["geometry"]["coordinates"] = [102.6, 24.9]
    document["features"][0]["properties"]["start_time"] = "not-a-time"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(InputError, match="ISO-8601"):
        load_points(path, "events")


@pytest.mark.parametrize(
    "document",
    [
        None,
        [],
        {"type": "FeatureCollection"},
        {"type": "FeatureCollection", "features": []},
        {
            "type": "Feature",
            "properties": {},
            "geometry": {"type": "Point", "coordinates": [102.6, 24.9]},
        },
    ],
)
def test_boundary_rejects_invalid_document_shapes(tmp_path: Path, document):
    path = tmp_path / "invalid-boundary.geojson"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(InputError):
        load_boundary(path)
