"""Draw-an-area: geometry (app/area.py) and the area page of the app."""

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import area
from conftest import DATA, ROOT

APP = str(ROOT / "app" / "app.py")
LUDHIANA_BOX = area.box_geometry(30.70, 75.60, 31.05, 76.20)  # south, west, north, east


def test_point_in_polygon_with_hole_and_open_ring():
    holed = {"type": "Polygon", "coordinates": [
        [[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]],
        [[1, 1], [3, 1], [3, 3], [1, 3], [1, 1]]]}
    lon = np.array([0.5, 2.0, 3.5, 5.0, 2.0])
    lat = np.array([0.5, 2.0, 3.5, 2.0, 0.5])
    assert area.area_contains(holed, lon, lat).tolist() == [True, False, True, False, True]
    open_triangle = {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [1, 2]]]}  # not closed
    assert area.area_contains(open_triangle, [1.0, 1.9], [0.5, 1.5]).tolist() == [True, False]


def test_multipolygon_and_bad_input():
    two = {"type": "MultiPolygon", "coordinates": [
        [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]], [[[5, 5], [6, 5], [6, 6], [5, 6], [5, 5]]]]}
    assert area.area_contains(two, [0.5, 5.5, 3.0], [0.5, 5.5, 3.0]).tolist() == [True, True, False]
    assert not area.valid_area({"type": "Point", "coordinates": [75, 30]})
    assert not area.valid_area(None)
    assert area.valid_area(LUDHIANA_BOX)


def test_area_km2():
    # 0.6 degrees of longitude x 0.35 of latitude at ~30.9 N
    expected = 0.6 * 111.32 * np.cos(np.radians(30.875)) * 0.35 * 111.32
    assert area.area_km2(LUDHIANA_BOX) == pytest.approx(expected, rel=0.01)


def test_area_counts_match_an_independent_filter():
    hotspots = pd.read_csv(DATA / "hotspots.csv.gz") if (DATA / "hotspots.csv.gz").exists() else None
    if hotspots is None:
        pytest.skip("hotspot list not generated in this checkout")
    inside = area.area_contains(LUDHIANA_BOX, hotspots["longitude"].to_numpy(), hotspots["latitude"].to_numpy())
    box = hotspots["latitude"].between(30.70, 31.05) & hotspots["longitude"].between(75.60, 76.20)
    assert inside.sum() == box.sum() > 10_000


def run(**state) -> AppTest:
    app = AppTest.from_file(APP, default_timeout=300)
    app.session_state["area_mode"] = "Draw an area"
    for key, value in state.items():
        app.session_state[key] = value
    app.run()
    assert not app.exception, [str(e.value) for e in app.exception]
    return app


def test_area_page_without_an_area_asks_for_one():
    app = run()
    assert any("Draw a box or polygon" in i.value for i in app.info)


@pytest.mark.parametrize("sensor", ["viirs_snpp", "aqua", "terra"])
def test_area_page_for_each_satellite(sensor):
    if not (DATA / "hotspots.csv.gz").exists():
        pytest.skip("hotspot list not generated in this checkout")
    app = run(drawn_area=LUDHIANA_BOX, area_sensor=sensor)
    assert any("Your area" in m.value and "Ludhiana" in m.value for m in app.markdown)
    labels = [b.proto.label for b in app.get("download_button")]
    assert any(label.startswith("Download the ") and "hotspots in this area" in label for label in labels)
    assert "Download the area (GeoJSON)" in labels
    assert any(m.label.startswith("Trend") for m in app.metric)


def test_area_outside_the_coverage():
    app = run(drawn_area=area.box_geometry(26.0, 70.0, 27.0, 71.0))  # Rajasthan
    assert any("outside the 49 districts" in w.value for w in app.warning)


def test_area_partly_outside_warns_and_still_works():
    if not (DATA / "hotspots.csv.gz").exists():
        pytest.skip("hotspot list not generated in this checkout")
    app = run(drawn_area=area.box_geometry(29.0, 72.5, 30.5, 75.0))
    assert any("lies inside the 49 districts" in w.value for w in app.warning)


@pytest.mark.parametrize("dates", [((2026, 12), (2026, 12)), ((2020, 1), (2021, 12))])
def test_area_awkward_dates(dates):
    run(drawn_area=LUDHIANA_BOX, dates=dates)


def test_typed_box():
    app = run()
    app.button(key="box_use").click().run()
    assert not app.exception
    assert any("Your area" in m.value for m in app.markdown)
