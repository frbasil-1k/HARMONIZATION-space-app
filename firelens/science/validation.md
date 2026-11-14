# FireLens Phase 2 — Harmonization Validation (v2)

**Owner:** R2 (Science Lead) · **Generated:** 2026-11-14 by `science/harmonize.py`
**Input:** `data/district_monthly.csv` (19,404 rows, 49 districts, period 2016-01 to 2026-12)
**Output:** `data/district_harmonized.csv` (6,468 district-months)

Every number below is computed by the script; none is typed in by hand.

## Method in one paragraph

Activity is `fire_pixel_days / clear_pixel_days` per district, month and sensor; rows with
`clear_coverage < 0.10` or `n_images == 0` stay `NaN`. Suomi-NPP VIIRS is the
anchor. Each MODIS sensor is mapped onto it with **one ratio per state and calendar month**
(`sum(viirs) / sum(modis)` over shared district-months of 2016–2022),
using only months before that sensor's **orbit drift** (Terra from
Oct 2022, Aqua from
Feb 2023). The harmonized value is the
weighted mean of VIIRS (weight 1) and each pre-drift scaled MODIS sensor (weight r² from
leave-one-year-out: Terra 0.83, Aqua 0.96). After the drift, MODIS only fills
months VIIRS could not see, flagged `modis_fill_drift`. `modis_recon` is the record rebuilt
from MODIS alone, the way it would look before VIIRS existed.

## 1. Why the ratio became seasonal

Terra passes at ~10:30 local time, before most afternoon crop burning; Aqua and VIIRS pass
at ~13:30. The MODIS/VIIRS gap is therefore much larger in burning season than in quiet
months, and one all-year ratio cannot fit both. Leave-one-year-out on 2016–2022
(fit on six years, test on the seventh; pre-drift months only). Peak months: Haryana Oct/Nov, Punjab Oct/Nov, Uttarakhand Apr/May.
`bias` = sum(scaled) ÷ sum(VIIRS); 1.00 means the same total burning.

| Method | Sensor | n | Pearson r | OLS slope | Bias | Peak-month bias |
|---|---|---|---|---|---|---|
| v1: all-month median | terra | 3,969 | 0.644 | 0.27 | 0.57 | 0.30 |
| v1: all-month median | aqua | 4,116 | 0.975 | 1.03 | 1.04 | 1.11 |
| v2: monthly ratio of sums | terra | 3,969 | 0.912 | 1.11 | 1.03 | 1.04 |
| v2: monthly ratio of sums | aqua | 4,116 | 0.979 | 0.99 | 1.01 | 1.00 |

Terra in the peak months moves from **0.30×** of VIIRS (v1) to
**1.04×** (v2), and its correlation from 0.64 to
0.91. Aqua was already close and stays close.

## 2. Ratios used (fit on all pre-drift 2016–2022 months)

VIIRS ÷ MODIS by calendar month. `*` = fewer than 15 burning district-months, so
the state's all-month ratio (last column) is used.

| State | Sensor | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec | All months |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Haryana | aqua | 0.83 | 1.18 | 0.83 | 0.77 | 1.50 | 0.85 | 0.86* | 0.50 | 1.89 | 0.75 | 0.74 | 0.74 | 0.86 |
| Haryana | terra | 2.58 | 0.91 | 0.66 | 1.10 | 1.26 | 3.42 | 2.10* | 0.37 | 2.10* | 3.54 | 9.05 | 1.44 | 2.10 |
| Punjab | aqua | 0.77 | 1.08 | 1.16 | 0.57 | 1.54 | 2.84 | 1.80 | 0.74 | 2.39 | 0.72 | 0.89 | 0.78 | 0.89 |
| Punjab | terra | 3.16 | 2.30 | 0.91 | 1.00 | 1.65 | 2.37 | 1.80 | 1.44 | 11.83 | 8.25 | 11.96 | 2.80 | 4.83 |
| Uttarakhand | aqua | 0.71 | 0.68 | 0.96 | 0.90 | 1.37 | 1.66 | 0.95* | 0.95* | 0.95* | 0.75 | 0.71 | 0.81 | 0.95 |
| Uttarakhand | terra | 2.64 | 1.65 | 1.74 | 1.30 | 1.36 | 1.94 | 1.57* | 1.57* | 1.57* | 4.93 | 3.24 | 2.01 | 1.57 |

### Stability by year (all-month ratio of sums)

| State | Sensor | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | CV |
|---|---|---|---|---|---|---|---|---|---|
| Haryana | terra | 1.89 | 2.81 | 2.37 | 1.94 | 1.74 | 2.17 | 1.62 | 0.198 |
| Punjab | terra | 4.88 | 6.16 | 4.53 | 4.09 | 6.34 | 5.67 | 1.77 | 0.328 |
| Uttarakhand | terra | 1.40 | 1.77 | 1.65 | 1.42 | 2.58 | 1.56 | 1.58 | 0.235 |
| Haryana | aqua | 0.85 | 0.91 | 1.02 | 0.96 | 0.74 | 0.86 | 0.61 | 0.165 |
| Punjab | aqua | 0.88 | 0.94 | 0.94 | 0.99 | 0.78 | 0.87 | 0.85 | 0.079 |
| Uttarakhand | aqua | 0.93 | 0.91 | 1.15 | 1.10 | 0.86 | 0.93 | 0.76 | 0.141 |

Every state-sensor yearly ratio has CV below the limit, so no fallback was needed.

