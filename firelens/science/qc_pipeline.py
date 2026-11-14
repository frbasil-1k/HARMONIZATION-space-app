"""FireLens Phase 1 — quality control, metrics and sanity plots.

Reads the frozen district x month x sensor fire table
(``data/district_monthly.csv``) and answers one question: *does this data mean what we
think it means?*

Public API
----------
load_data(csv_path)
    Read the CSV with explicit dtypes and add a first-of-month ``date`` column.
run_quality_checks(df, is_full_dataset=True)
    The eight Phase 1 checks, each printing PASS/FAIL (or INFO) with counts.
add_metrics(df)
    Add ``activity``, ``days_in_month``, ``land_pixel_baseline`` and ``clear_coverage``.
generate_sanity_plots(df, uttarakhand_district, output_dir="science/figures")
    Save the three high-DPI gate-review figures; returns their paths.
export_gaps(df, output_path="science/gaps.csv", min_coverage=0.10)
    Write every district-month-sensor row that is missing or badly under-covered.

Definitions (see ``docs/data-contract.md`` and ``docs/decisions.md``):

    fire_pixel_days   FireMask >= 8
    clear_pixel_days  FireMask == 5 or FireMask >= 7   (fire pixels are a subset)
    activity          fire_pixel_days / clear_pixel_days; NaN if clear == 0 or n_images == 0
    clear_coverage    (clear / days_in_month) / district baseline, where the baseline is the
                      district's maximum monthly clear / days_in_month (land-pixel proxy)

Everything here is read-only with respect to the input CSV: gaps are exported, never filled.
"""

from __future__ import annotations

import calendar
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless: safe on a laptop, a server and in CI

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

__all__ = [
    "SENSORS",
    "SENSOR_LABELS",
    "PERIOD_START",
    "PERIOD_END",
    "EXPECTED_MONTHS",
    "load_data",
    "run_quality_checks",
    "add_metrics",
    "generate_sanity_plots",
    "export_gaps",
]

# --------------------------------------------------------------------------------------
# Contract constants (frozen; see docs/decisions.md)
# --------------------------------------------------------------------------------------

SENSORS: tuple[str, ...] = ("terra", "aqua", "viirs_snpp")
SENSOR_LABELS: dict[str, str] = {
    "terra": "Terra MODIS",
    "aqua": "Aqua MODIS",
    "viirs_snpp": "Suomi-NPP VIIRS",
}
SENSOR_COLORS: dict[str, str] = {
    "terra": "#d1495b",
    "aqua": "#00798c",
    "viirs_snpp": "#edae49",
}
ANCHOR_SENSOR = "viirs_snpp"

PERIOD_START = (2016, 1)
PERIOD_END = (2026, 12)
EXPECTED_MONTHS = 132  # Jan 2016 .. Dec 2026 inclusive

MONSOON_MONTHS = (7, 8, 9)
PADDY_MONTHS = (10, 11)
WHEAT_MONTHS = (4, 5)
SPRING_FIRE_MONTHS = (4, 5)

