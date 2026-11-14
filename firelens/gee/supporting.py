"""Supporting data for R2 / the demo (run after merge_exports.py).

    python gee/supporting.py latest     # latest month per sensor -> post in team chat
    python gee/supporting.py land       # data/raw/**/fl_land_pixels.csv -> data/district_land_pixels.csv + checks
    python gee/supporting.py chart      # Ludhiana VIIRS vs Aqua vs Terra -> data/figures/ludhiana_sensors.png/.svg
"""
import json
import sys

import pandas as pd

from merge_exports import DATA

NAMES = {"viirs_snpp": "VIIRS (S-NPP)", "aqua": "MODIS Aqua", "terra": "MODIS Terra"}


def monthly():
    return pd.read_csv(DATA / "district_monthly.csv")


def latest():
    df = monthly()
    has = df[df.n_images > 0]
    for s, g in has.groupby("sensor"):
        last = g.loc[(g.year * 100 + g.month).idxmax()]
        print(f"{s}: data through {last.year}-{last.month:02d} ({last.n_images} images in that month)")


def land():
    src = next((DATA / "raw").rglob("fl_land_pixels.csv"), None)
    if src is None:
        sys.exit("no fl_land_pixels.csv under data/raw (run gee/export_land_pixels.js, download it)")
    lp = pd.read_csv(src)[["state", "district", "land_pixels"]].sort_values(["state", "district"])
    out = DATA / "district_land_pixels.csv"
    lp.to_csv(out, index=False)
    print(f"{len(lp)} rows -> {out}")

    geo = {(f["properties"]["state"], f["properties"]["district"])
           for f in json.load(open(DATA / "districts.geojson"))["features"]}
    keys = set(zip(lp.state, lp.district))
    df = monthly()
    # clear_pixel_days counts land pixels seen per day, so it can't exceed land_pixels x days.
    m = df.merge(lp, on=["state", "district"])
    over = m[~(m.clear_pixel_days <= m.land_pixels * m.n_images * 1.01)]  # NaN counts as over
    ok = [("names match districts.geojson", keys == geo, f"missing {geo - keys}, extra {keys - geo}"),
          ("one row per district", len(lp) == len(keys), f"{len(lp)} rows, {len(keys)} unique"),
          ("land_pixels > 0", (lp.land_pixels > 0).all(), lp.land_pixels.describe().round(0).to_dict()),
          ("clear_pixel_days <= land_pixels x n_images", over.empty, f"{len(over)} rows over")]
    for name, passed, detail in ok:
        print("PASS" if passed else "FAIL", name, "" if passed else detail)
    sys.exit(0 if all(p for _, p, _ in ok) else 1)


def chart():
    import matplotlib.pyplot as plt  # only here: the other commands don't need it

    df = monthly()
    # ponytail: >=10 images drops the partial current month (Nov 2026: VIIRS 2, MODIS 8) but keeps
    # real short months (Aqua 2022-04: 14, Terra 2022-10: 19). Revisit if a new outage dips below 10.
    lu = df[(df.district == "Ludhiana") & (df.n_images >= 10)].copy()
    lu["date"] = pd.to_datetime(dict(year=lu.year, month=lu.month, day=1))
    fig, ax = plt.subplots(figsize=(11, 4.5))
    for s, color in [("viirs_snpp", "#d1495b"), ("aqua", "#2e86ab"), ("terra", "#edae49")]:
        g = lu[lu.sensor == s]
        ax.plot(g.date, g.fire_pixel_days, color=color, lw=1.8, label=NAMES[s])
    ax.set_title("Ludhiana: same fires, three satellites, three different answers", loc="left", fontsize=14)
    ax.set_ylabel("raw fire pixel-days per month")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.3)
    ax.legend(frameon=False)
    fig.tight_layout()
    (DATA / "figures").mkdir(exist_ok=True)
    for ext in ("png", "svg"):
        fig.savefig(DATA / "figures" / f"ludhiana_sensors.{ext}", dpi=200)
    print("-> data/figures/ludhiana_sensors.png/.svg")
    # The numbers behind the shot, for the narration.
    peak = lu.pivot_table(index="year", columns="sensor", values="fire_pixel_days", aggfunc="sum").round(0)
    print("Ludhiana fire pixel-days per year:\n", peak.to_string())


if __name__ == "__main__":
    cmds = {"latest": latest, "land": land, "chart": chart}
    if len(sys.argv) != 2 or sys.argv[1] not in cmds:
        sys.exit(__doc__)
    cmds[sys.argv[1]]()
