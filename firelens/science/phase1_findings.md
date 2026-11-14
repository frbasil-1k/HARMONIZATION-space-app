# FireLens — Phase 1 Findings

**Status:** TEMPLATE — fill in at 19:45, read at the 20:00 gate
**Owner:** R2 (Science Lead) · **Data:** `data/district_monthly.csv` · **Run:**

```bash
python science/run_qc.py --input data/district_monthly.csv
```

| Field | Value |
|---|---|
| Filled at (IST) | `__:__` |
| File commit / hash | `________` |
| Rows / districts / sensors | `____` / `__` / 3 |
| Period covered (per sensor, latest active month) | terra `____-__` · aqua `____-__` · viirs_snpp `____-__` |
| Checks passed | `__ / 8` |
| Gaps exported | `____` rows (`__%` of file) → `science/gaps.csv` |

---

## 1. Headline paragraph (paste-ready for the team chat and R4's project page)

> FireLens covers **`__` districts** across **`__` states** of Northern India for
> **Jan 2016 – `____` 20`__`**, using Terra MODIS, Aqua MODIS and Suomi-NPP VIIRS. After
> `__ / 8` quality checks, the data shows the expected double cropping calendar: Ludhiana's
> VIIRS activity peaks in **`____`** (Oct–Nov mean `____` vs. annual `____`), consistent with
> paddy-residue burning, with a secondary **Apr–May** peak (`____`) from wheat residue.
> VIIRS and Aqua agree across all `____` shared district-months (`r = ____`, `p = ____`), with
> VIIRS reading a median `____×` higher — the first quantitative case for harmonization.
> `____` shows a **spring Apr–May** forest-fire season (activity `____` vs. `____` annual).
> `____` of `____` rows (`__%`) are gaps, concentrated in `____`, and are shown as blank/hatched
> cells rather than zeros. **Caveat:** activity is a share of clearly-seen land pixels, not a
> count of fires; GAUL boundaries are not official; months after the last available image are
> no-data, not no-fire.

---

## 2. Check results (from `run_qc.py`)

| # | Check | Result | Evidence (fill from the run) |
|---|---|---|---|
| V1 | Row count = districts × 3 × 132, no duplicate keys | `PASS/FAIL` | `____` rows vs `____` expected |
| V2 | Exactly 3 sensors; every district has all 3 | `PASS/FAIL` | `____` districts without all sensors |
| V3 | No nulls in required columns; values in domain | `PASS/FAIL` | `____` nulls, `____` bad dates |
| V4 | `fire_pixel_days <= clear_pixel_days` | `PASS/FAIL` | `____` violations |
| V5 | Jul–Sep clear view lower than other months | `PASS/FAIL` | monsoon `____` vs other `____`; `__/__` districts conform |
| V6 | `mean_frp_mw >= 0`, null iff `fire_pixel_days == 0` | `PASS/FAIL` | `____` non-null with no fire, `____` null with fire |
| V7 | Ludhiana VIIRS peaks in Oct–Nov | `PASS/FAIL` | peak month `__`, Oct–Nov `____` vs annual `____` |
| V8 | Latest active month per sensor noted | INFO | terra `____` · aqua `____` · viirs `____` |

Any FAIL: owner `____`, fix by `__:__`, re-run at `__:__`.

---

## 3. Key numbers

| Quantity | Value | Where it came from |
|---|---|---|
| Districts × states | `__` × `__` | `df[['state','district']].drop_duplicates()` |
| Rows in file | `____` | `len(df)` |
| Ludhiana Oct–Nov mean activity (VIIRS) | `____` | `plot1_ludhiana_seasonality.png` |
| Ludhiana Apr–May mean activity (VIIRS) | `____` | same |
| Oct–Nov / annual ratio (Ludhiana, VIIRS) | `____×` | profile mean |
| VIIRS vs Aqua Pearson `r` (`p`) | `____` (`____`) | `plot2_sensor_agreement.png` |
| Overlapping district-months in plot 2 | `____` | same |
| Median VIIRS / Aqua activity ratio | `____×` | same |
| Uttarakhand district used for plot 3 | `____` | `plot3_uttarakhand_forest.png` |
| Spring Apr–May vs annual activity, that district | `____` vs `____` | same |
| Gap rows / share of file | `____` / `__%` | `science/gaps.csv` |
| Districts with ≥ 6 fully missing months | `____` | gaps grouped by district and year |
| Share of rows with `n_images == 0` | `__%` | `df.n_images.eq(0).mean()` |
| Median clear-view coverage across rows | `__%` | `clear_coverage` median |

---

## 4. What looks right

- [ ] Row count and grid are exactly as contracted; no duplicate district-month-sensor keys.
- [ ] Monsoon suppression of clear view is visible (Jul–Sep mean clear pixels << other months).
- [ ] Ludhiana shows the Oct–Nov paddy band and the smaller Apr–May wheat band in every year,
      not just on average.
- [ ] VIIRS and Aqua rise and fall together; the fitted slope is positive and the correlation
      is high, with VIIRS biased high as expected from its finer resolution and overpass.
- [ ] At least one Uttarakhand district shows a spring (Apr–May) forest-fire season distinct
      from the Punjab crop calendar.
- [ ] `mean_frp_mw` behaves: nulls only where there is no fire, and values are plausible
      (single-digit to low-tens of MW).
- [ ] No activity value outside `[0, 1]`.

Notes: `______________________________________________________________`

---

## 5. What looks odd (and what we checked)

| Observation | First suspicion | What we checked | Verdict |
|---|---|---|---|
| `________________` | `____________` | `____________` | `____________` |
| `________________` | `____________` | `____________` | `____________` |
| `________________` | `____________` | `____________` | `____________` |

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

- [ ] `docs/decisions.md` complete and read by all four
- [ ] All eight checks pass on the full CSV (or each failure has an owner and a fix time)
- [ ] `plot1_ludhiana_seasonality.png` saved to `science/figures/` and posted
- [ ] `plot2_sensor_agreement.png` saved to `science/figures/` and posted
- [ ] `plot3_uttarakhand_forest.png` saved to `science/figures/` and posted
- [ ] `science/gaps.csv` committed and handed to R3 for hatching
- [ ] This file's headline paragraph filled in and posted

**Sign-off:** R2 `__________` at `__:__` IST
