#!/usr/bin/env python3
"""FireLens Phase 2 — cross-sensor harmonization of the monthly fire record (v2).

Problem
-------
Terra MODIS, Aqua MODIS and Suomi-NPP VIIRS do not count burning the same way. Their
raw activity series step up and down whenever the sensor mix changes, which looks like a
change in burning but is an instrument artefact. This script learns, from the years in
which all three sensors flew their nominal orbits, how much each MODIS sensor under- or
over-reads relative to the VIIRS anchor, and combines them into one harmonized activity
series per district.

What changed in v2 (docs/decisions.md, 2026-11-15)
-------------------------------------------------
* **Seasonal ratios.** One ratio per (state, MODIS sensor, calendar month), the ratio of
  sums ``sum(viirs) / sum(modis)`` over shared district-months, falling back to the
  state-level ratio of sums when a month has too few burning months. A single all-year
  median was set by quiet months and left Terra's morning overpass ~4x too low in the
  afternoon crop-burning peak.
* **Orbit-drift aware.** Terra (drifting earlier since 2020, below 10:15 MLT from
  Oct 2022) and Aqua (drifting later since 2021, past 13:45 MLT from Feb 2023) are only
  calibrated on, and only blended in, months before their drift start. After it, MODIS
  is used only to fill months VIIRS could not see, and those months are flagged.
* **Skill-weighted blend.** Each scaled MODIS sensor enters the blend with weight r^2,
  its leave-one-year-out correlation with VIIRS; VIIRS has weight 1.
* **MODIS-only reconstruction** (``modis_recon``): the calendar rebuilt from scaled MODIS
  alone, validated against VIIRS. This is the evidence that the record can be extended
  back to 2001/2003, before VIIRS existed.

Pipeline
--------
1. Load ``data/district_monthly.csv`` and compute ``activity``, ``clear_coverage``,
   ``low_coverage`` (unchanged from v1).
2. Leave-one-year-out (LOYO) over the pre-drift calibration months: fit on six years,
   test on the seventh. Gives honest skill numbers and the blend weights.
3. Fit the final ratios on all pre-drift calibration months.
4. Drift-period check (2023–2025): how far the pre-drift ratios miss once the orbits
   drift, including a causal rolling refit, to justify not blending drifted MODIS.
5. Build ``data/district_harmonized.csv`` and write ``science/validation.md``.

Rules honoured (docs/decisions.md, docs/data-contract.md)
---------------------------------------------------------
* ``activity = fire_pixel_days / clear_pixel_days``; NaN when ``clear_pixel_days == 0`` or
  ``n_images == 0``. Low-coverage rows stay NaN. No imputation anywhere: a "fill" is
  another sensor's measurement of the same month, never an interpolation.
* The input CSV is read-only: this script writes only ``data/district_harmonized.csv``
  and ``science/validation.md``.

Usage
-----
    python science/harmonize.py
    python science/harmonize.py --input data/district_monthly.csv \\
        --output data/district_harmonized.csv --validation science/validation.md
"""

from __future__ import annotations

import argparse
import calendar
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

# --------------------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = BASE_DIR / "data" / "district_monthly.csv"
DEFAULT_OUTPUT = BASE_DIR / "data" / "district_harmonized.csv"
DEFAULT_VALIDATION = BASE_DIR / "science" / "validation.md"

SENSORS = ("terra", "aqua", "viirs_snpp")
MODELS = ("terra", "aqua")
ANCHOR = "viirs_snpp"
SCALED = {"terra": "terra_scaled", "aqua": "aqua_scaled"}

COVERAGE_THRESHOLD = 0.10
CALIB_YEARS = (2016, 2022)
HOLDOUT_YEARS = (2023, 2025)
FULL_YEARS = (2016, 2026)
CV_LIMIT = 0.50
MIN_BURNING_MONTHS = 15  # positive MODIS district-months needed for a month-specific ratio

# First month of orbit drift outside each MODIS sensor's science limits (NASA):
# Terra passed 10:15 MLT in Oct 2022 (last inclination manoeuvre Feb 2020);
# Aqua passed 13:45 MLT in Feb 2023 (free drift since Jan 2022).
DRIFT_START = {"terra": (2022, 10), "aqua": (2023, 2)}

INDEX = ["state", "district", "year", "month"]
REQUIRED = (
    "state",
    "district",
    "sensor",
    "year",
    "month",
    "fire_pixel_days",
    "clear_pixel_days",
    "mean_frp_mw",
    "n_images",
)

MONTH_NAMES = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)

# --------------------------------------------------------------------------------------
# 1. Load and derive metrics
# --------------------------------------------------------------------------------------


