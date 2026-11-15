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
import folium.plugins
from branca.element import MacroElement
from jinja2 import Template
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit_folium import st_folium

sys.path.insert(0, str(Path(__file__).resolve().parent))  # so `import trends` works under any runner
import trends  # noqa: E402  (app/trends.py: Mann-Kendall and Sen's slope)
from area import area_contains, area_km2, box_geometry, polygons, valid_area  # noqa: E402  (app/area.py)

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
    "NOAA ended Suomi-NPP data delivery on 2 Nov 2026, so from November 2026 every value is "
    "drifted-MODIS fill (◦) until VIIRS on NOAA-20/21 takes over as the anchor. "
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
TREND_METHOD = (
    "a year counts only when every month of the season was observed with at least half its "
    "daily images. Trend test: Mann-Kendall (two-sided, exact for untied data); slope: Sen's "
    "median slope, also given as a percentage of the median season. A test needs at least "
    f"{trends.MIN_TREND_YEARS} seasons."
)
TREND_NOTE = (
    "Each point is the mean monthly activity of that season; " + TREND_METHOD +
    " With 49 districts tested at p < 0.05, two or three can look significant by chance."
)
AREA_TREND_NOTE = (
    "Each point is the mean monthly hotspot pixel-days of that season, for the satellite "
    "chosen above (not harmonized); " + TREND_METHOD
)
TREND_DRIFT_NOTE = (
    "Caution: seasons from 2023 on fall in the period when the MODIS orbits drifted and burning "
    "appears to have moved later in the day, past the early-afternoon overpass. Part of a decline "
    "may be a detection effect, not less burning. Compare the single sensors ({where}) before "
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
SNPP_LAST = (2026, 11)  # NOAA ended Suomi-NPP data delivery on 2 Nov 2026 (2 images that month)
# Opening view: a major rice-residue district with every view filled (fire type, static
# sources, a significant Oct-Nov trend). Used only if the data has it (not with mock data).
DEFAULT_PLACE = ("Punjab", "Ludhiana")
LOW_RATIO, HIGH_RATIO = 0.5, 2.0  # region-wide context: below half / above twice the median
# Official farm-fire counts, for context beside the satellite numbers (CAQM, 2 Dec 2025).
CAQM_NOTE = ("Official farm-fire counts (also from satellites) agree: Punjab's 2025 rice-residue "
             "season had 5,114 fires, 93% fewer than in 2021 (Commission for Air Quality "
             "Management, Dec 2025). Part of the fall may be burning moved past the "
             "early-afternoon overpasses; see the Trend tab.")
SERIES_LABELS = {HARMONIZED: "Harmonized (MODIS + VIIRS)", **SENSOR_LABELS}
MONTH_KEYS = ["state", "district", "year", "month"]
ALL_MONTHS = [(y, m) for y in YEARS for m in MONTHS]
# Quick date ranges under the slider. "Before MODIS drift" = the calibration period of the
# harmonization (Terra drifts from Oct 2022: science/harmonize.py DRIFT_START).
DATE_PRESETS = {
    "All years": (ALL_MONTHS[0], ALL_MONTHS[-1]),
    "Last 5 years": ((ALL_MONTHS[-1][0] - 4, 1), ALL_MONTHS[-1]),
    "Before MODIS drift": (ALL_MONTHS[0], (2022, 9)),
}
GUIDE_TEXT = """
1. **Pick a place.** Choose a state and district on the left, click a district on the map, or
   switch *Look at* to **Draw an area** for any box or polygon.
2. **Pick the data.** *Series*: **Harmonized** puts Terra, Aqua and Suomi-NPP on one scale
   (recommended), or choose one satellite as recorded. *Dates*: drag the slider or use a quick range.
3. **Read the cards.** The latest month with at least half its daily images, against the median
   of the same month in the selected years; its percentile rank; and the usual peak months.
4. **Use the map** to compare all 49 districts at once, then **the tabs** for one district:
   Calendar (month × year), Yearly, Anomaly (vs the usual month), Trend (Mann-Kendall + Sen's
   slope), Fire type (land cover), Sensor comparison. Each view has a one-line summary and an
   *About this view* panel with the method. Downloads sit under the tabs.

**Key terms.** *Hotspot pixel-day*: one 1 km pixel with a detection on one day. *Activity*:
hotspot pixel-days ÷ clearly seen pixel-days, so cloudy months stay comparable. *Blank cell*: no
clear view, not zero. *◦*: a month filled from drifted MODIS (lower confidence).
"""
OUTSIDE_DATES = "outside the selected dates"
BY_ACTIVITY, BY_COUNT = "Activity (share of clear land)", "Hotspot count"
HARMONIZED_LINE = dict(color="#111111", width=3)
SENSOR_LINES = {  # Okabe-Ito colours plus dash styles, so lines differ without colour
    "viirs_snpp": dict(color="#0072B2", width=2),
    "terra": dict(color="#E69F00", width=2, dash="dash"),
    "aqua": dict(color="#009E73", width=2, dash="dot"),
}


def data_version() -> tuple:
    """Name, size and modification time of every data file the app reads."""
    files = sorted(p for p in DATA_DIR.iterdir() if p.is_file()) if DATA_DIR.is_dir() else []
    return tuple((p.name, p.stat().st_size, p.stat().st_mtime_ns) for p in files)


@st.cache_resource
def seen_data_version() -> dict:
    """Process-wide memory of the data version the cached tables were read from."""
    return {}


def refresh_cache_on_new_data() -> None:
    """Drop cached tables when a data file changes.

    Streamlit Community Cloud pulls each new commit and reloads the code without restarting
    the process, and st.cache_data keys on the function and its arguments (a path), not on
    the file's contents. A pushed data file would therefore keep being served from the old
    cache: the deployed app showed the v1 harmonized numbers a day after v2 was merged.
    Clearing on the first run of each process also removes anything cached by older code.
    """
    seen, version = seen_data_version(), data_version()
    if seen.get("version") != version:
        st.cache_data.clear()
        seen["version"] = version


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


def explain(summary: str, details: str) -> None:
    """One short line always visible; the full method one click away, so the page stays
    scannable and the caveats stay complete."""
    st.caption(summary)
    with st.expander("About this view"):
        st.markdown(details)


def apply_date_preset() -> None:
    """Quick-range callback: set the Dates slider, then clear the choice so the same range
    can be picked again after dragging the slider."""
    choice = st.session_state.get("date_preset")
    if choice in DATE_PRESETS:
        st.session_state["dates"] = DATE_PRESETS[choice]
    st.session_state["date_preset"] = None


def date_range() -> tuple[tuple[int, int], tuple[int, int]]:
    """Dates slider plus quick ranges (call inside the sidebar). The value lives in session
    state, so a quick range can move the slider without a default-value conflict."""
    st.session_state.setdefault("dates", DATE_PRESETS["All years"])
    start, end = st.select_slider("Dates", ALL_MONTHS, key="dates",
                                  format_func=lambda ym: month_label(*ym))
    st.pills("Quick ranges", list(DATE_PRESETS), key="date_preset", on_change=apply_date_preset,
             help="Before MODIS drift = Jan 2016 to Sep 2022, the period the harmonization is "
                  "calibrated on, before Terra's and Aqua's orbits drifted.")
    return start, end


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


def trend_figure(values: pd.DataFrame, result: dict | None, title: str, scale: float = 100,
                 y_title: str = "Season mean activity (% of clear pixels)", suffix: str = "%") -> go.Figure:
    """Season mean per year, the sensor range as error bars, and Sen's line.

    scale/y_title/suffix: activity shares are shown as percentages (100, "%"); hotspot
    counts for a drawn area as they are (1, "").
    """
    error = None
    if "sensor_min" in values:
        error = dict(type="data", symmetric=False, color="#555555", thickness=1.2, width=4,
                     array=((values["sensor_max"] - values["value"]) * scale).clip(lower=0),
                     arrayminus=((values["value"] - values["sensor_min"]) * scale).clip(lower=0))
    fig = go.Figure(go.Scatter(
        x=values["year"], y=values["value"] * scale, mode="markers+lines", name="Season mean",
        line=dict(color="#0072B2", width=1), marker=dict(size=9, color="#0072B2"), error_y=error,
        hovertemplate="%{x} · %{y:,.3f}" + suffix + "<extra></extra>",
    ))
    if result is not None:
        xs = np.array([values["year"].min(), values["year"].max()], dtype=float)
        significant = result["direction"] != "none"
        fig.add_trace(go.Scatter(
            x=xs, y=(result["intercept"] + result["slope"] * xs) * scale, mode="lines", hoverinfo="skip",
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
        yaxis=dict(title=y_title, ticksuffix=suffix, rangemode="tozero"),
    )
    return fig


def trend_cards(result: dict, unit: str = "percentage points of clear land") -> None:
    """Direction, Sen's slope and Mann-Kendall p as three cards."""
    cols = st.columns(3)
    label = {"decreasing": "Decreasing", "increasing": "Increasing", "none": "No significant trend"}
    cols[0].metric("Trend (Mann-Kendall, p < 0.05)", label[result["direction"]])
    slope = "—" if np.isnan(result["slope_pct"]) else f"{result['slope_pct']:+.1f}% per year"
    cols[1].metric("Sen's slope", slope,
                   help=(f"{result['slope'] * 100:+.4f} {unit} per year; " if unit.startswith("percentage")
                         else f"{result['slope']:+,.1f} {unit} per year; ")
                        + "the percentage is relative to the median season.")
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
            st.warning(TREND_DRIFT_NOTE.format(where="the Series selector in the sidebar"))
    explain("One point per season; Mann-Kendall test and Sen's slope, at least "
            f"{trends.MIN_TREND_YEARS} complete seasons.", TREND_NOTE + (" " + RANGE_NOTE if extra else ""))
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
    explain("Hotspots by the land cover under them; static sources are fixed heat sources, "
            "not vegetation fires.", note)


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
    ended = (int(row["year"]), int(row["month"])) >= SNPP_LAST
    if ended and row["sensor"] == ANCHOR_SENSOR:
        return (f"Suomi-NPP data ended on 2 Nov 2026 (NOAA), so "
                f"{month_label(int(row['year']), int(row['month']))} has only "
                f"{int(row['n_images'])} daily images and the cards use the last full month.")
    return (f"{month_label(int(row['year']), int(row['month']))} is still in progress "
            f"({'at most ' if row['sensor'] == HARMONIZED else ''}{int(row['n_images'])} of "
            f"{days_in(row)} daily images so far), so the cards compare the latest month with "
            f"at least half its images."
            + (" Suomi-NPP data ended on 2 Nov 2026, so from November the harmonized value is "
               "drifted MODIS only (◦)." if ended and row["sensor"] == HARMONIZED else ""))


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


def region_context(df: pd.DataFrame, sensor: str, latest: pd.Series | None,
                   start: tuple[int, int], end: tuple[int, int],
                   state: str, district: str) -> str | None:
    """One sentence placing the headline month in the whole region, when most districts
    agree (e.g. Oct 2026 far below normal almost everywhere) and the district on screen is
    one of them, so a very low headline reads as what it is: a region-wide fall, not a
    data gap. Nothing for a district without a comparison or on the other side."""
    if latest is None:
        return None
    year, month = int(latest["year"]), int(latest["month"])
    rows = df[(df["sensor"] == sensor) & (df["month"] == month) & in_dates(df, start, end)]
    ratios, own = [], None
    for (place_state, place_district), place in rows.groupby(["state", "district"]):
        now = place.loc[place["year"] == year, "activity"].dropna()
        if not now.empty:
            ratio = anomaly_ratio(float(now.iloc[0]), place["activity"].dropna())
            if ratio is not None:
                ratios.append(ratio)
                if (place_state, place_district) == (state, district):
                    own = ratio
    if not ratios or own is None:
        return None
    label, usual = month_label(year, month), calendar.month_name[month]
    low = sum(r < LOW_RATIO for r in ratios)
    high = sum(r > HIGH_RATIO for r in ratios)
    if low >= len(ratios) / 2 and own < LOW_RATIO:
        count = f"all {low}" if low == len(ratios) else f"{low} of the {len(ratios)}"
        text = (f"Region-wide: in {label}, {count} districts with a comparison were below half "
                f"their usual {usual}, so a low value here is a region-wide fall, not missing data.")
        if month in (10, 11) and year >= 2024 and state in ("Punjab", "Haryana"):
            text += " " + CAQM_NOTE
        return text
    if high >= len(ratios) / 2 and own > HIGH_RATIO:
        count = f"all {high}" if high == len(ratios) else f"{high} of the {len(ratios)}"
        return (f"Region-wide: in {label}, {count} districts with a comparison were above "
                f"twice their usual {usual}.")
    return None


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
    explain("Each box is one month: brighter means more burning. Blank = no clear view, not zero."
            + (" ◦ = filled from drifted MODIS (lower confidence)." if estimated else ""),
            ACTIVITY_NOTE + (" " + HARMONIZED_NOTE if estimated else "") + "\n\n"
            + (HARMONIZED_COUNT_NOTE if estimated else COUNT_NOTE))


def render_comparison(district_rows: pd.DataFrame, scaled: pd.DataFrame | None, place: str) -> None:
    """Sensors side by side: after harmonization (when available) or as recorded."""
    views = ["After harmonization", "As recorded"] if scaled is not None else ["As recorded"]
    if scaled is not None and "modis_recon" in scaled:
        views.append("MODIS-only check")
    view = st.radio("Show", views, horizontal=True, key="comparison_view",
                    help="After harmonization: every satellite on the VIIRS scale. As recorded: each "
                         "satellite's own values. MODIS-only check: the calendar rebuilt from Terra "
                         "and Aqua alone, laid over what VIIRS saw, to test the method.")
    if view == "After harmonization":
        band = scaled if "sensor_min" in scaled else None
        fig = shade_drift(lines_figure(scaled_traces(scaled), place, band), scaled)
        show_chart(fig, f"{place} sensors harmonized")
        explain("Each satellite after scaling to VIIRS; the black line is the harmonized series.",
                SCALED_NOTE + " " + DRIFT_NOTE + (" " + RANGE_NOTE if band is not None else ""))
    elif view == "MODIS-only check":
        fig = shade_drift(lines_figure(recon_traces(scaled), place), scaled)
        show_chart(fig, f"{place} MODIS-only check")
        agreement = recon_agreement(scaled)
        if agreement:
            st.markdown(f"**{agreement}**")
        explain("The calendar rebuilt from MODIS alone, against what VIIRS saw.", RECON_NOTE)
    else:
        show_chart(lines_figure(recorded_traces(district_rows), place), f"{place} sensors recorded")
        explain("Each satellite as recorded, before harmonization.", RECORDED_NOTE)


# --- Map ------------------------------------------------------------------------

@st.cache_data
def load_geojson(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


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


class RefitWhenSized(MacroElement):
    """Fit the map to the districts again once its frame has its real size, and whenever
    that size changes (window resize). streamlit-folium can build the map before the frame
    has its final width; Leaflet then fits the districts into a tiny box and the map opens
    on the whole world (seen on the deployed app). A user's own zoom is kept unless the
    map's size changes."""

    _template = Template("""
        {% macro script(this, kwargs) %}
        (function () {
            var map = {{ this._parent.get_name() }};
            var bounds = {{ this.bounds|tojson }};
            var fitted = null;
            function refit() {
                map.invalidateSize();
                var size = map.getSize();
                if (size.x > 0 && size.y > 0 &&
                        (fitted === null || fitted.x !== size.x || fitted.y !== size.y)) {
                    map.fitBounds(bounds);
                    fitted = size;
                }
            }
            [100, 400, 1200, 3000].forEach(function (ms) { setTimeout(refit, ms); });
            window.addEventListener("resize", refit);
        })();
        {% endmacro %}
    """)

    def __init__(self, bounds: list[list[float]]):
        super().__init__()
        self._name = "RefitWhenSized"
        self.bounds = [[float(v) for v in corner] for corner in bounds]


def fit_districts(m: folium.Map, layer: folium.GeoJson) -> None:
    """Fit now, and again once the map has its real size (see RefitWhenSized)."""
    bounds = layer.get_bounds()
    m.fit_bounds(bounds)
    RefitWhenSized(bounds).add_to(m)


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
    fit_districts(m, layer)
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
                    height=420, use_container_width=True, returned_objects=["last_active_drawing"],
                    key=f"map-{state}-{district}-{sensor}-{tag}")
    clicked = (out or {}).get("last_active_drawing") or {}
    props = clicked.get("properties") or {}
    pick = (props.get("state"), props.get("district"))
    if all(pick) and pick != (state.strip(), district.strip()):
        st.session_state["pending_pick"] = pick
        st.rerun()
    st.markdown(map_legend(legend), unsafe_allow_html=True)
    explain("Click a district to open it. Each district is compared with its own usual value.",
            note + BOUNDARY_DISCLAIMER)


# --- Draw an area ---------------------------------------------------------------

MODE_DISTRICT, MODE_AREA = "A district", "Draw an area"
AREA_KEY = "drawn_area"  # GeoJSON geometry of the area in use, kept across reruns
AREA_SENSORS = ["viirs_snpp", "aqua", "terra"]  # VIIRS first: the anchor sensor
AREA_NOTE = (
    "Counts are hotspot pixel-days inside the area: 1 km pixels with a detection (FireMask ≥ 8), "
    "summed over each month's daily images, for one satellite at a time; never a sum of satellites. "
    "They are not harmonized: harmonized activity needs the clearly seen land behind each pixel, "
    "which is available per district, not per pixel. For harmonized values, pick a district. "
    "A blank month has no images; a zero means images but no detections."
)
AREA_HELP = (
    "Use the square or polygon tool at the top left of the map, then click to place points "
    "(double-click, or click the first point, to finish a polygon). Only hotspots inside the 49 "
    "districts of Punjab, Haryana and Uttarakhand are in the data."
)


@st.cache_data
def area_hotspots(geometry_json: str) -> pd.DataFrame:
    """Every hotspot in the area (all sensors, all dates)."""
    geometry = json.loads(geometry_json)
    df = load_hotspots(HOTSPOTS_PATH)
    inside = df[area_contains(geometry, df["longitude"].to_numpy(), df["latitude"].to_numpy())]
    year = (inside["ym"] - 1) // 12  # ym = year * 12 + month, month 1-12
    return inside.assign(year=year, month=inside["ym"] - 12 * year)


@st.cache_data
def area_coverage(geometry_json: str, geo_path: Path) -> tuple[float, list[str]]:
    """Share of the area inside the 49 districts, and the districts it overlaps (largest first).

    Estimated on a grid of up to ~4,000 points over the area, which is plenty for a share.
    """
    geometry = json.loads(geometry_json)
    points = np.array([p for rings in polygons(geometry) for p in rings[0]], dtype=float)
    (west, south), (east, north) = points[:, :2].min(axis=0), points[:, :2].max(axis=0)
    n = 64
    lon, lat = np.meshgrid(np.linspace(west, east, n), np.linspace(south, north, n))
    lon, lat = lon.ravel(), lat.ravel()
    inside = area_contains(geometry, lon, lat)
    lon, lat = lon[inside], lat[inside]
    if not len(lon):
        return 0.0, []
    covered = np.zeros(len(lon), dtype=bool)
    counts = {}
    for feature in load_geojson(geo_path)["features"]:
        hit = area_contains({"type": "MultiPolygon", "coordinates": polygons(feature["geometry"])}, lon, lat)
        hit &= ~covered
        if hit.any():
            state, district = district_key(feature)
            counts[f"{district}, {state}"] = int(hit.sum())
            covered |= hit
    names = [name for name, _ in sorted(counts.items(), key=lambda item: -item[1])]
    return float(covered.mean()), names


def sensor_images(df: pd.DataFrame) -> pd.DataFrame:
    """Daily images per sensor and month (the most any district had)."""
    rows = df[df["sensor"].isin(AREA_SENSORS)]
    return rows.groupby(["sensor", "year", "month"], as_index=False)["n_images"].max()


def area_series(points: pd.DataFrame, images: pd.DataFrame, sensor: str,
                start: tuple[int, int], end: tuple[int, int]) -> pd.DataFrame:
    """Monthly hotspot pixel-days of one sensor in the area, in the same shape as a district series.

    'activity' holds the count, so the calendar, cards and trend code can be reused; it is
    NaN for months without images (blank), 0 for months with images and no detections.
    """
    months = images[(images["sensor"] == sensor) & in_dates(images, start, end)].copy()
    counts = (points[points["sensor"] == sensor].groupby(["year", "month"]).size().rename("count"))
    months = months.merge(counts.reset_index(), on=["year", "month"], how="left")
    months["count"] = months["count"].fillna(0)
    months["activity"] = months["count"].where(months["n_images"] > 0)
    return months.assign(sensor=sensor)[["year", "month", "activity", "n_images", "sensor"]]


def area_map(geo: dict, geometry: dict | None) -> folium.Map:
    """District outlines, the area in use, and drawing tools (box and polygon only)."""
    m = folium.Map(tiles="OpenStreetMap", scrollWheelZoom=False)
    outlines = folium.GeoJson(
        {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"label": f"{district_key(f)[1]}, {district_key(f)[0]}"},
             "geometry": {"type": "MultiPolygon", "coordinates": polygons(f["geometry"])}}
            for f in geo["features"]]},
        style_function=lambda _: {"fillOpacity": 0.03, "color": "#666666", "weight": 0.6},
        tooltip=folium.GeoJsonTooltip(fields=["label"], labels=False),
    ).add_to(m)
    if geometry is not None:
        folium.GeoJson(geometry, style_function=lambda _: {
            "color": "#D55E00", "weight": 3, "fillOpacity": 0.12, "fillColor": "#D55E00"}).add_to(m)
    folium.plugins.Draw(
        draw_options={"polyline": False, "circle": False, "marker": False, "circlemarker": False,
                      "rectangle": {"shapeOptions": {"color": "#D55E00"}},
                      "polygon": {"allowIntersection": False, "shapeOptions": {"color": "#D55E00"}}},
        edit_options={"edit": False, "remove": False},
    ).add_to(m)
    fit_districts(m, outlines)
    return m


