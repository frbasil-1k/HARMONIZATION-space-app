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
GEO_PATH = DATA_DIR / "districts.geojson"
MOCK_PATH = DATA_DIR / "mock_district_monthly.csv"  # from app/make_mock.py
MOCK_GEO_PATH = DATA_DIR / "mock_districts.geojson"

CONTRACT_COLUMNS = ["state", "district", "sensor", "year", "month", "fire_pixel_days",
                    "clear_pixel_days", "mean_frp_mw", "n_images"]
MIN_YEARS = 3  # observed years of a calendar month needed before comparing against them
ACTIVITY_NOTE = (
    "Activity = fire pixel-days ÷ clearly observed pixel-days: the share of clearly "
    "seen land with a hotspot detection. Months are UTC calendar months. "
    "Blank cells mean no clear observations (no images, or fully clouded), not zero."
)
ANOMALY_NOTE = (
    "Each month's activity minus the median of the same calendar month across all observed "
    f"years, in percentage points. Orange is above the median, purple below. A grey × "
    f"means no data, or fewer than {MIN_YEARS} years of that month to compare against."
)
SENSORS_NOTE = (
    "Each satellite sensor's own activity for this district, not yet harmonized. The lines "
    "share the seasonal pattern but differ in level because the sensors see differently "
    "and pass over at different times. Breaks in a line are months with no data."
)
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
DEFAULT_SENSOR = "viirs_snpp"
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
    return df


def calendar_grid(series: pd.DataFrame) -> pd.DataFrame:
    """Year x month table of activity; every year and month present, gaps as NaN."""
    return (
        series.pivot_table(index="year", columns="month", values="activity", aggfunc="first")
        .reindex(index=YEARS, columns=MONTHS)
    )


