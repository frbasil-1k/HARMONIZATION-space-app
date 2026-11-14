"""FireLens: harmonized burning-activity calendar for Northern India, 2016-2026.

Run from firelens/:  streamlit run app/app.py
Data format: docs/data-contract.md.
"""

import calendar
from pathlib import Path

import json

import folium
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit_folium import st_folium

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_PATH = DATA_DIR / "district_monthly.csv"
HARMONIZED_PATH = DATA_DIR / "district_harmonized.csv"  # from science/harmonize.py
GEO_PATH = DATA_DIR / "districts.geojson"
HOTSPOTS_PATH = DATA_DIR / "hotspots.csv.gz"  # from gee/merge_hotspots.py; optional
MOCK_PATH = DATA_DIR / "mock_district_monthly.csv"  # from app/make_mock.py
MOCK_GEO_PATH = DATA_DIR / "mock_districts.geojson"

CONTRACT_COLUMNS = ["state", "district", "sensor", "year", "month", "fire_pixel_days",
                    "clear_pixel_days", "mean_frp_mw", "n_images"]
MIN_YEARS = 3  # observed years of a calendar month needed before comparing against them
MIN_IMAGE_SHARE = 0.5  # metric cards skip a month with fewer daily images than this share of its days
ACTIVITY_NOTE = (
    "Activity = fire pixel-days ÷ clearly observed pixel-days: the share of clearly "
    "seen land with a hotspot detection. Months are UTC calendar months. "
    "Blank cells mean no clear observations (no images, or fully clouded), not zero."
)
COUNT_NOTE = (
    "Hotspot count = hotspot pixel-days: 1 km pixels with a detection, summed over the "
    "month's daily images (detections, not individual fires). Hover a cell to see it, or "
    "colour the calendar by it. Counts are not comparable between sensors; activity is."
)
HARMONIZED_COUNT_NOTE = (
    "Hotspot count = an estimate: harmonized activity × the land VIIRS saw clearly, in "
    "hotspot pixel-days on the VIIRS scale (detections, not individual fires). It is not a "
    "sum of the satellites' counts. Hover a cell to see it, or colour the calendar by it; "
    "cells are blank in count view where VIIRS had no clear view."
)
HARMONIZED_NOTE = (
    "Harmonized = Terra and Aqua MODIS scaled to the Suomi-NPP VIIRS anchor with one ratio per "
    "state and calendar month (fitted on 2016–2022), then blended with VIIRS, weighted by how "
    "well each sensor predicted VIIRS in unseen years. From Oct 2022 the MODIS orbits drift "
    "(Terra earlier, Aqua later in the day), so from then on the value is VIIRS wherever VIIRS "
    "saw the district; a ◦ marks a month filled from drifted MODIS (lower confidence). "
    "Method and validation: science/validation.md."
)
DRIFT_NOTE = "Shaded: MODIS orbit drift (from Oct 2022). Scaled MODIS is shown for comparison only."
RECON_NOTE = (
    "The check behind harmonization: the calendar rebuilt from scaled MODIS alone (as it would "
    "be before VIIRS launched in 2012) against what VIIRS actually saw. Agreement before the "
    "drift is the evidence that the record can be extended back to 2001."
)
DRIFT_START = (2022, 10)  # science/harmonize.py DRIFT_START: Terra 2022-10, Aqua 2023-02
SOURCE_TEXT = {
    "blend": "VIIRS + MODIS",
    "viirs": "VIIRS",
    "modis_fill": "MODIS (VIIRS had no clear view)",
    "modis_fill_drift": "drifted MODIS, lower confidence (VIIRS had no clear view)",
}
MAP_NOTE = (
    "Each district coloured by the same month against its own median for that month, in the "
    "selected series and dates. Click a district to open it. Grey: fewer than {n} years to "
    "compare, or a zero median."
)
ANOMALY_NOTE = (
    "Each month's activity minus the median of the same calendar month across the selected "
    f"dates, in percentage points. Orange is above the median, purple below. A grey × "
    f"means no data, or fewer than {MIN_YEARS} years of that month to compare against."
)
RECORDED_NOTE = (
    "Each satellite sensor's own activity for this district, before harmonization. The lines "
    "share the seasonal pattern but differ in level because the sensors see differently "
    "and pass over at different times. Breaks in a line are months with no data."
)
SCALED_NOTE = (
    "After harmonization: Terra and Aqua MODIS scaled to the VIIRS anchor with monthly ratios, "
    "and the black line is the harmonized series. Breaks in a line are months with no data."
)
YEARLY_NOTE = (
    "Mean of the monthly activity in each year, for comparing years. Lighter, hatched bars "
    "are years with fewer than 12 observed months in the selected dates; they are not "
    "comparable with full years."
)
CHART_CONFIG = {"displaylogo": False}
PNG_NOTE = "To save a chart as an image, use the camera icon at its top right."
BOUNDARY_DISCLAIMER = "Boundaries: FAO/GAUL 2015 Level 2, simplified. Not an official boundary of India."

