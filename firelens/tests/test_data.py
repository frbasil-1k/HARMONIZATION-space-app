"""The committed data files against the data contract (docs/data-contract.md)."""

import json

import numpy as np
import pandas as pd
import pytest

from conftest import DATA

KEYS = ["state", "district", "year", "month"]
SOURCES = {"blend", "viirs", "modis_fill", "modis_fill_drift", "none"}


@pytest.fixture(scope="module")
def monthly():
    return pd.read_csv(DATA / "district_monthly.csv")


@pytest.fixture(scope="module")
def harmonized():
    return pd.read_csv(DATA / "district_harmonized.csv")


@pytest.fixture(scope="module")
def fire_types():
    return pd.read_csv(DATA / "district_fire_types.csv")


def test_monthly_grid_is_rectangular(monthly):
    districts = monthly[["state", "district"]].drop_duplicates()
    assert len(districts) == 49
    assert len(monthly) == 49 * 3 * 132
    assert not monthly.duplicated(KEYS + ["sensor"]).any()
    assert (monthly["fire_pixel_days"] <= monthly["clear_pixel_days"]).all()


def test_boundaries_match_the_tables(monthly):
    geo = json.loads((DATA / "districts.geojson").read_text(encoding="utf-8"))
    in_geo = {(f["properties"]["state"].strip(), f["properties"]["district"].strip()) for f in geo["features"]}
    assert in_geo == set(zip(monthly["state"], monthly["district"]))


def test_harmonized_contract(harmonized, monthly):
    h = harmonized
    assert len(h) == 49 * 132 and not h.duplicated(KEYS).any()
    assert set(h["source"]) <= SOURCES
    valid = h["act_harmonized"].notna()
    assert (valid == (h["source"] != "none")).all()
    assert h.loc[valid, "act_harmonized"].between(0, 1).all()
    # A month VIIRS saw is never filled from MODIS.
    assert h.loc[h["viirs_act"].notna(), "source"].isin(["blend", "viirs"]).all()
    # After the drift, MODIS is not blended with VIIRS.
    assert not ((h["source"] == "blend") & (h["year"] * 12 + h["month"] >= 2023 * 12 + 2)).any()


def test_uncertainty_columns(harmonized):
    h = harmonized
    valid = h["act_harmonized"].notna()
    assert (h.loc[valid, "n_blended"] >= 1).all() and (h.loc[~valid, "n_blended"] == 0).all()
    assert (h["n_blended"] <= h["n_valid_sensors"]).all()
    eps = 1e-12
    assert (h.loc[valid, "sensor_min"] <= h.loc[valid, "act_harmonized"] + eps).all()
    assert (h.loc[valid, "act_harmonized"] <= h.loc[valid, "sensor_max"] + eps).all()
    assert h.loc[valid, "clear_coverage"].between(0.10, 1.0).all()


def test_harmonized_stays_on_the_viirs_scale(harmonized):
    """The reason for v2: in burning season the blend must not sit below (or above) VIIRS."""
    h = harmonized[(harmonized["state"] == "Punjab") & harmonized["month"].isin([10, 11])
                   & harmonized["year"].between(2016, 2025)]
    by_year = h.groupby("year")[["act_harmonized", "viirs_act"]].sum()
    ratio = by_year["act_harmonized"] / by_year["viirs_act"]
    assert ratio.between(0.80, 1.20).all(), ratio.round(2).to_dict()


def test_fire_types_contract(fire_types, monthly):
    t = fire_types
    parts = ["n_cropland", "n_forest", "n_woodland_grass", "n_other", "n_static"]
    assert not t.duplicated(KEYS + ["sensor"]).any()
    assert (t[parts].sum(axis=1) == t["n_hotspots"]).all()
    assert (t[parts] >= 0).all().all() and (t["area_covered"] >= 0.95).all()
    assert set(zip(t["state"], t["district"])) <= set(zip(monthly["state"], monthly["district"]))
    # Same products and fire rule as the calendar, so the counts must agree.
    both = t.merge(monthly, on=KEYS + ["sensor"])
    assert len(both) == len(t)
    for sensor, g in both.groupby("sensor"):
        assert g["n_hotspots"].sum() / g["fire_pixel_days"].sum() == pytest.approx(1.0, abs=0.05), sensor
        assert np.corrcoef(g["n_hotspots"], g["fire_pixel_days"])[0, 1] > 0.99, sensor


