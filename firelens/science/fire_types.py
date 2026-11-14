#!/usr/bin/env python3
"""FireLens — what is burning: fire type by land cover, and persistent static sources.

The harmonized calendar says how much burning each district saw. This script adds the
context a fire scientist asks for next: was it cropland or forest, and how much of the
signal is not vegetation fire at all (refinery flares, furnaces and other fixed heat
sources that a thermal sensor also reports as hotspots).

Input (not committed, see gee/export_hotspots_context.js and gee/README.md):
    data/raw/firepulse_india_all.csv, or a folder holding the yearly FirePulse_India_*.csv
    exports — one row per hotspot pixel per day per satellite,
    from the same three products as the calendar (MOD14A1, MYD14A1, VNP14A1, native
    ~1 km grid), each with the MODIS land-cover class of that year (MCD12Q1 LC_Type1,
    IGBP) and the VIIRS night-light radiance of that month.

Rules (docs/decisions.md, docs/data-contract.md §8-9):
* Same fire rule as the calendar: nominal or high confidence only (FireMask >= 8).
* Counts are hotspot pixel-days per sensor. Sensors are never added together.
* The hotspot export covers two rectangles, not whole states. A district is reported
  only when at least 95 % of its area lies inside them; the others are left out, not
  estimated.
* A static source is a 1 km pixel with hotspots in at least 8 of the 12 calendar months
  and in at least 12 different months of the record (all sensors pooled, used only to
  locate the pixel). Crop and
  forest burning is seasonal; a pixel that is hot in winter, monsoon and summer alike is
  a fixed heat source. The rule is deliberately conservative and misses seasonal
  sources such as brick kilns.
* Months outside the hotspot file, or with no images in district_monthly.csv, get no
  row (blank, never zero).

Outputs:
    data/district_fire_types.csv   district x sensor x month counts by class
    data/static_sources.csv        the static pixels, for inspection
    science/fire_types.md          coverage, checks and headline numbers

Usage:
    python science/fire_types.py
    python science/fire_types.py --input data/raw/firepulse      # a folder of yearly CSVs
    python science/fire_types.py --input data/raw/firepulse_india_all.csv
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from matplotlib.path import Path as MplPath

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = BASE_DIR / "data" / "raw" / "firepulse_india_all.csv"
GEO_PATH = BASE_DIR / "data" / "districts.geojson"
MONTHLY_PATH = BASE_DIR / "data" / "district_monthly.csv"
OUT_TYPES = BASE_DIR / "data" / "district_fire_types.csv"
OUT_STATIC = BASE_DIR / "data" / "static_sources.csv"
OUT_REPORT = BASE_DIR / "science" / "fire_types.md"

# Rectangles the hotspot export sampled: [west, south, east, north], as in the GEE script.
ZONES = ((74.5, 29.5, 76.8, 31.8), (78.0, 29.0, 80.5, 30.8))
MIN_AREA_COVERED = 0.95
STATIC_MIN_CALENDAR_MONTHS = 8
STATIC_MIN_MONTHS = 12  # ...and in at least this many different months of the record
FIRST_DATE, LAST_DATE = "2016-01-01", "2026-12-31"

SENSOR_OF = {"Terra": "terra", "Aqua": "aqua", "S-NPP": "viirs_snpp"}
SENSORS = ("terra", "aqua", "viirs_snpp")
# MCD12Q1 LC_Type1 (IGBP) -> fire-type class.
CLASS_OF = {
    **{code: "forest" for code in (1, 2, 3, 4, 5)},           # the five IGBP forest classes
    **{code: "woodland_grass" for code in (6, 7, 8, 9, 10)},  # shrublands, savannas, grassland
    12: "cropland", 14: "cropland",                           # croplands, cropland mosaic
}
CLASSES = ("cropland", "forest", "woodland_grass", "other")
COUNT_COLUMNS = ["n_hotspots", "n_cropland", "n_forest", "n_woodland_grass", "n_other", "n_static"]
KEYS = ["state", "district", "sensor", "year", "month"]


# --------------------------------------------------------------------------------------
# Geometry (no GIS dependency: ray casting via matplotlib, clipping by hand)
# --------------------------------------------------------------------------------------


def polygons(geometry: dict) -> list:
    """Polygon coordinate lists from any GeoJSON geometry."""
    kind = geometry["type"]
    if kind == "Polygon":
        return [geometry["coordinates"]]
    if kind == "MultiPolygon":
        return list(geometry["coordinates"])
    if kind == "GeometryCollection":
        return [p for part in geometry["geometries"] for p in polygons(part)]
    return []


def ring_area(ring) -> float:
    """Planar (shoelace) area in square degrees; only ratios of areas are used."""
    if len(ring) < 3:
        return 0.0
    xy = np.asarray(ring, dtype=float)[:, :2]
    x, y = xy[:, 0], xy[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def clip_ring(ring, box) -> list:
    """Sutherland-Hodgman clip of a ring to a [west, south, east, north] rectangle."""
    west, south, east, north = box
    points = [tuple(p[:2]) for p in ring]
    edges = (
        (lambda p: p[0] >= west, lambda a, b: (west, a[1] + (west - a[0]) / (b[0] - a[0]) * (b[1] - a[1]))),
        (lambda p: p[0] <= east, lambda a, b: (east, a[1] + (east - a[0]) / (b[0] - a[0]) * (b[1] - a[1]))),
        (lambda p: p[1] >= south, lambda a, b: (a[0] + (south - a[1]) / (b[1] - a[1]) * (b[0] - a[0]), south)),
        (lambda p: p[1] <= north, lambda a, b: (a[0] + (north - a[1]) / (b[1] - a[1]) * (b[0] - a[0]), north)),
    )
    for inside, cross in edges:
        clipped = []
        for i, b in enumerate(points):
            a = points[i - 1]
            if inside(b):
                if not inside(a):
                    clipped.append(cross(a, b))
                clipped.append(b)
            elif inside(a):
                clipped.append(cross(a, b))
        points = clipped
        if not points:
            return []
    return points


def area_covered(geometry: dict, zones=ZONES) -> float:
    """Share of a district's area that lies inside the sampled rectangles."""
    total = inside = 0.0
    for rings in polygons(geometry):
        total += ring_area(rings[0]) - sum(ring_area(h) for h in rings[1:])
        for zone in zones:
            inside += ring_area(clip_ring(rings[0], zone))
            inside -= sum(ring_area(clip_ring(h, zone)) for h in rings[1:])
    return inside / total if total > 0 else 0.0


