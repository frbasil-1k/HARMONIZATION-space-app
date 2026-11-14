"""Merge the hotspot exports (gee/export_hotspots.js) into data/hotspots.csv.gz and check them.

    python gee/merge_hotspots.py [folder]     # default: data/raw

Put the downloaded fl_hot_*.csv files and fl_hotspot_districts.csv anywhere under that
folder (several Drive zips, "name(1).csv" duplicate downloads, and years exported in parts
as fl_hot_<sensor>_<year>_part1.csv, _part2.csv are all fine). One row per hotspot pixel per day; the app filters it for the "hotspots CSV" download.
Exits 1 if any check fails.
"""
import re
import sys
from pathlib import Path

import pandas as pd

DATA = Path(__file__).resolve().parent.parent / "data"
OUT = DATA / "hotspots.csv.gz"
SENSOR_NAMES = {"terra", "aqua", "viirs_snpp"}
COLUMNS = ["state", "district", "sensor", "acq_date", "latitude", "longitude", "frp_mw", "confidence"]
MAX_MB = 20  # repo rule: no file over 20 MB


YEARS = range(2016, 2027)
COPY_SUFFIX = re.compile(r"\s*\(\d+\)$")  # "fl_hot_aqua_2022(1).csv": a browser's second copy


def unique_files(raw: Path, pattern: str) -> dict[str, Path]:
    """Every CSV matching pattern under raw, by export name; duplicate downloads read once.

    Drive splits big folders into several zips, and browsers save a repeated download as
    "name(1).csv". Both copies hold the same export, so only the first is kept.
    """
    seen: dict[str, Path] = {}
    for path in sorted(raw.rglob(pattern), key=lambda p: (COPY_SUFFIX.sub("", p.stem), p.name)):
        seen.setdefault(COPY_SUFFIX.sub("", path.stem), path)
    return seen


EXPORT_NAME = re.compile(r"^fl_hot_(terra|aqua|viirs_snpp)_(\d{4})(?:_part(\d+))?$")


def hotspot_files(raw: Path) -> dict[tuple[str, int], list[Path]]:
    """The files to read for each (sensor, year).

    A sensor-year comes either as one export, fl_hot_<sensor>_<year>, or split into parts,
    fl_hot_<sensor>_<year>_part1, _part2, ... (used when a whole-year task fails). If both
    exist, the whole-year file is used and the parts are ignored, so nothing is counted twice.
    """
    whole: dict[tuple[str, int], Path] = {}
    parts: dict[tuple[str, int], list[Path]] = {}
    for stem, path in unique_files(raw, "fl_hot_*.csv").items():
        match = EXPORT_NAME.match(stem)
        if not match:
            print(f"note: ignoring {path.name} (not an fl_hot_<sensor>_<year> export)")
            continue
        key = (match.group(1), int(match.group(2)))
        if match.group(3):
            parts.setdefault(key, []).append(path)
        else:
            whole[key] = path
    files = {key: [path] for key, path in whole.items()}
    for key, paths in parts.items():
        if key in whole:
            print(f"note: {key[0]} {key[1]} has a whole-year file; its {len(paths)} part files are ignored")
        else:
            files[key] = sorted(paths)
    return files


def read_hotspots(raw: Path) -> list[pd.DataFrame]:
    return [pd.read_csv(p) for paths in hotspot_files(raw).values() for p in paths]


def missing_exports(raw: Path) -> list[str]:
    """Sensor-years with no export (whole or in parts) under raw."""
    have = set(hotspot_files(raw))
    return [f"fl_hot_{s}_{y}" for s in sorted(SENSOR_NAMES) for y in YEARS if (s, y) not in have]