REQUIRED_COLUMNS: tuple[str, ...] = (
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
NON_NULL_COLUMNS: tuple[str, ...] = (
    "state",
    "district",
    "sensor",
    "year",
    "month",
    "fire_pixel_days",
    "clear_pixel_days",
    "n_images",
)

DTYPES: dict[str, str] = {
    "state": "string",
    "district": "string",
    "sensor": "string",
    "year": "Int64",
    "month": "Int64",
    "fire_pixel_days": "float64",
    "clear_pixel_days": "float64",
    "mean_frp_mw": "float64",
    "n_images": "Int64",
}

# Check 7 reference district (Ludhiana, Punjab).
LUDHIANA = "Ludhiana"
UTTARAKHAND = "Uttarakhand"


# --------------------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------------------


def load_data(csv_path: str | Path) -> pd.DataFrame:
    """Load the FireLens monthly fire table with explicit dtypes and a date column.

    Parameters
    ----------
    csv_path
        Path to ``data/district_monthly.csv`` (or the Punjab test file, which must use
        the same column names).

    Returns
    -------
    pandas.DataFrame
        Sorted by state, district, sensor, year, month, with an extra ``date`` column
        holding the first day of each month (``datetime64[ns]``).

    Raises
    ------
    FileNotFoundError
        If the CSV does not exist.
    ValueError
        If required columns are missing, so a renamed export fails loudly instead of
        producing quietly wrong checks.
    """
    path = Path(csv_path)
    if not path.is_file():
        raise FileNotFoundError(f"CSV not found: {path.resolve()}")

    # Only pass dtypes for columns actually present, so the missing-column error we raise
    # below is the useful one instead of a pandas dtype error.
    header = pd.read_csv(path, nrows=0)
    present = [c for c in header.columns if c in DTYPES]
    df = pd.read_csv(path, dtype={c: DTYPES[c] for c in present}, keep_default_na=True)

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            f"{path} is missing required column(s): {missing}. "
            f"Found: {list(df.columns)}. See docs/data-contract.md."
        )

    # Normalise identifiers without destroying values: strip padding that a CSV round-trip
    # or a manual edit can introduce, but never rewrite names (the GeoJSON must match).
    for col in ("state", "district", "sensor"):
        df[col] = df[col].astype("string").str.strip()

    # Numbers: coerce so bad cells become NaN and are caught by check V3 rather than
    # crashing the whole run. Nullable dtypes preserve "missing" as <NA>.
    df["year"] = pd.to_numeric(df["year"], errors="coerce").round().astype("Int64")
    df["month"] = pd.to_numeric(df["month"], errors="coerce").round().astype("Int64")
    df["n_images"] = pd.to_numeric(df["n_images"], errors="coerce").round().astype("Int64")
    for col in ("fire_pixel_days", "clear_pixel_days", "mean_frp_mw"):
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")

    # First day of the month; invalid year/month pairs become NaT.
    df["date"] = pd.to_datetime(
        pd.DataFrame(
            {
                "year": df["year"].astype("float64"),
                "month": df["month"].astype("float64"),
                "day": 1.0,
            }
        ),
        errors="coerce",
    )
    df.loc[df["date"] < pd.Timestamp(1900, 1, 1), "date"] = pd.NaT

    return df.sort_values(
        ["state", "district", "sensor", "year", "month"], kind="mergesort"
    ).reset_index(drop=True)


# --------------------------------------------------------------------------------------
# Derived metrics
# --------------------------------------------------------------------------------------


def add_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of ``df`` with the contract metrics added.

    Adds
    ----
    days_in_month
        Calendar length of the row's month (29 in leap Februaries).
    activity
        ``fire_pixel_days / clear_pixel_days``; ``NaN`` where ``clear_pixel_days <= 0``
        or ``n_images <= 0``. Never 0-filled.
    clear_per_day
        ``clear_pixel_days / days_in_month``, the average clearly-seen pixel-days per day.
    land_pixel_baseline
        Per-district maximum of ``clear_per_day`` over all its months and sensors. This is
        the land-pixel proxy agreed for Phase 1: the clearest month sees essentially all
        land pixels, so it approximates the district's land pixel count.
    clear_coverage
        ``clear_per_day / land_pixel_baseline`` in ``[0, 1]``; ``NaN`` when the baseline is 0.
    """
    out = df.copy()

    year = pd.to_numeric(out["year"], errors="coerce")
    month = pd.to_numeric(out["month"], errors="coerce")
    days = pd.Series(np.nan, index=out.index, dtype="float64")
    valid = year.notna() & month.notna() & month.between(1, 12)
    if valid.any():
        days.loc[valid] = [
            float(calendar.monthrange(int(y), int(m))[1])
            for y, m in zip(year[valid], month[valid])
        ]
    out["days_in_month"] = days

    fire = pd.to_numeric(out["fire_pixel_days"], errors="coerce").astype("float64")
    clear = pd.to_numeric(out["clear_pixel_days"], errors="coerce").astype("float64")
    n_images = pd.to_numeric(out["n_images"], errors="coerce").astype("float64")

    activity = fire / clear
    observed = (clear > 0) & (n_images > 0)
    out["activity"] = activity.where(observed)

    clear_per_day = clear / out["days_in_month"]
    out["clear_per_day"] = clear_per_day

    # Per-district baseline across every sensor and month. District names can repeat
    # across states, so group on the pair.
    baseline = clear_per_day.groupby(
        [out["state"].astype("string"), out["district"].astype("string")], dropna=False
    ).transform("max")
    out["land_pixel_baseline"] = baseline
    out["clear_coverage"] = (clear_per_day / baseline).where(baseline > 0)

    return out


def _ensure_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Add metrics if the caller has not already done so."""
    if {"activity", "clear_coverage", "days_in_month"} <= set(df.columns):
        return df
    return add_metrics(df)