def assign_districts(lon: np.ndarray, lat: np.ndarray, geo: dict) -> tuple[np.ndarray, np.ndarray]:
    """State and district of each point (empty string when outside every district)."""
    points = np.column_stack([lon, lat])
    state = np.full(len(points), "", dtype=object)
    district = np.full(len(points), "", dtype=object)
    for feature in geo["features"]:
        hit = np.zeros(len(points), dtype=bool)
        for rings in polygons(feature["geometry"]):
            outer = np.asarray(rings[0], dtype=float)[:, :2]
            box = ((points[:, 0] >= outer[:, 0].min()) & (points[:, 0] <= outer[:, 0].max())
                   & (points[:, 1] >= outer[:, 1].min()) & (points[:, 1] <= outer[:, 1].max()))
            index = np.flatnonzero(box)
            if not len(index):
                continue
            inside = MplPath(outer).contains_points(points[index])
            for hole in rings[1:]:
                inside &= ~MplPath(np.asarray(hole, dtype=float)[:, :2]).contains_points(points[index])
            hit[index[inside]] = True
        new = hit & (district == "")
        state[new] = feature["properties"]["state"].strip()
        district[new] = feature["properties"]["district"].strip()
    return state, district


# --------------------------------------------------------------------------------------
# Pipeline
# --------------------------------------------------------------------------------------


