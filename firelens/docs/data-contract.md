# FireLens — Data Contract

**Version:** 1.1 (updated for Phase 2 harmonization) · **Owner:** R2 (Science Lead) · **Date:** 2026-11-14
**Applies to:** `data/district_monthly.csv`, `data/district_harmonized.csv`, `data/districts.geojson`
**Companion:** `docs/decisions.md` (why), `science/qc_pipeline.py` (machine enforcement)

Any change to either file's shape, names or meaning requires R2 approval and a new row in
`docs/decisions.md`. Downstream code (`app/`, `science/`) must read this contract, not
reverse-engineer the file.

---

## 1. `data/district_monthly.csv`

One row per **district × sensor × calendar month**. UTF-8, comma-separated, single header
row, no index column, `.` decimal separator, empty field (`""`) for missing numbers — never
`NA`, `null`, `-9999` or `0` as a stand-in.

### 1.1 Columns

| # | Column | Type | Allowed values / units | Null? | Meaning |
|---|---|---|---|---|---|
| 1 | `state` | string | Exact GAUL 2015 L2 `ADM1_NAME` | No | State/UT name, identical to the GeoJSON property |
| 2 | `district` | string | Exact GAUL 2015 L2 `ADM2_NAME` | No | District name, identical to the GeoJSON property |
| 3 | `sensor` | string enum | `terra` \| `aqua` \| `viirs_snpp` | No | `terra` = MOD14A1, `aqua` = MYD14A1, `viirs_snpp` = VNP14A1 |
| 4 | `year` | integer | 2016–2026 inclusive | No | UTC calendar year of the aggregation window |
| 5 | `month` | integer | 1–12 inclusive | No | UTC calendar month (1 = January) |
| 6 | `fire_pixel_days` | float | ≥ 0 | No | Sum over the month's images of 1 km pixels with `FireMask >= 8` |
| 7 | `clear_pixel_days` | float | ≥ 0, ≥ `fire_pixel_days` | No | Sum over the month's images of 1 km **land** pixels clearly seen: `FireMask == 5` or `FireMask >= 7`. Fire pixels are a subset. |
| 8 | `mean_frp_mw` | float | ≥ 0, megawatts | **Yes** | Mean fire radiative power over fire pixels (MODIS `MaxFRP` × 0.1; VNP14A1 `MaxFRP` used as stored, already in MW). Null **iff** `fire_pixel_days == 0` |
| 9 | `n_images` | integer | ≥ 0 | No | Daily images found in that UTC month; `0` means no data (not "no fire") |

Notes that are easy to get wrong:

- `fire_pixel_days` and `clear_pixel_days` are **pixel-days** accumulated across the month's
  images, not distinct pixels and not per-day averages. They can exceed the district's pixel
  count (an image per day over a month).
- `n_images == 0` implies both counts are `0` and `mean_frp_mw` is empty.
- `clear_pixel_days == 0` with `n_images > 0` is legitimate (all-cloud month) and keeps its
  row.
- `sensor` is a closed enum. No NOAA-20/21, no combined/"all" rows, no duplicate sensor rows
  per month.

### 1.2 Grain and uniqueness

Primary key: **(`state`, `district`, `sensor`, `year`, `month`)**. Exactly one row per key.

### 1.3 Expected size

```
rows = N_districts × 3 sensors × 132 months      (Jan 2016 … Dec 2026)
```

`N_districts` = number of distinct (`state`, `district`) pairs in the file. Months after the
latest available image for a sensor are present with `n_images = 0`; they are **not** deleted,
so the grid stays rectangular and countable.

### 1.4 Derived metric (computed by `science/qc_pipeline.py`, not stored in the CSV)

```
activity = fire_pixel_days / clear_pixel_days      NaN  if clear_pixel_days == 0
                                                   NaN  if n_images == 0
```

- Range: `0 ≤ activity ≤ 1` (fire pixels are a subset of clear pixels). A value above 1 is a
  data fault, not a rounding artefact.
- `0` means pixels were seen clearly and none burned. `NaN` means nothing was observed —
  these are different statements and the app must show them differently (blank cell vs. `0`).
- Activity is a **share of clearly-seen land area**, not a fire count, not an FRP and not an
  area in km². It is comparable across sensors, districts and months only in this normalised
  form.
- `clear_coverage` (QC only, not a CSV column) = `(clear_pixel_days / days_in_month) ÷
  baseline`, where each district's `baseline` is its maximum monthly
  `clear_pixel_days / days_in_month`. It estimates the share of land pixels seen clearly and
  lies in `[0, 1]`.

---

## 2. `data/districts.geojson`

A GeoJSON `FeatureCollection` of district polygons used by the app map. Same district set and
same name strings as the CSV.