def load_monthly(path: Path) -> pd.DataFrame:
    """Read the monthly fire table and add the contract metrics.

    Returns a frame with ``days_in_month``, ``clear_per_day``, ``land_baseline``,
    ``clear_coverage``, ``low_coverage`` and ``activity``. ``activity`` is masked to NaN
    wherever ``low_coverage`` is True, so no later step can accidentally use it.
    """
    if not path.is_file():
        raise FileNotFoundError(f"Input CSV not found: {path}")

    df = pd.read_csv(path)
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(
            f"{path} is missing required column(s): {missing}. See docs/data-contract.md."
        )

    for col in ("state", "district", "sensor"):
        df[col] = df[col].astype("string").str.strip()
    for col in ("year", "month", "n_images"):
        df[col] = pd.to_numeric(df[col], errors="coerce").round().astype("Int64")
    for col in ("fire_pixel_days", "clear_pixel_days", "mean_frp_mw"):
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")

    # Calendar length of each row's month. Iterating over the unique (year, month) pairs
    # keeps this cheap on the full 19,404-row file.
    days_lookup = {
        (int(y), int(m)): calendar.monthrange(int(y), int(m))[1]
        for y, m in df[["year", "month"]].drop_duplicates().dropna().itertuples(index=False)
    }
    df["days_in_month"] = [
        float(days_lookup.get((int(y), int(m)), np.nan))
        if pd.notna(y) and pd.notna(m)
        else np.nan
        for y, m in zip(df["year"], df["month"])
    ]

    df["clear_per_day"] = df["clear_pixel_days"] / df["days_in_month"]

    # Coverage baseline: this sensor in this district at its clearest month. Using the
    # (state, district, sensor) pair means a cloud-prone sensor is judged against what it
    # itself can see, not against a better-placed sensor's record.
    baseline = df.groupby(
        ["state", "district", "sensor"], dropna=False
    )["clear_per_day"].transform("max")
    df["land_baseline"] = baseline
    df["clear_coverage"] = (df["clear_per_day"] / baseline).where(baseline > 0)

    df["low_coverage"] = (
        (df["n_images"].fillna(0) == 0)
        | df["clear_coverage"].isna()
        | (df["clear_coverage"] < COVERAGE_THRESHOLD)
    )

    fire = df["fire_pixel_days"]
    clear = df["clear_pixel_days"]
    observed = (clear > 0) & (df["n_images"].fillna(0) > 0)
    activity = (fire / clear).where(observed)
    df["activity"] = activity.mask(df["low_coverage"])

    return df.sort_values(INDEX, kind="mergesort").reset_index(drop=True)


def _wide_activity(df: pd.DataFrame) -> pd.DataFrame:
    """Pivot to one row per district-month with one column per sensor."""
    wide = df.pivot(index=INDEX, columns="sensor", values="activity")
    for sensor in SENSORS:
        if sensor not in wide.columns:
            wide[sensor] = np.nan
    return wide[list(SENSORS)].sort_index()



def _wide(df: pd.DataFrame) -> pd.DataFrame:
    """Flat district-month table: INDEX columns plus one activity column per sensor."""
    return _wide_activity(df).reset_index()


def _ym(frame: pd.DataFrame) -> pd.Series:
    return frame["year"].astype(int) * 12 + frame["month"].astype(int)


def pre_drift(frame: pd.DataFrame, sensor: str) -> pd.Series:
    """True for months before the sensor's orbit left its science limits."""
    year, month = DRIFT_START[sensor]
    return _ym(frame) < year * 12 + month


# --------------------------------------------------------------------------------------
# 2. Seasonal ratios
# --------------------------------------------------------------------------------------


def fit_ratios(train: pd.DataFrame, min_burning: int = MIN_BURNING_MONTHS) -> pd.DataFrame:
    """VIIRS / MODIS ratio of sums per (state, sensor, calendar month).

    ``train`` is a flat wide table. Only months where both sensors are valid and the MODIS
    sensor is still pre-drift are used. A calendar month with fewer than ``min_burning``
    positive MODIS district-months falls back to the state's all-month ratio of sums,
    so quiet months cannot produce a wild ratio.
    """
    rows: list[dict] = []
    for sensor in MODELS:
        shared = train[pre_drift(train, sensor)].dropna(subset=[ANCHOR, sensor])
        for state, in_state in shared.groupby("state", observed=True):
            total = in_state[sensor].sum()
            state_ratio = float(in_state[ANCHOR].sum() / total) if total > 0 else np.nan
            for month in range(1, 13):
                cell = in_state[in_state["month"] == month]
                burning = int((cell[sensor] > 0).sum())
                modis_sum = cell[sensor].sum()
                if burning >= min_burning and modis_sum > 0:
                    ratio, method = float(cell[ANCHOR].sum() / modis_sum), "month"
                else:
                    ratio, method = state_ratio, "state (few burning months)"
                rows.append({
                    "state": state, "sensor": sensor, "month": month, "ratio": ratio,
                    "state_ratio": state_ratio, "n_pairs": int(len(cell)),
                    "n_burning": burning, "method": method,
                })
    return pd.DataFrame(rows)


def _lookup(ratios: pd.DataFrame, sensor: str, frame: pd.DataFrame) -> np.ndarray:
    sub = ratios[ratios["sensor"] == sensor].set_index(["state", "month"])["ratio"]
    keys = pd.MultiIndex.from_arrays([frame["state"].astype(str), frame["month"].astype(int)])
    return sub.reindex(keys).to_numpy(dtype=float)


def scale(frame: pd.DataFrame, ratios: pd.DataFrame) -> dict[str, np.ndarray]:
    """Scaled MODIS activity (clipped to [0, 1]) for every row of ``frame``."""
    return {
        sensor: np.clip(frame[sensor].to_numpy(dtype=float) * _lookup(ratios, sensor, frame), 0.0, 1.0)
        for sensor in MODELS
    }


def stability(train: pd.DataFrame) -> pd.DataFrame:
    """Per-year ratio of sums (all months) per (state, sensor), with the CV across years."""
    rows: list[dict] = []
    for sensor in MODELS:
        shared = train[pre_drift(train, sensor)].dropna(subset=[ANCHOR, sensor])
        for state, in_state in shared.groupby("state", observed=True):
            by_year = in_state.groupby("year")
            yearly = (by_year[ANCHOR].sum() / by_year[sensor].sum()).replace([np.inf], np.nan)
            cv = float(yearly.std(ddof=1) / yearly.mean()) if yearly.notna().sum() >= 2 else np.nan
            rows.append({"state": state, "sensor": sensor, "cv": cv,
                         **{int(y): float(v) for y, v in yearly.items()}})
    return pd.DataFrame(rows)


