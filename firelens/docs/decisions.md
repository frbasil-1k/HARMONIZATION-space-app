# FireLens — Decision Log

**Owner:** R2 (Science Lead) · **Status:** updated for Phase 2 harmonization · **Last updated:** 2026-11-14

Every choice below is binding for `data/district_monthly.csv`, `data/districts.geojson`, the
QC pipeline in `science/`, and the app. Changing anything in this table requires R2's
approval and a new row — never a silent edit to the CSV or the export script.

| Date | Decision | Rationale | Owner |
|---|---|---|---|
| 2026-11-14 | **Scope:** Northern India only — the states listed in *District universe* below, spelled exactly as in the FAO/GAUL 2015 Level 2 `ADM1_NAME` field. Punjab, Haryana and Uttarakhand are the core; Rajasthan is excluded from Phase 1. | The challenge is the agricultural-burning belt of Northern India. A fixed, small state list keeps the 33 exports and the district × month × sensor grid tractable inside one evening, and keeps the app legible. Rajasthan's desert districts mix dust and non-agricultural fire into the same signal and would need extra screening; it is deferred to Phase 2. | R2 |
| 2026-11-14 | **Period:** 2016-01 through 2026-12 (132 months) in the file; analysis and app headline stop at the **latest month with `n_images > 0`, per sensor**. Future/empty months are retained with `n_images = 0`. | Eleven calendar years give a stable per-month climatology (11 samples per calendar month) and match the 2026 challenge window. Keeping empty future months makes the grid rectangular (districts × 3 × 132) and therefore verifiable; it also lets the app hatch no-data months honestly instead of implying zero burning. | R2 |
| 2026-11-14 | **Sensors:** Terra MODIS (`MODIS/061/MOD14A1`), Aqua MODIS (`MODIS/061/MYD14A1`), Suomi-NPP VIIRS (`NASA/VIIRS/002/VNP14A1`) only. NOAA-20/21 VIIRS are excluded from the calendar. | Three sensors with long, overlapping records are enough to demonstrate harmonization. Adding NOAA-20/21 in Phase 1 would introduce a fourth, short, unvalidated series with a different overpass time and no time to characterise it. | R2 |
| 2026-11-14 | **Fire rule:** a 1 km pixel counts as fire when `FireMask >= 8` (nominal + high confidence). | The documented MODIS/VIIRS confidence convention: 8 = nominal, 9 = high. Including 7 (low confidence) inflates counts with false positives that vary by surface and season; excluding 8 loses real burning. `>= 8` is the standard, reproducible cut and is identical across all three products. | R2 |
| 2026-11-14 | **Clear-view rule:** a 1 km pixel counts as clearly seen when `FireMask == 5` (land, no fire) **or** `FireMask >= 7` (low/nominal/high-confidence fire). | Every fire pixel was, by definition, seen clearly. Counting only `== 5` would make `clear_pixel_days` ignore the burning pixels and would bias the denominator downward exactly where burning is intense. Note this makes fire pixels a subset of clear pixels, so `fire_pixel_days <= clear_pixel_days` always holds. | R2 |
| 2026-11-14 | **Core metric:** `activity = fire_pixel_days / clear_pixel_days`, per district × month × sensor. It is `NaN` (never 0) when `clear_pixel_days == 0` or `n_images == 0`. | Normalising by clearly-seen land pixels removes the dominant artefact: monsoon cloud, sensor outages and the sensor change itself all reduce the denominator and the numerator together. A raw hotspot count jumps when the satellite changes; a ratio of seen pixels does not. `NaN` distinguishes "no burning observed" from "nothing observed at all". | R2 |
| 2026-11-14 | **Anchor sensor:** Suomi-NPP VIIRS (`viirs_snpp`) is the reference series for the calendar, headline numbers and cross-sensor comparison; MODIS is scaled to it in Phase 2. | VIIRS is the only one of the three with an unbroken record across the whole 2016–2026 window, its early-afternoon overpass sits near peak burning behaviour, and it is the sensor that continues the record. All three are aggregated at the same 1 km scale here, so anchoring on continuity and sensitivity — not on native resolution — is the defensible choice. MODIS is harmonized onto it, not the reverse. | R2 |
| 2026-11-14 | **Time aggregation:** months are **UTC calendar months**. Exports filter `[month start, next month start)` in UTC. The app and all narrative text use IST (UTC+05:30). | Earth Engine's `filterDate` is UTC, so the file is reproducible from the script alone. The cost is a systematic boundary effect: the last ~5.5 hours of each IST month fall into the next UTC month. At monthly resolution this shifts at most a fraction of one day's detections and does not move any seasonal conclusion; it is recorded here so nobody later mistakes it for a bug. Sub-monthly or daily products in Phase 2 must state their time zone explicitly. | R2 |
| 2026-11-14 | **Boundaries:** FAO/GAUL 2015 Level 2 districts, simplified to 500 m, served with a visible disclaimer. | GAUL is the only district layer already joined to the Earth Engine export, so CSV names and geometry match by construction. It is **not** India's official boundary: it is outdated, its district set predates recent reorganisations, and it may not reflect the Government of India's position. The disclaimer must appear wherever the map does. An official district shapefile replaces it only with a new decision row here. | R2 |
| 2026-11-14 | **Gaps and missing values:** no imputation, no forward-fill, no zero-filling. Rows with `n_images == 0` stay in the file with both counts at 0 and `mean_frp_mw` / `activity` empty. Gaps are exported, not repaired. | Fabricated values are indistinguishable from measurements once they are in a CSV, and the app's blank cells are an honest statement about coverage. The gaps file (`science/gaps.csv`) is the hand-off for hatching in the app and the work list for Phase 2. | R2 |
| 2026-11-14 | **`mean_frp_mw` is null exactly when `fire_pixel_days == 0`.** Values are non-negative and in MW (MODIS/VIIRS `MaxFRP` × 0.1). | FRP is only defined over fire pixels, so averaging it with no fire pixels would be a division by zero. A non-null FRP with zero fire pixels, or a null with fire pixels, means the export merged the wrong columns. | R2 |
| 2026-11-14 | **Phase 2 coverage floor (`low_coverage`):** `clear_coverage < 0.10` (or `n_images == 0`), computed against each `(state, district, sensor)` maximum monthly `clear_pixel_days / days_in_month`. | Aligns with Phase 1 gap detection (<10% floor) while normalizing per sensor so VIIRS and MODIS clear-sky denominators use their native swath baselines. Low-coverage values are masked to `NaN` (never imputed) before calibration and climatology. | R2 |
| 2026-11-14 | **Phase 2 harmonization & climatology (`data/district_harmonized.csv`):** State-specific median `VIIRS / MODIS` ratios fit on `2016-2022` positive-fire valid months (`USE_FALLBACK = False`; max annual CV `0.220 < 0.50`). `act_harmonized` is the mean of available `viirs_act`, `terra_scaled`, and `aqua_scaled` clipped to [0, 1]; `baseline` is the calendar-month climatological mean per `(state, district)`; `anomaly = act_harmonized - baseline`; `percentile` is the empirical rank (0-100) across valid months within `(state, district)`. | Blind `2023-2025` validation confirms cross-sensor agreement (`r = 0.831` Aqua, `0.703` pooled; median abs error `1.79e-5`) and preserves Ludhiana (`4.19x` Oct-Nov) and Naini Tal (`4.02x` Apr-May) peaks. | R2 |