# --------------------------------------------------------------------------------------
# Quality checks
# --------------------------------------------------------------------------------------


def _fmt_pct(part: float, whole: float) -> str:
    return f"{100.0 * part / whole:.1f}%" if whole else "n/a"


def run_quality_checks(df: pd.DataFrame, is_full_dataset: bool = True) -> dict[str, bool]:
    """Run the eight Phase 1 checks and print PASS/FAIL diagnostics.

    Parameters
    ----------
    df
        Frame from :func:`load_data` (metrics are computed here if absent).
    is_full_dataset
        ``True`` for ``data/district_monthly.csv`` (rectangular 132-month grid required).
        ``False`` for the 17:00 Punjab test file, where only the observed period is
        required and the row-count check becomes a completeness check over that period.

    Returns
    -------
    dict[str, bool]
        Check name -> passed. Check 8 (latest active month) is informational and always
        ``True`` when every sensor has at least one active month; it is still reported.
    """
    df = _ensure_metrics(df)
    results: dict[str, bool] = {}
    n_rows = len(df)

    def report(label: str, ok: bool, detail: str = "", info: bool = False) -> None:
        status = "INFO" if info else ("PASS" if ok else "FAIL")
        results[label] = bool(ok)
        print(f"[{status}] {label}" + (f" — {detail}" if detail else ""))

    print("\n" + "=" * 78)
    print(f"FireLens quality checks — {n_rows:,} rows | "
          f"{'FULL DATASET' if is_full_dataset else 'PUNJAB TEST FILE'}")
    print("=" * 78)

    # ---- V1: row count ---------------------------------------------------------------
    n_districts = df[["state", "district"]].drop_duplicates().shape[0]
    n_dupes = int(df.duplicated(subset=["state", "district", "sensor", "year", "month"]).sum())
    if is_full_dataset:
        expected = n_districts * len(SENSORS) * EXPECTED_MONTHS
        months_present = df[["year", "month"]].drop_duplicates().shape[0]
        ok = (n_rows == expected) and n_dupes == 0 and months_present == EXPECTED_MONTHS
        report(
            "V1 row count and grain",
            ok,
            f"rows={n_rows:,}, expected={expected:,} "
            f"({n_districts} districts × 3 sensors × {EXPECTED_MONTHS} months), "
            f"duplicate keys={n_dupes}, distinct months={months_present}",
        )
    else:
        # Partial file: every district-sensor must carry the same complete month set.
        per_series = df.groupby(["state", "district", "sensor"], dropna=False).size()
        n_months = df[["year", "month"]].drop_duplicates().shape[0]
        ok = n_dupes == 0 and n_months > 0 and bool((per_series == n_months).all())
        bolts = int((per_series != n_months).sum())
        report(
            "V1 coverage and grain",
            ok,
            f"rows={n_rows:,}, districts={n_districts}, months={n_months}, "
            f"duplicate keys={n_dupes}, incomplete series={bolts}"
            + ("" if is_full_dataset else " (partial file: 132-month grid not required)"),
        )

    # ---- V2: exactly three sensors, every district x sensor ---------------------------
    found = sorted(df["sensor"].dropna().unique().tolist())
    unexpected = sorted(set(found) - set(SENSORS))
    per_district = df.groupby(["state", "district"], dropna=False)["sensor"].nunique()
    missing_sensor = int((per_district != len(SENSORS)).sum())
    if is_full_dataset:
        ok = set(found) == set(SENSORS) and not unexpected and missing_sensor == 0
        detail = (
            f"found={found}, unexpected={unexpected}, "
            f"districts without all 3 sensors={missing_sensor}/{n_districts}"
        )
    else:
        # A partial hand-off (e.g. Punjab 2020 VIIRS only) legitimately carries fewer
        # sensors; what must hold is that every value is a contract sensor.
        ok = bool(found) and not unexpected
        detail = (
            f"found={found}, unexpected={unexpected} "
            "(partial file: 3 sensors not required)"
        )
    report("V2 sensors", ok, detail)

    # ---- V3: completeness and domains ------------------------------------------------
    null_counts = {c: int(df[c].isna().sum()) for c in NON_NULL_COLUMNS}
    total_nulls = sum(null_counts.values())
    bad_year = int((~df["year"].dropna().between(PERIOD_START[0], PERIOD_END[0])).sum())
    bad_month = int((~df["month"].dropna().between(1, 12)).sum())
    bad_date = int(df["date"].isna().sum())
    negative = int(
        (
            (df["fire_pixel_days"].fillna(0) < 0)
            | (df["clear_pixel_days"].fillna(0) < 0)
            | (df["n_images"].fillna(0) < 0)
        ).sum()
    )
    # n_images == 0 means "no data": both counts must be 0 and FRP empty. Otherwise
    # add_metrics() turns real detections into NaN activity and export_gaps() files them
    # as "no_images", so a mis-mapped n_images column would silently hide data.
    no_image_rows = df["n_images"] == 0
    data_without_images = int(
        (
            no_image_rows
            & (
                (df["fire_pixel_days"].fillna(0) != 0)
                | (df["clear_pixel_days"].fillna(0) != 0)
                | df["mean_frp_mw"].notna()
            )
        ).sum()
    )
    ok = (
        total_nulls == 0
        and bad_year == 0
        and bad_month == 0
        and bad_date == 0
        and negative == 0
        and data_without_images == 0
    )
    worst = ", ".join(f"{c}={n}" for c, n in null_counts.items() if n) or "none"
    report(
        "V3 required fields and domains",
        ok,
        f"nulls={total_nulls} ({worst}), year outside {PERIOD_START[0]}-{PERIOD_END[0]}={bad_year}, "
        f"month outside 1-12={bad_month}, unparseable dates={bad_date}, negative counts={negative}, "
        f"n_images=0 rows with counts or FRP={data_without_images}",
    )

    # ---- V4: fire is a subset of clear ----------------------------------------------
    fire = df["fire_pixel_days"]
    clear = df["clear_pixel_days"]
    violations = int((fire > clear + 1e-9).sum())
    worst_gap = float((fire - clear).max()) if n_rows else float("nan")
    ok = violations == 0
    detail = f"rows with fire > clear: {violations}"
    if violations:
        detail += f" (largest excess {worst_gap:.1f} pixel-days)"
    report("V4 fire_pixel_days <= clear_pixel_days", ok, detail)

    # ---- V5: monsoon suppression of clear view ---------------------------------------
    monsoon = df["month"].isin(MONSOON_MONTHS)
    monsoon_mean = float(clear[monsoon].mean())
    dry_mean = float(clear[~monsoon].mean())
    district_means = (
        df.assign(_monsoon=monsoon)
        .groupby(["state", "district", "_monsoon"], dropna=False)["clear_pixel_days"]
        .mean()
        .unstack("_monsoon")
    )
    if True in district_means.columns and False in district_means.columns:
        comparable = district_means.dropna(subset=[True, False])
        conform = int((comparable[True] < comparable[False]).sum())
        share = conform / len(comparable) if len(comparable) else 0.0
    else:
        conform, share = 0, 0.0
    ok = bool(np.isfinite(monsoon_mean) and np.isfinite(dry_mean)
              and monsoon_mean < dry_mean and share >= 0.90)
    report(
        "V5 monsoon (Jul-Sep) clear view lower",
        ok,
        f"mean clear_pixel_days monsoon={monsoon_mean:,.0f} vs other={dry_mean:,.0f} "
        f"({_fmt_pct(monsoon_mean, dry_mean)} of other), "
        f"districts conforming={conform}/{len(district_means)} ({share:.0%})",
    )

    # ---- V6: FRP non-negative, null iff no fire --------------------------------------
    frp = df["mean_frp_mw"]
    no_fire = fire.fillna(0) == 0
    frp_present = frp.notna()
    frp_on_no_fire = int((no_fire & frp_present).sum())
    frp_missing_on_fire = int((~no_fire & ~frp_present).sum())
    negative_frp = int((frp.dropna() < 0).sum())
    ok = frp_on_no_fire == 0 and frp_missing_on_fire == 0 and negative_frp == 0
    report(
        "V6 mean_frp_mw null iff no fire, >= 0",
        ok,
        f"non-null with fire=0: {frp_on_no_fire}, null with fire>0: {frp_missing_on_fire}, "
        f"negative values: {negative_frp}, max={frp.max() if frp_present.any() else float('nan'):.1f} MW"
        if frp_present.any()
        else f"no FRP values at all; non-null with fire=0: {frp_on_no_fire}, "
             f"null with fire>0: {frp_missing_on_fire}",
    )

    # ---- V7: Ludhiana VIIRS October-November peak ------------------------------------
    lud = df[
        df["district"].astype("string").str.strip().str.casefold() == LUDHIANA.casefold()
    ]
    lud = lud[lud["sensor"] == ANCHOR_SENSOR]
    if lud.empty:
        ok = not is_full_dataset  # tolerable in the Punjab test, a hard failure on the full file
        report(
            "V7 Ludhiana (VIIRS) Oct-Nov peak",
            ok,
            "no Ludhiana/VIIRS rows in this file — skipped"
            + ("" if is_full_dataset else " (partial test file)"),
        )
    else:
        profile = lud.groupby("month")["activity"].mean()
        profile = profile.dropna()
        if profile.empty:
            report("V7 Ludhiana (VIIRS) Oct-Nov peak", False, "no usable activity values")
        else:
            peak_month = int(profile.idxmax())
            oct_nov = float(profile.reindex(PADDY_MONTHS).mean())
            apr_may = float(profile.reindex(WHEAT_MONTHS).mean())
            annual = float(profile.mean())
            ok = peak_month in PADDY_MONTHS and oct_nov > annual
            report(
                "V7 Ludhiana (VIIRS) Oct-Nov peak",
                ok,
                f"peak month={peak_month}, Oct-Nov mean activity={oct_nov:.4f} "
                f"vs annual={annual:.4f} vs Apr-May={apr_may:.4f}",
            )

    # ---- V8: latest active month per sensor (informational) --------------------------
    active = df[(df["n_images"].fillna(0) > 0) & df["date"].notna()]
    lines = []
    for sensor in SENSORS:
        sub = active[active["sensor"] == sensor]
        if sub.empty:
            lines.append(f"{sensor}=none")
            continue
        latest = sub["date"].max()
        lines.append(
            f"{sensor}={latest:%Y-%m} ({int((sub['date'] == latest).sum())} districts)"
        )
    # Informational by design: a sensor that ends earlier is a finding to report, not a
    # failed check. Missing sensors are caught by V2.
    report("V8 latest active month per sensor (info)", True, "; ".join(lines), info=True)

    passed = sum(results.values())
    print("-" * 78)
    print(f"{passed}/{len(results)} checks passed")
    print("=" * 78 + "\n")
    return results