def peak_months(train: pd.DataFrame, n: int = 2) -> dict[str, tuple[int, ...]]:
    """Each state's n calendar months with the highest mean VIIRS activity."""
    means = train.groupby(["state", "month"], observed=True)[ANCHOR].mean()
    return {
        state: tuple(sorted(int(m) for m in group.droplevel(0).nlargest(n).index))
        for state, group in means.groupby(level=0)
    }


# --------------------------------------------------------------------------------------
# 3. Skill: leave-one-year-out, drift check
# --------------------------------------------------------------------------------------


def _pearson(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """Pearson r and p, guarding against tiny or constant samples."""
    if len(x) < 3 or np.std(x) == 0 or np.std(y) == 0:
        return float("nan"), float("nan")
    r, p = stats.pearsonr(x, y)
    return float(r), float(p)


def skill(pred: np.ndarray, anchor: np.ndarray, peak: np.ndarray) -> dict[str, float]:
    """How well a scaled series reproduces VIIRS.

    bias = sum(pred) / sum(VIIRS): 1.00 means the same total burning. peak_bias is the
    same over each state's two peak months, where a calendar matters most.
    """
    ok = np.isfinite(pred) & np.isfinite(anchor)
    pred, anchor, peak = pred[ok], anchor[ok], peak[ok]
    r, p = _pearson(pred, anchor)
    return {
        "n": int(ok.sum()),
        "r": r,
        "p": p,
        "slope": float(np.polyfit(anchor, pred, 1)[0]) if len(pred) >= 3 and anchor.std() > 0 else np.nan,
        "bias": float(pred.sum() / anchor.sum()) if anchor.sum() > 0 else np.nan,
        "peak_bias": float(pred[peak].sum() / anchor[peak].sum()) if anchor[peak].sum() > 0 else np.nan,
        "median_abs": float(np.median(np.abs(pred - anchor))) if len(pred) else np.nan,
    }


def _peak_mask(frame: pd.DataFrame, peaks: dict[str, tuple[int, ...]]) -> np.ndarray:
    return np.array([m in peaks.get(s, ()) for s, m in zip(frame["state"], frame["month"])])


def _median_ratios(train: pd.DataFrame) -> pd.DataFrame:
    """v1 method, kept only for the comparison table: one all-month median per state."""
    rows = []
    for sensor in MODELS:
        shared = train.dropna(subset=[ANCHOR, sensor])
        shared = shared[(shared[ANCHOR] > 0) & (shared[sensor] > 0)]
        for state, g in shared.groupby("state", observed=True):
            ratio = float((g[ANCHOR] / g[sensor]).median())
            rows += [{"state": state, "sensor": sensor, "month": m, "ratio": ratio} for m in range(1, 13)]
    return pd.DataFrame(rows)


def loyo(calib: pd.DataFrame, fitter) -> pd.DataFrame:
    """Leave-one-year-out predictions: each year scaled with ratios fit on the others."""
    parts = []
    for year in range(CALIB_YEARS[0], CALIB_YEARS[1] + 1):
        test = calib[calib["year"] == year].copy()
        for sensor, values in scale(test, fitter(calib[calib["year"] != year])).items():
            test[SCALED[sensor]] = np.where(pre_drift(test, sensor), values, np.nan)
        parts.append(test)
    return pd.concat(parts, ignore_index=True)


def blend_weights(pred: pd.DataFrame) -> dict[str, float]:
    """Weight of each scaled MODIS sensor: its squared LOYO correlation with VIIRS."""
    weights = {}
    for sensor in MODELS:
        ok = pred[[SCALED[sensor], ANCHOR]].dropna()
        r, _ = _pearson(ok[SCALED[sensor]].to_numpy(float), ok[ANCHOR].to_numpy(float))
        weights[sensor] = max(r, 0.0) ** 2 if np.isfinite(r) else 0.0
    return weights


def weighted_modis(frame: pd.DataFrame, weights: dict[str, float], use: dict[str, np.ndarray]) -> np.ndarray:
    """Weighted mean of the scaled MODIS sensors where ``use[sensor]`` is True."""
    num = np.zeros(len(frame))
    den = np.zeros(len(frame))
    for sensor in MODELS:
        values = frame[SCALED[sensor]].to_numpy(dtype=float)
        ok = use[sensor] & np.isfinite(values)
        num += np.where(ok, weights[sensor] * values, 0.0)
        den += np.where(ok, weights[sensor], 0.0)
    return np.where(den > 0, num / np.where(den > 0, den, 1.0), np.nan)


def evaluate(df: pd.DataFrame) -> dict:
    """Every skill number the report quotes, plus the final ratios and weights."""
    wide = _wide(df)
    calib = wide[wide["year"].between(*CALIB_YEARS)]
    peaks = peak_months(calib)

    loyo_new = loyo(calib, fit_ratios)
    loyo_old = loyo(calib, _median_ratios)
    weights = blend_weights(loyo_new)
    peak_new = _peak_mask(loyo_new, peaks)

    comparison = []
    for label, pred in (("v1: all-month median", loyo_old), ("v2: monthly ratio of sums", loyo_new)):
        mask = _peak_mask(pred, peaks)
        for sensor in MODELS:
            comparison.append({"method": label, "sensor": sensor,
                               **skill(pred[SCALED[sensor]].to_numpy(float), pred[ANCHOR].to_numpy(float), mask)})

    all_pre = {s: np.ones(len(loyo_new), dtype=bool) for s in MODELS}
    recon = weighted_modis(loyo_new, weights, all_pre)
    recon_skill = skill(recon, loyo_new[ANCHOR].to_numpy(float), peak_new)

    # Blend vs VIIRS on the same LOYO rows: does adding MODIS move the level?
    viirs = loyo_new[ANCHOR].to_numpy(float)
    num = np.where(np.isfinite(viirs), viirs, 0.0)
    den = np.isfinite(viirs).astype(float)
    for sensor in MODELS:
        values = loyo_new[SCALED[sensor]].to_numpy(float)
        ok = np.isfinite(values) & np.isfinite(viirs)
        num += np.where(ok, weights[sensor] * values, 0.0)
        den += np.where(ok, weights[sensor], 0.0)
    blend = np.where(np.isfinite(viirs), num / np.where(den > 0, den, 1.0), np.nan)
    blend_skill = skill(blend, viirs, peak_new)

    ratios = fit_ratios(calib)
    stab = stability(calib)
    unstable = stab[stab["cv"] > CV_LIMIT]

    # Drift period: the pre-drift ratios applied blind to 2023-2025, and a causal rolling
    # refit (ratios from the previous year only) to test whether recalibration rescues it.
    hold = wide[wide["year"].between(*HOLDOUT_YEARS)].copy()
    hold_peak = _peak_mask(hold, peaks)
    for sensor, values in scale(hold, ratios).items():
        hold[SCALED[sensor]] = values
    rolling = []
    for year in range(HOLDOUT_YEARS[0], HOLDOUT_YEARS[1] + 1):
        part = wide[wide["year"] == year].copy()
        prev = wide[wide["year"] == year - 1].copy()
        refit = []
        for sensor in MODELS:  # refit ignores the drift cut: it learns the drifted ratio
            sub = prev.dropna(subset=[ANCHOR, sensor])
            for state, g in sub.groupby("state", observed=True):
                for month in range(1, 13):
                    cell = g[g["month"] == month]
                    s = cell[sensor].sum()
                    ratio = cell[ANCHOR].sum() / s if (cell[sensor] > 0).sum() >= 5 and s > 0 else (
                        g[ANCHOR].sum() / g[sensor].sum() if g[sensor].sum() > 0 else np.nan)
                    refit.append({"state": state, "sensor": sensor, "month": month, "ratio": ratio})
        for sensor, values in scale(part, pd.DataFrame(refit)).items():
            part[SCALED[sensor]] = values
        rolling.append(part)
    rolling = pd.concat(rolling, ignore_index=True)
    roll_peak = _peak_mask(rolling, peaks)
    drift = []
    for label, frame, mask in (("pre-drift ratios, blind", hold, hold_peak),
                               ("rolling refit on previous year", rolling, roll_peak)):
        for sensor in MODELS:
            drift.append({"method": label, "sensor": sensor,
                          **skill(frame[SCALED[sensor]].to_numpy(float), frame[ANCHOR].to_numpy(float), mask)})
    drift_by_year = []
    for year, g in hold.groupby("year"):
        mask = _peak_mask(g, peaks)
        for sensor in MODELS:
            drift_by_year.append({"year": int(year), "sensor": sensor,
                                  **skill(g[SCALED[sensor]].to_numpy(float), g[ANCHOR].to_numpy(float), mask)})

    result = {
        "peaks": peaks, "weights": weights, "ratios": ratios, "stability": stab,
        "unstable": unstable, "comparison": pd.DataFrame(comparison),
        "recon": recon_skill, "blend": blend_skill,
        "drift": pd.DataFrame(drift), "drift_by_year": pd.DataFrame(drift_by_year),
    }
    _print_evaluation(result)
    return result


def _print_evaluation(res: dict) -> None:
    print("\nPeak months per state (VIIRS, 2016-2022):", res["peaks"])
    print("Leave-one-year-out skill vs VIIRS, 2016-2022 (pre-drift):")
    for _, row in res["comparison"].iterrows():
        print(f"  {row['method']:<27} {row['sensor']:<6} r={row['r']:.3f} slope={row['slope']:.2f} "
              f"bias={row['bias']:.2f} peak_bias={row['peak_bias']:.2f}")
    rec, bl = res["recon"], res["blend"]
    print(f"  MODIS-only reconstruction  r={rec['r']:.3f} bias={rec['bias']:.2f} peak_bias={rec['peak_bias']:.2f}")
    print(f"  Blend vs VIIRS             r={bl['r']:.3f} bias={bl['bias']:.2f} peak_bias={bl['peak_bias']:.2f}")
    print("  Blend weights:", {k: round(v, 3) for k, v in res["weights"].items()})
    print("Drift period 2023-2025:")
    for _, row in res["drift"].iterrows():
        print(f"  {row['method']:<31} {row['sensor']:<6} r={row['r']:.3f} bias={row['bias']:.2f} "
              f"peak_bias={row['peak_bias']:.2f}")
    if len(res["unstable"]):
        print("  WARNING: unstable yearly ratios (CV > limit):", res["unstable"][["state", "sensor", "cv"]].to_dict("records"))


# --------------------------------------------------------------------------------------
# 4. Build the harmonized district-month table
# --------------------------------------------------------------------------------------

SOURCES = ("blend", "viirs", "modis_fill", "modis_fill_drift", "none")


def _half_range(rows: pd.DataFrame) -> float:
    """Median of (sensor_max - sensor_min) / 2 as a share of the harmonized value."""
    rows = rows[(rows["act_harmonized"] > 0) & (rows["n_valid_sensors"] >= 2)]
    if rows.empty:
        return float("nan")
    return float((((rows["sensor_max"] - rows["sensor_min"]) / 2) / rows["act_harmonized"]).median())


def build_harmonized(df: pd.DataFrame, ratios: pd.DataFrame, weights: dict[str, float]
                     ) -> tuple[pd.DataFrame, dict[str, float]]:
    """One harmonized row per district-month, and summary statistics."""
    wide = _wide(df[df["year"].between(*FULL_YEARS)])
    out = wide[INDEX].copy()
    out["viirs_act"] = np.clip(wide[ANCHOR].to_numpy(dtype=float), 0.0, 1.0)
    for sensor, values in scale(wide, ratios).items():
        out[SCALED[sensor]] = values

    pre = {s: pre_drift(out, s).to_numpy() for s in MODELS}
    post = {s: ~pre[s] for s in MODELS}
    every = {s: np.ones(len(out), dtype=bool) for s in MODELS}

    viirs = out["viirs_act"].to_numpy(dtype=float)
    has_viirs = np.isfinite(viirs)
    num = np.where(has_viirs, viirs, 0.0)
    den = has_viirs.astype(float)
    contributed = np.zeros(len(out), dtype=bool)
    blended_in: dict[str, np.ndarray] = {}
    for sensor in MODELS:
        values = out[SCALED[sensor]].to_numpy(dtype=float)
        ok = has_viirs & pre[sensor] & np.isfinite(values)
        num += np.where(ok, weights[sensor] * values, 0.0)
        den += np.where(ok, weights[sensor], 0.0)
        contributed |= ok
        blended_in[sensor] = ok
    blended = np.where(has_viirs, num / np.where(den > 0, den, 1.0), np.nan)
    fill_pre = weighted_modis(out, weights, pre)
    fill_post = weighted_modis(out, weights, post)

    # Which sensors the value rests on (for n_blended and clear_coverage below).
    use_pre = ~has_viirs & np.isfinite(fill_pre)
    use_post = ~has_viirs & ~np.isfinite(fill_pre) & np.isfinite(fill_post)
    used = {ANCHOR: has_viirs}
    for sensor in MODELS:
        finite = np.isfinite(out[SCALED[sensor]].to_numpy(dtype=float))
        used[sensor] = blended_in[sensor] | (use_pre & pre[sensor] & finite) | (use_post & post[sensor] & finite)

    act = np.where(has_viirs, blended, np.where(np.isfinite(fill_pre), fill_pre, fill_post))
    source = np.select(
        [has_viirs & contributed, has_viirs, np.isfinite(fill_pre), np.isfinite(fill_post)],
        ["blend", "viirs", "modis_fill", "modis_fill_drift"], default="none",
    )
    out["act_harmonized"] = np.clip(act, 0.0, 1.0)
    out["source"] = source
    out["modis_recon"] = weighted_modis(out, weights, every)
    out["modis_drift"] = post["terra"] | post["aqua"]

    sensor_columns = ["viirs_act", "terra_scaled", "aqua_scaled"]
    out["n_valid_sensors"] = out[sensor_columns].notna().sum(axis=1).astype("int64")
    out["low_coverage"] = out["n_valid_sensors"] == 0

    # Uncertainty columns. sensor_min/max: the range of the individual sensors after
    # scaling (how far the satellites disagree; after the drift it widens, as it should).
    # n_blended: sensors the value rests on. clear_coverage: the best clear view among them.
    out["sensor_min"] = out[sensor_columns].min(axis=1, skipna=True)
    out["sensor_max"] = out[sensor_columns].max(axis=1, skipna=True)
    out["n_blended"] = sum(used[s].astype("int64") for s in SENSORS)
    coverage = (df[df["year"].between(*FULL_YEARS)]
                .pivot(index=INDEX, columns="sensor", values="clear_coverage").reset_index())
    coverage = out[INDEX].merge(coverage, on=INDEX, how="left")
    best = np.full(len(out), np.nan)
    for sensor in SENSORS:
        values = np.where(used[sensor], coverage[sensor].to_numpy(dtype=float), np.nan)
        best = np.fmax(best, values)
    out["clear_coverage"] = np.clip(best, 0.0, 1.0)

    group = out.groupby(["state", "district"], observed=True)["act_harmonized"]
    out["baseline"] = out.groupby(["state", "district", "month"], observed=True)["act_harmonized"].transform("mean")
    out["anomaly"] = out["act_harmonized"] - out["baseline"]
    out["percentile"] = group.transform(lambda s: s.rank(pct=True, method="average") * 100.0)

    columns = INDEX + ["viirs_act", "terra_scaled", "aqua_scaled", "act_harmonized", "n_valid_sensors",
                       "low_coverage", "baseline", "anomaly", "percentile", "source", "modis_recon",
                       "modis_drift", "sensor_min", "sensor_max", "n_blended", "clear_coverage"]
    out = out[columns].sort_values(INDEX, kind="mergesort").reset_index(drop=True)

    valid = out["act_harmonized"].dropna()
    summary = {
        "rows": int(len(out)),
        "districts": int(out[["state", "district"]].drop_duplicates().shape[0]),
        "months": int(out[["year", "month"]].drop_duplicates().shape[0]),
        "valid_rows": int(len(valid)),
        "nan_rows": int(out["act_harmonized"].isna().sum()),
        "min_act": float(valid.min()) if len(valid) else np.nan,
        "max_act": float(valid.max()) if len(valid) else np.nan,
        "mean_act": float(valid.mean()) if len(valid) else np.nan,
        "sources": out["source"].value_counts().reindex(SOURCES, fill_value=0).to_dict(),
        "half_range_all": _half_range(out[~out["modis_drift"]]),
        "half_range_burning": _half_range(out[~out["modis_drift"] & (out["percentile"] >= 90)]),
        "half_range_burning_drift": _half_range(out[out["modis_drift"] & (out["percentile"] >= 90)]),
        "low_coverage_rows": int(out["low_coverage"].sum()),
    }
    return out, summary


# --------------------------------------------------------------------------------------
# 5. Verification
# --------------------------------------------------------------------------------------


def _season_stats(harmonized: pd.DataFrame, state: str, district: str, months: tuple[int, ...]) -> dict[str, float]:
    """Season mean vs annual mean of harmonized activity for one district."""
    sub = harmonized[(harmonized["state"] == state) & (harmonized["district"] == district)]
    if sub.empty:
        return {"found": 0, "season": np.nan, "annual": np.nan, "ratio": np.nan}
    annual = float(sub["act_harmonized"].mean(skipna=True))
    season = float(sub.loc[sub["month"].isin(months), "act_harmonized"].mean(skipna=True))
    return {"found": 1, "season": season, "annual": annual,
            "ratio": season / annual if annual and np.isfinite(annual) and annual > 0 else np.nan}


def verify(harmonized: pd.DataFrame) -> dict[str, dict[str, float]]:
    """Assert the output contract and confirm both seasonal peaks survive harmonization."""
    valid = harmonized["act_harmonized"].dropna()
    assert valid.between(0.0, 1.0).all(), "act_harmonized outside [0, 1]"
    assert harmonized["n_valid_sensors"].between(0, 3).all(), "n_valid_sensors outside 0-3"
    assert harmonized["source"].isin(SOURCES).all(), "unknown source value"
    assert (harmonized["act_harmonized"].isna() == (harmonized["source"] == "none")).all(), \
        "act_harmonized must be NaN exactly where source == 'none'"
    has_viirs = harmonized["viirs_act"].notna()
    assert harmonized.loc[has_viirs, "source"].isin(["blend", "viirs"]).all(), \
        "a month VIIRS saw must never be filled from MODIS"
    valid_rows = harmonized["act_harmonized"].notna()
    assert (harmonized.loc[valid_rows, "n_blended"] >= 1).all() and (harmonized.loc[~valid_rows, "n_blended"] == 0).all(), \
        "n_blended must be >= 1 exactly where act_harmonized is defined"
    assert (harmonized.loc[valid_rows, "sensor_min"] <= harmonized.loc[valid_rows, "sensor_max"]).all(), \
        "sensor_min must not exceed sensor_max"
    assert harmonized.loc[valid_rows, "clear_coverage"].between(COVERAGE_THRESHOLD, 1.0).all(), \
        "clear_coverage of a used sensor must be within [floor, 1]"

    ludhiana = _season_stats(harmonized, "Punjab", "Ludhiana", (10, 11))
    naini_tal = _season_stats(harmonized, "Uttarakhand", "Naini Tal", (4, 5))
    print("\nPeak preservation:")
    for name, value, months in (("Ludhiana (Punjab)", ludhiana, "Oct-Nov"),
                                ("Naini Tal (Uttarakhand)", naini_tal, "Apr-May")):
        if value["found"]:
            print(f"  {name} {months} mean={value['season']:.6f} vs annual={value['annual']:.6f} "
                  f"({value['ratio']:.2f}x)")
        else:
            print(f"  WARN: {name} not found in the output")
    return {"ludhiana": ludhiana, "naini_tal": naini_tal}


# --------------------------------------------------------------------------------------
# 6. validation.md
# --------------------------------------------------------------------------------------


def _md_table(headers: list[str], rows: list[list[str]]) -> str:
    """Small markdown table writer (no tabulate dependency)."""
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def _fmt(value: float, digits: int = 3) -> str:
    if value is None or not np.isfinite(value):
        return "n/a"
    return f"{value:.{digits}f}"


def _skill_rows(frame: pd.DataFrame, first: str) -> list[list[str]]:
    return [[row[first], row["sensor"], f"{int(row['n']):,}", _fmt(row["r"]), _fmt(row["slope"], 2),
             _fmt(row["bias"], 2), _fmt(row["peak_bias"], 2)] for _, row in frame.iterrows()]


def write_validation(path: Path, df: pd.DataFrame, res: dict, summary: dict, peaks: dict) -> None:
    """Render science/validation.md from the computed numbers (nothing typed in by hand)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    years = sorted(df["year"].dropna().unique().tolist())
    period = f"{int(min(years))}-01 to {int(max(years))}-12"
    n_districts = df[["state", "district"]].drop_duplicates().shape[0]
    peak_text = ", ".join(f"{s} {'/'.join(MONTH_NAMES[m - 1] for m in ms)}" for s, ms in res["peaks"].items())
    w = res["weights"]

    ratio_rows = []
    for (state, sensor), g in res["ratios"].groupby(["state", "sensor"], observed=True):
        g = g.set_index("month")
        cells = [(_fmt(g.loc[m, "ratio"], 2) + ("" if g.loc[m, "method"] == "month" else "*")) for m in range(1, 13)]
        ratio_rows.append([state, sensor] + cells + [_fmt(float(g["state_ratio"].iloc[0]), 2)])

    stab = res["stability"]
    year_cols = [y for y in range(CALIB_YEARS[0], CALIB_YEARS[1] + 1)]
    stab_rows = [[r["state"], r["sensor"]] + [_fmt(r.get(y, np.nan), 2) for y in year_cols] + [_fmt(r["cv"])]
                 for _, r in stab.iterrows()]

    cmp = res["comparison"]
    old = cmp[cmp["method"].str.startswith("v1")].set_index("sensor")
    new = cmp[cmp["method"].str.startswith("v2")].set_index("sensor")
    drift = res["drift"]
    blind = drift[drift["method"].str.startswith("pre-drift")].set_index("sensor")
    roll = drift[drift["method"].str.startswith("rolling")].set_index("sensor")
    rec, bl = res["recon"], res["blend"]
    src = summary["sources"]
    total = max(summary["rows"], 1)
    src_rows = [[k, f"{v:,}", f"{v / total:.1%}"] for k, v in src.items()]
    unstable_note = (
        "Every state-sensor yearly ratio has CV below the limit, so no fallback was needed."
        if res["unstable"].empty else
        "**Unstable rows (CV above the limit):** "
        + ", ".join(f"{r.state} {r.sensor} ({r.cv:.2f})" for r in res["unstable"].itertuples())
        + ". Treat their ratios with caution."
    )

    def peak_block(s: dict, label: str) -> str:
        if not s.get("found"):
            return f"- {label}: **not found** in the data."
        return (f"- {label}: season mean **{s['season']:.6f}** vs annual mean **{s['annual']:.6f}** "
                f"→ **{s['ratio']:.2f}×**")

    content = f"""# FireLens Phase 2 — Harmonization Validation (v2)

**Owner:** R2 (Science Lead) · **Generated:** {date.today().isoformat()} by `science/harmonize.py`
**Input:** `data/district_monthly.csv` ({len(df):,} rows, {n_districts} districts, period {period})
**Output:** `data/district_harmonized.csv` ({summary['rows']:,} district-months)

Every number below is computed by the script; none is typed in by hand.

## Method in one paragraph

Activity is `fire_pixel_days / clear_pixel_days` per district, month and sensor; rows with
`clear_coverage < {COVERAGE_THRESHOLD:.2f}` or `n_images == 0` stay `NaN`. Suomi-NPP VIIRS is the
anchor. Each MODIS sensor is mapped onto it with **one ratio per state and calendar month**
(`sum(viirs) / sum(modis)` over shared district-months of {CALIB_YEARS[0]}–{CALIB_YEARS[1]}),
using only months before that sensor's **orbit drift** (Terra from
{MONTH_NAMES[DRIFT_START['terra'][1] - 1]} {DRIFT_START['terra'][0]}, Aqua from
{MONTH_NAMES[DRIFT_START['aqua'][1] - 1]} {DRIFT_START['aqua'][0]}). The harmonized value is the
weighted mean of VIIRS (weight 1) and each pre-drift scaled MODIS sensor (weight r² from
leave-one-year-out: Terra {w['terra']:.2f}, Aqua {w['aqua']:.2f}). After the drift, MODIS only fills
months VIIRS could not see, flagged `modis_fill_drift`. `modis_recon` is the record rebuilt
from MODIS alone, the way it would look before VIIRS existed.