def render_area_input(geo: dict) -> dict | None:
    """Map to draw on, a box typed in degrees, and a clear button; returns the area in use."""
    geometry = st.session_state.get(AREA_KEY)
    st.markdown("**Draw the area of interest**")
    st.caption(AREA_HELP)
    out = st_folium(area_map(geo, geometry), height=460, use_container_width=True,
                    returned_objects=["all_drawings"], key=f"area-map-{st.session_state.get('area_map_n', 0)}")
    drawings = (out or {}).get("all_drawings") or []
    if drawings:
        drawn = drawings[-1].get("geometry")
        if valid_area(drawn) and drawn != geometry:
            st.session_state[AREA_KEY] = geometry = drawn
    with st.expander("Or enter a box in latitude / longitude"):
        cols = st.columns(4)
        south = cols[0].number_input("South", 28.0, 33.5, 30.70, 0.05, format="%.3f", key="box_s")
        north = cols[1].number_input("North", 28.0, 33.5, 31.05, 0.05, format="%.3f", key="box_n")
        west = cols[2].number_input("West", 73.5, 81.5, 75.60, 0.05, format="%.3f", key="box_w")
        east = cols[3].number_input("East", 73.5, 81.5, 76.20, 0.05, format="%.3f", key="box_e")
        if st.button("Use this box", key="box_use"):
            if south < north and west < east:
                st.session_state[AREA_KEY] = geometry = box_geometry(south, west, north, east)
            else:
                st.warning("South must be below north and west left of east.")
    if geometry is not None and st.button("Clear the area", key="area_clear"):
        st.session_state.pop(AREA_KEY, None)
        st.session_state["area_map_n"] = st.session_state.get("area_map_n", 0) + 1
        st.rerun()
    return geometry


