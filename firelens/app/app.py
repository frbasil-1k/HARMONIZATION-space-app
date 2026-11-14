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
    "Harmonized = Terra and Aqua MODIS scaled to the Suomi-NPP VIIRS anchor with state-level "
    "ratios fitted on 2016–2022, then averaged with VIIRS over the sensors that saw the "
    "district clearly that month. Method and blind 2023–2025 validation: science/validation.md."
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
    "After harmonization: Terra and Aqua MODIS scaled to the VIIRS anchor, and the black "
    "line is the harmonized series (the mean of the sensors that saw the district clearly). "
    "Breaks in a line are months with no data."
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
    rows = harmonized[MONTH_KEYS + ["act_harmonized", "viirs_act"]]
    # Inner join: only months the sensor file covers, so both files describe the same record.
    rows = rows.merge(images, on=MONTH_KEYS, how="inner").merge(anchor_clear(monthly), on=MONTH_KEYS, how="left")
    rows["detections"] = harmonized_detections(rows)
    rows = rows.rename(columns={"act_harmonized": "activity"})
    return rows[MONTH_KEYS + ["activity", "detections", "n_images"]].assign(sensor=HARMONIZED)


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


def calendar_hover(grid: pd.DataFrame, counts: pd.DataFrame, estimated: bool, selected):
    """Hover text per cell: outside the dates, no data, or activity plus count."""
    def text(y: int, m: int) -> str:
        if not selected(y, m):
            return OUTSIDE_DATES
        if np.isnan(grid.loc[y, m]):
            return "no data"
        return f"activity {grid.loc[y, m] * 100:.3f}% · {count_text(counts.loc[y, m], estimated)}"
    return text


def calendar_heatmap(grid: pd.DataFrame, counts: pd.DataFrame, title: str,
                     estimated: bool, by_count: bool, selected) -> go.Figure:
    """Calendar coloured by activity share, or by hotspot pixel-days when by_count."""
    if by_count:
        z, bar = counts, dict(title=dict(text="Hotspot<br>pixel-days"))
    else:  # activity as % of clearly seen pixels
        z, bar = grid * 100, dict(title=dict(text="Activity<br>(% of clear<br>pixels)"), ticksuffix="%")
    return heatmap_figure(z, title, calendar_hover(grid, counts, estimated, selected),
                          colorscale="Cividis", zmin=0, colorbar=bar)


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


def render_metrics(series: pd.DataFrame, grid: pd.DataFrame) -> None:
    latest = latest_observed(series)
    cols = st.columns(3)
    if latest is None:
        cols[0].info("No observed months for this selection.")
        return
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
    by_count = st.radio("Colour by", [BY_ACTIVITY, BY_COUNT], horizontal=True,
                        key="calendar_value") == BY_COUNT
    counts = calendar_grid(series, years, "detections")
    show_chart(calendar_heatmap(grid, counts, title, estimated, by_count, selected),
               f"{title} calendar")
    st.caption(ACTIVITY_NOTE + (" " + HARMONIZED_NOTE if estimated else ""))
    st.caption(HARMONIZED_COUNT_NOTE if estimated else COUNT_NOTE)


def render_comparison(district_rows: pd.DataFrame, scaled: pd.DataFrame | None, place: str) -> None:
    """Sensors side by side: after harmonization (when available) or as recorded."""
    views = ["After harmonization", "As recorded"] if scaled is not None else ["As recorded"]
    view = st.radio("Show", views, horizontal=True, key="comparison_view")
    if view == "After harmonization":
        show_chart(lines_figure(scaled_traces(scaled), place), f"{place} sensors harmonized")
        st.caption(SCALED_NOTE)
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


def district_map(feature: dict) -> folium.Map:
    m = folium.Map(tiles="OpenStreetMap")
    layer = folium.GeoJson(
        feature,
        style_function=lambda _: {"color": "#0072B2", "weight": 2, "fillOpacity": 0.1},
    ).add_to(m)
    m.fit_bounds(layer.get_bounds())
    return m


def render_map(geo_path: Path, state: str, district: str) -> None:
    feature = district_feature(load_geojson(geo_path), state, district)
    if feature is None:
        st.info(f"No boundary found for {district}, {state}.")
    else:
        st_folium(district_map(feature), height=420, use_container_width=True,
                  returned_objects=[], key=f"map-{state}-{district}")
    st.caption(BOUNDARY_DISCLAIMER)


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

    render_metrics(series, grid)
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
    st.subheader(f"{district}, {state}")
    render_map(geo_path, state, district)


main()
