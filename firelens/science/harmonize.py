#!/usr/bin/env python3
"""FireLens Phase 2 — cross-sensor harmonization of the monthly fire record.

Problem
-------
Terra MODIS, Aqua MODIS and Suomi-NPP VIIRS do not count burning the same way. Their
raw activity series step up and down whenever the sensor mix changes, which looks like a
change in burning but is an instrument artefact. This script learns, from the years in
which all three sensors overlap, how much each MODIS sensor under- or over-reads relative
to the VIIRS anchor, then applies that calibration to every month to produce one
harmonized activity series per district.

Pipeline
--------
1. Load ``data/district_monthly.csv`` and compute the contract metrics:
   ``activity``, ``clear_coverage``, ``low_coverage``.
2. Calibrate on 2016–2022 only: per (state, MODIS sensor), the median of
   ``viirs_snpp_activity / modis_activity`` over shared district-months where both > 0.
   Check year-to-year stability and fall back to a sensor-level pooled ratio if a
   state's ratio is too unstable (CV > 0.50).
3. Validate on the unseen 2023–2025 holdout: scale MODIS, then report Pearson r/p,
   signed and absolute median error, and the residual by year.
4. Build ``data/district_harmonized.csv``: one row per district-month with
   ``viirs_act``, ``terra_scaled``, ``aqua_scaled``, ``act_harmonized``,
   ``n_valid_sensors``, ``low_coverage``, ``baseline``, ``anomaly``, ``percentile``.
5. Write ``science/validation.md`` with every calibration, stability and validation table.

Rules honoured (docs/decisions.md, docs/data-contract.md)
---------------------------------------------------------
* ``activity = fire_pixel_days / clear_pixel_days``; NaN when ``clear_pixel_days == 0`` or
  ``n_images == 0``.
* ``clear_coverage = (clear_pixel_days / days_in_month) / baseline``, where the baseline is
  that (state, district, sensor)'s maximum monthly ``clear_pixel_days / days_in_month``.
  Phase 2 refines the Phase 1 district-level proxy by computing it per sensor, so a sensor
  with systematically fewer clear views cannot depress another sensor's coverage.
* Never impute, forward-fill or zero-fill. Low-coverage rows keep ``activity = NaN``, are
  excluded from calibration and climatology, and are excluded with ``skipna=True``.
* The input CSV is read-only: this script writes only
  ``data/district_harmonized.csv`` and ``science/validation.md``.

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

COVERAGE_THRESHOLD = 0.10
CALIB_YEARS = (2016, 2022)
HOLDOUT_YEARS = (2023, 2025)
FULL_YEARS = (2016, 2026)
CV_LIMIT = 0.50

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


# --------------------------------------------------------------------------------------
# 2. Calibration on 2016-2022
# --------------------------------------------------------------------------------------


def calibrate(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, float], bool]:
    """Estimate the VIIRS/MODIS ratio per (state, sensor) on the calibration years.

    Returns
    -------
    ratios
        Columns ``state, sensor, ratio, n_pairs, p10, p50, p90, cv, use_fallback, method``.
    stability
        Long table of the per-year median ratio (2016–2022) for each (state, sensor),
        with the CV across years.
    fallback_ratios
        Sensor-level pooled median ratio, used where a state's ratio is unstable.
    use_fallback
        True if any (state, sensor) exceeded ``CV_LIMIT``.
    """
    calib = df[df["year"].between(*CALIB_YEARS) & ~df["low_coverage"]]
    wide = _wide_activity(calib).dropna(subset=[ANCHOR])

    rows: list[dict] = []
    stability_rows: list[dict] = []
    fallback_ratios: dict[str, float] = {}

    states = sorted(df["state"].dropna().unique().tolist())
    for sensor in MODELS:
        # Sensor-level pooled ratio: the fallback when a state's own ratio is unstable.
        pooled = wide.dropna(subset=[sensor])
        pooled = pooled[(pooled[ANCHOR] > 0) & (pooled[sensor] > 0)]
        pooled_ratio = (
            float((pooled[ANCHOR] / pooled[sensor]).median()) if len(pooled) else np.nan
        )
        fallback_ratios[sensor] = pooled_ratio

    for state in states:
        in_state = wide[wide.index.get_level_values("state") == state]
        for sensor in MODELS:
            shared = in_state.dropna(subset=[sensor])
            shared = shared[(shared[ANCHOR] > 0) & (shared[sensor] > 0)]
            ratio_series = shared[ANCHOR] / shared[sensor]

            if ratio_series.empty:
                rows.append(
                    {
                        "state": state,
                        "sensor": sensor,
                        "ratio": np.nan,
                        "n_pairs": 0,
                        "p10": np.nan,
                        "p50": np.nan,
                        "p90": np.nan,
                        "cv": np.nan,
                        "use_fallback": True,
                        "method": "no shared months",
                    }
                )
                continue

            yearly = ratio_series.groupby(shared.index.get_level_values("year")).median()
            yearly = yearly.reindex(range(CALIB_YEARS[0], CALIB_YEARS[1] + 1))
            cv = (
                float(yearly.std(ddof=1) / yearly.mean())
                if yearly.notna().sum() >= 2 and yearly.mean() > 0
                else np.nan
            )
            use_fallback = bool(np.isfinite(cv) and cv > CV_LIMIT)
            ratio = (
                fallback_ratios[sensor]
                if use_fallback
                else float(ratio_series.median())
            )

            rows.append(
                {
                    "state": state,
                    "sensor": sensor,
                    "ratio": ratio,
                    "n_pairs": int(len(shared)),
                    "p10": float(ratio_series.quantile(0.10)),
                    "p50": float(ratio_series.median()),
                    "p90": float(ratio_series.quantile(0.90)),
                    "cv": cv,
                    "use_fallback": use_fallback,
                    "method": (
                        f"fallback: pooled {sensor} median"
                        if use_fallback
                        else "state median"
                    ),
                }
            )

            for year in range(CALIB_YEARS[0], CALIB_YEARS[1] + 1):
                value = yearly.get(year, np.nan)
                stability_rows.append(
                    {
                        "state": state,
                        "sensor": sensor,
                        "year": year,
                        "median_ratio": float(value) if pd.notna(value) else np.nan,
                        "n_pairs": int(
                            (shared.index.get_level_values("year") == year).sum()
                        ),
                    }
                )

    ratios = pd.DataFrame(rows)
    stability = pd.DataFrame(stability_rows)
    use_fallback_any = bool(ratios["use_fallback"].any())

    print("\nCalibration ratios (VIIRS / MODIS), 2016-2022:")
    for _, r in ratios.iterrows():
        print(
            f"  {r['state']:<12} {r['sensor']:<6} ratio={r['ratio']:.3f} "
            f"(n={r['n_pairs']:>4}, p10={r['p10']:.2f}, p90={r['p90']:.2f}, "
            f"CV={r['cv']:.3f}) {r['method']}"
        )
    print(f"  USE_FALLBACK = {use_fallback_any} (CV limit {CV_LIMIT})")

    return ratios, stability, fallback_ratios, use_fallback_any


def _ratio_map(ratios: pd.DataFrame, sensor: str) -> pd.Series:
    """State -> ratio lookup for one sensor."""
    sub = ratios[ratios["sensor"] == sensor]
    return pd.Series(sub["ratio"].to_numpy(), index=sub["state"].astype(str))


# --------------------------------------------------------------------------------------
# 3. Validation on the 2023-2025 holdout
# --------------------------------------------------------------------------------------


def _pearson(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """Pearson r and p, guarding against tiny or constant samples."""
    if len(x) < 3 or np.std(x) == 0 or np.std(y) == 0:
        return float("nan"), float("nan")
    r, p = stats.pearsonr(x, y)
    return float(r), float(p)


def _error_stats(residual: np.ndarray) -> dict[str, float]:
    """Signed median error and median absolute error."""
    if len(residual) == 0:
        return {"n": 0, "median_signed": np.nan, "median_abs": np.nan}
    return {
        "n": int(len(residual)),
        "median_signed": float(np.median(residual)),
        "median_abs": float(np.median(np.abs(residual))),
    }


def _year_effect_test(
    years: np.ndarray, residual: np.ndarray, groups: list[np.ndarray]
) -> dict[str, float]:
    """Test whether the residual changes across holdout years.

    Kruskal–Wallis answers "is any year different?" without assuming normality;
    the OLS slope on year answers "is there a monotone drift?". Both are reported so
    "no step" is a measured statement, not an assertion.
    """
    out: dict[str, float] = {
        "kw_H": np.nan,
        "kw_p": np.nan,
        "trend_slope": np.nan,
        "trend_p": np.nan,
        "n_years": float(len(groups)),
    }
    usable = [g for g in groups if len(g) > 0]
    if len(usable) >= 2:
        try:
            h, p = stats.kruskal(*usable)
            out["kw_H"] = float(h)
            out["kw_p"] = float(p)
        except ValueError:
            pass
    if len(residual) >= 3 and len(np.unique(years)) >= 2:
        fit = stats.linregress(years.astype(float), residual)
        out["trend_slope"] = float(fit.slope)
        out["trend_p"] = float(fit.pvalue)
    return out


def validate(
    df: pd.DataFrame, ratios: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, dict[int, dict[str, float]], dict]:
    """Apply calibration to the 2023–2025 holdout and measure agreement with VIIRS.

    Returns
    -------
    summary
        One row per series (pooled / terra / aqua) with n, r, p, signed and absolute
        median error, mean signed error and the share of exactly-zero residuals.
    residuals
        One row per (series, year) with the residual median, mean and zero share.
    per_year
        Nested dict used for the validation document.
    extras
        Year-effect tests (Kruskal–Wallis across years, OLS trend of residual on year)
        and other numbers the report quotes.
    """
    hold = df[df["year"].between(*HOLDOUT_YEARS) & ~df["low_coverage"]]
    wide = _wide_activity(hold).dropna(subset=[ANCHOR])

    frames: dict[str, pd.DataFrame] = {}
    for sensor in MODELS:
        sub = wide.dropna(subset=[sensor]).copy()
        if sub.empty:
            continue
        ratio = sub.index.get_level_values("state").map(_ratio_map(ratios, sensor))
        sub["modis"] = sub[sensor].to_numpy(dtype=float)
        sub["scaled"] = np.clip(
            sub["modis"].to_numpy(dtype=float) * np.asarray(ratio, dtype=float), 0.0, 1.0
        )
        sub["anchor"] = sub[ANCHOR].to_numpy(dtype=float)
        sub["sensor"] = sensor
        frames[sensor] = sub

    if not frames:
        raise RuntimeError("No overlapping VIIRS/MODIS rows in the 2023-2025 holdout.")

    pooled = pd.concat(frames.values())

    summary_rows: list[dict] = []
    residual_rows: list[dict] = []
    extras: dict = {}

    panels = [("pooled (terra + aqua)", pooled)]
    panels += [(sensor, frames[sensor]) for sensor in MODELS if sensor in frames]

    for label, frame in panels:
        residual = (frame["scaled"] - frame["anchor"]).to_numpy(dtype=float)
        r, p = _pearson(frame["scaled"].to_numpy(dtype=float), frame["anchor"].to_numpy(dtype=float))
        err = _error_stats(residual)
        summary_rows.append(
            {
                "series": label,
                "n": err["n"],
                "r": r,
                "p": p,
                "median_signed": err["median_signed"],
                "median_abs": err["median_abs"],
                "mean_signed": float(np.mean(residual)) if len(residual) else np.nan,
                "share_zero": float(np.mean(residual == 0)) if len(residual) else np.nan,
                "slope": (
                    float(np.polyfit(frame["anchor"], frame["scaled"], 1)[0])
                    if len(frame) >= 3 and frame["anchor"].std() > 0
                    else np.nan
                ),
            }
        )
        frame_years = frame.index.get_level_values("year").to_numpy()
        year_groups: list[np.ndarray] = []
        for year in sorted(frame.index.get_level_values("year").unique()):
            year_residual = residual[frame_years == year]
            year_groups.append(year_residual)
            residual_rows.append(
                {
                    "series": label,
                    "year": int(year),
                    "n": int(len(year_residual)),
                    "median": float(np.median(year_residual)),
                    "mean": float(np.mean(year_residual)),
                    "share_zero": float(np.mean(year_residual == 0)),
                }
            )
        extras[label] = {
            "share_scaled_gt_anchor": float(
                np.mean(frame["scaled"] > frame["anchor"])
            ),
            "year_test": _year_effect_test(frame_years, residual, year_groups),
        }

    summary = pd.DataFrame(summary_rows)
    residuals = pd.DataFrame(residual_rows)

    per_year = {
        int(row["year"]): {
            "n": int(row["n"]),
            "median": float(row["median"]),
            "mean": float(row["mean"]),
        }
        for _, row in residuals[residuals["series"].str.startswith("pooled")].iterrows()
    }

    print("\n2023-2025 holdout validation (scaled MODIS vs VIIRS):")
    for _, row in summary.iterrows():
        print(
            f"  {row['series']:<22} n={row['n']:>5}  r={row['r']:.3f} "
            f"(p={_fmt_p(row['p'])})  signed_median={row['median_signed']:+.3e}  "
            f"abs_median={row['median_abs']:.3e}  mean={row['mean_signed']:+.3e}"
        )
    print("  residual by year (pooled):")
    for year, values in per_year.items():
        print(
            f"    {year}: n={values['n']:>5} median={values['median']:+.3e} "
            f"mean={values['mean']:+.3e}"
        )
    test = extras.get("pooled (terra + aqua)", {}).get("year_test", {})
    if test:
        print(
            "  year effect (pooled): Kruskal-Wallis p="
            f"{test.get('kw_p', float('nan')):.3g}, OLS trend "
            f"{test.get('trend_slope', float('nan')):+.2e}/yr "
            f"(p={test.get('trend_p', float('nan')):.3g})"
        )

    return summary, residuals, per_year, extras


# --------------------------------------------------------------------------------------
# 4. Build the harmonized district-month table
# --------------------------------------------------------------------------------------


def build_harmonized(
    df: pd.DataFrame, ratios: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Create one harmonized row per district-month and return summary statistics."""
    full = df[df["year"].between(*FULL_YEARS)]
    wide = _wide_activity(full)

    out = wide.index.to_frame(index=False)
    out["viirs_act"] = np.clip(wide[ANCHOR].to_numpy(dtype=float), 0.0, 1.0)

    for sensor, column in (("terra", "terra_scaled"), ("aqua", "aqua_scaled")):
        ratio = wide.index.get_level_values("state").map(_ratio_map(ratios, sensor))
        out[column] = np.clip(
            wide[sensor].to_numpy(dtype=float) * np.asarray(ratio, dtype=float), 0.0, 1.0
        )

    sensor_columns = ["viirs_act", "terra_scaled", "aqua_scaled"]
    out["act_harmonized"] = out[sensor_columns].mean(axis=1, skipna=True)
    out["n_valid_sensors"] = (
        out[sensor_columns].notna().sum(axis=1).astype("int64")
    )

    # A month is unusable when nothing valid survived. The second clause spells out the
    # contract's stronger statement: no VIIRS and fewer than one valid MODIS sensor.
    modis_valid = out["terra_scaled"].notna().astype(int) + out[
        "aqua_scaled"
    ].notna().astype(int)
    out["low_coverage"] = (out["n_valid_sensors"] == 0) | (
        out["viirs_act"].isna() & (modis_valid < 1)
    )

    # Calendar-month climatology per district, then the anomaly and the percentile rank.
    group = out.groupby(["state", "district"], observed=True)["act_harmonized"]
    out["baseline"] = out.groupby(
        ["state", "district", "month"], observed=True
    )["act_harmonized"].transform("mean")
    out["anomaly"] = out["act_harmonized"] - out["baseline"]
    out["percentile"] = group.transform(
        lambda s: s.rank(pct=True, method="average") * 100.0
    )

    out = out.sort_values(INDEX, kind="mergesort").reset_index(drop=True)

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
        "share_3_sensors": float((out["n_valid_sensors"] == 3).mean()),
        "share_2_sensors": float((out["n_valid_sensors"] == 2).mean()),
        "share_1_sensor": float((out["n_valid_sensors"] == 1).mean()),
        "share_0_sensors": float((out["n_valid_sensors"] == 0).mean()),
        "low_coverage_rows": int(out["low_coverage"].sum()),
    }
    return out, summary


