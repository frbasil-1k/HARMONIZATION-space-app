# FireLens data dictionary

Everything a researcher needs to use the tables in this folder without reading the code.
The binding definitions are in `docs/data-contract.md`; the reasons are in `docs/decisions.md`.

**Region and period:** 49 districts of Punjab, Haryana and Uttarakhand (FAO GAUL 2015
names), January 2016 to December 2026, UTC calendar months.
**Missing values:** an empty field means "not observed". It never means zero.
**Hotspots are satellite detections, not confirmed fires.** Never add the sensors' counts
together.

## Core idea

`activity = fire_pixel_days / clear_pixel_days`: the share of clearly seen 1 km land
pixel-days that had a hotspot (FireMask ≥ 8). Dividing by what was clearly seen removes
most of the effect of cloud and of each satellite's coverage, so activity can be compared
between months, districts and sensors. Multiply by 100 for a percentage.

## `district_monthly.csv` — what each sensor recorded

One row per district × sensor × month (19,404 rows).

| Column | Unit | Meaning |
|---|---|---|
| `state`, `district` | text | GAUL 2015 names; join on the pair |
| `sensor` | text | `terra` (MOD14A1), `aqua` (MYD14A1), `viirs_snpp` (VNP14A1) |
| `year`, `month` | int | UTC calendar month |
| `fire_pixel_days` | pixel-days | 1 km pixels with FireMask ≥ 8, summed over the month's daily images (area-weighted at district borders, so not always whole numbers) |
| `clear_pixel_days` | pixel-days | 1 km land pixels clearly seen (FireMask 5 or ≥ 7), summed the same way |
| `mean_frp_mw` | MW | mean fire radiative power over fire pixels; empty when there were none |
| `n_images` | count | daily images that month; 0 means no data |

## `district_harmonized.csv` — one consistent record

One row per district × month (6,468 rows). All activity columns are shares in [0, 1].

| Column | Meaning |
|---|---|
| `viirs_act` | Suomi-NPP VIIRS activity (the anchor) |
| `terra_scaled`, `aqua_scaled` | MODIS activity put on the VIIRS scale with one ratio per state and calendar month |
| `act_harmonized` | **the harmonized value**: VIIRS blended with pre-drift scaled MODIS; MODIS fills months VIIRS could not see |
| `source` | where the value came from: `blend`, `viirs`, `modis_fill`, `modis_fill_drift` (lower confidence), `none` |
| `n_blended` | how many sensors the value rests on (0–3) |
| `sensor_min`, `sensor_max` | lowest and highest of the three scaled sensors that month: the range of sensor disagreement (not a confidence interval) |
| `clear_coverage` | share of the district's land seen clearly by the best sensor used, in [0, 1] |
| `n_valid_sensors` | sensors with a usable value that month (0–3), whether blended or not |
| `low_coverage` | true when no sensor had a usable view |
| `baseline` | mean `act_harmonized` of that calendar month across years, per district |
| `anomaly` | `act_harmonized − baseline` |
| `percentile` | rank of the month within the district's record, 0–100 |
| `modis_recon` | the record rebuilt from MODIS alone, for validating an extension to before VIIRS |
| `modis_drift` | true from October 2022, when the MODIS orbits left their science limits |

Method, skill and limits: `science/validation.md`.

## `district_fire_types.csv` — what burns

One row per district × sensor × month for the **19 districts** the land-cover hotspot
export covers (7,410 rows). Counts are hotspot pixel-days of that sensor (FireMask ≥ 8).

| Column | Meaning |
|---|---|
| `n_hotspots` | all hotspot pixel-days; equals the sum of the five columns below |
| `n_cropland` | on cropland or cropland mosaic (MCD12Q1 IGBP 12, 14) |
| `n_forest` | on forest (IGBP 1–5) |
| `n_woodland_grass` | on shrubland, savanna or grassland (IGBP 6–10) |
| `n_other` | on any other land cover, including built-up |
| `n_static` | on a static-source pixel (see below), whatever its land cover |
| `area_covered` | share of the district's area inside the sampled rectangles (≥ 0.95) |

## `static_sources.csv` — fixed heat sources

One row per 1 km pixel with hotspots in at least 8 of the 12 calendar months and at least
12 different months of the record: flares, furnaces and similar, not vegetation fires.

| Column | Meaning |
|---|---|
| `latitude`, `longitude` | pixel centre, degrees |
| `n_detections` | hotspot pixel-days, all three sensors (used only to locate the pixel) |
| `n_months`, `n_calendar_months` | different months, and different calendar months, with a detection |
| `night_share` | share of detections at night |
| `median_nightlight` | VIIRS night-light radiance at the pixel, nW/cm²/sr |
| `land_cover_code` | most frequent MCD12Q1 IGBP class |

Method and checks: `science/fire_types.md`.

## `districts.geojson`

District polygons (FAO GAUL 2015 Level 2, simplified to 500 m), properties `state` and
`district`. Not an official boundary of India.

## `hotspots.csv.gz` — every hotspot detection

One row per hotspot pixel per day per sensor, all 49 districts, 2016-01-01 to 2026-11-08
(619,188 rows, gzip-compressed CSV). This is the file behind the app's "Download hotspots
CSV" button. Counts per district, sensor and month match `fire_pixel_days` above to within
0.1 % (check H6 of `gee/merge_hotspots.py`). Detections as recorded, **not harmonized**.

| Column | Meaning |
|---|---|
| `state`, `district` | district containing the pixel centre |
| `sensor` | `terra`, `aqua` or `viirs_snpp` |
| `acq_date` | UTC date of the daily composite, `YYYY-MM-DD` |
| `latitude`, `longitude` | centre of the ~1 km pixel, degrees |
| `frp_mw` | fire radiative power, MW; empty if not recorded |
| `confidence` | `nominal` (FireMask 8) or `high` (FireMask 9) |

Full rules: `docs/data-contract.md` §7.

## Licence and citation

Derived tables: CC BY 4.0. Boundaries: FAO GAUL 2015 data licence (non-commercial), not
relicensed. Code: MIT. How to cite FireLens and the NASA products: `CITATION.cff` at the
repository root.
