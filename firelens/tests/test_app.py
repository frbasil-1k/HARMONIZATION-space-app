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



def test_hotspot_download_is_enabled():
    """With data/hotspots.csv.gz present, the Download hotspots CSV button is live."""
    if not (DATA / "hotspots.csv.gz").exists():
        pytest.skip("hotspot list not generated in this checkout")
    app = run(state="Punjab", district="Ludhiana", dates=((2020, 10), (2020, 11)))
    button = next(b for b in app.get("download_button") if b.proto.label == "Download hotspots CSV")
    assert not button.proto.disabled


def test_changed_data_file_is_read_again(monkeypatch):
    """A new commit of a data file must reach a running app (Streamlit Cloud reloads code
    without restarting, and st.cache_data keys on the path, not the contents)."""
    import os

    reads = []
    real_read_csv = pd.read_csv

    def counting_read_csv(path, *args, **kwargs):
        reads.append(str(path))
        return real_read_csv(path, *args, **kwargs)

    monkeypatch.setattr(pd, "read_csv", counting_read_csv)
    app = run(state="Punjab", district="Ludhiana")
    reads.clear()
    app.run()
    assert not any("district_harmonized" in r for r in reads)  # unchanged: served from cache
    target = DATA / "district_harmonized.csv"
    stat = target.stat()
    try:
        os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
        app.run()
        assert not app.exception
        assert any("district_harmonized" in r for r in reads)  # changed: read again
    finally:
        os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns))


def test_opening_view_and_region_context():
    """First impression: Ludhiana, and the region-wide fall explained, not left to look broken."""
    app = run()
    assert (app.session_state["state"], app.session_state["district"]) == ("Punjab", "Ludhiana")
    context = [i.value for i in app.info if i.value.startswith("Region-wide:")]
    assert context and "Commission for Air Quality Management" in context[0]  # Oct 2026, Punjab


def test_snpp_end_is_explained():
    app = run(state="Punjab", district="Ludhiana", sensor="viirs_snpp")
    assert any("Suomi-NPP data ended on 2 Nov 2026" in c.value for c in app.caption)


@pytest.mark.parametrize("state,district,expect", [
    ("Punjab", "Ludhiana", "Commission for Air Quality Management"),  # low, rice belt: note + CAQM
    ("Uttarakhand", "Rudra Prayag", None),  # no October comparison: no note at all
])
def test_region_note_fits_the_district(state, district, expect):
    app = run(state=state, district=district)
    notes = [i.value for i in app.info if i.value.startswith("Region-wide:")]
    if expect is None:
        assert not notes
    else:
        assert notes and expect in notes[0]


def test_region_note_names_punjab_counts_only_in_the_rice_belt():
    """An Uttarakhand district below its usual October gets the note, not Punjab's count."""
    for district in ("Dehra Dun", "Haridwar", "Udham Singh Nagar", "Naini Tal"):
        app = run(state="Uttarakhand", district=district)
        notes = [i.value for i in app.info if i.value.startswith("Region-wide:")]
        if notes:
            assert "Commission for Air Quality Management" not in notes[0]
            return
    pytest.skip("no Uttarakhand district below half its usual October in this data")



def test_maps_refit_once_sized():
    """Both maps carry the refit script, bound to the map streamlit-folium builds.

    Without it the deployed map sometimes opened on the whole world: the fit ran before
    the frame had its final width.
    """
    import json
    import sys

    from streamlit_folium import generate_leaflet_string

    sys.path.insert(0, str(ROOT / "app"))
    source = (ROOT / "app" / "app.py").read_text(encoding="utf-8").replace("\nmain()\n", "\n")
    module = {"__file__": str(ROOT / "app" / "app.py"), "__name__": "app_for_test"}
    exec(compile(source, "app.py", "exec"), module)
    geo = json.loads((DATA / "districts.geojson").read_text(encoding="utf-8"))
    for m in (module["overview_map"](geo, {}, ("Punjab", "Ludhiana")), module["area_map"](geo, None)):
        script = generate_leaflet_string(m)
        assert "var map = map_div;" in script and "invalidateSize" in script
        assert "window.addEventListener(\"resize\", refit)" in script