## 3. MODIS-only reconstruction — the evidence for extending back to 2001

If VIIRS had never flown, the calendar would be `modis_recon`: the weighted mean of the scaled
MODIS sensors. Leave-one-year-out against VIIRS: **r = 0.968**, bias **1.02**,
peak-month bias **1.02**, slope 1.04 (n = 4,116). This is the
skill to expect when the same ratios are applied to Terra (2001–) and Aqua (2003–) before
2012, when both still flew their nominal orbits.

The blend itself stays on the VIIRS scale: harmonized vs VIIRS on the same rows,
bias **1.01**, peak-month bias **1.01**, r = 0.986. So months
with and without a given MODIS sensor sit at the same level, and the sensor mix no longer
steps the series.

## 4. Drift period (2023–2025): why drifted MODIS is not blended

By 2023 Terra had drifted to an earlier and Aqua to a later overpass (Aqua ~15:30 local time
by mid-2026), while farm burning in Punjab also moved later in the day. The pre-drift ratios,
applied blind:

| Method | Sensor | n | Pearson r | OLS slope | Bias | Peak-month bias |
|---|---|---|---|---|---|---|
| pre-drift ratios, blind | terra | 1,764 | 0.659 | 0.33 | 0.60 | 0.37 |
| pre-drift ratios, blind | aqua | 1,764 | 0.871 | 1.26 | 1.29 | 1.82 |
| rolling refit on previous year | terra | 1,764 | 0.497 | 0.48 | 0.96 | 0.88 |
| rolling refit on previous year | aqua | 1,764 | 0.792 | 1.62 | 1.62 | 1.67 |

By year (pre-drift ratios):

| Year | Sensor | n | Pearson r | OLS slope | Bias | Peak-month bias |
|---|---|---|---|---|---|---|
| 2023 | terra | 588 | 0.581 | 0.18 | 0.42 | 0.22 |
| 2023 | aqua | 588 | 0.947 | 1.22 | 1.05 | 1.35 |
| 2024 | terra | 588 | 0.842 | 0.65 | 0.72 | 0.55 |
| 2024 | aqua | 588 | 0.875 | 1.69 | 1.55 | 2.08 |
| 2025 | terra | 588 | 0.882 | 0.66 | 0.77 | 1.02 |
| 2025 | aqua | 588 | 0.608 | 0.87 | 1.40 | 5.08 |

Aqua reads **1.82×** VIIRS in the peak months, and refitting on the
previous year still leaves **1.67×**: the overpass keeps moving, so last
year's ratio is already stale. A blend would inherit that drift, so after the drift start
the harmonized value is VIIRS where VIIRS saw the district, and drifted MODIS only fills
the rest (`source = modis_fill_drift`, shown as lower confidence in the app). The post-2023
decline in VIIRS is consistent with burning moving after the 13:30 overpass; part of it may
be a detection effect rather than less burning.

## 5. Harmonized product checks

| Check | Value |
|---|---|
| District-months written | 6,468 (49 districts × 132 months) |
| Rows with a usable `act_harmonized` | 6,419 |
| Rows left `NaN` | 49 |
| `act_harmonized` range | [0.000000, 0.030565] |
| Mean `act_harmonized` | 0.000411 |
| Low-coverage rows | 49 |

Where each value comes from (`source`):

| Source | Rows | Share |
|---|---|---|
| blend | 4,165 | 64.4% |
| viirs | 2,205 | 34.1% |
| modis_fill | 0 | 0.0% |
| modis_fill_drift | 49 | 0.8% |
| none | 49 | 0.8% |

Uncertainty columns (`sensor_min`, `sensor_max`, `n_blended`, `clear_coverage`): the range
of the three sensors after scaling is the app's uncertainty band. Half of that range, as a
share of the harmonized value (median over district-months with at least two sensors):
**±27%** in the burning months (each district's top 10% of months)
before the drift, **±79%** over all months (quiet months have few
detections, so sensors disagree more in relative terms), and **±38%**
in burning months after the drift. It is a measure of sensor disagreement, not a confidence
interval.

Peak preservation:

- Ludhiana (Punjab), Oct–Nov paddy peak: season mean **0.003693** vs annual mean **0.000851** → **4.34×**
- Naini Tal (Uttarakhand), Apr–May forest-fire peak: season mean **0.000599** vs annual mean **0.000154** → **3.90×**

Assertions enforced by the script: `0 <= act_harmonized <= 1`; `n_valid_sensors` in 0–3;
`act_harmonized` is `NaN` exactly where `source == "none"`; a month VIIRS saw is never filled
from MODIS; `n_blended >= 1` exactly where a value exists; `sensor_min <= sensor_max`. All passed.

## 6. Notes and limitations

- **Ratios are per state and calendar month, not per district.** A per-district ratio would
  fit noise. Months with few burning district-months fall back to the state ratio.
- **The fill is a measurement, not an imputation.** A `modis_fill` value is another
  satellite's observation of the same district and month, put on the VIIRS scale.
- **Drift dates** are NASA's: Terra below 10:15 MLT from October 2022, Aqua above 13:45 MLT
  from February 2023.
- **Not corrected here:** NOAA-20/21, VIIRS 375 m detail (the 1 km VNP14A1 grid is used so
  that all sensors share one grid), boundary vintage, and the UTC/IST month edge. See
  `docs/decisions.md`.
- `data/district_monthly.csv` is untouched; this script only writes
  `data/district_harmonized.csv` and this file.
