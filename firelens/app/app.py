"""FireLens: harmonized burning-activity calendar for Northern India, 2016-2026.

Run from firelens/:  streamlit run app/app.py
Data format: docs/data-contract.md.
"""

import calendar
import io
import json
import sys
import zipfile
from pathlib import Path

import folium
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit_folium import st_folium

sys.path.insert(0, str(Path(__file__).resolve().parent))  # so `import trends` works under any runner
import trends  # noqa: E402  (app/trends.py: Mann-Kendall and Sen's slope)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_PATH = DATA_DIR / "district_monthly.csv"
HARMONIZED_PATH = DATA_DIR / "district_harmonized.csv"  # from science/harmonize.py
GEO_PATH = DATA_DIR / "districts.geojson"
HOTSPOTS_PATH = DATA_DIR / "hotspots.csv.gz"  # from gee/merge_hotspots.py; optional
FIRE_TYPES_PATH = DATA_DIR / "district_fire_types.csv"  # from science/fire_types.py; optional
STATIC_PATH = DATA_DIR / "static_sources.csv"  # from science/fire_types.py; optional
PROJECT_DIR = DATA_DIR.parent  # firelens/
REPO_DIR = PROJECT_DIR.parent  # repository root: LICENSE, CITATION.cff
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
UNCERTAINTY_COLUMNS = ["sensor_min", "sensor_max", "n_blended", "clear_coverage"]  # contract §6
RANGE_NOTE = (
    "Grey band / error bars: the range of the three sensors after scaling, a measure of how "
    "far the satellites disagree (not a confidence interval)."
)
TREND_NOTE = (
    "Each point is the mean monthly activity of that season; a year counts only when every "
    "month of the season was observed with at least half its daily images. Trend test: "
    "Mann-Kendall (two-sided, exact for untied data); slope: Sen's median slope, also given "
    f"as a percentage of the median season. A test needs at least {trends.MIN_TREND_YEARS} seasons. "
    "With 49 districts tested at p < 0.05, two or three can look significant by chance."
)
TREND_DRIFT_NOTE = (
    "Caution: seasons from 2023 on fall in the period when the MODIS orbits drifted and burning "
    "appears to have moved later in the day, past the early-afternoon overpass. Part of a decline "
    "may be a detection effect, not less burning. Compare the single sensors (Series) before "
    "drawing conclusions."
)
FIRE_TYPE_NOTE = (
    "Hotspot pixel-days by the land cover under each detection (MODIS MCD12Q1, IGBP classes, "
    "year of the detection): cropland = croplands and cropland mosaics; forest = the five forest "
    "classes; woodland & grass = shrubland, savanna and grassland (much open Himalayan pine "
    "forest falls here); static sources = pixels hot in at least 8 of the 12 calendar months, "
    "i.e. fixed heat sources such as flares and furnaces, not vegetation fires. Counts are one "
    "sensor's detections as recorded, never a sum of sensors. Method and checks: science/fire_types.md."
)
MAP_LATEST, MAP_TREND = "Latest month vs median", "Trend"
MAP_TREND_NOTE = (
    "Each district coloured by its Sen's slope for the season chosen in the Trend tab, as a "
    "percentage of its median season per year, where Mann-Kendall p < 0.05; white where no "
    "significant trend. Click a district to open it. "
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
    The uncertainty columns (contract §6) ride along when the file has them.
    """
    images = monthly.groupby(MONTH_KEYS, as_index=False)["n_images"].max()
    if "source" not in harmonized:  # v1 file: no provenance column
        harmonized = harmonized.assign(source="blend")
    extra = [c for c in UNCERTAINTY_COLUMNS if c in harmonized]
    rows = harmonized[MONTH_KEYS + ["act_harmonized", "viirs_act", "source"] + extra]
    # Inner join: only months the sensor file covers, so both files describe the same record.
    rows = rows.merge(images, on=MONTH_KEYS, how="inner").merge(anchor_clear(monthly), on=MONTH_KEYS, how="left")
    rows["detections"] = harmonized_detections(rows)
    rows = rows.rename(columns={"act_harmonized": "activity"})
    return rows[MONTH_KEYS + ["activity", "detections", "n_images", "source"] + extra].assign(sensor=HARMONIZED)


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


def has_range(frame: pd.DataFrame) -> bool:
    """True when the rows carry a usable sensor range (the harmonized series, v2 file)."""
    return set(UNCERTAINTY_COLUMNS) <= set(frame.columns) and bool(frame["n_blended"].notna().any())


def confidence_grids(series: pd.DataFrame, years: list[int]) -> dict | None:
    """Year x month tables of the uncertainty columns, or None for a single sensor."""
    if not has_range(series):
        return None
    return {column: calendar_grid(series, years, column) for column in UNCERTAINTY_COLUMNS}


def confidence_text(grids: dict, y: int, m: int) -> str:
    """Hover wording: how many sensors the value rests on, their range, the clear view."""
    n = grids["n_blended"].loc[y, m]
    if np.isnan(n) or n < 1:
        return ""
    low, high = grids["sensor_min"].loc[y, m] * 100, grids["sensor_max"].loc[y, m] * 100
    text = f" · rests on {int(n)} sensor{'' if n == 1 else 's'}; sensors range {low:.3f}–{high:.3f}%"
    cover = grids["clear_coverage"].loc[y, m]
    return text if np.isnan(cover) else text + f" · {cover:.0%} of land seen clearly"


def calendar_hover(grid: pd.DataFrame, counts: pd.DataFrame, estimated: bool, selected,
                   sources: pd.DataFrame | None = None, confidence: dict | None = None):
    """Hover text per cell: outside the dates, no data, or activity, count, source, confidence."""
    def text(y: int, m: int) -> str:
        if not selected(y, m):
            return OUTSIDE_DATES
        if np.isnan(grid.loc[y, m]):
            return "no data"
        base = f"activity {grid.loc[y, m] * 100:.3f}% · {count_text(counts.loc[y, m], estimated)}"
        source = sources.loc[y, m] if sources is not None else None
        if source in SOURCE_TEXT:
            base += f" · from {SOURCE_TEXT[source]}"
        return base + (confidence_text(confidence, y, m) if confidence else "")
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
                     sources: pd.DataFrame | None = None, confidence: dict | None = None) -> go.Figure:
    """Calendar coloured by hotspot pixel-days, or by activity share when not by_count."""
    if by_count:
        z, bar = counts, dict(title=dict(text="Hotspot<br>pixel-days"))
    else:  # activity as % of clearly seen pixels
        z, bar = grid * 100, dict(title=dict(text="Activity<br>(% of clear<br>pixels)"), ticksuffix="%")
    fig = heatmap_figure(z, title, calendar_hover(grid, counts, estimated, selected, sources, confidence),
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


def lines_figure(traces: list, title: str, band: pd.DataFrame | None = None) -> go.Figure:
    """Monthly series on one time axis; gaps break the line.

    band: rows with sensor_min / sensor_max, drawn as a grey range behind the lines.
    """
    fig = go.Figure()
    if band is not None:
        rows = band.sort_values(["year", "month"])
        dates = pd.to_datetime(rows[["year", "month"]].assign(day=1))
        edge = dict(mode="lines", line=dict(width=0), hoverinfo="skip", connectgaps=False)
        fig.add_trace(go.Scatter(x=dates, y=rows["sensor_min"] * 100, showlegend=False, **edge))
        fig.add_trace(go.Scatter(x=dates, y=rows["sensor_max"] * 100, name="Sensor range",
                                 fill="tonexty", fillcolor="rgba(17,17,17,0.16)", **edge))
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
    """Per year: mean monthly activity, months observed and (harmonized) the mean sensor range."""
    by_year = series.groupby("year")
    table = pd.DataFrame({"mean": by_year["activity"].mean(), "months": by_year["activity"].count()})
    if has_range(series):
        table["low"], table["high"] = by_year["sensor_min"].mean(), by_year["sensor_max"].mean()
    return table.reindex(years)


def yearly_chart(summary: pd.DataFrame, title: str) -> go.Figure:
    """Bar per year; years with fewer than 12 observed months are drawn lighter and hatched."""
    full = summary["months"] == 12
    ranged = "low" in summary
    hover = []
    for year, row in summary.iterrows():
        if not row["months"] or np.isnan(row["months"]):
            hover.append(f"{year} · no data")
            continue
        text = f"{year} · mean activity {row['mean'] * 100:.3f}% · {int(row['months'])} of 12 months observed"
        if ranged and not np.isnan(row["low"]):
            text += f" · sensors range {row['low'] * 100:.3f}–{row['high'] * 100:.3f}%"
        hover.append(text)
    error = None
    if ranged:
        error = dict(type="data", symmetric=False, color="#333333", thickness=1.3, width=5,
                     array=((summary["high"] - summary["mean"]) * 100).clip(lower=0),
                     arrayminus=((summary["mean"] - summary["low"]) * 100).clip(lower=0))
    fig = go.Figure(go.Bar(
        x=[str(y) for y in summary.index], y=summary["mean"] * 100, text=hover,
        hovertemplate="%{text}<extra></extra>", textposition="none", error_y=error,
        marker=dict(color=["#0072B2" if ok else "#9EC5E0" for ok in full],
                    pattern=dict(shape=["" if ok else "/" for ok in full])),
    ))
    fig.update_layout(
        title=title, height=420, margin=dict(l=10, r=10, t=60, b=10),
        xaxis=dict(type="category", title=None),
        yaxis=dict(title="Mean monthly activity (% of clear pixels)", ticksuffix="%"),
    )
    return fig


# --- Trend ----------------------------------------------------------------------

def default_season(series: pd.DataFrame) -> int:
    """Index of the district's main burning season: Oct-Nov (0) or Apr-May (1)."""
    seasons = list(trends.SEASONS.values())[:2]
    medians = [series.loc[series["month"].isin(months), "activity"].median() for months in seasons]
    return int(np.nanargmax(medians)) if not all(np.isnan(medians)) else 0


def p_text(p: float) -> str:
    return "< 0.001" if p < 0.001 else f"{p:.3f}"


def trend_figure(values: pd.DataFrame, result: dict | None, title: str) -> go.Figure:
    """Season mean per year, the sensor range as error bars, and Sen's line."""
    error = None
    if "sensor_min" in values:
        error = dict(type="data", symmetric=False, color="#555555", thickness=1.2, width=4,
                     array=((values["sensor_max"] - values["value"]) * 100).clip(lower=0),
                     arrayminus=((values["value"] - values["sensor_min"]) * 100).clip(lower=0))
    fig = go.Figure(go.Scatter(
        x=values["year"], y=values["value"] * 100, mode="markers+lines", name="Season mean",
        line=dict(color="#0072B2", width=1), marker=dict(size=9, color="#0072B2"), error_y=error,
        hovertemplate="%{x} · %{y:.3f}%<extra></extra>",
    ))
    if result is not None:
        xs = np.array([values["year"].min(), values["year"].max()], dtype=float)
        significant = result["direction"] != "none"
        fig.add_trace(go.Scatter(
            x=xs, y=(result["intercept"] + result["slope"] * xs) * 100, mode="lines", hoverinfo="skip",
            name="Sen's slope" + ("" if significant else " (not significant)"),
            line=dict(color="#111111", width=2, dash="solid" if significant else "dash"),
        ))
    if values["year"].max() >= 2023:
        fig.add_vrect(x0=2022.5, x1=values["year"].max() + 0.5, fillcolor="#8a8a8a", opacity=0.12,
                      line_width=0, layer="below", annotation_text="MODIS orbit drift period",
                      annotation_position="top left")
    fig.update_layout(
        title=title, height=440, margin=dict(l=10, r=10, t=60, b=10),
        xaxis=dict(title=None, dtick=1), legend=dict(orientation="h", y=-0.15),
        yaxis=dict(title="Season mean activity (% of clear pixels)", ticksuffix="%", rangemode="tozero"),
    )
    return fig


def trend_cards(result: dict) -> None:
    """Direction, Sen's slope and Mann-Kendall p as three cards."""
    cols = st.columns(3)
    label = {"decreasing": "Decreasing", "increasing": "Increasing", "none": "No significant trend"}
    cols[0].metric("Trend (Mann-Kendall, p < 0.05)", label[result["direction"]])
    slope = "—" if np.isnan(result["slope_pct"]) else f"{result['slope_pct']:+.1f}% per year"
    cols[1].metric("Sen's slope", slope,
                   help=f"{result['slope'] * 100:+.4f} percentage points of clear land per year; "
                        "the percentage is relative to the median season.")
    cols[2].metric("Mann-Kendall p", p_text(result["p"]),
                   help=f"{result['n']} complete seasons, {result['first_year']}–{result['last_year']}; "
                        f"Kendall's tau {result['tau']:+.2f}; {result['method']} p-value.")


@st.cache_data
def district_trends(_df: pd.DataFrame, sensor: str, start: tuple[int, int], end: tuple[int, int],
                    months: tuple[int, ...]) -> dict:
    """Trend result (or None) for every district: same series, dates and season."""
    rows = _df[(_df["sensor"] == sensor) & in_dates(_df, start, end)]
    results = {}
    for key, group in rows.groupby(["state", "district"]):
        values = trends.season_values(group, months)
        results[key] = trends.trend(values["year"], values["value"]) if len(values) else None
    return results


def trends_csv(results: dict, season: str, series: str) -> bytes:
    """All districts' trend results as a table."""
    rows = []
    for (state, district), r in sorted(results.items()):
        row = {"state": state, "district": district, "season": season, "series": series}
        if r is not None:
            row.update(n_seasons=r["n"], first_year=r["first_year"], last_year=r["last_year"],
                       median_activity=r["median"], sen_slope_per_year=r["slope"],
                       sen_slope_pct_of_median_per_year=r["slope_pct"], kendall_tau=r["tau"],
                       mann_kendall_p=r["p"], p_method=r["method"], direction=r["direction"])
        rows.append(row)
    return pd.DataFrame(rows).to_csv(index=False).encode("utf-8")


def render_trend(df: pd.DataFrame, series: pd.DataFrame, state: str, sensor: str, title: str,
                 start: tuple[int, int], end: tuple[int, int], file_stem: str) -> str:
    """Trend tab; returns the season chosen, which the trend map also uses."""
    seasons = list(trends.SEASONS)
    season = st.radio("Season", seasons, index=default_season(series), horizontal=True,
                      key=f"trend_season_{state}")
    months = trends.SEASONS[season]
    extra = ("sensor_min", "sensor_max") if has_range(series) else ()
    values = trends.season_values(series, months, extra)
    if values.empty:
        st.info("No complete season in the selected dates.")
        return season
    result = trends.trend(values["year"], values["value"])
    show_chart(trend_figure(values, result, f"{title} · {season}"), f"{title} trend")
    if result is None:
        st.info(f"A trend test needs at least {trends.MIN_TREND_YEARS} complete seasons; "
                f"the selected dates have {len(values)}.")
    else:
        trend_cards(result)
        if result["last_year"] >= 2023:
            st.warning(TREND_DRIFT_NOTE)
    st.caption(TREND_NOTE + (" " + RANGE_NOTE if extra else ""))
    st.download_button(
        "Download trend table (all districts) CSV",
        data=trends_csv(district_trends(df, sensor, start, end, months), season, SERIES_LABELS[sensor]),
        file_name=f"firelens_trends_{sensor}_{file_stem}.csv", mime="text/csv",
        help="Sen's slope and Mann-Kendall p for every district: this season, series and dates.",
    )
    return season


# --- Fire type ------------------------------------------------------------------

FIRE_CLASSES = [  # column, label, Okabe-Ito colour, hatch (so classes differ without colour)
    ("n_cropland", "Cropland", "#E69F00", ""),
    ("n_forest", "Forest", "#009E73", "/"),
    ("n_woodland_grass", "Woodland & grass", "#56B4E9", "."),
    ("n_other", "Other land", "#999999", ""),
    ("n_static", "Static sources", "#111111", ""),
]
BY_MONTH, BY_YEAR = "By month of year", "By year"


@st.cache_data
def load_table(path: Path) -> pd.DataFrame:
    return pd.read_csv(path)


def fire_type_figure(rows: pd.DataFrame, by_month: bool, title: str) -> go.Figure:
    """Stacked hotspot pixel-days by fire type: mean per calendar month, or total per year."""
    columns = [column for column, *_ in FIRE_CLASSES]
    if by_month:
        table = rows.groupby("month")[columns].sum().div(rows.groupby("month")["year"].nunique(), axis=0)
        table = table.reindex(MONTHS)
        x, y_title = MONTH_NAMES, "Hotspot pixel-days per year (mean)"
    else:
        table = rows.groupby("year")[columns].sum()
        x, y_title = [str(y) for y in table.index], "Hotspot pixel-days"
    fig = go.Figure()
    for column, label, colour, hatch in FIRE_CLASSES:
        fig.add_trace(go.Bar(
            x=x, y=table[column], name=label,
            marker=dict(color=colour, pattern=dict(shape=hatch, fillmode="overlay", fgcolor="rgba(0,0,0,0.5)")),
            hovertemplate=label + " · %{x} · %{y:,.1f}<extra></extra>",
        ))
    fig.update_layout(
        barmode="stack", title=title, height=440, margin=dict(l=10, r=10, t=60, b=10),
        xaxis=dict(type="category", title=None), yaxis=dict(title=y_title),
        legend=dict(orientation="h", y=-0.15, traceorder="normal"),
    )
    return fig


def render_fire_types(state: str, district: str, sensor: str, start: tuple[int, int],
                      end: tuple[int, int], place: str) -> None:
    """Fire type tab: what burns, by land cover, and how much is a static source."""
    if not FIRE_TYPES_PATH.exists():
        st.info("Fire-type data has not been generated in this build (science/fire_types.py).")
        return
    types = load_table(FIRE_TYPES_PATH)
    here = types[(types["state"] == state) & (types["district"] == district)]
    if here.empty:
        n_covered = types[["state", "district"]].drop_duplicates().shape[0]
        in_state = sorted(types.loc[types["state"] == state, "district"].unique())
        st.info(f"Fire type is not available for {district} yet: the land-cover hotspot export covers "
                f"{n_covered} districts so far. In {state}: {', '.join(in_state) or 'none'}. "
                "The calendar, trend and anomaly views cover every district.")
        return
    use = ANCHOR_SENSOR if sensor == HARMONIZED else sensor
    rows = here[(here["sensor"] == use) & in_dates(here, start, end)]
    total = int(rows["n_hotspots"].sum())
    if total == 0:
        st.info(f"No {SENSOR_LABELS[use]} hotspots in {district} in these dates.")
        return
    by_month = st.radio("Show", [BY_MONTH, BY_YEAR], horizontal=True, key="fire_type_view") == BY_MONTH
    title = f"{place} · {SENSOR_LABELS[use]}"
    show_chart(fire_type_figure(rows, by_month, title), f"{title} fire type")
    shares = " · ".join(f"{label} {rows[column].sum() / total:.1%}" for column, label, *_ in FIRE_CLASSES)
    st.markdown(f"**{shares}** of {total:,} hotspot pixel-days.")
    quiet = rows[~rows["month"].isin([4, 5, 10, 11])]
    if rows["n_static"].sum() > 0 and quiet["n_hotspots"].sum() > 0:
        st.markdown(f"Outside the two burning seasons (Apr–May, Oct–Nov), static sources are "
                    f"**{quiet['n_static'].sum() / quiet['n_hotspots'].sum():.0%}** of this district's "
                    "detections: they set the quiet-month baseline, not the peaks.")
    if STATIC_PATH.exists():
        static = load_table(STATIC_PATH)
        static = static[(static["state"] == state) & (static["district"] == district)]
        if len(static):
            st.markdown(f"Static-source pixels in {district} ({len(static)}):")
            st.dataframe(static[["latitude", "longitude", "n_detections", "n_months", "n_calendar_months",
                                 "night_share", "median_nightlight"]].rename(columns={
                "n_detections": "detections", "n_months": "months with detections",
                "n_calendar_months": "calendar months (of 12)", "night_share": "share at night",
                "median_nightlight": "night light (nW/cm²/sr)"}), hide_index=True)
    note = FIRE_TYPE_NOTE
    if sensor == HARMONIZED:
        note += (" Shown for Suomi-NPP VIIRS, the anchor sensor: fire type belongs to individual "
                 "detections, which are not harmonized.")
    if float(here["area_covered"].iloc[0]) < 0.999:
        note += f" The export sampled {float(here['area_covered'].iloc[0]):.0%} of this district's area."
    st.caption(note)


# --- About: citation, sources, everything in one download ------------------------

ABOUT_TEXT = """
**Cite FireLens**

COSMICBRO's (2026). *FireLens: a harmonized MODIS–VIIRS burning-activity calendar for Northern
India, 2016–2026* [software and data]. NASA Space Apps Challenge 2026.
https://github.com/frbasil-1k/HARMONIZATION-space-app

**NASA data used (please cite these too)**

- Giglio, L., & Justice, C. (2021). *MODIS/Terra Thermal Anomalies/Fire Daily L3 Global 1km SIN
  Grid V061* [MOD14A1]. NASA LP DAAC. https://doi.org/10.5067/MODIS/MOD14A1.061
- Giglio, L., & Justice, C. (2021). *MODIS/Aqua Thermal Anomalies/Fire Daily L3 Global 1km SIN
  Grid V061* [MYD14A1]. NASA LP DAAC. https://doi.org/10.5067/MODIS/MYD14A1.061
- Giglio, L. (2023). *VIIRS/NPP Thermal Anomalies and Fire Daily L3 Global 1km SIN Grid V002*
  [VNP14A1]. NASA LP DAAC. https://doi.org/10.5067/VIIRS/VNP14A1.002
- Friedl, M., & Sulla-Menashe, D. (2022). *MODIS/Terra+Aqua Land Cover Type Yearly L3 Global 500m
  SIN Grid V061* [MCD12Q1; fire-type view]. NASA LP DAAC. https://doi.org/10.5067/MODIS/MCD12Q1.061
- VIIRS Day/Night Band monthly composites (VCMSLCFG), Earth Observation Group, Payne Institute,
  Colorado School of Mines [night lights; static-source check].

All accessed through Google Earth Engine. We acknowledge the use of data from NASA's Land Processes
Distributed Active Archive Center (LP DAAC) and Fire Information for Resource Management System
(FIRMS), part of NASA's Earth Science Data and Information System (ESDIS).

**Boundaries**

FAO Global Administrative Unit Layers (GAUL) 2015, Level 2, simplified; © FAO, used under the GAUL
2015 data licence (non-commercial use). Not an official boundary of India.

**Licence**

Code: MIT. FireLens's derived tables (the CSV files): CC BY 4.0. The district boundaries keep
FAO's GAUL terms and are not relicensed. Hotspots are satellite detections, not confirmed fires.
"""


@st.cache_data
def all_data_zip() -> bytes:
    """Every derived table plus the documents needed to use and cite them."""
    files = [
        (HARMONIZED_PATH, "data/district_harmonized.csv"),
        (DATA_PATH, "data/district_monthly.csv"),
        (FIRE_TYPES_PATH, "data/district_fire_types.csv"),
        (STATIC_PATH, "data/static_sources.csv"),
        (HOTSPOTS_PATH, "data/hotspots.csv.gz"),
        (DATA_DIR / "README.md", "DATA_DICTIONARY.md"),
        (PROJECT_DIR / "science" / "validation.md", "docs/harmonization_validation.md"),
        (PROJECT_DIR / "science" / "fire_types.md", "docs/fire_types.md"),
        (REPO_DIR / "CITATION.cff", "CITATION.cff"),
        (REPO_DIR / "LICENSE", "LICENSE"),
    ]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, name in files:
            if path.exists():
                archive.write(path, name)
    return buffer.getvalue()


def render_about() -> None:
    with st.expander("How to cite · data sources · licence"):
        st.markdown(ABOUT_TEXT)


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


def ratio_text(ratio: float | None) -> str:
    """Headline wording: '0×' (none detected) and '<0.01×' instead of a misleading '0.00×'."""
    if ratio is None:
        return "—"
    if ratio == 0:
        return "0× (no hotspots)"
    return "<0.01×" if ratio < 0.01 else f"{ratio:.2f}×"


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
                   ratio_text(ratio), help=note, **partial)
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
    cols = st.columns(4)
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
    cols[3].download_button(
        "Download all data (ZIP)", data=all_data_zip(), file_name="firelens_data.zip",
        mime="application/zip",
        help="Every district: the harmonized and per-sensor tables, fire types, static sources and "
             "the individual hotspot list, with the data dictionary, validation reports, licence "
             "and citation file.",
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
    confidence = confidence_grids(series, years) if estimated else None
    show_chart(calendar_heatmap(grid, counts, title, estimated, by_count, selected, sources, confidence),
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
        band = scaled if "sensor_min" in scaled else None
        fig = shade_drift(lines_figure(scaled_traces(scaled), place, band), scaled)
        show_chart(fig, f"{place} sensors harmonized")
        st.caption(SCALED_NOTE + " " + DRIFT_NOTE + (" " + RANGE_NOTE if band is not None else ""))
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


def overview_map(geo: dict, styles: dict, selected: tuple[str, str]) -> folium.Map:
    """All districts filled by styles[(state, district)] = (colour, text); selected one outlined."""
    features = []
    for feature in geo["features"]:
        key = district_key(feature)
        colour, text = styles.get(key, (MAP_NO_DATA, "no comparison"))
        features.append({
            "type": "Feature",
            "geometry": {"type": "MultiPolygon", "coordinates": polygons(feature["geometry"])},
            "properties": {"state": key[0], "district": key[1], "label": f"{key[1]}, {key[0]}: {text}",
                           "fill": colour, "selected": key == selected},
        })
    # No scroll-wheel zoom: scrolling the page over the map should scroll the page.
    m = folium.Map(tiles="OpenStreetMap", scrollWheelZoom=False)
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


def map_legend(items: list[tuple[str, str]]) -> str:
    """Legend row from (colour, label) pairs."""
    swatch = ('<span style="display:inline-block;width:14px;height:14px;background:{c};'
              'border:1px solid #888;margin:0 4px 0 10px;vertical-align:middle"></span>{t}')
    return '<div style="font-size:0.85rem">' + "".join(swatch.format(c=c, t=t) for c, t in items) + "</div>"


# Sen's slope classes for the trend map, % of the median season per year (PuOr).
TREND_BINS = [(-10, "below −10% per year", "#542788"), (-5, "−10 to −5", "#8073ac"), (0, "−5 to 0", "#b2abd2"),
              (5, "0 to +5", "#fdb863"), (10, "+5 to +10", "#e08214"), (np.inf, "above +10% per year", "#b35806")]
TREND_NOT_SIGNIFICANT = "#ffffff"


def ratio_style(ratio: float, month_name: str) -> tuple[str, str]:
    """Map colour and tooltip text for one district's month-vs-median ratio."""
    if ratio == 0:
        return ratio_colour(ratio), f"no hotspots (its {month_name} median is above zero)"
    return ratio_colour(ratio), f"{'<0.01' if ratio < 0.01 else f'{ratio:.2f}'}× its {month_name} median"


def trend_style(result: dict | None) -> tuple[str, str]:
    """Map colour and tooltip text for one district's trend result."""
    if result is None:
        return MAP_NO_DATA, "too few complete seasons for a trend test"
    if result["direction"] == "none" or np.isnan(result["slope_pct"]):
        return TREND_NOT_SIGNIFICANT, f"no significant trend (p = {p_text(result['p'])})"
    colour = next(c for upper, _, c in TREND_BINS if result["slope_pct"] < upper)
    return colour, f"{result['direction']}, {result['slope_pct']:+.1f}% per year (p = {p_text(result['p'])})"


def render_map(geo_path: Path, df: pd.DataFrame, sensor: str, state: str, district: str,
               start: tuple[int, int], end: tuple[int, int], latest: pd.Series | None,
               season: str) -> None:
    """All districts, by the headline month vs median or by trend; clicking a district opens it."""
    geo = load_geojson(geo_path)
    if district_feature(geo, state, district) is None:
        st.info(f"No boundary found for {district}, {state}.")
    by_trend = st.radio("Colour the map by", [MAP_LATEST, MAP_TREND], horizontal=True,
                        key="map_mode") == MAP_TREND
    if by_trend:
        results = district_trends(df, sensor, start, end, trends.SEASONS[season])
        styles = {key: trend_style(result) for key, result in results.items()}
        tag = f"trend-{season}"
        st.markdown(f"**All districts · trend in {season} · {SERIES_LABELS[sensor]}**")
        legend = ([(c, t) for _, t, c in TREND_BINS]
                  + [(TREND_NOT_SIGNIFICANT, "no significant trend"), (MAP_NO_DATA, "too few seasons")])
        note = MAP_TREND_NOTE
    elif latest is None:
        styles, tag = {}, "none"
        st.markdown("**All districts** · no observed month to compare in these dates")
        legend, note = [(MAP_NO_DATA, "no comparison")], MAP_NOTE.format(n=MIN_YEARS) + " "
    else:
        target = (int(latest["year"]), int(latest["month"]))
        month_name = MONTH_NAMES[target[1] - 1]
        ratios = district_ratios(df, sensor, start, end, target)
        styles = {key: ratio_style(ratio, month_name) for key, ratio in ratios.items()}
        tag = f"{target}"
        st.markdown(f"**All districts · {month_label(*target)} vs each district's {month_name} median "
                    f"· {SERIES_LABELS[sensor]}**")
        legend = [(c, t) for _, t, c in MAP_BINS] + [(MAP_NO_DATA, "no comparison")]
        note = MAP_NOTE.format(n=MIN_YEARS) + " "
    out = st_folium(overview_map(geo, styles, (state.strip(), district.strip())),
                    height=480, use_container_width=True, returned_objects=["last_active_drawing"],
                    key=f"map-{state}-{district}-{sensor}-{tag}")
    clicked = (out or {}).get("last_active_drawing") or {}
    props = clicked.get("properties") or {}
    pick = (props.get("state"), props.get("district"))
    if all(pick) and pick != (state.strip(), district.strip()):
        st.session_state["pending_pick"] = pick
        st.rerun()
    st.markdown(map_legend(legend), unsafe_allow_html=True)
    st.caption(note + BOUNDARY_DISCLAIMER)


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
    calendar_tab, yearly_tab, anomaly_tab, trend_tab, types_tab, sensors_tab = st.tabs(
        ["Calendar", "Yearly", "Anomaly", "Trend", "Fire type", "Sensor comparison"])
    with calendar_tab:
        render_calendar(series, grid, years, place_sensor, sensor == HARMONIZED, selected)
    with yearly_tab:
        show_chart(yearly_chart(yearly_summary(series, years), place_sensor), f"{place_sensor} yearly")
        st.caption(YEARLY_NOTE + (" " + RANGE_NOTE if has_range(series) else ""))
    with anomaly_tab:
        show_chart(anomaly_heatmap(anomaly_grid(grid), place_sensor, selected), f"{place_sensor} anomaly")
        st.caption(ANOMALY_NOTE)
    with trend_tab:
        season = render_trend(df, series, state, sensor, place_sensor, start, end, file_span)
    with types_tab:
        render_fire_types(state, district, sensor, start, end, place)
    with sensors_tab:
        render_comparison(district_rows, scaled, place)
    render_downloads(df[dated], scaled, state, district, file_span, start, end)
    st.subheader("Map")
    render_map(geo_path, df, sensor, state, district, start, end, latest, season)
    render_about()


main()
