from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from nc_visual_cli.service import RunConfig, run_batch


def test_batch_and_latest_only(tmp_path: Path, dataset_factory):
    folder = tmp_path / "batch"
    folder.mkdir()
    dataset_factory().to_netcdf(folder / "a.nc")
    dataset_factory().to_netcdf(folder / "b.nc")
    batch = run_batch(RunConfig(folder=folder, output=tmp_path / "all"))
    assert batch.success is True
    assert len(batch.results) == 2
    latest = run_batch(
        RunConfig(folder=folder, output=tmp_path / "latest", latest_only=True)
    )
    assert latest.success is True
    assert len(latest.results) == 1


def test_cli_json_stdout_is_one_document(nc_folder: Path, tmp_path: Path):
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "nc_visual_cli",
            str(nc_folder),
            "--output",
            str(tmp_path / "reports"),
            "--json",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        check=False,
    )
    assert completed.returncode == 0
    document = json.loads(completed.stdout)
    assert document["schema_version"] == "2.0.0"
    assert document["success"] is True
    assert completed.stderr == ""


def test_cli_missing_folder_returns_input_code(tmp_path: Path):
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")
    completed = subprocess.run(
        [sys.executable, "-m", "nc_visual_cli", str(tmp_path / "missing"), "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        check=False,
    )
    assert completed.returncode == 2
    assert json.loads(completed.stdout)["error_type"] == "InputError"


def test_cli_partial_batch_returns_partial_code(tmp_path: Path, dataset_factory):
    folder = tmp_path / "partial"
    folder.mkdir()
    dataset_factory().to_netcdf(folder / "good.nc")
    (folder / "bad.nc").write_text("not a NetCDF file", encoding="utf-8")
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "nc_visual_cli",
            str(folder),
            "--output",
            str(tmp_path / "reports"),
            "--json",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        check=False,
    )
    document = json.loads(completed.stdout)
    assert completed.returncode == 4
    assert document["success"] is False
    assert document["partial"] is True
    assert {item["success"] for item in document["results"]} == {True, False}
    assert completed.stderr == ""


@pytest.mark.parametrize(
    "invalid_arguments",
    [
        ["--theme", "neon"],
        ["--risk-horizon-min", "0"],
        ["--max-event-wind-distance-km", "NaN"],
        ["--max-event-wind-distance-km", "Infinity"],
    ],
)
def test_cli_argument_errors_preserve_json_contract(
    nc_folder: Path, invalid_arguments: list[str]
):
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "nc_visual_cli",
            str(nc_folder),
            *invalid_arguments,
            "--json",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        check=False,
    )
    document = json.loads(completed.stdout)
    assert completed.returncode == 2
    assert document["success"] is False
    assert document["error_type"] == "InputError"
    assert completed.stderr == ""


def test_cli_global_configuration_errors_return_input_code(nc_folder: Path, tmp_path: Path):
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")
    output_file = tmp_path / "not-a-folder.txt"
    output_file.write_text("occupied", encoding="utf-8")
    cases = [
        ["--timezone", "Invalid/Zone"],
        ["--timezone", "../UTC"],
        ["--output", str(output_file)],
    ]
    for arguments in cases:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "nc_visual_cli",
                str(nc_folder),
                *arguments,
                "--json",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=environment,
            check=False,
        )
        assert completed.returncode == 2
        assert json.loads(completed.stdout)["error_type"] == "InputError"
        assert completed.stderr == ""
