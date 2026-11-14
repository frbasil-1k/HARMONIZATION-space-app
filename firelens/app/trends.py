"""Trend statistics for the FireLens app: Mann-Kendall test and Sen's slope.

Pure numpy, so the app needs no extra dependency. Checked against scipy in
tests/test_trends.py.

Why these two: fire activity is skewed and has outlier years, so a least-squares line
and its p-value are unreliable. Mann-Kendall only uses the order of the values, and
Sen's slope is the median of all pairwise slopes; both are the standard, robust choice
for short environmental series.
"""

from __future__ import annotations

import calendar
import math

import numpy as np
import pandas as pd

MIN_TREND_YEARS = 8   # fewer seasons than this: no test (too little power to mean anything)
ALPHA = 0.05          # significance level used for wording and map colours
MIN_IMAGE_SHARE = 0.5  # a month needs at least this share of its daily images to count

# Seasons a fire scientist would ask for in this region. Months are calendar months.
SEASONS = {
    "Oct–Nov (rice-residue season)": (10, 11),
    "Apr–May (wheat-residue and forest-fire season)": (4, 5),
    "Whole year": tuple(range(1, 13)),
}


def _inversion_counts(n: int) -> np.ndarray:
    """Number of permutations of n items with k inversions, k = 0..n(n-1)/2."""
    counts = np.array([1.0])
    for m in range(2, n + 1):
        new = np.zeros(len(counts) + m - 1)
        for shift in range(m):
            new[shift:shift + len(counts)] += counts
        counts = new
    return counts


def mann_kendall(values, continuity: bool = True) -> dict:
    """Two-sided Mann-Kendall trend test on values in time order.

    Returns n, s (the MK statistic), tau, p and method. With no tied values and n <= 30
    the p-value is exact (from the distribution of S); otherwise the normal approximation
    with the tie-corrected variance, and a continuity correction unless switched off.
    """
    y = np.asarray(values, dtype=float)
    n = len(y)
    if n < 3:
        return {"n": n, "s": 0.0, "tau": float("nan"), "p": float("nan"), "method": "too few"}
    diffs = np.sign(y[None, :] - y[:, None])[np.triu_indices(n, k=1)]
    s = float(diffs.sum())
    pairs = n * (n - 1) / 2
    _, ties = np.unique(y, return_counts=True)
    tied = ties[ties > 1]

    if len(tied) == 0 and n <= 30:
        # S = pairs - 2 * inversions, so P(|S| >= |s|) is a tail sum of inversion counts.
        counts = _inversion_counts(n)
        s_values = pairs - 2 * np.arange(len(counts))
        p = float(counts[np.abs(s_values) >= abs(s) - 1e-9].sum() / counts.sum())
        return {"n": n, "s": s, "tau": s / pairs, "p": min(p, 1.0), "method": "exact"}

    var = (n * (n - 1) * (2 * n + 5) - float((tied * (tied - 1) * (2 * tied + 5)).sum())) / 18.0
    if var <= 0:  # every value identical
        return {"n": n, "s": s, "tau": 0.0, "p": 1.0, "method": "all tied"}
    shift = 1.0 if continuity else 0.0
    z = 0.0 if s == 0 else (s - math.copysign(shift, s)) / math.sqrt(var)
    p = math.erfc(abs(z) / math.sqrt(2))
    # tau-b: pairs tied in value are removed from one side of the denominator.
    tau_den = math.sqrt(pairs * (pairs - float((tied * (tied - 1) / 2).sum())))
    return {"n": n, "s": s, "tau": s / tau_den if tau_den > 0 else 0.0, "p": float(p), "method": "normal"}


def sens_slope(x, y) -> tuple[float, float]:
    """Sen's slope (median of pairwise slopes) and the matching intercept."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    i, j = np.triu_indices(len(x), k=1)
    slope = float(np.median((y[j] - y[i]) / (x[j] - x[i])))
    return slope, float(np.median(y - slope * x))


def season_values(series: pd.DataFrame, months: tuple[int, ...],
                  extra: tuple[str, ...] = ()) -> pd.DataFrame:
    """One value per year: mean monthly activity over the season's months.

    A year counts only when every month of the season has a defined activity and at
    least half its daily images, so a half-observed season is never compared with full
    ones. `extra` columns (e.g. the sensor range) are averaged the same way.
    Returns columns: year, value, *extra; years that do not qualify are left out.
    """
    rows = series[series["month"].isin(months)].copy()
    if rows.empty:
        return pd.DataFrame(columns=["year", "value", *extra])
    days = [calendar.monthrange(int(y), int(m))[1] for y, m in zip(rows["year"], rows["month"])]
    rows["ok"] = rows["activity"].notna() & (rows["n_images"] >= np.array(days) * MIN_IMAGE_SHARE)
    by_year = rows.groupby("year")
    complete = by_year["ok"].sum() == len(months)
    table = by_year[["activity", *extra]].mean().rename(columns={"activity": "value"})
    return table[complete].reset_index()


def trend(years, values) -> dict | None:
    """Mann-Kendall + Sen's slope for one yearly series; None with too few years.

    slope is in the units of `values` per year; slope_pct is the slope as a percentage
    of the series median per year (NaN when the median is 0).
    """
    years = np.asarray(years, dtype=float)
    values = np.asarray(values, dtype=float)
    if len(values) < MIN_TREND_YEARS:
        return None
    test = mann_kendall(values)
    slope, intercept = sens_slope(years, values)
    median = float(np.median(values))
    direction = "none"
    if test["p"] < ALPHA and slope != 0:
        direction = "increasing" if slope > 0 else "decreasing"
    return {**test, "slope": slope, "intercept": intercept, "median": median,
            "slope_pct": 100 * slope / median if median > 0 else float("nan"),
            "direction": direction,
            "first_year": int(years.min()), "last_year": int(years.max())}