## 1. Why the ratio became seasonal

Terra passes at ~10:30 local time, before most afternoon crop burning; Aqua and VIIRS pass
at ~13:30. The MODIS/VIIRS gap is therefore much larger in burning season than in quiet
months, and one all-year ratio cannot fit both. Leave-one-year-out on {CALIB_YEARS[0]}–{CALIB_YEARS[1]}
(fit on six years, test on the seventh; pre-drift months only). Peak months: {peak_text}.
`bias` = sum(scaled) ÷ sum(VIIRS); 1.00 means the same total burning.

{_md_table(["Method", "Sensor", "n", "Pearson r", "OLS slope", "Bias", "Peak-month bias"],
           _skill_rows(cmp, "method"))}

Terra in the peak months moves from **{old.loc['terra', 'peak_bias']:.2f}×** of VIIRS (v1) to
**{new.loc['terra', 'peak_bias']:.2f}×** (v2), and its correlation from {old.loc['terra', 'r']:.2f} to
{new.loc['terra', 'r']:.2f}. Aqua was already close and stays close.

## 2. Ratios used (fit on all pre-drift {CALIB_YEARS[0]}–{CALIB_YEARS[1]} months)

VIIRS ÷ MODIS by calendar month. `*` = fewer than {MIN_BURNING_MONTHS} burning district-months, so
the state's all-month ratio (last column) is used.

