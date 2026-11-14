"""Smoke tests: the Streamlit app renders every view without an exception."""

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from conftest import DATA, ROOT

APP = str(ROOT / "app" / "app.py")
SERIES = ["harmonized", "viirs_snpp", "terra", "aqua"]
SEASONS = ["Oct–Nov (rice-residue season)", "Apr–May (wheat-residue and forest-fire season)", "Whole year"]


def run(**state) -> AppTest:
    app = AppTest.from_file(APP, default_timeout=300)
    for key, value in state.items():
        app.session_state[key] = value
    app.run()
    assert not app.exception, [str(e.value) for e in app.exception]
    return app


def metric(app: AppTest, label: str) -> str:
    return next(m.value for m in app.metric if m.label.startswith(label))


def all_districts() -> list[tuple[str, str]]:
    table = pd.read_csv(DATA / "district_monthly.csv", usecols=["state", "district"])
    return sorted(set(zip(table["state"], table["district"])))


@pytest.mark.parametrize("state,district", all_districts())
def test_every_district_renders(state, district):
    run(state=state, district=district)


@pytest.mark.parametrize("series", SERIES)
@pytest.mark.parametrize("comparison", ["After harmonization", "As recorded", "MODIS-only check"])
def test_series_and_comparison_views(series, comparison):
    run(state="Punjab", district="Ludhiana", sensor=series, comparison_view=comparison,
        calendar_value="Activity (share of clear land)")


@pytest.mark.parametrize("series", SERIES)
@pytest.mark.parametrize("season", SEASONS)
def test_trend_seasons_and_trend_map(series, season):
    run(state="Uttarakhand", district="Naini Tal", sensor=series, map_mode="Trend",
        trend_season_Uttarakhand=season, fire_type_view="By year")


@pytest.mark.parametrize("dates", [
    ((2026, 12), (2026, 12)),  # nothing observed yet
    ((2026, 11), (2026, 12)),  # only a partial month
    ((2016, 1), (2016, 1)),    # a single month
    ((2020, 1), (2023, 12)),   # too few seasons for a trend test
    ((2022, 6), (2023, 6)),
])
@pytest.mark.parametrize("series", ["harmonized", "terra"])
def test_awkward_date_ranges(dates, series):
    run(state="Punjab", district="Bathinda", sensor=series, dates=dates, map_mode="Trend")


def test_headline_trend_for_ludhiana():
    app = run(state="Punjab", district="Ludhiana")
    assert metric(app, "Trend") == "Decreasing"
    assert metric(app, "Sen's slope").endswith("% per year")
    assert any("orbits drifted" in w.value for w in app.warning)  # the detection caveat is shown


def test_trend_needs_enough_seasons():
    app = run(state="Punjab", district="Ludhiana", dates=((2020, 1), (2023, 12)))
    assert any("at least 8 complete seasons" in i.value for i in app.info)


def test_fire_type_views():
    app = run(state="Punjab", district="Bathinda")
    assert any("Cropland" in m.value and "Static sources" in m.value for m in app.markdown)
    assert len(app.dataframe) == 1  # Bathinda's static-source pixels are listed
    app = run(state="Haryana", district="Ambala")  # outside the land-cover export
    assert any("Fire type is not available for Ambala" in i.value for i in app.info)


def test_map_click_opens_the_district():
    app = run(pending_pick=("Uttarakhand", "Dehra Dun"))
    assert app.session_state["district"] == "Dehra Dun"


def test_downloads_and_citation_panel():
    app = run(state="Punjab", district="Ludhiana")
    labels = [b.proto.label for b in app.get("download_button")]
    for expected in ("Download harmonized CSV", "Download per-sensor CSV", "Download hotspots CSV",
                     "Download all data (ZIP)", "Download trend table (all districts) CSV"):
        assert expected in labels
    assert any("How to cite" in e.label for e in app.expander)
    assert any("10.5067/VIIRS/VNP14A1.002" in m.value for m in app.markdown)