YEARS = list(range(2016, 2027))
MONTHS = list(range(1, 13))
MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
SENSOR_LABELS = {
    "viirs_snpp": "Suomi-NPP VIIRS",
    "terra": "Terra MODIS",
    "aqua": "Aqua MODIS",
}
HARMONIZED = "harmonized"
ANCHOR_SENSOR = "viirs_snpp"  # docs/decisions.md: the reference series
SERIES_LABELS = {HARMONIZED: "Harmonized (MODIS + VIIRS)", **SENSOR_LABELS}
MONTH_KEYS = ["state", "district", "year", "month"]
ALL_MONTHS = [(y, m) for y in YEARS for m in MONTHS]
OUTSIDE_DATES = "outside the selected dates"
BY_ACTIVITY, BY_COUNT = "Activity (share of clear land)", "Hotspot count"
HARMONIZED_LINE = dict(color="#111111", width=3)
SENSOR_LINES = {  # Okabe-Ito colours plus dash styles, so lines differ without colour
    "viirs_snpp": dict(color="#0072B2", width=2),
    "terra": dict(color="#E69F00", width=2, dash="dash"),
    "aqua": dict(color="#009E73", width=2, dash="dot"),
}


@st.cache_data
def load_data(path: Path) -> pd.DataFrame:
    """Read the contract CSV and add activity (NaN where nothing was observed)."""
    df = pd.read_csv(path)
    observed = (df["n_images"] > 0) & (df["clear_pixel_days"] > 0)
    df["activity"] = (df["fire_pixel_days"] / df["clear_pixel_days"]).where(observed)
    df["detections"] = df["fire_pixel_days"].where(observed)  # hotspot pixel-days, per sensor
    return df


@st.cache_data
def load_harmonized(path: Path) -> pd.DataFrame:
    """Read R2's harmonized file as is (contract §6)."""
    return pd.read_csv(path)


def harmonized_rows(harmonized: pd.DataFrame, monthly: pd.DataFrame) -> pd.DataFrame:
    """Harmonized activity in the same long shape as the sensor rows.

    n_images is the most images any sensor had that month, used only to flag partial months.
    detections is the harmonized count: see harmonized_detections.
    """
    images = monthly.groupby(MONTH_KEYS, as_index=False)["n_images"].max()
    if "source" not in harmonized:  # v1 file: no provenance column
        harmonized = harmonized.assign(source="blend")
    rows = harmonized[MONTH_KEYS + ["act_harmonized", "viirs_act", "source"]]
    # Inner join: only months the sensor file covers, so both files describe the same record.
    rows = rows.merge(images, on=MONTH_KEYS, how="inner").merge(anchor_clear(monthly), on=MONTH_KEYS, how="left")
    rows["detections"] = harmonized_detections(rows)
    rows = rows.rename(columns={"act_harmonized": "activity"})
    return rows[MONTH_KEYS + ["activity", "detections", "n_images", "source"]].assign(sensor=HARMONIZED)


def anchor_clear(monthly: pd.DataFrame) -> pd.DataFrame:
    """Clear pixel-days of the anchor sensor (VIIRS) per district-month."""
    anchor = monthly[monthly["sensor"] == ANCHOR_SENSOR]
    return anchor[MONTH_KEYS + ["clear_pixel_days"]].rename(columns={"clear_pixel_days": "anchor_clear"})


def harmonized_detections(rows: pd.DataFrame) -> pd.Series:
    """Harmonized activity expressed as hotspot pixel-days on the VIIRS scale.

    harmonized activity x the land VIIRS saw clearly: the count VIIRS would have recorded
    at the harmonized rate. Left empty where R2's file masks VIIRS (no usable clear view),
    because there is then no anchor denominator. An estimate, never a sum of sensor counts.
    """
    return (rows["act_harmonized"] * rows["anchor_clear"]).where(rows["viirs_act"].notna())


@st.cache_data
def load_series(data_path: Path, harmonized_path: Path | None) -> pd.DataFrame:
    """Sensor rows plus, when the harmonized file exists, one "harmonized" series."""
    df = load_data(data_path)
    if harmonized_path is None or not harmonized_path.exists():
        return df
    extra = harmonized_rows(load_harmonized(harmonized_path), df)
    return pd.concat([df, extra], ignore_index=True)


def month_label(year: int, month: int) -> str:
    return f"{MONTH_NAMES[month - 1]} {year}"


def in_dates(frame: pd.DataFrame, start: tuple[int, int], end: tuple[int, int]) -> pd.Series:
    """Rows whose (year, month) lies between start and end, inclusive."""
    index = frame["year"] * 12 + frame["month"]
    return index.between(start[0] * 12 + start[1], end[0] * 12 + end[1])


def calendar_grid(series: pd.DataFrame, years: list[int], value: str = "activity") -> pd.DataFrame:
    """Year x month table of one column; every year and month present, gaps as NaN."""
    return (
        series.pivot_table(index="year", columns="month", values=value, aggfunc="first",
                           dropna=False)
        .reindex(index=years, columns=MONTHS)
    )