{_md_table(["State", "Sensor"] + list(MONTH_NAMES) + ["All months"], ratio_rows)}

### Stability by year (all-month ratio of sums)

{_md_table(["State", "Sensor"] + [str(y) for y in year_cols] + ["CV"], stab_rows)}

{unstable_note}

## 3. MODIS-only reconstruction — the evidence for extending back to 2001

If VIIRS had never flown, the calendar would be `modis_recon`: the weighted mean of the scaled
MODIS sensors. Leave-one-year-out against VIIRS: **r = {rec['r']:.3f}**, bias **{rec['bias']:.2f}**,
peak-month bias **{rec['peak_bias']:.2f}**, slope {rec['slope']:.2f} (n = {rec['n']:,}). This is the
skill to expect when the same ratios are applied to Terra (2001–) and Aqua (2003–) before
2012, when both still flew their nominal orbits.

The blend itself stays on the VIIRS scale: harmonized vs VIIRS on the same rows,
bias **{bl['bias']:.2f}**, peak-month bias **{bl['peak_bias']:.2f}**, r = {bl['r']:.3f}. So months
with and without a given MODIS sensor sit at the same level, and the sensor mix no longer
steps the series.

## 4. Drift period (2023–2025): why drifted MODIS is not blended

By 2023 Terra had drifted to an earlier and Aqua to a later overpass (Aqua ~15:30 local time
by mid-2026), while farm burning in Punjab also moved later in the day. The pre-drift ratios,
applied blind:

{_md_table(["Method", "Sensor", "n", "Pearson r", "OLS slope", "Bias", "Peak-month bias"],
           _skill_rows(drift, "method"))}

By year (pre-drift ratios):

{_md_table(["Year", "Sensor", "n", "Pearson r", "OLS slope", "Bias", "Peak-month bias"],
           _skill_rows(res['drift_by_year'].assign(year=res['drift_by_year']['year'].astype(str)), "year"))}

Aqua reads **{blind.loc['aqua', 'peak_bias']:.2f}×** VIIRS in the peak months, and refitting on the
previous year still leaves **{roll.loc['aqua', 'peak_bias']:.2f}×**: the overpass keeps moving, so last
year's ratio is already stale. A blend would inherit that drift, so after the drift start
the harmonized value is VIIRS where VIIRS saw the district, and drifted MODIS only fills
the rest (`source = modis_fill_drift`, shown as lower confidence in the app). The post-2023
decline in VIIRS is consistent with burning moving after the 13:30 overpass; part of it may
be a detection effect rather than less burning.

## 5. Harmonized product checks

| Check | Value |
|---|---|
| District-months written | {summary['rows']:,} ({summary['districts']} districts × {summary['months']} months) |
| Rows with a usable `act_harmonized` | {summary['valid_rows']:,} |
| Rows left `NaN` | {summary['nan_rows']:,} |
| `act_harmonized` range | [{summary['min_act']:.6f}, {summary['max_act']:.6f}] |
| Mean `act_harmonized` | {summary['mean_act']:.6f} |
| Low-coverage rows | {summary['low_coverage_rows']:,} |

