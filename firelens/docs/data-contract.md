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
| 8 | `mean_frp_mw` | float | ≥ 0, megawatts | **Yes** | Mean fire radiative power over fire pixels (`MaxFRP` × 0.1). Null **iff** `fire_pixel_days == 0` |
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

## 6. `data/district_harmonized.csv` (Phase 2 Harmonized Output)

Generated by `python science/harmonize.py`. One row per **district x calendar month** (6,468 rows = 49 districts x 132 months, 2016-01 to 2026-12). `data/district_monthly.csv` remains untouched.

| Column | Type | Allowed values / units | Null? | Meaning |
|---|---|---|---|---|
| `state` | string | Exact GAUL 2015 L2 `ADM1_NAME` | No | State name |
| `district` | string | Exact GAUL 2015 L2 `ADM2_NAME` | No | District name |
| `year` | integer | 2016-2026 | No | UTC calendar year |
| `month` | integer | 1-12 | No | UTC calendar month |
| `viirs_act` | float | [0, 1] | Yes | Suomi-NPP VIIRS activity (`NaN` if `clear_coverage < 0.10` or `n_images == 0`) |
| `terra_scaled` | float | [0, 1] | Yes | Terra MODIS activity scaled by 2016-2022 state ratio (1.484 HR, 2.393 PB, 1.845 UK) |
| `aqua_scaled` | float | [0, 1] | Yes | Aqua MODIS activity scaled by 2016-2022 state ratio (0.966 HR, 0.906 PB, 0.971 UK) |
| `act_harmonized` | float | [0, 1] | Yes | Mean of non-null `viirs_act`, `terra_scaled`, `aqua_scaled` (`NaN` if all 3 are null) |
| `n_valid_sensors` | integer | 0-3 | No | Count of sensors with `clear_coverage >= 0.10` contributing to `act_harmonized` |
| `low_coverage` | boolean | True / False | No | `True` when `n_valid_sensors == 0` (no sensor meets the 0.10 per-sensor clear-view floor) |
| `baseline` | float | [0, 1] | Yes | Calendar-month (1-12) climatological mean of `act_harmonized` per `(state, district)` |
| `anomaly` | float | [-1, 1] | Yes | `act_harmonized - baseline` |
| `percentile` | float | [0, 100] | Yes | Empirical percentile rank of `act_harmonized` across valid months within `(state, district)` |