def load_hotspots(path: Path) -> pd.DataFrame:
    """Hotspot pixel-days of the three calendar sensors, FireMask >= 8, 2016 onwards."""
    columns = ["satellite", "acq_date", "latitude", "longitude", "confidence", "daynight",
               "land_cover_code", "nightlight_rad"]
    files = sorted(path.glob("*.csv")) if path.is_dir() else [path] if path.is_file() else []
    if not files:
        raise FileNotFoundError(f"{path} not found. See gee/README.md (fire-type context export).")
    df = pd.concat((pd.read_csv(f, usecols=columns, dtype={"acq_date": str}) for f in files),
                   ignore_index=True)
    keep = (df["satellite"].isin(list(SENSOR_OF)) & df["confidence"].isin(["nominal", "high"])
            & df["acq_date"].between(FIRST_DATE, LAST_DATE))
    df = df[keep].copy()
    df["sensor"] = df["satellite"].map(SENSOR_OF)
    df["year"] = df["acq_date"].str[:4].astype(int)
    df["month"] = df["acq_date"].str[5:7].astype(int)
    # Pixel identity: the centre of the 1 km grid cell, as exported.
    df["lat"] = df["latitude"].round(4)
    df["lon"] = df["longitude"].round(4)
    df["fire_class"] = df["land_cover_code"].map(CLASS_OF).fillna("other")
    return df


def locate(df: pd.DataFrame, geo: dict) -> pd.DataFrame:
    """Add state and district; drop hotspots outside every district."""
    cells = df[["lat", "lon"]].drop_duplicates()
    state, district = assign_districts(cells["lon"].to_numpy(), cells["lat"].to_numpy(), geo)
    cells = cells.assign(state=state, district=district)
    df = df.merge(cells, on=["lat", "lon"], how="left")
    return df[df["district"] != ""].copy()


def find_static(df: pd.DataFrame) -> pd.DataFrame:
    """Per-pixel statistics, with `static` set by the two STATIC_MIN_* thresholds."""
    df = df.assign(ym=df["year"] * 12 + df["month"], night=df["daynight"] == "N",
                   lit=df["nightlight_rad"].where(df["nightlight_rad"] > -9000))
    cells = df.groupby(["state", "district", "lat", "lon"]).agg(
        n_detections=("month", "size"), n_months=("ym", "nunique"),
        n_calendar_months=("month", "nunique"), night_share=("night", "mean"),
        median_nightlight=("lit", "median"),
        land_cover_code=("land_cover_code", lambda s: int(s.mode().iloc[0])),
    ).reset_index()
    cells["static"] = ((cells["n_calendar_months"] >= STATIC_MIN_CALENDAR_MONTHS)
                       & (cells["n_months"] >= STATIC_MIN_MONTHS))
    return cells


def aggregate(df: pd.DataFrame, covered: pd.DataFrame, monthly: pd.DataFrame) -> pd.DataFrame:
    """Rectangular district x sensor x month table for the covered districts."""
    df = df.merge(covered[["state", "district"]], on=["state", "district"])
    df["bucket"] = np.where(df["static"], "static", df["fire_class"])
    counts = (df.groupby(KEYS + ["bucket"]).size().unstack("bucket", fill_value=0)
              .reindex(columns=[*CLASSES, "static"], fill_value=0))
    counts.columns = ["n_cropland", "n_forest", "n_woodland_grass", "n_other", "n_static"]
    counts["n_hotspots"] = counts.sum(axis=1)

    last = int(df["year"].max() * 12 + df.loc[df["year"] == df["year"].max(), "month"].max())
    grid = monthly[KEYS + ["n_images"]].merge(covered[["state", "district", "area_covered"]],
                                               on=["state", "district"])
    grid = grid[(grid["n_images"] > 0) & (grid["year"] * 12 + grid["month"] <= last)]
    out = grid.merge(counts.reset_index(), on=KEYS, how="left")
    out[COUNT_COLUMNS] = out[COUNT_COLUMNS].fillna(0).astype(int)
    out["area_covered"] = out["area_covered"].round(3)
    return out[KEYS + COUNT_COLUMNS + ["area_covered"]].sort_values(KEYS, ignore_index=True)


