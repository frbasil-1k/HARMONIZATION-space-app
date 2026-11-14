"""R1 Earth Engine extraction for FireLens (playbook section 3).

    python gee/export_monthly.py smoke        # step 1: access check + exact GAUL state names
    python gee/export_monthly.py test         # step 2: Punjab 2020 VIIRS -> data/test_punjab_2020_viirs.csv
    python gee/export_monthly.py export       # step 3: 33 Drive tasks (3 sensors x 11 years)
    python gee/export_monthly.py boundaries   # step 4: district GeoJSON to Drive

First time: pip install earthengine-api pandas, then: earthengine authenticate
"""
import sys
from pathlib import Path

import ee
import pandas as pd

from merge_exports import DATA, to_contract

PROJECT = "firelens-hackathon"
DRIVE_FOLDER = "firelens_exports"
# Exact ADM1_NAME spellings from `smoke`, final list decided by R2 (docs/decisions.md).
STATES = ["Punjab", "Haryana", "Uttaranchal"]
YEARS = range(2016, 2027)
SENSORS = {"terra": "MODIS/061/MOD14A1",
           "aqua": "MODIS/061/MYD14A1",
           "viirs_snpp": "NASA/VIIRS/002/VNP14A1"}
# MaxFRP -> MW. MODIS is stored x10. The playbook also scales VNP14A1 by 0.1, but our earlier
# hotspot run showed unscaled VNP14A1 (median 11 MW) already matches MODIS (16 MW). Confirm with R2.
FRP_SCALE = {"terra": 0.1, "aqua": 0.1, "viirs_snpp": 1.0}
BANDS = ["fire", "clear", "frp"]


def districts(states):
    g2 = ee.FeatureCollection("FAO/GAUL/2015/level2").filter(ee.Filter.eq("ADM0_NAME", "India"))
    return g2.filter(ee.Filter.inList("ADM1_NAME", states)).select(["ADM1_NAME", "ADM2_NAME"])


def month_table(sensor, year, month, regions):
    cid, scale = SENSORS[sensor], FRP_SCALE[sensor]
    start = ee.Date.fromYMD(year, month, 1)
    col = ee.ImageCollection(cid).filterDate(start, start.advance(1, "month"))

    def daily(img):
        fm = img.select("FireMask")
        fire = fm.gte(8)                       # nominal + high confidence
        clear = fm.eq(5).Or(fm.gte(7))         # land seen clearly (no fire, or fire)
        frp = img.select("MaxFRP").unmask(0).multiply(scale).multiply(fire)
        return ee.Image.cat(fire, clear, frp).rename(BANDS).toFloat()

    # Empty month (after the latest image) -> zeros, so counts are 0 not blank; n_images says 0.
    zeros = ee.Image.constant([0, 0, 0]).rename(BANDS).toFloat()
    img = ee.Image(ee.Algorithms.If(col.size().gt(0), col.map(daily).sum(), zeros))

    # Reduce on the sensor's native ~1 km grid, not a resampled one.
    proj = ee.ImageCollection(cid).first().select("FireMask").projection()
    fc = img.reduceRegions(collection=regions, reducer=ee.Reducer.sum(),
                           crs=proj, scale=proj.nominalScale(), tileScale=4)
    return fc.map(lambda f: f.set({"sensor": sensor, "year": year, "month": month,
                                   "n_images": col.size()}))


def smoke():
    n = ee.ImageCollection(SENSORS["viirs_snpp"]).filterDate("2020-10-01", "2020-12-01").size().getInfo()
    print(f"VNP14A1 Oct-Nov 2020 images: {n} (daily product, so ~61; playbook's ~31 is per month)")
    g2 = ee.FeatureCollection("FAO/GAUL/2015/level2").filter(ee.Filter.eq("ADM0_NAME", "India"))
    print("GAUL India states:", sorted(g2.aggregate_array("ADM1_NAME").distinct().getInfo()))
    counts = {s: districts([s]).size().getInfo() for s in STATES}
    print("Districts per configured state:", counts, "<- 0 means the spelling is wrong")


def test():
    fc = ee.FeatureCollection([month_table("viirs_snpp", 2020, m, districts(["Punjab"]))
                               for m in range(1, 13)]).flatten()
    df = to_contract(pd.DataFrame([f["properties"] for f in fc.getInfo()["features"]]))
    out = DATA / "test_punjab_2020_viirs.csv"
    df.to_csv(out, index=False)
    print(f"{len(df)} rows -> {out}")
    lu = df[df.district == "Ludhiana"].set_index("month").fire_pixel_days
    print("Ludhiana fire_pixel_days by month (expect Oct-Nov peak):\n", lu.round(1).to_string())


def export():
    regions = districts(STATES)
    for sensor in SENSORS:
        for year in YEARS:
            fc = ee.FeatureCollection([month_table(sensor, year, m, regions) for m in range(1, 13)]).flatten()
            task = ee.batch.Export.table.toDrive(
                collection=fc, description=f"fl_{sensor}_{year}", folder=DRIVE_FOLDER, fileFormat="CSV",
                selectors=["ADM1_NAME", "ADM2_NAME", "sensor", "year", "month", "fire", "clear", "frp", "n_images"])
            task.start()
            print("started", f"fl_{sensor}_{year}")


def boundaries():
    fc = districts(STATES).map(lambda f: ee.Feature(f.geometry().simplify(maxError=500),
                                                    {"state": f.get("ADM1_NAME"), "district": f.get("ADM2_NAME")}))
    ee.batch.Export.table.toDrive(collection=fc, description="fl_districts", folder=DRIVE_FOLDER,
                                  fileFormat="GeoJSON").start()
    print("started fl_districts")


if __name__ == "__main__":
    cmds = {"smoke": smoke, "test": test, "export": export, "boundaries": boundaries}
    if len(sys.argv) != 2 or sys.argv[1] not in cmds:
        sys.exit(__doc__)
    DATA.mkdir(exist_ok=True)
    ee.Initialize(project=PROJECT)
    cmds[sys.argv[1]]()