def test_fire_types_tell_crop_from_forest(fire_types):
    """Sanity: Punjab burns cropland, the Uttarakhand hills burn forest and woodland."""
    viirs = fire_types[fire_types["sensor"] == "viirs_snpp"]
    by_state = viirs.groupby("state")[["n_hotspots", "n_cropland", "n_forest", "n_woodland_grass"]].sum()
    assert by_state.loc["Punjab", "n_cropland"] / by_state.loc["Punjab", "n_hotspots"] > 0.9
    hills = by_state.loc["Uttarakhand"]
    assert (hills["n_forest"] + hills["n_woodland_grass"]) / hills["n_hotspots"] > 0.9


def test_static_sources(fire_types):
    static = pd.read_csv(DATA / "static_sources.csv")
    assert len(static) > 0 and not static.duplicated(["latitude", "longitude"]).any()
    assert (static["n_calendar_months"] >= 8).all() and (static["n_months"] >= 12).all()
    # Independent evidence they are not vegetation fires: brightly lit at night.
    assert static["median_nightlight"].median() > 20


def test_hotspot_list(monthly):
    """data/hotspots.csv.gz: contract §7, and it adds up to the calendar (check H6)."""
    path = DATA / "hotspots.csv.gz"
    if not path.exists():
        pytest.skip("hotspot list not generated in this checkout")
    assert path.stat().st_size < 20e6
    h = pd.read_csv(path, dtype={"acq_date": str})
    assert list(h.columns) == ["state", "district", "sensor", "acq_date", "latitude", "longitude",
                               "frp_mw", "confidence"]
    assert set(h["sensor"]) == {"terra", "aqua", "viirs_snpp"}
    assert set(h["confidence"]) <= {"nominal", "high"}
    assert h.drop(columns="frp_mw").notna().all().all() and (h["frp_mw"].dropna() >= 0).all()
    assert h["acq_date"].between("2016-01-01", "2026-12-31").all()
    assert not h.duplicated().any()
    assert set(zip(h["state"], h["district"])) <= set(zip(monthly["state"], monthly["district"]))
    h["year"], h["month"] = h["acq_date"].str[:4].astype(int), h["acq_date"].str[5:7].astype(int)
    counts = h.groupby(["state", "district", "sensor", "year", "month"]).size().rename("n")
    both = monthly.set_index(counts.index.names)[["fire_pixel_days"]].join(counts).fillna(0)
    for sensor, g in both.groupby(level="sensor"):
        assert g["n"].sum() / g["fire_pixel_days"].sum() == pytest.approx(1.0, abs=0.02), sensor
    by_year = both.groupby(level=["sensor", "year"]).sum()
    active = by_year[by_year["fire_pixel_days"] > 100]
    assert (active["n"] / active["fire_pixel_days"]).between(0.97, 1.03).all()  # no year missing
    assert np.corrcoef(both["n"], both["fire_pixel_days"])[0, 1] > 0.99
    # What the app's download returns for one district and two months (app.hotspots_csv filter).
    lud = h[(h["district"] == "Ludhiana") & (h["year"] == 2020) & h["month"].isin([10, 11])]
    expected = monthly[(monthly["district"] == "Ludhiana") & (monthly["year"] == 2020)
                       & monthly["month"].isin([10, 11])]["fire_pixel_days"].sum()
    assert len(lud) == pytest.approx(expected, rel=0.02) and len(lud) > 500