**Note on `CLAUDE.md`:** its one-line contract says "Dates are IST". That shorthand is
superseded by the UTC row above: the file is built on UTC months, narrative text uses IST.

## District universe

Exact `ADM1_NAME` spellings are copied from R1's step-1 printout of the GAUL layer; the CSV
and the GeoJSON must use the same strings, character for character.

| State (GAUL `ADM1_NAME`) | Phase 1 status | Note |
|---|---|---|
| Punjab | Included | Core agricultural-burning state; contains Ludhiana, the reference district. |
| Haryana | Included | Core agricultural-burning state; Delhi-adjacent stubble belt. |
| Uttarakhand | Included | Hill/forest state; provides the spring forest-fire contrast to the Punjab crop calendar. |
| Rajasthan | Excluded | Deferred to Phase 2 (dust and non-agricultural fire confound the agricultural signal). |
| Delhi, Chandigarh, Himachal Pradesh, Uttar Pradesh, Jammu & Kashmir, Ladakh | Excluded | Outside the frozen Phase 1 extent; do not add rows for them. |

## Change control

1. Any change to the data contract, the CSV, the GeoJSON or the definitions above needs R2's
   approval and a new row in this table, dated.
2. A change that alters existing values (e.g. a different FireMask cut) requires re-running
   `python science/run_qc.py` and re-checking every plot and the gaps list.
3. The app must not compute its own metric variants; it reads `activity` semantics from
   `docs/data-contract.md`.
