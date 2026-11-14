# gee/: how to rerun (R1)

Earth Engine steps run in the Code Editor (https://code.earthengine.google.com): paste the file, click Run, then click RUN on each task in the Tasks tab. Exports go to Google Drive. Python steps run from the repo root. They need `pandas`, plus `matplotlib` for the chart.

| Step | Run | Output |
|---|---|---|
| 1. Monthly fire table | `export_monthly.js`: 33 tasks, one per sensor per year | Drive `firelens_exports_<sensor>/fl_<sensor>_<year>.csv`, `fl_districts.geojson` |
| 1b. Terra gaps only | `export_missing_terra.js` | the 4 Terra years that failed the first time |
| 2. Land pixels | `export_land_pixels.js`: 1 task | Drive `firelens_exports/fl_land_pixels.csv` |
| 3. Download | put every Drive CSV and the GeoJSON anywhere under `data/raw/` | (raw files, never committed) |
| 4. Merge + 8 checks | `python gee/merge_exports.py` | `data/district_monthly.csv`, `data/districts.geojson` |
| 5. Land pixels + checks | `python gee/supporting.py land` | `data/district_land_pixels.csv` |
| 6. Latest month | `python gee/supporting.py latest` | printed; post it in team chat |
| 7. Demo chart | `python gee/supporting.py chart` | `data/figures/ludhiana_sensors.png/.svg` |
| 8. Hotspot list | `export_hotspots.js`: 33 tasks + 1 lookup | Drive `firelens_hotspots/fl_hot_<sensor>_<year>.csv`, `fl_hotspot_districts.csv` |
| 9. Merge + 8 checks | `python gee/merge_hotspots.py` | `data/hotspots.csv.gz` (app's "Download hotspots CSV") |
| 10. Hotspots with land cover (fire type) | `export_hotspots_context.js`: one task per year | Drive `FirePulse_India_Data/FirePulse_India_*.csv`; put them in `data/raw/firepulse/` |
| 11. Fire types + checks | `python science/fire_types.py --input data/raw/firepulse` | `data/district_fire_types.csv`, `data/static_sources.csv`, `science/fire_types.md` |

`export_monthly.py` is the Python version of step 1 (`smoke`, `test`, `export`, `boundaries`). It needs `earthengine-api` and `earthengine authenticate`.

Notes
- Every number uses the same ~1 km MODIS grid and the same partial-pixel weighting, so `fire_pixel_days`, `clear_pixel_days` and `land_pixels` can be compared directly.
- Months with `n_images = 0` (after the latest image) are kept as zeros. R2 decides how to treat them.
- Short months in the data: Aqua 2022-04 (14 images), Terra 2022-10 (19), and the current month while it's still in progress.
- Step 10 is the script exactly as it was run: it samples four rectangles (two of them ours) from 2012, with MCD12Q1 land cover and VIIRS night lights attached to each hotspot. `fire_types.py` keeps the three calendar sensors, FireMask ≥ 8 and 2016 onwards, and reports only districts at least 95 % inside the rectangles (19 of 49). To cover all 49, replace `STUDY_ZONES` with the district collection used in `export_hotspots.js`, re-run, and pass `--full-coverage`.