# --------------------------------------------------------------------------------------
# Sanity plots
# --------------------------------------------------------------------------------------


def _pick_district(df: pd.DataFrame, name: str) -> pd.DataFrame:
    """Rows for a district, matched case-insensitively, optionally as 'State: District'."""
    target = name.split(":")[-1].strip().casefold()
    mask = df["district"].astype("string").str.strip().str.casefold() == target
    if ":" in name:
        state = name.split(":")[0].strip().casefold()
        mask &= df["state"].astype("string").str.strip().str.casefold() == state
    sub = df[mask]
    if sub.empty:
        raise ValueError(
            f"District {name!r} not found. Known districts: "
            f"{sorted(df['district'].dropna().unique().tolist())[:12]}..."
        )
    return sub


def _climatology(sub: pd.DataFrame) -> pd.DataFrame:
    """Mean activity by calendar month and sensor (the seasonal profile)."""
    prof = (
        sub.dropna(subset=["activity"])
        .groupby(["sensor", "month"])["activity"]
        .mean()
        .unstack("sensor")
    )
    return prof.reindex(range(1, 13))


def _month_bands(ax: plt.Axes, months: tuple[int, ...], color: str, label: str) -> None:
    """Shade a contiguous block of calendar months (1-12) and label it above the axes.

    The label sits outside the plotting area so it can never land on a data peak or on
    the legend; saved with ``bbox_inches='tight'`` it is included in the figure.
    """
    ax.axvspan(months[0] - 0.5, months[-1] + 0.5, color=color, alpha=0.12, zorder=0)
    ax.annotate(
        label,
        xy=((months[0] + months[-1]) / 2, 1.015),
        xycoords=("data", "axes fraction"),
        ha="center",
        va="bottom",
        fontsize=8.5,
        color=color,
        fontweight="bold",
        clip_on=False,
    )


