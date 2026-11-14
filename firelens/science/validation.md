# FireLens Phase 2 — Harmonization Validation

**Owner:** R2 (Science Lead) · **Generated:** 2026-11-14 by `science/harmonize.py`
**Input:** `data/district_monthly.csv` (19,404 rows, 49 districts, period 2016-01 to 2026-12)
**Output:** `data/district_harmonized.csv` (6,468 district-months)

Purpose: remove the sensor step from the record. VIIRS is the anchor (continuous
2016–2026 record); each MODIS sensor is scaled to it using only the years all three
sensors overlap (2016–2022), then checked on three years it never saw (2023–2025).

Method in one paragraph: activity is `fire_pixel_days / clear_pixel_days` per district,
month and sensor; rows with `clear_coverage < 0.10` or `n_images == 0` are
low-coverage and stay `NaN` (no imputation anywhere). For each state and MODIS sensor we
take the median of `viirs_activity / modis_activity` over shared district-months where
both are positive, which is the multiplicative factor that maps MODIS onto the VIIRS
scale. That factor is applied to every MODIS month, clipped to `[0, 1]`, and the three
sensor series are averaged (`skipna=True`) into `act_harmonized`. Weather, cloud and
district area largely cancel in the ratio, so the factor is a sensor calibration, not a
correction for burning.

---

## 1. Calibration ratios (2016–2022)

Median of `viirs_snpp / modis` over shared district-months where both activities > 0.
`p10`/`p90` show the spread of the individual pairs; `CV` is the coefficient of variation
of the year-by-year median ratio, i.e. the stability check.

| State | MODIS sensor | Shared months | Ratio | p10 | p50 | p90 | CV | Method |
|---|---|---|---|---|---|---|---|---|
| Haryana | terra | 594 | 1.484 | 0.36 | 1.484 | 7.11 | 0.190 | state median |
| Haryana | aqua | 664 | 0.966 | 0.33 | 0.966 | 3.09 | 0.220 | state median |
| Punjab | terra | 744 | 2.393 | 0.49 | 2.393 | 16.69 | 0.163 | state median |
| Punjab | aqua | 834 | 0.906 | 0.38 | 0.906 | 2.84 | 0.107 | state median |
| Uttarakhand | terra | 437 | 1.845 | 0.54 | 1.845 | 6.75 | 0.191 | state median |
| Uttarakhand | aqua | 508 | 0.971 | 0.37 | 0.971 | 2.90 | 0.049 | state median |

**USE_FALLBACK = False** (limit `CV > 0.50`). Every state-sensor ratio is stable enough to use directly, so no fallback was needed. The fallback, when triggered, is the median of all shared pairs for that sensor across
states (the 50th percentile); `p10`/`p90` are kept in the table so the spread remains
visible.

Reading the table: a ratio above 1 means VIIRS reads more burning than that MODIS sensor
in that state, so MODIS must be scaled **up** to match. Aqua sits close to VIIRS; Terra
reads substantially lower, which is consistent with its earlier overpass and coarser
detection of small residue fires.

## 2. Stability by year

Per-year median ratio, same filters as above. A flat row means the calibration is not
tracking anything that changes year to year.

| State | Sensor | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | CV |
|---|---|---|---|---|---|---|---|---|---|
| Haryana | aqua | 0.91 | 0.99 | 1.31 | 0.98 | 0.75 | 0.96 | 0.66 | 0.220 |
| Haryana | terra | 1.09 | 1.27 | 1.67 | 1.76 | 1.13 | 1.61 | 1.54 | 0.190 |
| Punjab | aqua | 0.84 | 1.02 | 0.93 | 0.99 | 0.74 | 0.86 | 0.89 | 0.107 |
| Punjab | terra | 1.73 | 2.51 | 2.06 | 1.98 | 2.69 | 2.48 | 2.67 | 0.163 |
| Uttarakhand | aqua | 0.96 | 0.91 | 0.99 | 1.04 | 0.91 | 0.94 | 0.96 | 0.049 |
| Uttarakhand | terra | 1.34 | 1.97 | 1.98 | 1.38 | 2.19 | 2.15 | 1.75 | 0.191 |

## 3. Slide 4 — validation on the 2023–2025 holdout

Unseen years: the ratio learned on 2016–2022 is applied without refitting.
`scaled_modis = clip(modis * ratio, 0, 1)`; residual = `scaled_modis - viirs_snpp`
(positive means the scaled MODIS series still sits above VIIRS).

| Series | n | Pearson r | p-value | Median signed error | Median abs error | Mean signed error | Residual = 0 | OLS slope |
|---|---|---|---|---|---|---|---|---|
| pooled (terra + aqua) | 3528 | 0.703 | < 1e-300 | +0.00e+00 | 1.79e-05 | -1.47e-05 | 30% | 0.76 |
| terra | 1764 | 0.570 | 2.66e-152 | +0.00e+00 | 2.10e-05 | -6.90e-05 | 31% | 0.38 |
| aqua | 1764 | 0.831 | < 1e-300 | +0.00e+00 | 1.57e-05 | +3.96e-05 | 29% | 1.15 |

