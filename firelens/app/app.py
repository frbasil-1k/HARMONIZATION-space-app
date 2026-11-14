"""FireLens: harmonized burning-activity calendar for Northern India, 2016-2026.

Run from firelens/:  streamlit run app/app.py
Data format: docs/data-contract.md.
"""

from pathlib import Path

import json

import folium
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit_folium import st_folium

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_PATH = DATA_DIR / "test_punjab_2020_viirs.csv"
GEO_PATH = DATA_DIR / "districts.geojson"
MOCK_PATH = DATA_DIR / "mock_district_monthly.csv"  # from app/make_mock.py
MOCK_GEO_PATH = DATA_DIR / "mock_districts.geojson"

CONTRACT_COLUMNS = ["state", "district", "sensor", "year", "month", "fire_pixel_days",
                    "clear_pixel_days", "mean_frp_mw", "n_images"]
MIN_YEARS = 3  # observed years of a calendar month needed before comparing against them
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


def calendar_heatmap(grid: pd.DataFrame, title: str) -> go.Figure:
    pct = grid * 100  # activity as % of clearly seen pixels
    hover = [
        [
            f"{MONTH_NAMES[m - 1]} {y} · "
            + ("no data" if np.isnan(pct.loc[y, m]) else f"activity {pct.loc[y, m]:.3f}%")
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
            colorscale="Cividis",
            zmin=0,
            xgap=2,
            ygap=2,
            colorbar=dict(title=dict(text="Activity<br>(% of clear<br>pixels)"), ticksuffix="%"),
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
    cols[0].metric(f"{label} vs {MONTH_NAMES[month - 1]} median",
                   "—" if ratio is None else f"{ratio:.2f}×", help=note)
    cols[1].metric(f"{label} percentile rank",
                   "—" if pct is None else f"{pct:.0f}th", help=note)
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


def district_feature(geo: dict, state: str, district: str) -> dict | None:
    """Join on the (state, district) pair, never the name alone (contract §2)."""
    for feature in geo["features"]:
        props = feature["properties"]
        if (props["state"].strip(), props["district"].strip()) == (state.strip(), district.strip()):
            return feature
    return None


def district_map(feature: dict) -> folium.Map:
    m = folium.Map(tiles="CartoDB positron")
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
        state = st.selectbox("State", sorted(df["state"].unique()))
        district = st.selectbox(
            "District", sorted(df.loc[df["state"] == state, "district"].unique())
        )
        sensors = [s for s in SENSOR_LABELS if s in set(df["sensor"])]
        sensor = st.selectbox(
            "Sensor",
            sensors,
            index=sensors.index(DEFAULT_SENSOR) if DEFAULT_SENSOR in sensors else 0,
            format_func=SENSOR_LABELS.get,
        )

    series = df[(df["state"] == state) & (df["district"] == district) & (df["sensor"] == sensor)]
    grid = calendar_grid(series)

    render_metrics(series, grid)
    st.plotly_chart(
        calendar_heatmap(grid, f"{district}, {state} · {SENSOR_LABELS[sensor]}"),
        width="stretch",
    )
    st.caption(
        "Activity = fire pixel-days ÷ clearly observed pixel-days: the share of clearly "
        "seen land with a hotspot detection. Months are UTC calendar months. "
        "Blank cells mean no clear observations (no images, or fully clouded), not zero."
    )
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