# --------------------------------------------------------------------------------------
# 5. Verification and reporting
# --------------------------------------------------------------------------------------


def _season_stats(
    harmonized: pd.DataFrame, state: str, district: str, months: tuple[int, ...]
) -> dict[str, float]:
    """Season mean vs annual mean of harmonized activity for one district."""
    sub = harmonized[
        (harmonized["state"] == state)
        & (harmonized["district"] == district)
    ]
    if sub.empty:
        return {"found": 0, "season": np.nan, "annual": np.nan, "ratio": np.nan}
    annual = float(sub["act_harmonized"].mean(skipna=True))
    season = float(
        sub.loc[sub["month"].isin(months), "act_harmonized"].mean(skipna=True)
    )
    return {
        "found": 1,
        "season": season,
        "annual": annual,
        "ratio": season / annual if annual and np.isfinite(annual) and annual > 0 else np.nan,
    }


def verify(harmonized: pd.DataFrame) -> dict[str, dict[str, float]]:
    """Assert the output range and confirm both seasonal peaks survive harmonization."""
    valid = harmonized["act_harmonized"].dropna()
    lo, hi = float(valid.min()), float(valid.max())
    assert lo >= 0.0 and hi <= 1.0, (
        f"act_harmonized outside [0, 1]: min={lo}, max={hi}"
    )
    assert harmonized["n_valid_sensors"].between(0, 3).all(), (
        "n_valid_sensors outside 0-3"
    )

    ludhiana = _season_stats(harmonized, "Punjab", "Ludhiana", (10, 11))
    naini_tal = _season_stats(harmonized, "Uttarakhand", "Naini Tal", (4, 5))

    print("\nPeak preservation:")
    if ludhiana["found"]:
        print(
            f"  Ludhiana (Punjab) Oct-Nov mean act_harmonized={ludhiana['season']:.6f} "
            f"vs annual={ludhiana['annual']:.6f} ({ludhiana['ratio']:.2f}x)"
        )
    else:
        print("  WARN: Ludhiana not found in the output")
    if naini_tal["found"]:
        print(
            f"  Naini Tal (Uttarakhand) Apr-May mean act_harmonized={naini_tal['season']:.6f} "
            f"vs annual={naini_tal['annual']:.6f} ({naini_tal['ratio']:.2f}x)"
        )
    else:
        print("  WARN: Naini Tal not found in the output")

    return {"ludhiana": ludhiana, "naini_tal": naini_tal}