def _with_headroom(ax: plt.Axes, factor: float = 1.12) -> None:
    """Give the top of the y axis breathing room above the highest drawn value."""
    top = ax.get_ylim()[1]
    if np.isfinite(top) and top > 0:
        ax.set_ylim(0, top * factor)


def generate_sanity_plots(
    df: pd.DataFrame,
    uttarakhand_district: str,
    output_dir: str | Path = "science/figures",
    dpi: int = 200,
) -> list[Path]:
    """Save the three Phase 1 gate-review figures as high-DPI PNGs.

    Parameters
    ----------
    df
        Frame from :func:`load_data` (metrics added if absent).
    uttarakhand_district
        District name to use for plot 3, e.g. ``"Nainital"``. A ``"State: District"``
        form is accepted when names repeat.
    output_dir
        Directory for the PNGs, created if needed.
    dpi
        Raster resolution; 200 keeps labels crisp in slides and the repo small.

    Returns
    -------
    list[Path]
        Paths of the three written files, in plot order.
    """
    df = _ensure_metrics(df)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []

    plt.rcParams.update(
        {
            "figure.dpi": 110,
            "savefig.dpi": dpi,
            "savefig.bbox": "tight",
            "font.size": 10,
            "axes.titlesize": 12,
            "axes.labelsize": 10,
            "axes.grid": True,
            "grid.alpha": 0.25,
            "grid.linestyle": ":",
            "axes.spines.top": False,
            "axes.spines.right": False,
            "legend.frameon": False,
        }
    )

    # ------------------------------------------------------------------ Plot 1: Ludhiana
    lud = _pick_district(df, LUDHIANA)
    lud = lud[lud["sensor"].isin(SENSORS)]
    prof = _climatology(lud)
    fig, ax = plt.subplots(figsize=(9.0, 5.0))
    _month_bands(ax, WHEAT_MONTHS, "#c9a227", "Wheat residue (Apr-May)")
    _month_bands(ax, PADDY_MONTHS, "#b23a48", "Paddy residue (Oct-Nov)")
    for sensor in SENSORS:
        if sensor not in prof.columns:
            continue
        series = prof[sensor].dropna()
        if series.empty:
            continue
        ax.plot(
            series.index,
            series.values,
            marker="o",
            markersize=5,
            linewidth=2.0,
            color=SENSOR_COLORS[sensor],
            label=f"{SENSOR_LABELS[sensor]} (n={len(series)})",
        )
    years = lud["year"].dropna()
    span = f"{int(years.min())}-{int(years.max())}" if not years.empty else "no years"
    ax.set_xticks(range(1, 13))
    ax.set_xticklabels(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    )
    ax.set_xlim(0.5, 12.5)
    ax.set_ylim(bottom=0)
    _with_headroom(ax)
    ax.set_xlabel("Calendar month (UTC)")
    ax.set_ylabel("Mean activity\n(fire pixel-days / clear pixel-days)")
    ax.set_title(
        f"Ludhiana, Punjab — burning seasonality, {span}\n"
        "Mean activity by calendar month, one line per sensor",
        pad=26,
    )
    ax.legend(loc="upper left", ncols=1)
    fig.tight_layout()
    path1 = out_dir / "plot1_ludhiana_seasonality.png"
    fig.savefig(path1)
    plt.close(fig)
    saved.append(path1)

    # -------------------------------------------------- Plot 2: VIIRS vs Aqua agreement
    pair = (
        df.pivot_table(
            index=["state", "district", "year", "month"],
            columns="sensor",
            values="activity",
            aggfunc="first",
        )
        .reindex(columns=list(SENSORS))
        .dropna(subset=["viirs_snpp", "aqua"])
    )
    fig, ax = plt.subplots(figsize=(6.4, 6.4))
    if len(pair) >= 3:
        x = pair["aqua"].to_numpy(dtype=float)
        y = pair["viirs_snpp"].to_numpy(dtype=float)
        ax.scatter(x, y, s=14, alpha=0.35, edgecolors="none", color="#3b6ea5",
                   label=f"District-months (n={len(pair):,})")
        hi = float(max(np.nanmax(x), np.nanmax(y))) * 1.05
        ax.plot([0, hi], [0, hi], color="#444444", linewidth=1.0, linestyle="--",
                label="1:1 line")
        fit = stats.linregress(x, y)
        xs = np.linspace(0, hi, 100)
        ax.plot(xs, fit.intercept + fit.slope * xs, color="#b23a48", linewidth=1.6,
                label=f"OLS fit: y = {fit.slope:.2f}x {fit.intercept:+.4f}")
        r, p = stats.pearsonr(x, y)
        p_text = "< 1e-300" if p < 1e-300 else f"= {p:.2e}"
        ax.annotate(
            f"$r$ = {r:.3f}\n$p$ {p_text}\nn = {len(pair):,}\n"
            f"median VIIRS/Aqua = {np.nanmedian(y / np.where(x > 0, x, np.nan)):.2f}×",
            xy=(0.04, 0.96),
            xycoords="axes fraction",
            va="top",
            ha="left",
            fontsize=10,
            bbox=dict(boxstyle="round,pad=0.4", facecolor="white", edgecolor="#cccccc"),
        )
        ax.set_xlim(0, hi)
        ax.set_ylim(0, hi)
        ax.set_aspect("equal", adjustable="box")
        ax.legend(loc="lower right", fontsize=8.5)
    else:
        ax.text(0.5, 0.5, "Not enough overlapping district-months\nfor a sensor comparison",
                ha="center", va="center", transform=ax.transAxes)
        ax.set_xticks([])
        ax.set_yticks([])
    ax.set_xlabel("Aqua MODIS activity")
    ax.set_ylabel("Suomi-NPP VIIRS activity")
    ax.set_title("Sensor agreement: VIIRS vs Aqua\nAll district-months, activity = fire / clear")
    fig.tight_layout()
    path2 = out_dir / "plot2_sensor_agreement.png"
    fig.savefig(path2)
    plt.close(fig)
    saved.append(path2)

    # ------------------------------------------- Plot 3: Uttarakhand forest seasonality
    try:
        forest = _pick_district(df, uttarakhand_district)
        forest_label = f"{forest['district'].iloc[0]}, {forest['state'].iloc[0]}"
    except ValueError:
        forest, forest_label = pd.DataFrame(), f"{uttarakhand_district} (not found)"
    fprof = _climatology(forest) if not forest.empty else pd.DataFrame()
    fig, ax = plt.subplots(figsize=(9.0, 5.0))
    _month_bands(ax, SPRING_FIRE_MONTHS, "#2f6b3a", "Spring forest-fire season (Apr-May)")
    if not fprof.empty:
        for sensor in SENSORS:
            if sensor not in fprof.columns:
                continue
            series = fprof[sensor].dropna()
            if series.empty:
                continue
            ax.plot(
                series.index,
                series.values,
                marker="s",
                markersize=5,
                linewidth=2.0,
                color=SENSOR_COLORS[sensor],
                label=f"{SENSOR_LABELS[sensor]} (n={len(series)})",
            )
    else:
        ax.text(0.5, 0.5, f"No rows for {uttarakhand_district}\nin this dataset",
                ha="center", va="center", transform=ax.transAxes, fontsize=11)
    fy = forest["year"].dropna() if not forest.empty else pd.Series(dtype=float)
    fspan = f"{int(fy.min())}-{int(fy.max())}" if not fy.empty else "no years"
    ax.set_xticks(range(1, 13))
    ax.set_xticklabels(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    )
    ax.set_xlim(0.5, 12.5)
    ax.set_ylim(bottom=0)
    _with_headroom(ax)
    ax.set_xlabel("Calendar month (UTC)")
    ax.set_ylabel("Mean activity\n(fire pixel-days / clear pixel-days)")
    ax.set_title(
        f"{forest_label} — forest-fire seasonality, {fspan}\n"
        "Mean activity by calendar month, one line per sensor",
        pad=26,
    )
    if not fprof.empty:
        ax.legend(loc="upper right")
    fig.tight_layout()
    path3 = out_dir / "plot3_uttarakhand_forest.png"
    fig.savefig(path3)
    plt.close(fig)
    saved.append(path3)

    for path in saved:
        print(f"  saved {path}")
    return saved