| Element | Rule |
|---|---|
| Type | `FeatureCollection` with a `features` array |
| CRS | WGS 84, EPSG:4326, longitude/latitude decimal degrees (GeoJSON's default; no `crs` member) |
| Geometry | `Polygon` or `MultiPolygon`, one feature per district, valid and closed rings |
| `properties.state` | string, exactly equal to the CSV `state` value |
| `properties.district` | string, exactly equal to the CSV `district` value |
| Simplification | `simplify(maxError=500)` metres in Earth Engine, to keep the file small enough to ship to the browser |
| Feature count | equal to the number of distinct (`state`, `district`) pairs in the CSV |

Join rule: the app joins on the **pair** (`properties.state`, `properties.district`), compared
as exact strings after trimming surrounding whitespace. Never join on district name alone —
names repeat across states.

The app must display, wherever the map appears:

> Boundaries: FAO/GAUL 2015 Level 2, simplified. Not an official boundary of India.

---

## 3. Validation rules

`python science/run_qc.py --input data/district_monthly.csv` must exit `0`. Each rule prints
`PASS`/`FAIL` with counts.

| ID | Rule | Failure means |
|---|---|---|
| V1 | Row count equals `N_districts × 3 × 132`, with no duplicate primary keys | Missing export task, duplicated merge, or a district dropped by a spatial join |
| V2 | Exactly the 3 allowed sensor values appear; every district has rows for all 3 | A sensor export failed or was named differently |
| V3 | No nulls in `state, district, sensor, year, month, fire_pixel_days, clear_pixel_days, n_images`; `year` 2016–2026; `month` 1–12; counts and `n_images` non-negative; rows with `n_images == 0` have both counts `0` and `mean_frp_mw` empty | Wrong column mapping in the merge, or text in numeric fields |
| V4 | `fire_pixel_days <= clear_pixel_days` in every row | Clear-view mask and fire mask disagree (usually the `== 5`-only mistake) |
| V5 | Mean `clear_pixel_days` in Jul–Sep is lower than in the other months (globally, and in ≥ 90 % of districts) | Date filter or clear-view rule wrong; also fires when the export is not really monthly |
| V6 | `mean_frp_mw >= 0`; null exactly where `fire_pixel_days == 0`, non-null where `fire_pixel_days > 0` | FRP divided by the wrong count, or `unmask(0)` leaked zeros into no-fire rows |
| V7 | Ludhiana, `viirs_snpp`: the peak calendar month of mean activity is October or November, and Oct–Nov mean activity exceeds the annual mean | FireMask threshold, date filter, or district filter wrong — in that order |
| V8 | Reports the latest month with `n_images > 0` for each sensor (informational, not a pass/fail gate) | Tells R4 how far the calendar can honestly extend |

Additional contract checks a reviewer should apply by eye:

- `activity` within `[0, 1]` everywhere it is defined; no `-1`, no `inf`.
- The three sensors' latest active months are plausible and consistent with each other
  (VIIRS typically extends furthest; a MODIS sensor stopping months earlier is normal).
- No district appears in one file but not the other.

---

## 4. Gap handling

A **gap** is a district-month-sensor row with `n_images == 0`, or with
`clear_coverage < 0.10` (fewer than ~10 % of land pixels seen clearly), or with no usable
baseline.

Rules:

1. **Keep the row.** Gaps are part of the rectangular grid; deleting them breaks V1 and hides
   the problem from the app.
2. **Never impute.** No interpolation, forward-fill, district-mean substitution, zero-fill or
   "nearest month" copy. `activity` stays `NaN`.
3. **Never plot as zero.** The app shows `NaN` activity as a blank/hatched cell with "no
   data" on hover. A `0` would assert that nothing burned.
4. **Export the list.** `python science/run_qc.py` writes `science/gaps.csv` with columns
   `state, district, sensor, year, month, date, n_images, clear_pixel_days,
   clear_pixel_coverage, fire_pixel_days, activity, reason`, sorted by state, district,
   sensor and date. `reason` is the dominant cause: `no_images` (no images that month),
   `low_clear_coverage` (images exist, coverage below the floor), or `no_clear_baseline`
   (the district has no usable baseline at all).
5. **A gap is not a failure.** R2 reports gaps; R1 fixes only genuinely broken rows.
6. **Months after the last image** stay in the file, are counted as gaps, and are excluded
   from headline numbers and climatology means (means use `skipna`).

---

## 5. Provenance and reproducibility

- Source: Google Earth Engine, `MODIS/061/MOD14A1`, `MODIS/061/MYD14A1`,
  `NASA/VIIRS/002/VNP14A1`; district layer `FAO/GAUL/2015/level2`, India features.
- Aggregation: daily `FireMask` masks and `MaxFRP` reduced with `Reducer.sum` at 1000 m scale
  over district polygons, one table per sensor per year, concatenated by
  `gee/merge_exports.py`.
- The CSV is generated, never hand-edited. A correction ships as a new export.
- `data/district_monthly.csv` is the only file the app reads for series; nothing is
  recomputed from rasters at runtime.

---

## 6. `data/district_harmonized.csv` (Phase 2 Harmonized Output, v2)

Generated by `python science/harmonize.py`. One row per **district x calendar month** (6,468 rows = 49 districts x 132 months, 2016-01 to 2026-12). `data/district_monthly.csv` remains untouched. Method and every number: `science/validation.md`.

| Column | Type | Allowed values / units | Null? | Meaning |
|---|---|---|---|---|
| `state` | string | Exact GAUL 2015 L2 `ADM1_NAME` | No | State name |
| `district` | string | Exact GAUL 2015 L2 `ADM2_NAME` | No | District name |
| `year` | integer | 2016-2026 | No | UTC calendar year |
| `month` | integer | 1-12 | No | UTC calendar month |
| `viirs_act` | float | [0, 1] | Yes | Suomi-NPP VIIRS activity (`NaN` if `clear_coverage < 0.10` or `n_images == 0`) |
| `terra_scaled` | float | [0, 1] | Yes | Terra MODIS activity x the (state, calendar-month) VIIRS/Terra ratio fit on pre-drift 2016-2022 months. Present in every month; after Oct 2022 it is shown for comparison only |
| `aqua_scaled` | float | [0, 1] | Yes | Same for Aqua MODIS; after Feb 2023 for comparison only |
| `act_harmonized` | float | [0, 1] | Yes | Where VIIRS is valid: weighted mean of VIIRS (weight 1) and each **pre-drift** scaled MODIS sensor (weight r^2 from leave-one-year-out). Where VIIRS is not: weighted mean of the scaled MODIS sensors (pre-drift ones first). `NaN` exactly when `source == "none"` |
| `n_valid_sensors` | integer | 0-3 | No | Count of `viirs_act`, `terra_scaled`, `aqua_scaled` that are non-null |
| `low_coverage` | boolean | True / False | No | `True` when `n_valid_sensors == 0` |
| `baseline` | float | [0, 1] | Yes | Calendar-month (1-12) climatological mean of `act_harmonized` per `(state, district)` |
| `anomaly` | float | [-1, 1] | Yes | `act_harmonized - baseline` |
| `percentile` | float | [0, 100] | Yes | Empirical percentile rank of `act_harmonized` across valid months within `(state, district)` |
| `source` | string enum | `blend` \| `viirs` \| `modis_fill` \| `modis_fill_drift` \| `none` | No | Where `act_harmonized` came from: VIIRS + pre-drift MODIS; VIIRS alone; pre-drift MODIS filling a month VIIRS did not see; drifted MODIS filling such a month (lower confidence); nothing valid |
| `modis_recon` | float | [0, 1] | Yes | MODIS-only reconstruction: weighted mean of `terra_scaled` and `aqua_scaled`, ignoring VIIRS. The validation series for extending the record before VIIRS (2001-2011) |
| `modis_drift` | boolean | True / False | No | `True` from Oct 2022, when at least one MODIS orbit is outside its science limits (Terra from 2022-10, Aqua from 2023-02) |
| `sensor_min` | float | [0, 1] | Yes | Lowest of the non-null `viirs_act`, `terra_scaled`, `aqua_scaled` that month |
| `sensor_max` | float | [0, 1] | Yes | Highest of the same three. `[sensor_min, sensor_max]` is the app's uncertainty band: the range of sensor disagreement, **not** a confidence interval. `act_harmonized` always lies inside it |
| `n_blended` | integer | 0-3 | No | Sensors `act_harmonized` rests on (those blended or used as a fill). `0` exactly when `source == "none"`; never more than `n_valid_sensors` |
| `clear_coverage` | float | [0.10, 1] | Yes | Clear coverage (§1.4) of the best-covered sensor among those `act_harmonized` rests on |

---

## 7. `data/hotspots.csv.gz` (individual hotspot detections, optional)

Generated by `gee/export_hotspots.js` + `python gee/merge_hotspots.py` (8 checks, H1–H8).
One row per **hotspot pixel per day per sensor**, gzip-compressed CSV (< 20 MB). Used only for
the app's "Download hotspots CSV" button; the calendar never reads it. The app works without it.

| Column | Type | Allowed values / units | Null? | Meaning |
|---|---|---|---|---|
| `state` | string | Exact GAUL 2015 L2 `ADM1_NAME` | No | Same strings as §1 |
| `district` | string | Exact GAUL 2015 L2 `ADM2_NAME` | No | District containing the pixel centre |
| `sensor` | string enum | `terra` \| `aqua` \| `viirs_snpp` | No | As §1 |
| `acq_date` | date | `YYYY-MM-DD`, 2016-01-01 to 2026-12-31 | No | UTC date of the daily composite |
| `latitude`, `longitude` | float | degrees, 4 decimals | No | Centre of the ~1 km pixel |
| `frp_mw` | float | ≥ 0, MW | Yes | Pixel `MaxFRP`, scaled as §1 column 8; empty if not recorded |
| `confidence` | string enum | `nominal` (FireMask 8) \| `high` (9) | No | Same fire rule as §1 (`FireMask >= 8`) |

Same grid and fire rule as `fire_pixel_days`, so per district-month-sensor counts match it
except at district borders (whole pixels by centre here, area-weighted in §1); check H6
requires totals within 10 % and r ≥ 0.95. Rows are detections as recorded, **not harmonized**:
never add sensors together.

---

## 8. `data/district_fire_types.csv` (fire type by land cover, optional)

Generated by `python science/fire_types.py` from the land-cover hotspot export
(`gee/export_hotspots_context.js`; raw file under `data/raw/`, not committed). One row per
**district × sensor × month**, only for districts with at least 95 % of their area inside the
export's rectangles (19 of 49 today) and only for months with images in §1 and inside the
export's period. Absent rows mean "not available", never zero. The app works without the file.

| Column | Type | Allowed values / units | Null? | Meaning |
|---|---|---|---|---|
| `state`, `district`, `sensor`, `year`, `month` | as §1 | as §1 | No | Primary key |
| `n_hotspots` | integer | ≥ 0, hotspot pixel-days | No | Pixels with `FireMask >= 8`, whole pixels by centre. Equals the sum of the five columns below |
| `n_cropland` | integer | ≥ 0 | No | On MCD12Q1 `LC_Type1` (IGBP) classes 12 or 14, land cover of the detection's year |
| `n_forest` | integer | ≥ 0 | No | On IGBP classes 1–5 |
| `n_woodland_grass` | integer | ≥ 0 | No | On IGBP classes 6–10 (shrublands, savannas, grassland) |
| `n_other` | integer | ≥ 0 | No | On any other class, including built-up, or no land-cover value |
| `n_static` | integer | ≥ 0 | No | On a static-source pixel (§9), whatever its land cover; such pixels are not counted in the four classes |
| `area_covered` | float | [0.95, 1] | No | Share of the district's area inside the export's rectangles |

Same products and fire rule as §1, so `n_hotspots` must match `fire_pixel_days`: the script
and the tests require the total within 15 % (5 % in the tests) and r ≥ 0.95 per sensor.
Counts are per sensor and **not harmonized**: never add sensors together. The app shows
Suomi-NPP VIIRS when the harmonized series is selected.

## 9. `data/static_sources.csv` (persistent thermal sources, optional)

Generated with §8. One row per ~1 km pixel that had hotspots in **at least 8 of the 12
calendar months and at least 12 different months** of the record (all sensors pooled, only to
locate the pixel): fixed heat sources such as flares and furnaces, not vegetation fires. The
rule is conservative; seasonal sources (brick kilns) are not caught.

| Column | Type | Meaning |
|---|---|---|
| `state`, `district` | string | District containing the pixel centre (any of the 49, covered by §8 or not) |
| `latitude`, `longitude` | float | Pixel centre, degrees, 4 decimals |
| `n_detections` | integer | Hotspot pixel-days, all sensors |
| `n_months`, `n_calendar_months` | integer | Different months, and different calendar months (1–12), with a detection |
| `night_share` | float | Share of detections at night |
| `median_nightlight` | float | Median VIIRS DNB radiance at the pixel, nW/cm²/sr |
| `land_cover_code` | integer | Most frequent IGBP class |

The calendar (§1, §6) still includes these pixels. Removing them needs a re-export and a new
row in `docs/decisions.md`.

## 10. Analyses the app computes on the fly

These are views of §1 and §6, not new metrics, and depend on the dates the user selects:

- **Season value:** mean monthly `activity` over a season's months (Oct–Nov, Apr–May, or
  Jan–Dec); a year counts only when every month of the season has a defined activity and at
  least half its daily images.
- **Trend:** two-sided Mann-Kendall test on the season values in year order (exact p-value
  without ties, otherwise the tie-corrected normal approximation with continuity correction)
  and Sen's slope; at least 8 seasons; significance at p < 0.05. Implemented in
  `app/trends.py` and checked against scipy in `tests/test_trends.py`.

## 11. Enforcement

`python -m pytest tests -q` checks §1, §2, §6, §8 and §9 against the committed files, rebuilds
§6 from §1, and renders every view of the app. GitHub Actions runs it, with the §3 rules, on
every pull request (`.github/workflows/ci.yml`).