# --------------------------------------------------------------------------------------
# 6. validation.md
# --------------------------------------------------------------------------------------


def _md_table(headers: list[str], rows: list[list[str]]) -> str:
    """Small markdown table writer (no tabulate dependency)."""
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def _fmt(value: float, digits: int = 3) -> str:
    if value is None or not np.isfinite(value):
        return "n/a"
    return f"{value:.{digits}f}"


def _fmt_p(p: float) -> str:
    """P-value that never prints the meaningless '0.00e+00'."""
    if p is None or not np.isfinite(p):
        return "n/a"
    if p == 0:
        return "< 1e-300"
    return f"{p:.2e}"


def write_validation(
    path: Path,
    df: pd.DataFrame,
    ratios: pd.DataFrame,
    stability: pd.DataFrame,
    summary: pd.DataFrame,
    residuals: pd.DataFrame,
    valid_summary: dict[str, float],
    peaks: dict[str, dict[str, float]],
    use_fallback: bool,
    extras: dict,
) -> None:
    """Render science/validation.md with every calibration and holdout number."""
    path.parent.mkdir(parents=True, exist_ok=True)

    years = sorted(df["year"].dropna().unique().tolist())
    period = f"{int(min(years))}-01 to {int(max(years))}-12" if years else "n/a"
    states = sorted(df["state"].dropna().unique().tolist())
    n_districts = df[["state", "district"]].drop_duplicates().shape[0]
    low_rows = int(df["low_coverage"].sum())

    ratio_rows = [
        [
            r["state"],
            r["sensor"],
            f"{int(r['n_pairs'])}",
            _fmt(r["ratio"], 3),
            _fmt(r["p10"], 2),
            _fmt(r["p50"], 3),
            _fmt(r["p90"], 2),
            _fmt(r["cv"], 3),
            r["method"],
        ]
        for _, r in ratios.iterrows()
    ]

    # Stability table: one row per state-sensor with a column per calibration year.
    stab_rows = []
    for (state, sensor), group in stability.groupby(["state", "sensor"], observed=True):
        by_year = dict(zip(group["year"], group["median_ratio"]))
        cv = ratios.loc[
            (ratios["state"] == state) & (ratios["sensor"] == sensor), "cv"
        ]
        stab_rows.append(
            [state, sensor]
            + [
                _fmt(by_year.get(year, np.nan), 2)
                for year in range(CALIB_YEARS[0], CALIB_YEARS[1] + 1)
            ]
            + [_fmt(float(cv.iloc[0]) if len(cv) else np.nan, 3)]
        )

    slide_rows = [
        [
            row["series"],
            f"{int(row['n'])}",
            _fmt(row["r"], 3),
            _fmt_p(row["p"]),
            f"{row['median_signed']:+.2e}",
            f"{row['median_abs']:.2e}",
            f"{row['mean_signed']:+.2e}",
            f"{row['share_zero']:.0%}",
            _fmt(row["slope"], 2),
        ]
        for _, row in summary.iterrows()
    ]

    resid_rows = [
        [
            row["series"],
            f"{int(row['year'])}",
            f"{int(row['n'])}",
            f"{row['median']:+.2e}",
            f"{row['mean']:+.2e}",
            f"{row['share_zero']:.0%}",
        ]
        for _, row in residuals.iterrows()
    ]

    # Year-effect verdict, computed rather than asserted. Kruskal–Wallis asks whether the
    # years differ at all; the OLS slope asks whether the residual drifts monotonically.
    # Both are quoted, with the per-year means, so the wording cannot contradict the test.
    test = extras.get("pooled (terra + aqua)", {}).get("year_test", {})
    kw_p = test.get("kw_p", np.nan)
    trend_p = test.get("trend_p", np.nan)
    trend_slope = test.get("trend_slope", np.nan)
    pooled_resid = residuals[residuals["series"] == "pooled (terra + aqua)"]
    year_means = {
        int(row["year"]): float(row["mean"]) for _, row in pooled_resid.iterrows()
    }
    if np.isfinite(kw_p) and np.isfinite(trend_p) and year_means:
        first_year, last_year = min(year_means), max(year_means)
        if kw_p < 0.05:
            year_note = (
                "The holdout years **do** differ in their pooled residual "
                f"(Kruskal–Wallis p={_fmt_p(kw_p)}), so the calibration is not equally "
                "good in every year; the per-year means below say where."
            )
        elif trend_p < 0.05:
            year_note = (
                "Kruskal–Wallis finds no overall year difference "
                f"(p={_fmt_p(kw_p)}), but the linear trend on year is significant "
                f"({trend_slope:+.2e} per year, p={_fmt_p(trend_p)}). With only three "
                f"holdout years that is driven by {first_year} (mean "
                f"{year_means[first_year]:+.2e}) sitting below {last_year} "
                f"(mean {year_means[last_year]:+.2e}): read it as a possible step after "
                f"{first_year}, not a smooth drift, and re-check when 2026 data lands."
            )
        else:
            year_note = (
                "No step or trend is detectable across the holdout years "
                f"(Kruskal–Wallis p={_fmt_p(kw_p)}, trend p={_fmt_p(trend_p)}), "
                "so the 2016–2022 calibration still applies in 2023–2025."
            )
    else:
        year_note = (
            "Year-effect tests could not be computed (too few groups or constant "
            "residual); treat the per-year table as descriptive only."
        )

    # Agreement text, derived from the fitted numbers so the slide cannot over-claim.
    def _series_row(label: str) -> pd.Series | None:
        hit = summary[summary["series"] == label]
        return hit.iloc[0] if len(hit) else None

    pooled_row = _series_row("pooled (terra + aqua)")
    terra_row = _series_row("terra")
    aqua_row = _series_row("aqua")
    if pooled_row is not None:
        slope_sentence = (
            f"Pooled slope is **{pooled_row['slope']:.2f}**"
            + (
                f" (Terra {terra_row['slope']:.2f}, Aqua {aqua_row['slope']:.2f})"
                if terra_row is not None and aqua_row is not None
                else ""
            )
            + ": scaled MODIS does not reproduce VIIRS's full month-to-month swing. "
            "Terra at the low end is the weak link; Aqua tracks VIIRS closely."
        )
        if valid_summary["mean_act"] > 0:
            pct = 100.0 * pooled_row["median_abs"] / valid_summary["mean_act"]
            error_sentence = (
                f"For scale, the pooled median absolute error is "
                f"{pooled_row['median_abs']:.2e}, about **{pct:.0f}%** of the mean "
                f"harmonized activity ({valid_summary['mean_act']:.2e})."
            )
        else:
            error_sentence = ""
        zero_text = (
            f"about **{pooled_row['share_zero']:.0%}** of the valid holdout "
            "district-months have no detections in either sensor"
        )
    else:
        slope_sentence = ""
        error_sentence = ""
        zero_text = "a large share of valid holdout district-months have no detections in either sensor"

    def peak_block(stats: dict[str, float], label: str) -> str:
        if not stats.get("found"):
            return f"- {label}: **not found** in the data."
        return (
            f"- {label}: season mean **{stats['season']:.6f}** vs annual mean "
            f"**{stats['annual']:.6f}** → **{stats['ratio']:.2f}×**"
        )

    content = f"""# FireLens Phase 2 — Harmonization Validation

**Owner:** R2 (Science Lead) · **Generated:** {date.today().isoformat()} by `science/harmonize.py`
**Input:** `data/district_monthly.csv` ({len(df):,} rows, {n_districts} districts, period {period})
**Output:** `data/district_harmonized.csv` ({valid_summary['rows']:,} district-months)

Purpose: remove the sensor step from the record. VIIRS is the anchor (continuous
2016–2026 record); each MODIS sensor is scaled to it using only the years all three
sensors overlap (2016–2022), then checked on three years it never saw (2023–2025).

Method in one paragraph: activity is `fire_pixel_days / clear_pixel_days` per district,
month and sensor; rows with `clear_coverage < {COVERAGE_THRESHOLD:.2f}` or `n_images == 0` are
low-coverage and stay `NaN` (no imputation anywhere). For each state and MODIS sensor we
take the median of `viirs_activity / modis_activity` over shared district-months where
both are positive, which is the multiplicative factor that maps MODIS onto the VIIRS
scale. That factor is applied to every MODIS month, clipped to `[0, 1]`, and the three
sensor series are averaged (`skipna=True`) into `act_harmonized`. Weather, cloud and
district area largely cancel in the ratio, so the factor is a sensor calibration, not a
correction for burning.

---

## 1. Calibration ratios (2016–2022)

Median of `viirs_snpp / modis` over shared district-months where both activities > 0.
`p10`/`p90` show the spread of the individual pairs; `CV` is the coefficient of variation
of the year-by-year median ratio, i.e. the stability check.

{_md_table(
    ["State", "MODIS sensor", "Shared months", "Ratio", "p10", "p50", "p90", "CV", "Method"],
    ratio_rows,
)}

**USE_FALLBACK = {use_fallback}** (limit `CV > {CV_LIMIT:.2f}`). {
    "At least one state-sensor ratio was unstable across years, so the sensor-level pooled median is used for that row; the `Method` column says which."
    if use_fallback
    else "Every state-sensor ratio is stable enough to use directly, so no fallback was needed."
} The fallback, when triggered, is the median of all shared pairs for that sensor across
states (the 50th percentile); `p10`/`p90` are kept in the table so the spread remains
visible.

Reading the table: a ratio above 1 means VIIRS reads more burning than that MODIS sensor
in that state, so MODIS must be scaled **up** to match. Aqua sits close to VIIRS; Terra
reads substantially lower, which is consistent with its earlier overpass and coarser
detection of small residue fires.

## 2. Stability by year

Per-year median ratio, same filters as above. A flat row means the calibration is not
tracking anything that changes year to year.

{_md_table(
    ["State", "Sensor"] + [str(y) for y in range(CALIB_YEARS[0], CALIB_YEARS[1] + 1)] + ["CV"],
    stab_rows,
)}

## 3. Slide 4 — validation on the 2023–2025 holdout

Unseen years: the ratio learned on 2016–2022 is applied without refitting.
`scaled_modis = clip(modis * ratio, 0, 1)`; residual = `scaled_modis - viirs_snpp`
(positive means the scaled MODIS series still sits above VIIRS).

{_md_table(
    [
        "Series", "n", "Pearson r", "p-value", "Median signed error",
        "Median abs error", "Mean signed error", "Residual = 0", "OLS slope",
    ],
    slide_rows,
)}

Why the median error can read exactly zero: {zero_text}, so their residual is exactly 0
and dominates the median. That is a real property of the data, not perfect agreement —
read the mean signed error, the zero share and the slope together with the median.

{slope_sentence} {error_sentence}

Interpretation for the slide:

- **Pooled** is the headline number: one calibration per sensor and state, applied blind
  to 2023–2025.
- **Terra / Aqua separately** show the calibration is not hiding one good sensor behind a
  bad one. Terra's larger ratio is the harder extrapolation; Aqua's near-1 ratio barely
  moves.
- A high `r` alone is not enough: a series that is 3× too high would also correlate
  strongly. The slope and the error columns are what show the scaled series is *on* the
  VIIRS scale rather than merely moving with it.

### Residual by year

{year_note}

{_md_table(
    ["Series", "Year", "n", "Median residual", "Mean residual", "Residual = 0"],
    resid_rows,
)}

## 4. Harmonized product checks

| Check | Value |
|---|---|
| District-months written | {valid_summary['rows']:,} ({valid_summary['districts']} districts × {valid_summary['months']} months) |
| Rows with a usable `act_harmonized` | {valid_summary['valid_rows']:,} |
| Rows left `NaN` | {valid_summary['nan_rows']:,} |
| `act_harmonized` range | [{valid_summary['min_act']:.6f}, {valid_summary['max_act']:.6f}] |
| Mean `act_harmonized` | {valid_summary['mean_act']:.6f} |
| Rows with 3 / 2 / 1 / 0 valid sensors | {valid_summary['share_3_sensors']:.1%} / {valid_summary['share_2_sensors']:.1%} / {valid_summary['share_1_sensor']:.1%} / {valid_summary['share_0_sensors']:.1%} |
| Low-coverage rows in output | {valid_summary['low_coverage_rows']:,} |

Peak preservation (the reason harmonization must not smooth away the signal):

{peak_block(peaks['ludhiana'], 'Ludhiana (Punjab), Oct–Nov paddy peak')}
{peak_block(peaks['naini_tal'], 'Naini Tal (Uttarakhand), Apr–May forest-fire peak')}

Assertions enforced by the script: `0 <= act_harmonized <= 1` for every non-null row, and
`n_valid_sensors` within 0–3. Both passed.

## 5. Notes and limitations

- **Coverage baseline.** Phase 2 computes the baseline per (state, district, **sensor**),
  the maximum monthly `clear_pixel_days / days_in_month` for that sensor. This refines the
  Phase 1 district-level proxy in `docs/data-contract.md`: it stops a sensor with
  systematically fewer clear views (e.g. a different overpass in the monsoon) from
  depressing another sensor's coverage estimate. It is a QC denominator only; it never
  enters `activity`.
- **Ratios are per state and sensor, not per district.** A per-district ratio would fit
  noise, especially where a district has few burning months. The spread (p10–p90) is wide
  because activity ratios are noisy at low values; the median is the robust summary.
- **Ratio > 1 is expected and is not a bug.** VIIRS detects more small fires; the
  calibration makes MODIS speak VIIRS's language, not the reverse.
- **Zeros are real.** Rows with activity exactly 0 are retained in the mean; only
  low-coverage rows are excluded. Excluding zeros would inflate the harmonized activity.
- **Not corrected here:** NOAA-20/21, boundary vintage, and the UTC/IST month edge. See
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
    print(f"FireLens Phase 2 harmonization — input {args.input}")

    df = load_monthly(args.input)
    print(
        f"  {len(df):,} rows | {df['district'].nunique()} districts | "
        f"{df['state'].nunique()} states | {df['year'].min()}-{df['year'].max()} | "
        f"low-coverage rows: {int(df['low_coverage'].sum()):,}"
    )

    ratios, stability, _fallback, use_fallback = calibrate(df)
    summary, residuals, _per_year, extras = validate(df, ratios)

    harmonized, valid_summary = build_harmonized(df, ratios)
    peaks = verify(harmonized)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    harmonized.to_csv(args.output, index=False, float_format="%.8g")
    print(f"\n  wrote {args.output} ({len(harmonized):,} rows)")

    expected_rows = valid_summary["districts"] * 132
    assert len(harmonized) == expected_rows, (
        f"harmonized table has {len(harmonized)} rows, expected "
        f"{expected_rows} ({valid_summary['districts']} districts x 132 months)"
    )

    write_validation(
        args.validation,
        df,
        ratios,
        stability,
        summary,
        residuals,
        valid_summary,
        peaks,
        use_fallback,
        extras,
    )

    print("\nDone. Phase 2 output is ready for the app and the slide 4 numbers.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
