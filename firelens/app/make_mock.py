"""Generate mock data for developing the FireLens app without the real exports.

    python app/make_mock.py        # run from firelens/

Writes, following docs/data-contract.md exactly:
    data/mock_district_monthly.csv   3 states, 6 districts, 3 sensors, Jan 2016 - Dec 2026
    data/mock_districts.geojson      6 rectangle districts with the same (state, district) pairs

Built-in patterns, so every app view has something to show:
    - Punjab: strong Oct-Nov paddy-residue peak, smaller Apr-May wheat peak
    - Haryana: the same calendar, weaker
    - Uttarakhand: Apr-May forest-fire season
    - clear_pixel_days much lower in Jul-Sep (monsoon cloud)
    - VIIRS reads higher than MODIS, so harmonization has something to correct
    - n_images = 0 (no data) for every month after Aug 2026
    - one all-cloud month (Nainital, Terra, Jul 2019: n_images > 0, clear = 0) for blank cells

The output is deterministic (fixed seed). The numbers are invented: never present them as
real detections.
"""

from __future__ import annotations

import calendar
import json
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).resolve().parent.parent / "data"
CSV_OUT = DATA / "mock_district_monthly.csv"
GEOJSON_OUT = DATA / "mock_districts.geojson"

SEED = 2026
YEARS = range(2016, 2027)
LAST_DATA_MONTH = (2026, 8)  # months after this have n_images = 0
SENSORS = ("terra", "aqua", "viirs_snpp")
COLUMNS = [
    "state", "district", "sensor", "year", "month",
    "fire_pixel_days", "clear_pixel_days", "mean_frp_mw", "n_images",
]

# (state, district, centre lat, centre lon, approx land pixels at 1 km).
# Names are real GAUL 2015 L2 spellings; centres are near the real districts.
DISTRICTS = [
    ("Punjab", "Ludhiana", 30.90, 75.85, 3700),
    ("Punjab", "Amritsar", 31.63, 74.87, 2700),
    ("Haryana", "Karnal", 29.69, 76.99, 2500),
    ("Haryana", "Hisar", 29.15, 75.72, 4000),
    ("Uttarakhand", "Nainital", 29.38, 79.46, 4200),
    ("Uttarakhand", "Dehradun", 30.32, 78.03, 3100),
]
HALF_SIZE_DEG = 0.2  # rectangles are 0.4 x 0.4 degrees, none overlap

# Monthly fire rate (share of clear pixel-days that are fire), MODIS scale.
_CROP = {10: 0.020, 11: 0.024, 4: 0.004, 5: 0.006}
_FOREST = {3: 0.0015, 4: 0.0050, 5: 0.0060, 6: 0.0010}
STATE_CALENDAR = {
    "Punjab": (_CROP, 1.0),
    "Haryana": (_CROP, 0.45),
    "Uttarakhand": (_FOREST, 1.0),
}
BACKGROUND_RATE = 0.0003
SENSOR_FACTOR = {"terra": 0.8, "aqua": 1.0, "viirs_snpp": 2.2}

MONSOON_CLEAR = (0.30, 0.50)  # share of land seen clearly per image, Jul-Sep
DRY_CLEAR = (0.80, 0.95)

ALL_CLOUD = ("Uttarakhand", "Nainital", "terra", 2019, 7)


def make_monthly(rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for state, district, _, _, land in DISTRICTS:
        calendar_rates, strength = STATE_CALENDAR[state]
        # Year-to-year swing in burning, shared by all sensors (they see the same fires).
        year_factor = {year: rng.uniform(0.6, 1.4) for year in YEARS}
        for sensor in SENSORS:
            for year in YEARS:
                for month in range(1, 13):
                    if (year, month) > LAST_DATA_MONTH:
                        rows.append([state, district, sensor, year, month, 0.0, 0.0, np.nan, 0])
                        continue

                    n_images = calendar.monthrange(year, month)[1]
                    if (state, district, sensor, year, month) == ALL_CLOUD:
                        rows.append([state, district, sensor, year, month, 0.0, 0.0, np.nan, n_images])
                        continue

                    lo, hi = MONSOON_CLEAR if month in (7, 8, 9) else DRY_CLEAR
                    clear = round(land * n_images * rng.uniform(lo, hi), 1)

                    rate = BACKGROUND_RATE + strength * calendar_rates.get(month, 0.0) * year_factor[year]
                    rate *= SENSOR_FACTOR[sensor]
                    fire = float(min(rng.poisson(clear * rate), clear))

                    frp = round(float(rng.lognormal(np.log(12.0), 0.5)), 2) if fire > 0 else np.nan
                    rows.append([state, district, sensor, year, month, fire, clear, frp, n_images])

    df = pd.DataFrame(rows, columns=COLUMNS)
    df["n_images"] = df["n_images"].astype(int)
    df["year"] = df["year"].astype(int)
    df["month"] = df["month"].astype(int)
    return df.sort_values(["state", "district", "sensor", "year", "month"]).reset_index(drop=True)


def make_geojson() -> dict:
    features = []
    for state, district, lat, lon, _ in DISTRICTS:
        w, e = round(lon - HALF_SIZE_DEG, 4), round(lon + HALF_SIZE_DEG, 4)
        s, n = round(lat - HALF_SIZE_DEG, 4), round(lat + HALF_SIZE_DEG, 4)
        # Exterior ring, counter-clockwise and closed (RFC 7946).
        ring = [[w, s], [e, s], [e, n], [w, n], [w, s]]
        features.append({
            "type": "Feature",
            "properties": {"state": state, "district": district},
            "geometry": {"type": "Polygon", "coordinates": [ring]},
        })
    return {"type": "FeatureCollection", "features": features}


def main() -> None:
    DATA.mkdir(exist_ok=True)
    df = make_monthly(np.random.default_rng(SEED))
    df.to_csv(CSV_OUT, index=False)  # NaN -> empty field, as the contract requires
    GEOJSON_OUT.write_text(json.dumps(make_geojson(), indent=1) + "\n")
    print(f"{len(df):,} rows -> {CSV_OUT}")
    print(f"{len(DISTRICTS)} districts -> {GEOJSON_OUT}")


if __name__ == "__main__":
    main()
