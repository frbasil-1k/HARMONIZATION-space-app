"""The app's trend maths (app/trends.py) against scipy and against the rules it documents."""

import numpy as np
import pandas as pd
import pytest
from scipy import stats

import trends


@pytest.mark.parametrize("n", [8, 9, 10, 11, 15])
def test_mann_kendall_exact_matches_scipy(n):
    rng = np.random.default_rng(n)
    for _ in range(50):
        y = rng.normal(size=n) + 0.2 * rng.normal() * np.arange(n)
        ours, ref = trends.mann_kendall(y), stats.kendalltau(np.arange(n), y, method="exact")
        assert ours["method"] == "exact"
        assert ours["p"] == pytest.approx(ref.pvalue, abs=1e-9)
        assert ours["tau"] == pytest.approx(ref.statistic, abs=1e-9)


def test_mann_kendall_with_ties_matches_scipy():
    rng = np.random.default_rng(7)
    checked = 0
    for _ in range(200):
        y = np.round(rng.normal(size=11) + 0.3 * np.arange(11))  # rounding creates ties
        if len(np.unique(y)) in (1, len(y)):
            continue
        ours = trends.mann_kendall(y, continuity=False)
        ref = stats.kendalltau(np.arange(len(y)), y, method="asymptotic")
        assert ours["method"] == "normal"
        assert ours["p"] == pytest.approx(ref.pvalue, abs=1e-9)
        assert ours["tau"] == pytest.approx(ref.statistic, abs=1e-9)
        checked += 1
    assert checked > 50


def test_mann_kendall_edge_cases():
    assert trends.mann_kendall([0.0] * 10)["p"] == 1.0  # nothing ever detected: no trend
    rising = trends.mann_kendall(list(range(10)))
    assert rising["tau"] == 1.0 and rising["p"] < 0.001
    assert np.isnan(trends.mann_kendall([1.0, 2.0])["p"])
    # The continuity correction can only make the test more cautious.
    y = [3, 3, 2, 5, 4, 4, 6, 7, 7, 9]
    assert trends.mann_kendall(y)["p"] >= trends.mann_kendall(y, continuity=False)["p"]


def test_sens_slope_matches_scipy():
    rng = np.random.default_rng(3)
    for _ in range(100):
        x, y = np.arange(2016, 2027), rng.normal(size=11)
        slope, intercept = trends.sens_slope(x, y)
        assert slope == pytest.approx(stats.theilslopes(y, x).slope, abs=1e-12)
        assert intercept == pytest.approx(np.median(y - slope * x), abs=1e-12)


def monthly(year, month, activity, n_images):
    return {"year": year, "month": month, "activity": activity, "n_images": n_images}


def test_season_values_only_counts_complete_seasons():
    rows = pd.DataFrame([
        monthly(2020, 10, 0.02, 31), monthly(2020, 11, 0.04, 30),    # complete
        monthly(2021, 10, 0.02, 31), monthly(2021, 11, 0.04, 8),     # November barely observed
        monthly(2022, 10, 0.02, 31), monthly(2022, 11, np.nan, 30),  # November not observed
        monthly(2023, 10, 0.02, 31),                                 # November missing
        monthly(2024, 10, 0.01, 16), monthly(2024, 11, 0.03, 15),    # exactly half the images: counts
    ])
    values = trends.season_values(rows, (10, 11))
    assert values["year"].tolist() == [2020, 2024]
    assert values["value"].tolist() == pytest.approx([0.03, 0.02])


def test_trend_needs_enough_years_and_reports_direction():
    years = np.arange(2016, 2026)
    assert trends.trend(years[:5], [5, 4, 3, 2, 1]) is None
    falling = trends.trend(years, np.linspace(10, 1, 10))
    assert falling["direction"] == "decreasing" and falling["slope"] == pytest.approx(-1.0)
    assert falling["slope_pct"] == pytest.approx(100 * -1.0 / 5.5)
    noise = trends.trend(years, [3, 1, 4, 1, 5, 9, 2, 6, 5, 3])
    assert noise["direction"] == "none"
    flat = trends.trend(years, [0.0] * 10)
    assert flat["direction"] == "none" and np.isnan(flat["slope_pct"])
