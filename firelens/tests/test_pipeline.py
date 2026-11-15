"""The science scripts reproduce the committed files from the committed input."""

import pandas as pd
import pytest

import fire_types
import harmonize
from conftest import DATA


def test_harmonize_reproduces_committed_file(tmp_path):
    out, report = tmp_path / "harmonized.csv", tmp_path / "validation.md"
    assert harmonize.main(["--input", str(DATA / "district_monthly.csv"),
                           "--output", str(out), "--validation", str(report)]) == 0
    pd.testing.assert_frame_equal(pd.read_csv(out), pd.read_csv(DATA / "district_harmonized.csv"),
                                  rtol=1e-9, atol=1e-12)
    assert "Leave-one-year-out" in report.read_text(encoding="utf-8")


def test_harmonize_skill_has_not_regressed():
    """Leave-one-year-out against VIIRS: the numbers the README quotes."""
    result = harmonize.evaluate(harmonize.load_monthly(DATA / "district_monthly.csv"))
    new = result["comparison"][result["comparison"]["method"].str.startswith("v2")].set_index("sensor")
    assert new.loc["terra", "r"] > 0.88 and new.loc["aqua", "r"] > 0.96
    assert new["peak_bias"].between(0.93, 1.07).all()
    assert result["recon"]["r"] > 0.95 and 0.95 < result["recon"]["bias"] < 1.05


def test_area_covered_geometry():
    square = {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]}
    assert fire_types.area_covered(square, zones=((0, 0, 1, 2),)) == pytest.approx(0.5)
    assert fire_types.area_covered(square, zones=((-1, -1, 3, 3),)) == pytest.approx(1.0)
    assert fire_types.area_covered(square, zones=((5, 5, 6, 6),)) == 0.0
    holed = {"type": "Polygon", "coordinates": [[[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]],
                                                [[1, 1], [3, 1], [3, 3], [1, 3], [1, 1]]]}
    assert fire_types.area_covered(holed, zones=((0, 0, 2, 4),)) == pytest.approx(0.5)


def test_fire_types_reproduces_committed_file(tmp_path, monkeypatch):
    raw = DATA / "raw" / "firepulse_india_all.csv"
    if not raw.exists():
        pytest.skip("raw hotspot export not present (285 MB, not committed)")
    for name in ("OUT_TYPES", "OUT_STATIC", "OUT_REPORT"):
        monkeypatch.setattr(fire_types, name, tmp_path / getattr(fire_types, name).name)
    assert fire_types.main(["--input", str(raw)]) == 0
    for name in ("district_fire_types.csv", "static_sources.csv"):
        pd.testing.assert_frame_equal(pd.read_csv(tmp_path / name), pd.read_csv(DATA / name))


def test_fire_types_reads_a_repeat_download_once(tmp_path):
    """Drive's "name (1).csv" copies must not double-count hotspots."""
    names = ["fl_ctx_aqua_2020.csv", "fl_ctx_aqua_2020 (1).csv", "fl_ctx_aqua_2021 (1).csv"]
    files = [tmp_path / n for n in names]
    kept = [f.name for f in fire_types.unique_files(files)]
    assert kept == ["fl_ctx_aqua_2020.csv", "fl_ctx_aqua_2021 (1).csv"]  # a lone copy is kept

