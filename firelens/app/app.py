"""FireLens: harmonized burning-activity calendar for Northern India, 2016-2026.

Run from firelens/:  streamlit run app/app.py
Data format: docs/data-contract.md.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_PATH = DATA_DIR / "district_monthly.csv"
MOCK_PATH = DATA_DIR / "mock_district_monthly.csv"  # from app/make_mock.py

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


def main() -> None:
    st.set_page_config(page_title="FireLens", layout="wide")
    st.title("FireLens")
    st.caption("Burning-activity calendar for Northern India, 2016–2026, "
               "from MODIS and VIIRS satellite hotspot detections.")

    if DATA_PATH.exists():
        df = load_data(DATA_PATH)
    elif MOCK_PATH.exists():
        st.warning("**MOCK data**: the real data file is missing, so these numbers are "
                   "invented for development. Do not use them.")
        df = load_data(MOCK_PATH)
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

    st.plotly_chart(
        calendar_heatmap(grid, f"{district}, {state} · {SENSOR_LABELS[sensor]}"),
        width="stretch",
    )
    st.caption(
        "Activity = fire pixel-days ÷ clearly observed pixel-days: the share of clearly "
        "seen land with a hotspot detection. Months are UTC calendar months. "
        "Blank cells mean no clear observations (no images, or fully clouded), not zero."
    )


main()