# --------------------------------------------------------------------------------------
# Gap export
# --------------------------------------------------------------------------------------


def export_gaps(
    df: pd.DataFrame,
    output_path: str | Path = "science/gaps.csv",
    min_coverage: float = 0.10,
) -> pd.DataFrame:
    """Write district-month-sensor rows that are missing or barely observed.

    A row is exported when ``n_images == 0``, or ``clear_coverage < min_coverage``, or the
    district has no usable coverage baseline. Nothing is imputed and the input frame is
    not modified.

    Parameters
    ----------
    df
        Frame from :func:`load_data`.
    output_path
        Destination CSV (parent directory created if needed).
    min_coverage
        Coverage floor in ``[0, 1]``; rows below it are flagged as low coverage.

    Returns
    -------
    pandas.DataFrame
        The exported gap rows, sorted by state, district, sensor, date.
    """
    df = _ensure_metrics(df)

    no_images = df["n_images"].fillna(0) == 0
    no_baseline = df["clear_coverage"].isna() & ~no_images
    low_coverage = df["clear_coverage"].notna() & (df["clear_coverage"] < min_coverage)
    mask = no_images | no_baseline | low_coverage

    # One dominant reason per row: a month with no images has no coverage either, but
    # "no_images" is the actionable fact, so it wins over the coverage flags.
    reason = pd.Series("", index=df.index, dtype="object")
    reason[no_baseline] = "no_clear_baseline"
    reason[low_coverage] = "low_clear_coverage"
    reason[no_images] = "no_images"

    cols = {
        "state": "state",
        "district": "district",
        "sensor": "sensor",
        "year": "year",
        "month": "month",
        "date": "date",
        "n_images": "n_images",
        "clear_pixel_days": "clear_pixel_days",
        "clear_coverage": "clear_pixel_coverage",
        "fire_pixel_days": "fire_pixel_days",
        "activity": "activity",
    }
    gaps = df.loc[mask, list(cols)].rename(columns=cols).copy()
    gaps["reason"] = reason[mask].to_numpy()
    gaps["date"] = pd.to_datetime(gaps["date"]).dt.strftime("%Y-%m-%d")
    gaps = gaps.sort_values(
        ["state", "district", "sensor", "date"], kind="mergesort"
    ).reset_index(drop=True)

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    gaps.to_csv(path, index=False, float_format="%.6g")

    total = len(df)
    print(
        f"  gaps: {len(gaps):,} of {total:,} rows ({_fmt_pct(len(gaps), total)}) "
        f"written to {path} (min_coverage={min_coverage:.0%})"
    )
    if len(gaps):
        by_reason = gaps["reason"].value_counts().to_dict()
        print(f"  gap reasons: {by_reason}")
        print(
            f"  no-image months: {int(no_images.sum()):,} | "
            f"low-coverage rows: {int(low_coverage.sum()):,}"
        )
    return gaps