def render_area_metrics(series: pd.DataFrame, grid: pd.DataFrame, sensor: str) -> None:
    """Latest complete month vs median, its rank, and the peak months, for the area's counts."""
    latest = latest_observed(series)
    cols = st.columns(3)
    if latest is None:
        cols[0].info("No observed months in these dates.")
        return
    month, value = int(latest["month"]), latest["activity"]
    history = month_history(series, month)
    ratio, pct = anomaly_ratio(value, history), percentile_rank(value, history)
    label = f"{MONTH_NAMES[month - 1]} {int(latest['year'])}"
    note = (f"{SENSOR_LABELS[sensor]}: {value:,.0f} hotspot pixel-days in {label}, compared with every "
            f"observed {MONTH_NAMES[month - 1]} in the selected dates ({len(history)} year(s)); "
            f"needs at least {MIN_YEARS}.")
    cols[0].metric(f"{label} vs {MONTH_NAMES[month - 1]} median", ratio_text(ratio), help=note)
    cols[1].metric(f"{label} percentile rank", "—" if pct is None else ordinal(pct), help=note)
    cols[2].metric("Peak months (median count)", " · ".join(peak_months(grid)) or "—")


def area_yearly_figure(points: pd.DataFrame, images: pd.DataFrame, start, end, title: str) -> go.Figure:
    """Hotspot pixel-days per year, one bar per sensor side by side (never stacked or summed)."""
    fig = go.Figure()
    for sensor in AREA_SENSORS:
        rows = area_series(points, images, sensor, start, end)
        by_year = rows.groupby("year")["activity"].sum(min_count=1)
        months = rows.groupby("year")["activity"].count()
        fig.add_trace(go.Bar(
            x=[str(y) for y in by_year.index], y=by_year, name=SENSOR_LABELS[sensor],
            marker=dict(color=SENSOR_LINES[sensor]["color"],
                        pattern=dict(shape={"viirs_snpp": "", "aqua": ".", "terra": "/"}[sensor])),
            customdata=months, hovertemplate=SENSOR_LABELS[sensor]
            + " · %{x} · %{y:,.0f} hotspot pixel-days (%{customdata} months observed)<extra></extra>",
        ))
    fig.update_layout(barmode="group", title=title, height=420, margin=dict(l=10, r=10, t=60, b=10),
                      xaxis=dict(type="category", title=None), yaxis=dict(title="Hotspot pixel-days"),
                      legend=dict(orientation="h", y=-0.15))
    return fig