def build(raw: Path) -> pd.DataFrame:
    """Raw exports -> one tidy table with exact GAUL names."""
    parts = [p for p in read_hotspots(raw) if len(p)]
    lookup = [pd.read_csv(p) for p in unique_files(raw, "fl_hotspot_districts.csv").values()]
    if not parts or not lookup:
        sys.exit(f"no fl_hot_*.csv or fl_hotspot_districts.csv under {raw}")
    df = pd.concat(parts, ignore_index=True)
    names = lookup[0].rename(columns={"ADM2_CODE": "adm2_code", "ADM1_NAME": "state", "ADM2_NAME": "district"})
    df = df.merge(names, on="adm2_code", how="left")
    df["frp_mw"] = df["frp_mw"].where(df["frp_mw"] >= 0).round(1)  # -1 = FRP missing
    df["confidence"] = df["fire_mask"].map({8: "nominal", 9: "high"})
    df[["latitude", "longitude"]] = df[["latitude", "longitude"]].round(4)
    return df[COLUMNS].sort_values(["state", "district", "acq_date", "sensor"], ignore_index=True)


def checks(df: pd.DataFrame, monthly: pd.DataFrame, missing: list[str]) -> bool:
    results = []

    def check(name, ok, detail=""):
        print("PASS" if ok else "FAIL", name, detail)
        results.append(bool(ok))

    check(f"H0 all {len(SENSOR_NAMES) * len(YEARS)} sensor-year exports present", not missing,
          f"missing: {', '.join(missing)}" if missing else "")
    mb = OUT.stat().st_size / 1e6
    check(f"H1 file under {MAX_MB} MB", mb < MAX_MB, f"{mb:.1f} MB, {len(df):,} rows")
    check("H2 exactly the 3 sensors", set(df.sensor) == SENSOR_NAMES, sorted(set(df.sensor)))
    blanks = df.drop(columns="frp_mw").isna().sum()
    check("H3 no blanks (FireMask 8/9, known district)", blanks.sum() == 0, blanks[blanks > 0].to_dict())
    dates = pd.to_datetime(df.acq_date, errors="coerce")
    check("H4 dates in 2016-01-01..2026-12-31", dates.between("2016-01-01", "2026-12-31").all(),
          f"{dates.min():%Y-%m-%d}..{dates.max():%Y-%m-%d}")
    known = set(zip(monthly.state, monthly.district))
    unknown = set(zip(df.state, df.district)) - known
    check("H5 names match district_monthly.csv", not unknown, sorted(unknown)[:5])

    # Same grid and fire rule as the monthly table; only border pixels differ (whole
    # pixel by centre here, area-weighted there), so totals agree closely but not exactly.
    count = (df.assign(year=dates.dt.year, month=dates.dt.month)
             .groupby(["state", "district", "sensor", "year", "month"]).size().rename("hotspots"))
    both = monthly.set_index(count.index.names)["fire_pixel_days"].to_frame().join(count).fillna(0)
    ratio = both.groupby("sensor").sum().eval("hotspots / fire_pixel_days").round(3)
    r = both["hotspots"].corr(both["fire_pixel_days"])
    check("H6 counts match fire_pixel_days (total within 10%, r >= 0.95)",
          ratio.between(0.9, 1.1).all() and r >= 0.95, f"ratio {ratio.to_dict()}, r={r:.3f}")

    lu = both.xs(("Ludhiana", "viirs_snpp"), level=("district", "sensor"))["hotspots"]
    peak = lu[lu.index.get_level_values("month").isin([10, 11])].mean()
    rest = lu[~lu.index.get_level_values("month").isin([10, 11])].mean()
    check("H7 Ludhiana VIIRS Oct-Nov peak", peak > 3 * rest, f"{peak:.0f} vs {rest:.0f} per month")
    check("H8 frp_mw >= 0 where present", (df.frp_mw.dropna() >= 0).all(),
          f"{df.frp_mw.isna().sum()} rows without FRP")
    return all(results)


def main() -> None:
    raw = Path(sys.argv[1]) if len(sys.argv) > 1 else DATA / "raw"
    missing = missing_exports(raw)
    df = build(raw)
    df.to_csv(OUT, index=False, compression="gzip")
    print(f"{len(df):,} hotspots -> {OUT}")
    ok = checks(df, pd.read_csv(DATA / "district_monthly.csv"), missing)
    if not ok:
        print(f"\nChecks failed: do not commit {OUT.name}. Fix the input and run again.")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
