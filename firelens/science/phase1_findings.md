# FireLens — Phase 1 Findings

**Status:** COMPLETE — verified at 17:23 IST, ready for the 20:00 gate
**Owner:** R2 (Science Lead) · **Data:** `data/district_monthly.csv` · **Run:**

```bash
python science/run_qc.py --input data/district_monthly.csv
```

| Field | Value |
|---|---|
| Filled at (IST) | `17:23` |
| File commit / hash | `153c70b` |
| Rows / districts / sensors | `19,404` / `49` / 3 |
| Period covered (per sensor, latest active month) | terra `2026-11` · aqua `2026-11` · viirs_snpp `2026-11` |
| Checks passed | `8 / 8` |
| Gaps exported | `196` rows (`1.0%` of file) → `science/gaps.csv` |

---

## 1. Headline paragraph (paste-ready for the team chat and R4's project page)

> FireLens covers **`49` districts** across **`3` states** of Northern India for
> **Jan 2016 – `Nov` 20`26`**, using Terra MODIS, Aqua MODIS and Suomi-NPP VIIRS. After
> `8 / 8` quality checks, the data shows the expected double cropping calendar: Ludhiana's
> VIIRS activity peaks in **`November`** (Oct–Nov mean `0.0034` vs. annual `0.0008`), consistent with
> paddy-residue burning, with a secondary **Apr–May** peak (`0.0012`) from wheat residue.
> VIIRS and Aqua agree across all `6,419` shared district-months (`r = 0.913`, `p < 1e-16`), with
> VIIRS reading a ratio of `0.83×` (OLS slope `0.73`) — the first quantitative case for harmonization.
> `Naini Tal` shows a **spring Apr–May** forest-fire season (activity `0.0006` vs. `0.0001` annual).
> `196` of `19,404` rows (`1.0%`) are gaps, — 147 `no_images` rows in `2026-12` plus 49 `low_clear_coverage` rows in partial `2026-11` VIIRS (only 2 images so far), and are shown as blank/hatched
> cells rather than zeros. **Caveat:** activity is a share of clearly-seen land pixels, not a
> count of fires; GAUL boundaries are not official; months after the last available image are
> no-data, not no-fire.

---

## 2. Check results (from `run_qc.py`)

| # | Check | Result | Evidence (fill from the run) |
|---|---|---|---|
| V1 | Row count = districts × 3 × 132, no duplicate keys | `PASS` | `19,404` rows vs `19,404` expected |
| V2 | Exactly 3 sensors; every district has all 3 | `PASS` | `0/49` districts without all sensors |
| V3 | No nulls in required columns; values in domain | `PASS` | `0` nulls, `0` bad dates |
| V4 | `fire_pixel_days <= clear_pixel_days` | `PASS` | `0` violations |
| V5 | Jul–Sep clear view lower than other months | `PASS` | monsoon `85,510` vs other `91,121`; `45/49` districts conform |
| V6 | `mean_frp_mw >= 0`, null iff `fire_pixel_days == 0` | `PASS` | `0` non-null with no fire, `0` null with fire |
| V7 | Ludhiana VIIRS peaks in Oct–Nov | `PASS` | peak month `11`, Oct–Nov `0.0034` vs annual `0.0008` |
| V8 | Latest active month per sensor noted | INFO | terra `2026-11` · aqua `2026-11` · viirs `2026-11` |

Any FAIL: none (8/8 PASS after R1 patched 4 missing Terra yearly exports).

---

## 3. Key numbers

| Quantity | Value | Where it came from |
|---|---|---|
| Districts × states | 49 × 3 | df[['state','district']].drop_duplicates() |
| Rows in file | 19,404 | len(df) |
| Ludhiana Oct–Nov mean activity (VIIRS) | 0.0034 | plot1_ludhiana_seasonality.png |
| Ludhiana Apr–May mean activity (VIIRS) | 0.0012 | same |
| Oct–Nov / annual ratio (Ludhiana, VIIRS) | 4.23× | profile mean (0.0034 / 0.0008) |
| VIIRS vs Aqua Pearson r (p) | 0.913 (< 1e-16) | plot2_sensor_agreement.png |
| Overlapping district-months in plot 2 | 6,419 | same |
| Median VIIRS / Aqua ratio (OLS slope) | 0.83× (0.73) | plot2_sensor_agreement.png |
| Uttarakhand district used for plot 3 | Naini Tal | plot3_uttarakhand_forest.png |
| Spring Apr–May vs annual activity, that district | 0.0006 vs 0.0001 | same |
| Gap rows / share of file | 196 / 1.0% | science/gaps.csv (147 no-image, 49 low-coverage) |
| Districts with ≥ 6 fully missing months | 0 | gaps grouped by district and year |
| Share of rows with n_images == 0 | 0.76% | df.n_images.eq(0).mean() |
| Median clear-view coverage across rows | 93.3% | clear_coverage median |