def heatmap_figure(pct: pd.DataFrame, title: str, describe, **trace) -> go.Figure:
    """Month x year heatmap of pct; gaps are empty cells that say "no data" on hover."""
    hover = [
        [
            f"{MONTH_NAMES[m - 1]} {y} · "
            + ("no data" if np.isnan(pct.loc[y, m]) else describe(pct.loc[y, m]))
            for m in MONTHS
        ]
        for y in YEARS
    ]
    fig = go.Figure(
        go.Heatmap(
            # Plain lists with None for gaps: Plotly draws None as an empty cell.
            z=pct.astype(object).where(pct.notna(), None).to_numpy().tolist(),
            x=MONTH_NAMES,
            y=[str(y) for y in YEARS],
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
        height=520,
        margin=dict(l=10, r=10, t=90, b=10),
        plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def calendar_heatmap(grid: pd.DataFrame, title: str) -> go.Figure:
    return heatmap_figure(
        grid * 100,  # activity as % of clearly seen pixels
        title,
        lambda v: f"activity {v:.3f}%",
        colorscale="Cividis",
        zmin=0,
        colorbar=dict(title=dict(text="Activity<br>(% of clear<br>pixels)"), ticksuffix="%"),
    )


# --- Anomaly view ---------------------------------------------------------------

def anomaly_grid(grid: pd.DataFrame) -> pd.DataFrame:
    """Each month minus that calendar month's median; NaN where too few years."""
    enough = grid.count() >= MIN_YEARS
    return (grid - grid.median(skipna=True)).where(enough, axis="columns")


def anomaly_heatmap(anomaly: pd.DataFrame, title: str) -> go.Figure:
    pct = anomaly * 100  # percentage points of clearly seen pixels
    limit = float(np.nanmax(np.abs(pct.to_numpy()))) if pct.notna().any().any() else 1.0
    fig = heatmap_figure(
        pct,
        title,
        lambda v: f"{v:+.3f} points vs median",
        colorscale="PuOr_r",  # purple = below median, orange = above; colour-blind safe
        zmin=-limit,
        zmax=limit,
        zmid=0,
        colorbar=dict(title=dict(text="Difference<br>from median<br>(% points)")),
    )
    return mark_gaps(fig, pct)


def mark_gaps(fig: go.Figure, pct: pd.DataFrame) -> go.Figure:
    """Put a grey x on no-data cells, where a blank would look like a zero difference."""
    gaps = [(MONTH_NAMES[m - 1], str(y)) for y in YEARS for m in MONTHS if np.isnan(pct.loc[y, m])]
    fig.add_trace(go.Scatter(
        x=[x for x, _ in gaps], y=[y for _, y in gaps], mode="markers", hoverinfo="skip",
        marker=dict(symbol="x-thin", size=9, line=dict(color="#8a8a8a", width=1.5)),
        showlegend=False,
    ))
    return fig


# --- Sensor comparison ----------------------------------------------------------

def sensor_comparison(district_rows: pd.DataFrame, title: str) -> go.Figure:
    """Monthly activity of every sensor on one time axis; gaps break the line."""
    fig = go.Figure()
    for sensor, label in SENSOR_LABELS.items():
        rows = district_rows[district_rows["sensor"] == sensor].sort_values(["year", "month"])
        if rows.empty:
            continue
        dates = pd.to_datetime(rows[["year", "month"]].assign(day=1))
        fig.add_trace(go.Scatter(
            x=dates, y=rows["activity"] * 100, name=label, mode="lines",
            connectgaps=False, line=SENSOR_LINES[sensor],
            hovertemplate=label + " · %{x|%b %Y} · %{y:.3f}%<extra></extra>",
        ))
    fig.update_layout(
        title=title, height=460, margin=dict(l=10, r=10, t=60, b=10),
        yaxis=dict(title="Activity (% of clear pixels)", ticksuffix="%", rangemode="tozero"),
        legend=dict(orientation="h", y=-0.15),
    )
    return fig


# --- Metric cards ---------------------------------------------------------------

def latest_observed(series: pd.DataFrame) -> pd.Series | None:
    """Most recent row with defined activity (skips trailing no-data months)."""
    observed = series.dropna(subset=["activity"]).sort_values(["year", "month"])
    return None if observed.empty else observed.iloc[-1]


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
    days = calendar.monthrange(int(row["year"]), int(row["month"]))[1]
    images = int(row["n_images"])
    return None if images >= days else f"Partial month: {images} of {days} daily images"


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
    note = (f"Compared with every observed {MONTH_NAMES[month - 1]} "
            f"({len(history)} year(s)); needs at least {MIN_YEARS}.")
    partial = dict(delta=partial_note(latest), delta_color="off", delta_arrow="off")
    cols[0].metric(f"{label} vs {MONTH_NAMES[month - 1]} median",
                   "—" if ratio is None else f"{ratio:.2f}×", help=note, **partial)
    cols[1].metric(f"{label} percentile rank",
                   "—" if pct is None else f"{pct:.0f}th", help=note, **partial)
    cols[2].metric("Peak months (median activity)", " · ".join(peak_months(grid)) or "—")


# --- Download -------------------------------------------------------------------

def district_csv(df: pd.DataFrame, state: str, district: str) -> bytes:
    """The district's contract rows (all sensors) as CSV; missing values left empty."""
    rows = df.loc[(df["state"] == state) & (df["district"] == district), CONTRACT_COLUMNS]
    return rows.to_csv(index=False).encode("utf-8")


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
    st.caption("Burning-activity calendar for Northern India, 2016–2026, "
               "from MODIS and VIIRS satellite hotspot detections.")

    if DATA_PATH.exists():
        df, geo_path = load_data(DATA_PATH), GEO_PATH
    elif MOCK_PATH.exists():
        st.warning("**MOCK data**: the real data file is missing, so these numbers are "
                   "invented for development. Do not use them.")
        df, geo_path = load_data(MOCK_PATH), MOCK_GEO_PATH
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
        sensors = [s for s in SENSOR_LABELS if s in set(df["sensor"])]
        sensor = st.selectbox(
            "Sensor",
            sensors,
            index=sensors.index(DEFAULT_SENSOR) if DEFAULT_SENSOR in sensors else 0,
            format_func=SENSOR_LABELS.get,
            key="sensor",
        )

    district_rows = df[(df["state"] == state) & (df["district"] == district)]
    series = district_rows[district_rows["sensor"] == sensor]
    grid = calendar_grid(series)
    place, place_sensor = f"{district}, {state}", f"{district}, {state} · {SENSOR_LABELS[sensor]}"

    render_metrics(series, grid)
    calendar_tab, anomaly_tab, sensors_tab = st.tabs(["Calendar", "Anomaly", "Sensor comparison"])
    with calendar_tab:
        st.plotly_chart(calendar_heatmap(grid, place_sensor), width="stretch")
        st.caption(ACTIVITY_NOTE)
    with anomaly_tab:
        st.plotly_chart(anomaly_heatmap(anomaly_grid(grid), place_sensor), width="stretch")
        st.caption(ANOMALY_NOTE)
    with sensors_tab:
        st.plotly_chart(sensor_comparison(district_rows, place), width="stretch")
        st.caption(SENSORS_NOTE)
    st.download_button(
        "Download CSV",
        data=district_csv(df, state, district),
        file_name=f"{state}_{district}_monthly.csv".replace(" ", "_"),
        mime="text/csv",
        help="All sensors' monthly rows for this district, in the data-contract format.",
    )
    st.subheader(f"{district}, {state}")
    render_map(geo_path, state, district)


main()