def check_against_calendar(types: pd.DataFrame, monthly: pd.DataFrame) -> pd.DataFrame:
    """Per sensor: do the hotspot counts match the calendar's fire_pixel_days?"""
    both = types.merge(monthly[KEYS + ["fire_pixel_days"]], on=KEYS)
    rows = []
    for sensor, g in both.groupby("sensor"):
        rows.append({"sensor": sensor, "n": len(g),
                     "ratio": g["n_hotspots"].sum() / g["fire_pixel_days"].sum(),
                     "r": float(np.corrcoef(g["n_hotspots"], g["fire_pixel_days"])[0, 1])})
    return pd.DataFrame(rows)


def _md_table(headers: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def write_report(path: Path, coverage: pd.DataFrame, types: pd.DataFrame, cells: pd.DataFrame,
                 check: pd.DataFrame, n_raw: int) -> None:
    covered = coverage[coverage["covered"]]
    anchor = types[types["sensor"] == "viirs_snpp"]
    share_rows = []
    for state, g in anchor.groupby("state"):
        total = max(g["n_hotspots"].sum(), 1)
        share_rows.append([state, g["district"].nunique(), f"{g['n_hotspots'].sum():,}"]
                          + [f"{g[c].sum() / total:.1%}" for c in COUNT_COLUMNS[1:]])
    static = cells[cells["static"]].sort_values("n_months", ascending=False)
    other = cells[~cells["static"]]
    peak = anchor["month"].isin([4, 5, 10, 11])
    off_total = max(anchor.loc[~peak, "n_hotspots"].sum(), 1)
    peak_total = max(anchor.loc[peak, "n_hotspots"].sum(), 1)
    worst = (anchor.groupby(["state", "district"])[["n_static", "n_hotspots"]].sum()
             .assign(share=lambda t: t["n_static"] / t["n_hotspots"].clip(lower=1))
             .sort_values("share", ascending=False).head(5))
    static_rows = [[r.state, r.district, f"{r.lat:.4f}", f"{r.lon:.4f}", r.n_detections, r.n_months,
                    r.n_calendar_months, f"{r.night_share:.0%}", f"{r.median_nightlight:.1f}"]
                   for r in static.itertuples()]
    not_covered = coverage[~coverage["covered"]].sort_values(["state", "district"])
    content = f"""# FireLens — fire types and static sources

**Generated:** {date.today().isoformat()} by `science/fire_types.py` · every number below is computed.
**Input:** hotspot pixel-days with land cover and night lights ({n_raw:,} rows kept: three
calendar sensors, FireMask ≥ 8, 2016 onwards) · **Outputs:** `data/district_fire_types.csv`
({len(types):,} rows), `data/static_sources.csv` ({len(static)} pixels)

## 1. Coverage

The hotspot export sampled two rectangles, not whole states. A district is reported only
when at least {MIN_AREA_COVERED:.0%} of its area lies inside them: **{len(covered)} of {len(coverage)} districts**.

Reported: {", ".join(f"{r.district} ({r.state})" for r in covered.sort_values(["state", "district"]).itertuples())}.

Not reported (share of area sampled): {", ".join(f"{r.district} {r.area_covered:.0%}" for r in not_covered.itertuples())}.
Re-running the export over the district boundaries (see `gee/README.md`) fills these in.

## 2. Check against the calendar

The hotspot list and `district_monthly.csv` come from the same products and fire rule, so
their counts must agree for the reported districts. The list counts whole pixels by centre
and drops pixels the product flags as water or coast; the calendar is area-weighted, so
small differences are expected.

{_md_table(["Sensor", "District-months", "Hotspots ÷ fire_pixel_days", "Pearson r"],
           [[r.sensor, f"{r.n:,}", f"{r.ratio:.3f}", f"{r.r:.3f}"] for r in check.itertuples()])}

## 3. What burns (Suomi-NPP VIIRS, reported districts, whole record)

Land cover is MCD12Q1 (IGBP) for the year of the detection: cropland = classes 12 and 14;
forest = 1–5; woodland and grass = 6–10 (shrubland, savanna, grassland; much open
Himalayan pine forest falls here); other = everything else, including built-up. LP DAAC
advises caution with MCD12Q1 v6.1 classes for 2021 onwards, so treat recent small shifts
between classes as uncertain.

{_md_table(["State", "Districts", "Hotspot pixel-days", "Cropland", "Forest", "Woodland & grass", "Other", "Static sources"],
           share_rows)}

## 4. Static sources

A pixel is static when it has hotspots in at least {STATIC_MIN_CALENDAR_MONTHS} of the 12 calendar months
and in at least {STATIC_MIN_MONTHS} different months of the record (all years and sensors pooled). **{len(static)} pixels** qualify, out of {len(cells):,} that ever had a hotspot.
Independent evidence that they are not vegetation fires: their median night-light radiance
is **{static["median_nightlight"].median():.0f}** nW/cm²/sr against **{other["median_nightlight"].median():.1f}** for all other
hotspot pixels, and **{static["night_share"].mean():.0%}** of their detections are at night against
**{other["night_share"].mean():.0%}**.

Static sources are **{anchor.loc[~peak, "n_static"].sum() / off_total:.1%}** of VIIRS hotspot pixel-days outside the two
burning seasons (Apr–May, Oct–Nov) and **{anchor.loc[peak, "n_static"].sum() / peak_total:.2%}** inside them: negligible for the
seasonal peaks, but visible in the quiet-month baseline. Districts with the largest share:
{", ".join(f"{d} {row.share:.1%}" for (_, d), row in worst.iterrows())}.

The calendar (`district_monthly.csv`) still includes these pixels; removing them needs a
re-export and a decision-log entry. The rule is conservative: seasonal fixed sources
(brick kilns) are not caught.

{_md_table(["State", "District", "Lat", "Lon", "Detections", "Months", "Calendar months", "At night", "Night light"],
           static_rows)}
"""
    path.write_text(content, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--full-coverage", action="store_true",
                        help="the export covered every district (skip the rectangle test)")
    args = parser.parse_args(argv)

    geo = json.loads(GEO_PATH.read_text(encoding="utf-8"))
    monthly = pd.read_csv(MONTHLY_PATH)
    coverage = pd.DataFrame([
        {"state": f["properties"]["state"].strip(), "district": f["properties"]["district"].strip(),
         "area_covered": 1.0 if args.full_coverage else area_covered(f["geometry"])}
        for f in geo["features"]])
    coverage["covered"] = coverage["area_covered"] >= MIN_AREA_COVERED

    df = locate(load_hotspots(args.input), geo)
    cells = find_static(df)
    df = df.merge(cells[["lat", "lon", "static"]], on=["lat", "lon"])
    types = aggregate(df, coverage[coverage["covered"]], monthly)
    check = check_against_calendar(types, monthly)

    print(f"hotspot pixel-days kept: {len(df):,} | districts reported: {int(coverage['covered'].sum())} of {len(coverage)}")
    print(check.round(3).to_string(index=False))
    assert (types[COUNT_COLUMNS[1:]].sum(axis=1) == types["n_hotspots"]).all(), "classes must add up"
    assert not types.duplicated(KEYS).any(), "duplicate keys"
    assert (check["r"] >= 0.95).all() and check["ratio"].between(0.85, 1.15).all(), \
        "hotspot counts do not match the calendar; check the input file"

    static = cells[cells["static"]].drop(columns="static").sort_values(
        ["state", "district", "lat", "lon"], ignore_index=True)
    static = static.rename(columns={"lat": "latitude", "lon": "longitude"})
    static["night_share"] = static["night_share"].round(3)
    static["median_nightlight"] = static["median_nightlight"].round(2)
    types.to_csv(OUT_TYPES, index=False)
    static.to_csv(OUT_STATIC, index=False)
    write_report(OUT_REPORT, coverage, types, cells, check, len(df))
    print(f"wrote {OUT_TYPES.name} ({len(types):,} rows), {OUT_STATIC.name} ({len(static)} pixels), {OUT_REPORT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