def render_area_trend(series: pd.DataFrame, sensor: str, title: str) -> None:
    seasons = list(trends.SEASONS)
    season = st.radio("Season", seasons, index=default_season(series), horizontal=True, key="area_season")
    values = trends.season_values(series, trends.SEASONS[season])
    if values.empty:
        st.info("No complete season in the selected dates.")
        return
    result = trends.trend(values["year"], values["value"])
    show_chart(trend_figure(values, result, f"{title} · {season}", scale=1,
                            y_title="Season mean hotspot pixel-days per month", suffix=""),
               f"{title} trend")
    if result is None:
        st.info(f"A trend test needs at least {trends.MIN_TREND_YEARS} complete seasons; "
                f"the selected dates have {len(values)}.")
    else:
        trend_cards(result, unit="hotspot pixel-days per month")
        if result["last_year"] >= 2023:
            st.warning(TREND_DRIFT_NOTE.format(where="the Satellite choice above"))
        if sensor != ANCHOR_SENSOR:
            st.caption("A trend in one MODIS sensor's raw counts also carries its orbit drift after "
                       "2022; Suomi-NPP VIIRS is the steadier choice for trends.")
    explain("One point per season, for the satellite chosen above; Mann-Kendall and Sen's slope.",
            AREA_TREND_NOTE)


