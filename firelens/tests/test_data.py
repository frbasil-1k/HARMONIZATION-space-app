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