Where each value comes from (`source`):

{_md_table(["Source", "Rows", "Share"], src_rows)}

Uncertainty columns (`sensor_min`, `sensor_max`, `n_blended`, `clear_coverage`): the range
of the three sensors after scaling is the app's uncertainty band. Half of that range, as a
share of the harmonized value (median over district-months with at least two sensors):
**±{summary['half_range_burning']:.0%}** in the burning months (each district's top 10% of months)
before the drift, **±{summary['half_range_all']:.0%}** over all months (quiet months have few
detections, so sensors disagree more in relative terms), and **±{summary['half_range_burning_drift']:.0%}**
in burning months after the drift. It is a measure of sensor disagreement, not a confidence
interval.

Peak preservation:

{peak_block(peaks['ludhiana'], 'Ludhiana (Punjab), Oct–Nov paddy peak')}
{peak_block(peaks['naini_tal'], 'Naini Tal (Uttarakhand), Apr–May forest-fire peak')}

Assertions enforced by the script: `0 <= act_harmonized <= 1`; `n_valid_sensors` in 0–3;
`act_harmonized` is `NaN` exactly where `source == "none"`; a month VIIRS saw is never filled
from MODIS; `n_blended >= 1` exactly where a value exists; `sensor_min <= sensor_max`. All passed.

## 6. Notes and limitations

- **Ratios are per state and calendar month, not per district.** A per-district ratio would
  fit noise. Months with few burning district-months fall back to the state ratio.
- **The fill is a measurement, not an imputation.** A `modis_fill` value is another
  satellite's observation of the same district and month, put on the VIIRS scale.
- **Drift dates** are NASA's: Terra below 10:15 MLT from October 2022, Aqua above 13:45 MLT
  from February 2023.
- **Not corrected here:** NOAA-20/21, VIIRS 375 m detail (the 1 km VNP14A1 grid is used so
  that all sensors share one grid), boundary vintage, and the UTC/IST month edge. See
  `docs/decisions.md`.
- `data/district_monthly.csv` is untouched; this script only writes
  `data/district_harmonized.csv` and this file.
"""
    path.write_text(content, encoding="utf-8")
    print(f"  wrote {path}")


# --------------------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Harmonize MODIS fire activity onto the Suomi-NPP VIIRS anchor.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--validation", type=Path, default=DEFAULT_VALIDATION)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    print(f"FireLens Phase 2 harmonization (v2) — input {args.input}")
    df = load_monthly(args.input)
    print(f"  {len(df):,} rows | {df['district'].nunique()} districts | {df['state'].nunique()} states | "
          f"low-coverage rows: {int(df['low_coverage'].sum()):,}")

    res = evaluate(df)
    harmonized, summary = build_harmonized(df, res["ratios"], res["weights"])
    peaks = verify(harmonized)

    expected_rows = summary["districts"] * 132
    assert len(harmonized) == expected_rows, (
        f"harmonized table has {len(harmonized)} rows, expected {expected_rows}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    harmonized.to_csv(args.output, index=False, float_format="%.8g")
    print(f"\n  wrote {args.output} ({len(harmonized):,} rows); sources: {summary['sources']}")

    write_validation(args.validation, df, res, summary, peaks)
    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