---

## 4. What looks right

- [x] Row count and grid are exactly as contracted; no duplicate district-month-sensor keys.
- [x] Jul–Sep clear view is lower than other months, but only by ~6% (45/49 districts);
      weaker than expected, see section 5.
- [x] Ludhiana shows the Oct–Nov paddy band and the smaller Apr–May wheat band in every year,
      not just on average.
- [x] VIIRS and Aqua rise and fall together (r = 0.913), but VIIRS reads lower than Aqua
      (median 0.83×, slope 0.73), not higher as expected; see section 5.
- [x] At least one Uttarakhand district shows a spring (Apr–May) forest-fire season distinct
      from the Punjab crop calendar.
- [x] `mean_frp_mw` behaves: nulls only where there is no fire, and values are plausible
      (single-digit to low-tens of MW).
- [x] No activity value outside `[0, 1]`.

Notes: the two unexpected results (weak monsoon drop, VIIRS lower than Aqua) are in section 5.

---

## 5. What looks odd (and what we checked)

| Observation | First suspicion | What we checked | Verdict |
|---|---|---|---|
| Initial CSV had 17,052 rows (2,352 short of 19,404) | Districts missing from export | Checked sensor-year counts; traced to 4 missing Terra yearly exports (4 × 49 × 12 = 2,352) | Fixed by R1 (153c70b); re-run passed 8/8 |
| Monsoon clear-pixel reduction is weak (~6% lower; 4/49 districts higher in Jul–Sep) | Cloud mask missing monsoon cloud or winter snow suppressing non-monsoon view | Checked V5 across districts (consistent with R1 PR #5); 45/49 districts conform | Accepted for Phase 1; audit daily cloud mask in Phase 2 |
| VIIRS reads lower than Aqua (0.83× median ratio, slope 0.73) | Expected VIIRS normalized activity to exceed Aqua | Partly explained by clear_pixel_days denominator: VIIRS sees ~6% more clear pixels per image than Aqua (~3,088 vs 2,922) | Empirical baseline for Phase 2 seasonal calibration |

Known, accepted artefacts (not bugs):

- **Sensor switch steps.** Raw counts step at sensor boundaries; normalised activity reduces
  but does not remove them. Harmonization is Phase 2.
- **UTC months vs. IST narrative.** Up to ~5.5 h of each IST month lands in the next UTC month.
  Immaterial at monthly resolution; documented in `docs/decisions.md`.
- **GAUL boundary vintage.** District set and names are outdated and not the official boundary
  of India; the disclaimer is mandatory wherever the map appears.
- **Latest months.** Short/absent records after the last available image are `n_images = 0`
  rows, shown as no-data.

---

## 6. What Phase 2 must handle

1. **Harmonization.** Fit per-sensor, per-season calibration to the VIIRS anchor; quantify the
   residual after scaling and report it (do not hide the step in a single global factor).
2. **Coverage-aware aggregation.** Weight or mask district-months with `clear_coverage` below
   `0.10`; decide whether annual means exclude sub-threshold months entirely.
3. **Sensor-boundary diagnostics.** Test for a structural break at 2016–2026 MODIS/VIIRS
   overlap and at any product reprocessing change.
4. **Gap structure.** `science/gaps.csv` is the work list: which districts are chronically
   under-observed (cloud, terrain, orbit edge), and whether a re-export or a coarser grid fixes it.
5. **Boundary upgrade.** Replace GAUL with an official district layer if one is available, and
   re-verify the name join in both files.
6. **Attribution limits.** Activity is burning *detected*, not area burned and not fire count;
   any crop-residue or health claim needs the human-activity context panel and explicit caveats.

---

## 7. Gate checklist (R2 items, 20:00)

- [x] `docs/decisions.md` complete and read by all four
- [x] All eight checks pass on the full CSV (or each failure has an owner and a fix time)
- [x] `plot1_ludhiana_seasonality.png` saved to `science/figures/` and posted
- [x] `plot2_sensor_agreement.png` saved to `science/figures/` and posted
- [x] `plot3_uttarakhand_forest.png` saved to `science/figures/` and posted
- [x] `science/gaps.csv` committed and handed to R3 for hatching
- [x] This file's headline paragraph filled in and posted

**Sign-off:** R2 `__________` at `__:__` IST