Why the median error can read exactly zero: about **30%** of the valid holdout district-months have no detections in either sensor, so their residual is exactly 0
and dominates the median. That is a real property of the data, not perfect agreement —
read the mean signed error, the zero share and the slope together with the median.

Pooled slope is **0.76** (Terra 0.38, Aqua 1.15): scaled MODIS does not reproduce VIIRS's full month-to-month swing. Terra at the low end is the weak link; Aqua tracks VIIRS closely. For scale, the pooled median absolute error is 1.79e-05, about **5%** of the mean harmonized activity (3.59e-04).

Interpretation for the slide:

- **Pooled** is the headline number: one calibration per sensor and state, applied blind
  to 2023–2025.
- **Terra / Aqua separately** show the calibration is not hiding one good sensor behind a
  bad one. Terra's larger ratio is the harder extrapolation; Aqua's near-1 ratio barely
  moves.
- A high `r` alone is not enough: a series that is 3× too high would also correlate
  strongly. The slope and the error columns are what show the scaled series is *on* the
  VIIRS scale rather than merely moving with it.

### Residual by year

Kruskal–Wallis finds no overall year difference (p=2.16e-01), but the linear trend on year is significant (+4.76e-05 per year, p=2.50e-04). With only three holdout years that is driven by 2023 (mean -7.68e-05) sitting below 2025 (mean +1.85e-05): read it as a possible step after 2023, not a smooth drift, and re-check when 2026 data lands.

| Series | Year | n | Median residual | Mean residual | Residual = 0 |
|---|---|---|---|---|---|
| pooled (terra + aqua) | 2023 | 1176 | +0.00e+00 | -7.68e-05 | 29% |
| pooled (terra + aqua) | 2024 | 1176 | +0.00e+00 | +1.42e-05 | 28% |
| pooled (terra + aqua) | 2025 | 1176 | +0.00e+00 | +1.85e-05 | 32% |
| terra | 2023 | 588 | +0.00e+00 | -1.72e-04 | 30% |
| terra | 2024 | 588 | +0.00e+00 | -3.05e-05 | 30% |
| terra | 2025 | 588 | +0.00e+00 | -4.56e-06 | 34% |
| aqua | 2023 | 588 | +0.00e+00 | +1.85e-05 | 28% |
| aqua | 2024 | 588 | +0.00e+00 | +5.89e-05 | 27% |
| aqua | 2025 | 588 | +0.00e+00 | +4.15e-05 | 31% |

## 4. Harmonized product checks

| Check | Value |
|---|---|
| District-months written | 6,468 (49 districts × 132 months) |
| Rows with a usable `act_harmonized` | 6,419 |
| Rows left `NaN` | 49 |
| `act_harmonized` range | [0.000000, 0.020785] |
| Mean `act_harmonized` | 0.000359 |
| Rows with 3 / 2 / 1 / 0 valid sensors | 98.5% / 0.8% / 0.0% / 0.8% |
| Low-coverage rows in output | 49 |

Peak preservation (the reason harmonization must not smooth away the signal):

- Ludhiana (Punjab), Oct–Nov paddy peak: season mean **0.002846** vs annual mean **0.000679** → **4.19×**
- Naini Tal (Uttarakhand), Apr–May forest-fire peak: season mean **0.000679** vs annual mean **0.000169** → **4.02×**

Assertions enforced by the script: `0 <= act_harmonized <= 1` for every non-null row, and
`n_valid_sensors` within 0–3. Both passed.

## 5. Notes and limitations

- **Coverage baseline.** Phase 2 computes the baseline per (state, district, **sensor**),
  the maximum monthly `clear_pixel_days / days_in_month` for that sensor. This refines the
  Phase 1 district-level proxy in `docs/data-contract.md`: it stops a sensor with
  systematically fewer clear views (e.g. a different overpass in the monsoon) from
  depressing another sensor's coverage estimate. It is a QC denominator only; it never
  enters `activity`.
- **Ratios are per state and sensor, not per district.** A per-district ratio would fit
  noise, especially where a district has few burning months. The spread (p10–p90) is wide
  because activity ratios are noisy at low values; the median is the robust summary.
- **Ratio > 1 is expected and is not a bug.** VIIRS detects more small fires; the
  calibration makes MODIS speak VIIRS's language, not the reverse.
- **Zeros are real.** Rows with activity exactly 0 are retained in the mean; only
  low-coverage rows are excluded. Excluding zeros would inflate the harmonized activity.
- **Not corrected here:** NOAA-20/21, boundary vintage, and the UTC/IST month edge. See
  `docs/decisions.md`.
- `data/district_monthly.csv` is untouched; this script only writes
  `data/district_harmonized.csv` and this file.
