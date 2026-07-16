from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from nc_visual_cli.service import RunConfig, run_batch


@pytest.mark.integration
def test_real_demo_report_is_compact_and_complete(tmp_path: Path):
    source = Path(__file__).parents[1] / "demo_data"
    started = time.perf_counter()
    result = run_batch(RunConfig(folder=source, output=tmp_path / "report"))
    elapsed = time.perf_counter() - started
    assert result.success is True
    assert elapsed < 15
    html_path = Path(result.results[0]["html_path"])
    assert html_path.stat().st_size < 5 * 1024 * 1024
    manifest = json.loads(Path(result.results[0]["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["dimensions"] == {"time": 13, "height": 237, "lat": 24, "lon": 47}
    assert manifest["quality"]["status"] == "provided"
    html = html_path.read_text(encoding="utf-8")
    assert "fetch(" not in html
    assert "XMLHttpRequest" not in html
    assert "https://" not in html.replace("http://www.w3.org/2000/svg", "")
