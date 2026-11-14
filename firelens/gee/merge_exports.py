"""Step 5: merge the Drive exports into data/district_monthly.csv and run the 8 R1 checks.

    python gee/merge_exports.py [folder]     # default: data/raw

Put the downloaded fl_*.csv files (and fl_districts.geojson) anywhere under that folder;
subfolders are searched (one per sensor is fine). A file name found twice is read once.
Exits 1 if any check fails.
"""
import shutil
import sys
from pathlib import Path

import pandas as pd

DATA = Path(__file__).resolve().parent.parent / "data"
SENSOR_NAMES = {"terra", "aqua", "viirs_snpp"}
N_MONTHS = 132  # Jan 2016 - Dec 2026
CONTRACT = ["state", "district", "sensor", "year", "month",
            "fire_pixel_days", "clear_pixel_days", "mean_frp_mw", "n_images"]


def to_contract(df):
    """Raw GEE export columns -> data-contract columns (shared with the Punjab test)."""
    df = df.rename(columns={"ADM1_NAME": "state", "ADM2_NAME": "district",
                            "fire": "fire_pixel_days", "clear": "clear_pixel_days"})
    df["mean_frp_mw"] = (df["frp"] / df["fire_pixel_days"]).where(df["fire_pixel_days"] > 0)
    return df[CONTRACT].sort_values(["state", "district", "sensor", "year", "month"])


def checks(df):
    results = []

    def check(name, ok, detail=""):
        print("PASS" if ok else "FAIL", name, detail)
        results.append(bool(ok))

    n_d = len(df[["state", "district"]].drop_duplicates())
    expected = n_d * len(SENSOR_NAMES) * N_MONTHS
    check("1 rows = districts x 3 x 132", len(df) == expected, f"{len(df)} vs {expected} ({n_d} districts)")

    per = df[["sensor", "state", "district"]].drop_duplicates().groupby("sensor").size()
    check("2 three sensors, every district in each", set(df.sensor) == SENSOR_NAMES and (per == n_d).all(),
          per.to_dict())

    blanks = df[[c for c in CONTRACT if c != "mean_frp_mw"]].isna().sum()
    check("3 no blanks", blanks.sum() == 0, blanks[blanks > 0].to_dict())

    bad = int((df.fire_pixel_days > df.clear_pixel_days + 1e-6).sum())
    check("4 fire <= clear", bad == 0, f"{bad} bad rows")

    has = df.n_images > 0
    monsoon = df.month.between(7, 9)
    a, b = df[has & monsoon].clear_pixel_days.mean(), df[has & ~monsoon].clear_pixel_days.mean()
    check("5 clear lower in Jul-Sep", a < b, f"{a:.0f} vs {b:.0f}")

    fire = df.fire_pixel_days > 0
    ok6 = (df.mean_frp_mw.dropna() >= 0).all() and df.mean_frp_mw.isna().eq(~fire).all()
    check("6 mean_frp_mw >= 0, empty only where no fire", ok6)

    lu = df[(df.district == "Ludhiana") & (df.sensor == "viirs_snpp") & (df.n_images > 0)]
    peak = lu[lu.month.isin([10, 11])].fire_pixel_days.mean()
    rest = lu[~lu.month.isin([10, 11])].fire_pixel_days.mean()
    check("7 Ludhiana VIIRS Oct-Nov high", len(lu) > 0 and peak > 3 * rest, f"{peak:.1f} vs {rest:.1f} other months")

    latest = (df[has].year * 100 + df[has].month).groupby(df[has].sensor).max()
    check("8 latest month with data (post in team chat)", set(latest.index) == SENSOR_NAMES, latest.to_dict())

    return all(results)


if __name__ == "__main__":
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DATA / "raw"
    files = sorted({f.name: f for f in src.rglob("fl_*.csv")}.values())
    if not files:
        sys.exit(f"no fl_*.csv files in {src}")
    df = to_contract(pd.concat(map(pd.read_csv, files), ignore_index=True))
    df.to_csv(DATA / "district_monthly.csv", index=False)
    print(f"{len(files)} files -> {DATA / 'district_monthly.csv'}")

    geo = next(src.rglob("fl_districts.geojson"), None)
    if geo:
        shutil.copy(geo, DATA / "districts.geojson")
        print(f"copied {geo.name} -> data/districts.geojson")

    sys.exit(0 if checks(df) else 1)