def render_area_page(df: pd.DataFrame, geo_path: Path, start: tuple[int, int], end: tuple[int, int]) -> None:
    """Everything for a drawn (or typed) area: input, coverage, cards, views and download."""
    geo = load_geojson(geo_path)
    if not HOTSPOTS_PATH.exists():
        st.info("Drawing an area needs the hotspot list (data/hotspots.csv.gz), which is not in "
                "this build. Pick a district instead.")
        return
    geometry = render_area_input(geo)
    if geometry is None:
        st.info("Draw a box or polygon on the map to see its burning calendar.")
        return
    geometry_json = json.dumps(geometry, sort_keys=True)
    share, districts = area_coverage(geometry_json, geo_path)
    size = area_km2(geometry)
    if share == 0:
        st.warning("That area is outside the 49 districts FireLens covers (Punjab, Haryana and "
                   "Uttarakhand), so there is no data for it. Draw inside the outlined districts.")
        return
    shown = ", ".join(districts[:6]) + (f" and {len(districts) - 6} more" if len(districts) > 6 else "")
    st.markdown(f"**Your area:** about {size:,.0f} km², overlapping {shown}.")
    if share < 0.95:
        st.warning(f"Only {share:.0%} of the area lies inside the 49 districts covered; hotspots in "
                   "the rest are not in the data, so the counts below are a lower bound.")

    sensor = st.radio("Satellite", AREA_SENSORS, format_func=SENSOR_LABELS.get, horizontal=True,
                      key="area_sensor")
    points = area_hotspots(geometry_json)
    images = sensor_images(df)
    series = area_series(points, images, sensor, start, end)
    years = list(range(start[0], end[0] + 1))
    grid = calendar_grid(series, years)
    span = month_label(*start) if start == end else f"{month_label(*start)}–{month_label(*end)}"
    title = f"Drawn area ({size:,.0f} km²) · {SENSOR_LABELS[sensor]} · {span}"

    def selected(year: int, month: int) -> bool:
        return start <= (year, month) <= end

    render_area_metrics(series, grid, sensor)
    calendar_tab, yearly_tab, anomaly_tab, trend_tab = st.tabs(["Calendar", "Yearly", "Anomaly", "Trend"])
    with calendar_tab:
        def hover(y: int, m: int) -> str:
            if not selected(y, m):
                return OUTSIDE_DATES
            value = grid.loc[y, m]
            return "no images" if np.isnan(value) else f"{value:,.0f} hotspot pixel-days"
        fig = heatmap_figure(grid, title, hover, colorscale="Cividis", zmin=0,
                             colorbar=dict(title=dict(text="Hotspot<br>pixel-days")))
        show_chart(fig, f"{title} calendar")
    with yearly_tab:
        show_chart(area_yearly_figure(points, images, start, end, f"Drawn area · {span}"), "drawn area yearly")
        st.caption("All three satellites side by side. They see differently (overpass time, pixel "
                   "size), so compare the shape of each series, not the heights across satellites.")
    with anomaly_tab:
        anomaly = anomaly_grid(grid)
        limit = float(np.nanmax(np.abs(anomaly.to_numpy()))) if anomaly.notna().any().any() else 1.0

        def anomaly_text(y: int, m: int) -> str:
            if not selected(y, m):
                return OUTSIDE_DATES
            value = anomaly.loc[y, m]
            return "no data" if np.isnan(value) else f"{value:+,.0f} vs median"
        fig = heatmap_figure(anomaly, title, anomaly_text, colorscale="PuOr_r", zmin=-limit, zmax=limit,
                             zmid=0, colorbar=dict(title=dict(text="Difference<br>from median")))
        show_chart(mark_gaps(fig, anomaly, selected), f"{title} anomaly")
        st.caption("Each month's count minus the median count of the same calendar month across the "
                   f"selected dates. Orange is above the median, purple below; × means no data or fewer "
                   f"than {MIN_YEARS} years to compare.")
    with trend_tab:
        render_area_trend(series, sensor, title)
    explain("Hotspot counts per satellite inside your area, not harmonized.", AREA_NOTE)

    in_dates_points = points[points["ym"].between(start[0] * 12 + start[1], end[0] * 12 + end[1])]
    file_span = f"{start[0]}-{start[1]:02d}_to_{end[0]}-{end[1]:02d}"
    st.download_button(
        f"Download the {len(in_dates_points):,} hotspots in this area (CSV)",
        data=in_dates_points.drop(columns=["ym", "year", "month"]).to_csv(index=False).encode("utf-8"),
        file_name=f"firelens_area_{file_span}_hotspots.csv", mime="text/csv",
        help="Every hotspot detection inside the area in the selected dates, all three satellites "
             "(sensor column), as recorded; don't add sensors together.",
    )
    st.download_button(
        "Download the area (GeoJSON)", data=json.dumps({"type": "Feature", "properties": {},
                                                         "geometry": geometry}).encode("utf-8"),
        file_name="firelens_area.geojson", mime="application/geo+json",
        help="The shape you drew, to reuse in GIS software or to reproduce this view.",
    )