def heatmap_figure(z: pd.DataFrame, title: str, hover_text, **trace) -> go.Figure:
    """Month x year heatmap of z; NaN cells are drawn empty.

    hover_text(year, month) returns the hover text for any cell, observed or not.
    """
    hover = [[f"{month_label(y, m)} · {hover_text(y, m)}" for m in MONTHS] for y in z.index]
    fig = go.Figure(
        go.Heatmap(
            # Plain lists with None for gaps: Plotly draws None as an empty cell.
            z=z.astype(object).where(z.notna(), None).to_numpy().tolist(),
            x=MONTH_NAMES,
            y=[str(y) for y in z.index],
            text=hover,
            hovertemplate="%{text}<extra></extra>",
            hoverongaps=True,
            xgap=2,
            ygap=2,
            **trace,
        )
    )
    fig.update_layout(
        title=title,
        yaxis=dict(autorange="reversed", type="category", title=None),
        xaxis=dict(side="top", type="category", title=None),
        height=140 + 36 * len(z.index),
        margin=dict(l=10, r=10, t=90, b=10),
        plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def count_text(count: float, estimated: bool) -> str:
    """Hover wording for a month's hotspot pixel-days."""
    if np.isnan(count):
        return "count not available (VIIRS had no clear view)"
    if estimated:
        return f"about {count:,.1f} hotspot pixel-days (VIIRS-equivalent estimate)"
    return f"{count:,.1f} hotspot pixel-days"


def source_grid(series: pd.DataFrame, years: list[int]) -> pd.DataFrame | None:
    """Year x month table of where each harmonized value came from, or None for a sensor."""
    if "source" not in series or series["source"].isna().all():
        return None
    return series.pivot(index="year", columns="month", values="source").reindex(index=years, columns=MONTHS)


def calendar_hover(grid: pd.DataFrame, counts: pd.DataFrame, estimated: bool, selected,
                   sources: pd.DataFrame | None = None):
    """Hover text per cell: outside the dates, no data, or activity, count and source."""
    def text(y: int, m: int) -> str:
        if not selected(y, m):
            return OUTSIDE_DATES
        if np.isnan(grid.loc[y, m]):
            return "no data"
        base = f"activity {grid.loc[y, m] * 100:.3f}% · {count_text(counts.loc[y, m], estimated)}"
        source = sources.loc[y, m] if sources is not None else None
        return f"{base} · from {SOURCE_TEXT[source]}" if source in SOURCE_TEXT else base
    return text


def mark_cells(fig: go.Figure, cells: list[tuple[int, int]], symbol: str, color: str) -> go.Figure:
    """Overlay a small marker on the given (year, month) cells of a calendar heatmap."""
    fig.add_trace(go.Scatter(
        x=[MONTH_NAMES[m - 1] for _, m in cells], y=[str(y) for y, _ in cells], mode="markers",
        hoverinfo="skip", showlegend=False,
        marker=dict(symbol=symbol, size=9, color=color, line=dict(color=color, width=1.5)),
    ))
    return fig


def calendar_heatmap(grid: pd.DataFrame, counts: pd.DataFrame, title: str,
                     estimated: bool, by_count: bool, selected,
                     sources: pd.DataFrame | None = None) -> go.Figure:
    """Calendar coloured by hotspot pixel-days, or by activity share when not by_count."""
    if by_count:
        z, bar = counts, dict(title=dict(text="Hotspot<br>pixel-days"))
    else:  # activity as % of clearly seen pixels
        z, bar = grid * 100, dict(title=dict(text="Activity<br>(% of clear<br>pixels)"), ticksuffix="%")
    fig = heatmap_figure(z, title, calendar_hover(grid, counts, estimated, selected, sources),
                         colorscale="Cividis", zmin=0, colorbar=bar)
    if sources is not None:
        drift = [(y, m) for y in sources.index for m in MONTHS
                 if selected(y, m) and sources.loc[y, m] == "modis_fill_drift"]
        if drift:
            mark_cells(fig, drift, "circle-open", "#D55E00")
    return fig


# --- Anomaly view ---------------------------------------------------------------

def anomaly_grid(grid: pd.DataFrame) -> pd.DataFrame:
    """Each month minus that calendar month's median; NaN where too few years."""
    enough = grid.count() >= MIN_YEARS
    anomaly = grid - grid.median(skipna=True)
    anomaly.loc[:, ~enough] = np.nan  # where(<Series>, axis="columns") raises TypeError in pandas 2.3
    return anomaly


def anomaly_hover(pct: pd.DataFrame, selected):
    def text(y: int, m: int) -> str:
        if not selected(y, m):
            return OUTSIDE_DATES
        return "no data" if np.isnan(pct.loc[y, m]) else f"{pct.loc[y, m]:+.3f} points vs median"
    return text


def anomaly_heatmap(anomaly: pd.DataFrame, title: str, selected) -> go.Figure:
    pct = anomaly * 100  # percentage points of clearly seen pixels
    limit = float(np.nanmax(np.abs(pct.to_numpy()))) if pct.notna().any().any() else 1.0
    fig = heatmap_figure(
        pct,
        title,
        anomaly_hover(pct, selected),
        colorscale="PuOr_r",  # purple = below median, orange = above; colour-blind safe
        zmin=-limit,
        zmax=limit,
        zmid=0,
        colorbar=dict(title=dict(text="Difference<br>from median<br>(% points)")),
    )
    return mark_gaps(fig, pct, selected)


def mark_gaps(fig: go.Figure, pct: pd.DataFrame, selected) -> go.Figure:
    """Put a grey x on no-data cells, where a blank would look like a zero difference."""
    gaps = [(MONTH_NAMES[m - 1], str(y)) for y in pct.index for m in MONTHS
            if selected(y, m) and np.isnan(pct.loc[y, m])]
    fig.add_trace(go.Scatter(
        x=[x for x, _ in gaps], y=[y for _, y in gaps], mode="markers", hoverinfo="skip",
        marker=dict(symbol="x-thin", size=9, line=dict(color="#8a8a8a", width=1.5)),
        showlegend=False,
    ))
    return fig


# --- Sensor comparison ----------------------------------------------------------

def recorded_traces(district_rows: pd.DataFrame) -> list:
    """Each sensor's own activity, as recorded."""
    return [
        (label, district_rows[district_rows["sensor"] == sensor], "activity", SENSOR_LINES[sensor])
        for sensor, label in SENSOR_LABELS.items()
        if (district_rows["sensor"] == sensor).any()
    ]


def scaled_traces(scaled: pd.DataFrame) -> list:
    """Sensors after scaling to the VIIRS anchor, plus the harmonized series (contract §6)."""
    columns = {"viirs_snpp": "viirs_act", "terra": "terra_scaled", "aqua": "aqua_scaled"}
    sensors = [(f"{SENSOR_LABELS[s]} (scaled)" if s != "viirs_snpp" else SENSOR_LABELS[s],
                scaled, column, SENSOR_LINES[s]) for s, column in columns.items()]
    return sensors + [("Harmonized", scaled, "act_harmonized", HARMONIZED_LINE)]


def lines_figure(traces: list, title: str) -> go.Figure:
    """Monthly series on one time axis; gaps break the line."""
    fig = go.Figure()
    for label, rows, column, line in traces:
        rows = rows.sort_values(["year", "month"])
        dates = pd.to_datetime(rows[["year", "month"]].assign(day=1))
        fig.add_trace(go.Scatter(
            x=dates, y=rows[column] * 100, name=label, mode="lines",
            connectgaps=False, line=line,
            hovertemplate=label + " · %{x|%b %Y} · %{y:.3f}%<extra></extra>",
        ))
    fig.update_layout(
        title=title, height=460, margin=dict(l=10, r=10, t=60, b=10),
        yaxis=dict(title="Activity (% of clear pixels)", ticksuffix="%", rangemode="tozero"),
        legend=dict(orientation="h", y=-0.15),
    )
    return fig


def shade_drift(fig: go.Figure, rows: pd.DataFrame) -> go.Figure:
    """Grey band over the months after the MODIS orbits left their science limits."""
    if rows.empty:
        return fig
    last = rows.sort_values(["year", "month"]).iloc[-1]
    if (int(last["year"]), int(last["month"])) < DRIFT_START:
        return fig
    first = max(pd.Timestamp(*DRIFT_START, 1), pd.to_datetime(rows[["year", "month"]].assign(day=1)).min())
    fig.add_vrect(x0=first, x1=pd.Timestamp(int(last["year"]), int(last["month"]), 1),
                  fillcolor="#8a8a8a", opacity=0.12, line_width=0, layer="below",
                  annotation_text="MODIS orbit drift", annotation_position="top left")
    return fig


def recon_traces(scaled: pd.DataFrame) -> list:
    return [("Suomi-NPP VIIRS (observed)", scaled, "viirs_act", SENSOR_LINES["viirs_snpp"]),
            ("MODIS-only reconstruction", scaled, "modis_recon", dict(color="#CC79A7", width=2, dash="dash"))]


def recon_agreement(scaled: pd.DataFrame) -> str | None:
    """r and total-burning ratio of the reconstruction vs VIIRS, before the drift."""
    ym = scaled["year"] * 12 + scaled["month"]
    pre = scaled[ym < DRIFT_START[0] * 12 + DRIFT_START[1]][["modis_recon", "viirs_act"]].dropna()
    if len(pre) < 12 or pre["viirs_act"].std() == 0 or pre["modis_recon"].std() == 0:
        return None
    r = np.corrcoef(pre["modis_recon"], pre["viirs_act"])[0, 1]
    total = pre["modis_recon"].sum() / pre["viirs_act"].sum() if pre["viirs_act"].sum() > 0 else np.nan
    return (f"Before the drift, in these dates: r = {r:.2f}, and the reconstruction totals "
            f"{total:.2f}× the burning VIIRS recorded ({len(pre)} months).")


# --- Yearly view ----------------------------------------------------------------

def yearly_summary(series: pd.DataFrame, years: list[int]) -> pd.DataFrame:
    """Per year: mean monthly activity and how many months were observed."""
    by_year = series.groupby("year")["activity"]
    table = pd.DataFrame({"mean": by_year.mean(), "months": by_year.count()})
    return table.reindex(years)


def yearly_chart(summary: pd.DataFrame, title: str) -> go.Figure:
    """Bar per year; years with fewer than 12 observed months are drawn lighter and hatched."""
    full = summary["months"] == 12
    hover = [
        f"{year} · no data" if not months else f"{year} · mean activity {mean * 100:.3f}% · "
        f"{int(months)} of 12 months observed"
        for year, mean, months in zip(summary.index, summary["mean"], summary["months"].fillna(0))
    ]
    fig = go.Figure(go.Bar(
        x=[str(y) for y in summary.index], y=summary["mean"] * 100, text=hover,
        hovertemplate="%{text}<extra></extra>", textposition="none",
        marker=dict(color=["#0072B2" if ok else "#9EC5E0" for ok in full],
                    pattern=dict(shape=["" if ok else "/" for ok in full])),
    ))
    fig.update_layout(
        title=title, height=420, margin=dict(l=10, r=10, t=60, b=10),
        xaxis=dict(type="category", title=None),
        yaxis=dict(title="Mean monthly activity (% of clear pixels)", ticksuffix="%"),
    )
    return fig


# --- Metric cards ---------------------------------------------------------------

def days_in(row: pd.Series) -> int:
    return calendar.monthrange(int(row["year"]), int(row["month"]))[1]


def latest_observed(series: pd.DataFrame) -> pd.Series | None:
    """Most recent month with defined activity and at least half its daily images.

    Skips trailing no-data months and a current month still too early to judge
    (e.g. 2 of 30 images), so the headline never rests on a few days.
    """
    observed = series.dropna(subset=["activity"]).sort_values(["year", "month"])
    if observed.empty:  # e.g. a date range with no data yet; apply() on an empty frame breaks
        return None
    enough = observed["n_images"] >= observed.apply(days_in, axis=1) * MIN_IMAGE_SHARE
    observed = observed[enough]
    return None if observed.empty else observed.iloc[-1]


def skipped_note(series: pd.DataFrame, latest: pd.Series) -> str | None:
    """Name the newer, too-incomplete month the cards skipped, if there is one."""
    newer = series[(series["year"] * 12 + series["month"] > latest["year"] * 12 + latest["month"])
                   & (series["n_images"] > 0)].sort_values(["year", "month"])
    if newer.empty:
        return None
    row = newer.iloc[-1]
    return (f"{month_label(int(row['year']), int(row['month']))} is still in progress "
            f"({'at most ' if row['sensor'] == HARMONIZED else ''}{int(row['n_images'])} of "
            f"{days_in(row)} daily images so far), so the cards compare the latest month with "
            f"at least half its images.")


def ordinal(n: float) -> str:
    """1st, 2nd, 3rd, 4th, 11th, 12th, 13th, 21st, ..."""
    n = int(round(n))
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def month_history(series: pd.DataFrame, month: int) -> pd.Series:
    """Defined activity values for one calendar month, across all years."""
    return series.loc[series["month"] == month, "activity"].dropna()


def anomaly_ratio(value: float, history: pd.Series) -> float | None:
    """value / median(history); None if too few years or a zero median."""
    if len(history) < MIN_YEARS or history.median() == 0:
        return None
    return value / history.median()


def percentile_rank(value: float, history: pd.Series) -> float | None:
    """Percent of years in history at or below value; None if too few years."""
    if len(history) < MIN_YEARS:
        return None
    return 100 * (history <= value).mean()


def peak_months(grid: pd.DataFrame, n: int = 3) -> list[str]:
    """Calendar months with the highest median activity across years."""
    medians = grid.median(skipna=True).dropna()
    return [MONTH_NAMES[m - 1] for m in medians.nlargest(n).index]


def partial_note(row: pd.Series) -> str | None:
    """Say so when the month has fewer daily images than calendar days."""
    days = days_in(row)
    images = int(row["n_images"])
    if images >= days:
        return None
    most = "at most " if row["sensor"] == HARMONIZED else ""
    return f"Partial month: {most}{images} of {days} daily images"


def render_metrics(series: pd.DataFrame, grid: pd.DataFrame) -> pd.Series | None:
    """Headline cards; returns the month they describe (None if nothing observed)."""
    latest = latest_observed(series)
    cols = st.columns(3)
    if latest is None:
        cols[0].info("No observed months for this selection.")
        return None
    month, value = int(latest["month"]), latest["activity"]
    history = month_history(series, month)
    ratio, pct = anomaly_ratio(value, history), percentile_rank(value, history)
    label = f"{MONTH_NAMES[month - 1]} {int(latest['year'])}"
    note = (f"Compared with every observed {MONTH_NAMES[month - 1]} in the selected dates "
            f"({len(history)} year(s)); needs at least {MIN_YEARS}.")
    partial = dict(delta=partial_note(latest), delta_color="off", delta_arrow="off")
    cols[0].metric(f"{label} vs {MONTH_NAMES[month - 1]} median",
                   "—" if ratio is None else f"{ratio:.2f}×", help=note, **partial)
    cols[1].metric(f"{label} percentile rank",
                   "—" if pct is None else ordinal(pct), help=note, **partial)
    cols[2].metric("Peak months (median activity)", " · ".join(peak_months(grid)) or "—")
    skipped = skipped_note(series, latest)
    if skipped:
        st.caption(skipped)
    return latest


# --- Download -------------------------------------------------------------------

def district_csv(df: pd.DataFrame, state: str, district: str) -> bytes:
    """The district's contract rows (all sensors) as CSV; missing values left empty."""
    sensors = df["sensor"] != HARMONIZED
    rows = df.loc[sensors & (df["state"] == state) & (df["district"] == district), CONTRACT_COLUMNS]
    return rows.to_csv(index=False).encode("utf-8")


def harmonized_csv(rows: pd.DataFrame) -> bytes:
    """The district's harmonized rows exactly as R2's file has them (contract §6)."""
    return rows.sort_values(["year", "month"]).to_csv(index=False).encode("utf-8")


@st.cache_data
def load_hotspots(path: Path) -> pd.DataFrame:
    """Every hotspot pixel-day, with a year*12+month index for date filtering."""
    df = pd.read_csv(path, dtype={"acq_date": str})
    df["ym"] = df["acq_date"].str[:4].astype(int) * 12 + df["acq_date"].str[5:7].astype(int)
    return df


def hotspots_csv(state: str, district: str, start: tuple[int, int], end: tuple[int, int]) -> bytes | None:
    """The district's individual hotspots in the selected dates, or None without the file."""
    if not HOTSPOTS_PATH.exists():
        return None
    df = load_hotspots(HOTSPOTS_PATH)
    keep = ((df["state"] == state) & (df["district"] == district)
            & df["ym"].between(start[0] * 12 + start[1], end[0] * 12 + end[1]))
    return df.loc[keep].drop(columns="ym").to_csv(index=False).encode("utf-8")


def render_downloads(df: pd.DataFrame, harmonized: pd.DataFrame | None, state: str, district: str,
                     span: str, start: tuple[int, int], end: tuple[int, int]) -> None:
    """CSV buttons for the selected district and dates."""
    stem = f"{state}_{district}_{span}".replace(" ", "_")
    cols = st.columns([3, 3, 3, 1])
    hotspots = hotspots_csv(state, district, start, end)
    if hotspots is not None:
        cols[2].download_button(
            "Download hotspots CSV", data=hotspots, file_name=f"{stem}_hotspots.csv", mime="text/csv",
            help="Every hotspot detection in this district and these dates: sensor, UTC date, "
                 "pixel-centre latitude/longitude, FRP (MW) and confidence. One row per 1 km pixel "
                 "per day per sensor, as recorded (not harmonized); don't add sensors together.",
        )
    else:
        cols[2].download_button(
            "Download hotspots CSV", data=b"", file_name="hotspots.csv", disabled=True,
            help="The hotspot list (data/hotspots.csv.gz) has not been generated in this build. "
                 "It comes from gee/export_hotspots.js + gee/merge_hotspots.py.",
        )
    if harmonized is not None:
        cols[0].download_button(
            "Download harmonized CSV", data=harmonized_csv(harmonized),
            file_name=f"{stem}_harmonized.csv", mime="text/csv",
            help="Harmonized monthly activity for this district and these dates, "
                 "with each scaled sensor, baseline, anomaly and percentile.",
        )
    cols[1].download_button(
        "Download per-sensor CSV", data=district_csv(df, state, district),
        file_name=f"{stem}_per_sensor.csv", mime="text/csv",
        help="Every sensor's monthly rows for this district and these dates, "
             "in the data-contract format.",
    )
    st.caption(PNG_NOTE)


def show_chart(fig: go.Figure, name: str) -> None:
    """Plot with a named, high-resolution PNG export on the chart's camera button."""
    options = {"format": "png", "scale": 2, "filename": name.replace(" · ", "_").replace(" ", "_")}
    st.plotly_chart(fig, width="stretch", config={**CHART_CONFIG, "toImageButtonOptions": options})


def district_harmonized(harmonized: pd.DataFrame | None, state: str, district: str,
                        start: tuple[int, int], end: tuple[int, int]) -> pd.DataFrame | None:
    """R2's harmonized rows for one district and date range, or None without the file."""
    if harmonized is None:
        return None
    keep = ((harmonized["state"] == state) & (harmonized["district"] == district)
            & in_dates(harmonized, start, end))
    return harmonized[keep]


def render_calendar(series: pd.DataFrame, grid: pd.DataFrame, years: list[int],
                    title: str, estimated: bool, selected) -> None:
    """Calendar tab: colour by activity or by hotspot count."""
    by_count = st.radio("Colour by", [BY_COUNT, BY_ACTIVITY], horizontal=True,
                        key="calendar_value") == BY_COUNT
    counts = calendar_grid(series, years, "detections")
    sources = source_grid(series, years) if estimated else None
    show_chart(calendar_heatmap(grid, counts, title, estimated, by_count, selected, sources),
               f"{title} calendar")
    st.caption(ACTIVITY_NOTE + (" " + HARMONIZED_NOTE if estimated else ""))
    st.caption(HARMONIZED_COUNT_NOTE if estimated else COUNT_NOTE)


def render_comparison(district_rows: pd.DataFrame, scaled: pd.DataFrame | None, place: str) -> None:
    """Sensors side by side: after harmonization (when available) or as recorded."""
    views = ["After harmonization", "As recorded"] if scaled is not None else ["As recorded"]
    if scaled is not None and "modis_recon" in scaled:
        views.append("MODIS-only check")
    view = st.radio("Show", views, horizontal=True, key="comparison_view")
    if view == "After harmonization":
        fig = shade_drift(lines_figure(scaled_traces(scaled), place), scaled)
        show_chart(fig, f"{place} sensors harmonized")
        st.caption(SCALED_NOTE + " " + DRIFT_NOTE)
    elif view == "MODIS-only check":
        fig = shade_drift(lines_figure(recon_traces(scaled), place), scaled)
        show_chart(fig, f"{place} MODIS-only check")
        agreement = recon_agreement(scaled)
        if agreement:
            st.markdown(f"**{agreement}**")
        st.caption(RECON_NOTE)
    else:
        show_chart(lines_figure(recorded_traces(district_rows), place), f"{place} sensors recorded")
        st.caption(RECORDED_NOTE)


# --- Map ------------------------------------------------------------------------

@st.cache_data
def load_geojson(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def polygons(geometry: dict) -> list:
    """Polygon coordinate lists from any geometry; stray lines and points are dropped."""
    kind = geometry["type"]
    if kind == "Polygon":
        return [geometry["coordinates"]]
    if kind == "MultiPolygon":
        return list(geometry["coordinates"])
    if kind == "GeometryCollection":
        return [p for part in geometry["geometries"] for p in polygons(part)]
    return []


def district_key(feature: dict) -> tuple[str, str]:
    props = feature["properties"]
    return props["state"].strip(), props["district"].strip()


def district_feature(geo: dict, state: str, district: str) -> dict | None:
    """Join on the (state, district) pair, never the name alone (contract §2)."""
    for feature in geo["features"]:
        if district_key(feature) == (state.strip(), district.strip()):
            shape = {"type": "MultiPolygon", "coordinates": polygons(feature["geometry"])}
            return {"type": "Feature", "properties": feature["properties"], "geometry": shape}
    return None


# --- Location search ------------------------------------------------------------

def in_ring(lon: float, lat: float, ring: list) -> bool:
    """Ray casting: is the point inside this closed ring of [lon, lat] points?"""
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        if (y1 > lat) != (y2 > lat) and lon < x1 + (lat - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def in_polygon(lon: float, lat: float, rings: list) -> bool:
    """Inside the outer ring and outside every hole."""
    return in_ring(lon, lat, rings[0]) and not any(in_ring(lon, lat, h) for h in rings[1:])


def find_district(geo: dict, lat: float, lon: float) -> tuple[str, str] | None:
    """(state, district) of the boundary containing the point, if any."""
    for feature in geo["features"]:
        if any(in_polygon(lon, lat, rings) for rings in polygons(feature["geometry"])):
            return district_key(feature)
    return None


def go_to_location(geo: dict, known: set) -> None:
    """Button callback: point the State and District selectors at the typed location."""
    hit = find_district(geo, st.session_state["lat"], st.session_state["lon"])
    if hit in known:
        st.session_state["state"], st.session_state["district"] = hit
        st.session_state["search_note"] = ("success", f"Found {hit[1]}, {hit[0]}.")
    else:
        st.session_state["search_note"] = ("warning", "That point is outside the districts covered.")


def render_search(geo: dict, df: pd.DataFrame) -> None:
    known = set(zip(df["state"].str.strip(), df["district"].str.strip()))
    with st.expander("Find by latitude / longitude"):
        st.number_input("Latitude", -90.0, 90.0, 30.90, format="%.4f", key="lat")
        st.number_input("Longitude", -180.0, 180.0, 75.85, format="%.4f", key="lon")
        st.button("Go to district", on_click=go_to_location, args=(geo, known))
        kind, text = st.session_state.pop("search_note", (None, None))  # show once
        if kind:
            getattr(st, kind)(text)


# Month-vs-median classes for the overview map (PuOr, purple = below, orange = above).
MAP_BINS = [(0.25, "< 0.25×", "#542788"), (0.5, "0.25–0.5×", "#8073ac"), (0.8, "0.5–0.8×", "#b2abd2"),
            (1.25, "0.8–1.25×", "#f7f7f7"), (2.0, "1.25–2×", "#fdb863"), (4.0, "2–4×", "#e08214"),
            (np.inf, "> 4×", "#b35806")]
MAP_NO_DATA = "#cccccc"


def district_ratios(df: pd.DataFrame, sensor: str, start: tuple[int, int], end: tuple[int, int],
                    target: tuple[int, int]) -> dict[tuple[str, str], float]:
    """Every district's target month ÷ its median of that calendar month, in the dates."""
    rows = df[(df["sensor"] == sensor) & in_dates(df, start, end) & (df["month"] == target[1])]
    observed = rows.dropna(subset=["activity"])
    history = observed.groupby(["state", "district"])["activity"].agg(["median", "count"])
    now = observed[observed["year"] == target[0]].set_index(["state", "district"])["activity"]
    ratio = (now / history["median"]).where((history["count"] >= MIN_YEARS) & (history["median"] > 0))
    return {key: float(v) for key, v in ratio.dropna().items()}


def ratio_colour(ratio: float | None) -> str:
    if ratio is None or not np.isfinite(ratio):
        return MAP_NO_DATA
    return next(colour for upper, _, colour in MAP_BINS if ratio < upper)


def overview_map(geo: dict, ratios: dict, selected: tuple[str, str], month_name: str) -> folium.Map:
    """All districts coloured by month vs median; the selected one outlined in black."""
    features = []
    for feature in geo["features"]:
        key = district_key(feature)
        ratio = ratios.get(key)
        value = "not enough history" if ratio is None else f"{ratio:.2f}× its {month_name} median"
        features.append({
            "type": "Feature",
            "geometry": {"type": "MultiPolygon", "coordinates": polygons(feature["geometry"])},
            "properties": {"state": key[0], "district": key[1], "label": f"{key[1]}, {key[0]}: {value}",
                           "fill": ratio_colour(ratio), "selected": key == selected},
        })
    m = folium.Map(tiles="OpenStreetMap")
    layer = folium.GeoJson(
        {"type": "FeatureCollection", "features": features},
        style_function=lambda f: {
            "fillColor": f["properties"]["fill"], "fillOpacity": 0.8,
            "color": "#111111" if f["properties"]["selected"] else "#666666",
            "weight": 3 if f["properties"]["selected"] else 0.6,
        },
        highlight_function=lambda _: {"weight": 2, "color": "#0072B2"},
        tooltip=folium.GeoJsonTooltip(fields=["label"], labels=False),
    ).add_to(m)
    m.fit_bounds(layer.get_bounds())
    return m


def map_legend() -> str:
    swatch = ('<span style="display:inline-block;width:14px;height:14px;background:{c};'
              'border:1px solid #888;margin:0 4px 0 10px;vertical-align:middle"></span>{t}')
    items = [swatch.format(c=c, t=t) for _, t, c in MAP_BINS] + [swatch.format(c=MAP_NO_DATA, t="no comparison")]
    return '<div style="font-size:0.85rem">' + "".join(items) + "</div>"


def render_map(geo_path: Path, df: pd.DataFrame, sensor: str, state: str, district: str,
               start: tuple[int, int], end: tuple[int, int], latest: pd.Series | None) -> None:
    """Overview of all districts for the headline month; clicking a district opens it."""
    geo = load_geojson(geo_path)
    if district_feature(geo, state, district) is None:
        st.info(f"No boundary found for {district}, {state}.")
    if latest is None:
        target, ratios, month_name = None, {}, ""
        st.markdown("**All districts** · no observed month to compare in these dates")
    else:
        target = (int(latest["year"]), int(latest["month"]))
        month_name = MONTH_NAMES[target[1] - 1]
        ratios = district_ratios(df, sensor, start, end, target)
        st.markdown(f"**All districts · {month_label(*target)} vs each district's {month_name} median "
                    f"· {SERIES_LABELS[sensor]}**")
    out = st_folium(overview_map(geo, ratios, (state.strip(), district.strip()), month_name),
                    height=480, use_container_width=True, returned_objects=["last_active_drawing"],
                    key=f"map-{state}-{district}-{sensor}-{target}")
    clicked = (out or {}).get("last_active_drawing") or {}
    props = clicked.get("properties") or {}
    pick = (props.get("state"), props.get("district"))
    if all(pick) and pick != (state.strip(), district.strip()):
        st.session_state["pending_pick"] = pick
        st.rerun()
    st.markdown(map_legend(), unsafe_allow_html=True)
    st.caption(MAP_NOTE.format(n=MIN_YEARS) + " " + BOUNDARY_DISCLAIMER)


def main() -> None:
    st.set_page_config(page_title="FireLens", layout="wide")
    st.title("FireLens")
    st.caption("Harmonized burning-activity calendar for Northern India, 2016–2026, "
               "from MODIS and VIIRS satellite hotspot detections.")

    if DATA_PATH.exists():
        df, geo_path = load_series(DATA_PATH, HARMONIZED_PATH), GEO_PATH
        has_harmonized = HARMONIZED in set(df["sensor"])
        harmonized = load_harmonized(HARMONIZED_PATH) if has_harmonized else None
    elif MOCK_PATH.exists():
        st.warning("**MOCK data**: the real data file is missing, so these numbers are "
                   "invented for development. Do not use them.")
        df, geo_path, harmonized = load_series(MOCK_PATH, None), MOCK_GEO_PATH, None
    else:
        st.error(f"No data found. Expected {DATA_PATH.name} (or run app/make_mock.py).")
        st.stop()

    # A district clicked on the map last run: apply it before the selectors are drawn.
    pick = st.session_state.pop("pending_pick", None)
    if pick:
        st.session_state["state"], st.session_state["district"] = pick

    with st.sidebar:
        st.header("Location")
        render_search(load_geojson(geo_path), df)
        state = st.selectbox("State", sorted(df["state"].unique()), key="state")
        district = st.selectbox(
            "District", sorted(df.loc[df["state"] == state, "district"].unique()),
            key="district",
        )
        st.header("Data")
        available = [s for s in SERIES_LABELS if s in set(df["sensor"])]  # harmonized first
        sensor = st.selectbox("Series", available, format_func=SERIES_LABELS.get, key="sensor")
        start, end = st.select_slider(
            "Dates", ALL_MONTHS, (ALL_MONTHS[0], ALL_MONTHS[-1]), key="dates",
            format_func=lambda ym: month_label(*ym),
        )
        years = list(range(start[0], end[0] + 1))

    def selected(year: int, month: int) -> bool:
        return start <= (year, month) <= end

    dated = in_dates(df, start, end)
    district_rows = df[(df["state"] == state) & (df["district"] == district) & dated]
    series = district_rows[district_rows["sensor"] == sensor]
    grid = calendar_grid(series, years)
    span = month_label(*start) if start == end else f"{month_label(*start)}–{month_label(*end)}"
    place = f"{district}, {state} · {span}"
    place_sensor = f"{district}, {state} · {SERIES_LABELS[sensor]} · {span}"
    file_span = f"{start[0]}-{start[1]:02d}_to_{end[0]}-{end[1]:02d}"

    scaled = district_harmonized(harmonized, state, district, start, end)

    latest = render_metrics(series, grid)
    calendar_tab, yearly_tab, anomaly_tab, sensors_tab = st.tabs(
        ["Calendar", "Yearly", "Anomaly", "Sensor comparison"])
    with calendar_tab:
        render_calendar(series, grid, years, place_sensor, sensor == HARMONIZED, selected)
    with yearly_tab:
        show_chart(yearly_chart(yearly_summary(series, years), place_sensor), f"{place_sensor} yearly")
        st.caption(YEARLY_NOTE)
    with anomaly_tab:
        show_chart(anomaly_heatmap(anomaly_grid(grid), place_sensor, selected), f"{place_sensor} anomaly")
        st.caption(ANOMALY_NOTE)
    with sensors_tab:
        render_comparison(district_rows, scaled, place)
    render_downloads(df[dated], scaled, state, district, file_span, start, end)
    st.subheader("Map")
    render_map(geo_path, df, sensor, state, district, start, end, latest)


main()