def main() -> None:
    st.set_page_config(page_title="FireLens", layout="wide")
    refresh_cache_on_new_data()
    st.title("FireLens")
    st.caption("Harmonized burning-activity calendar for Northern India, 2016–2026, "
               "from MODIS and VIIRS satellite hotspot detections.")
    with st.expander("New here? How to use FireLens in 4 steps"):
        st.markdown(GUIDE_TEXT)

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
    elif "state" not in st.session_state and DEFAULT_PLACE in set(zip(df["state"], df["district"])):
        st.session_state["state"], st.session_state["district"] = DEFAULT_PLACE

    with st.sidebar:
        st.header("Location")
        mode = st.radio("Look at", [MODE_DISTRICT, MODE_AREA], horizontal=True, key="area_mode",
                        help="A district gives the harmonized record; a drawn area gives hotspot "
                             "counts per satellite inside any shape you draw.")
    if mode == MODE_AREA:
        with st.sidebar:
            start, end = date_range()
        render_area_page(df, geo_path, start, end)
        render_about()
        return

    with st.sidebar:
        render_search(load_geojson(geo_path), df)
        state = st.selectbox("State", sorted(df["state"].unique()), key="state")
        district = st.selectbox(
            "District", sorted(df.loc[df["state"] == state, "district"].unique()),
            key="district",
        )
        st.header("Data")
        available = [s for s in SERIES_LABELS if s in set(df["sensor"])]  # harmonized first
        sensor = st.selectbox("Series", available, format_func=SERIES_LABELS.get, key="sensor")
        start, end = date_range()
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
    context = region_context(df, sensor, latest, start, end, state, district)
    if context:
        st.info(context)
    # The map comes before the tabs: it is the overview a researcher starts from. Its trend
    # colouring follows the Trend tab's season (session state; the default until it is touched).
    seasons = list(trends.SEASONS)
    season = st.session_state.get(f"trend_season_{state}", seasons[default_season(series)])
    st.subheader("Map: all 49 districts")
    render_map(geo_path, df, sensor, state, district, start, end, latest, season)
    st.subheader(f"{district}, {state}")
    calendar_tab, yearly_tab, anomaly_tab, trend_tab, types_tab, sensors_tab = st.tabs(
        ["Calendar", "Yearly", "Anomaly", "Trend", "Fire type", "Sensor comparison"])
    with calendar_tab:
        render_calendar(series, grid, years, place_sensor, sensor == HARMONIZED, selected)
    with yearly_tab:
        show_chart(yearly_chart(yearly_summary(series, years), place_sensor), f"{place_sensor} yearly")
        explain("Mean monthly activity per year. Hatched bars = incomplete years; don't compare them.",
                YEARLY_NOTE + (" " + RANGE_NOTE if has_range(series) else ""))
    with anomaly_tab:
        show_chart(anomaly_heatmap(anomaly_grid(grid), place_sensor, selected), f"{place_sensor} anomaly")
        explain("Each month against its usual value: orange above, purple below.", ANOMALY_NOTE)
    with trend_tab:
        season = render_trend(df, series, state, sensor, place_sensor, start, end, file_span)
    with types_tab:
        render_fire_types(state, district, sensor, start, end, place)
    with sensors_tab:
        render_comparison(district_rows, scaled, place)
    render_downloads(df[dated], scaled, state, district, file_span, start, end)
    render_about()


main()
