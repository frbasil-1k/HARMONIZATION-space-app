# FireLens — Storyboard & Slide Skeleton
> **Status:** DRAFT · R4 owner: Mohammed Zaidan Contractor · Last updated: 2026-11-14
> ⚠️ Verify Oct–Nov peak district against R2's (Mohammed Basil's) real Ludhiana plot before finalising.

---

## 30-Second Demo Storyboard

| Seconds | Screen | Subtitle (spoken / on screen) |
|---------|--------|-------------------------------|
| 0–5 | R1’s figure: Three satellites disagreeing about the same fires over Northern India (Terra MODIS, Aqua MODIS, Suomi-NPP VIIRS displaying conflicting counts for the same period) | *"Three satellites, three different stories about the same fires. Which one is true?"* |
| 5–15 | App: User selects **Punjab → Ludhiana** → the calendar heatmap appears, harmonizing the sensors into one continuous, consistent burning record | *"FireLens harmonizes MODIS and VIIRS into one consistent burning calendar."* |
| 15–25 | Metric cards zoom in (this month vs median ratio, percentile rank, top-3 peak months), followed by R2's sensor-agreement validation scatter plot | *"See if this month is unusual — backed by a decade of validated data."* |
| 25–30 | CSV download button clicked; footer displays COSMICBRO's team and NASA LP DAAC data credits | *"Built with NASA open fire data for Northern India."* |

### Notes for recording
- Record at **1080p**, keep cursor movements slow and deliberate.
- Use **English subtitles** (burned into video or supplied via .srt).
- Total runtime must strictly be ≤ 30 seconds.
- **Visual opening:** Start immediately on R1's multi-sensor divergence chart with the bold visual question *"Which one is true?"*, transitioning directly into the FireLens interface showing the unified answer.

---

## Slide Skeleton (7 slides max)

### Slide 1 — Title, Team & Challenge
- **Title:** FireLens
- **Subtitle:** A harmonized burning-activity calendar for Northern India, 2016–2026
- **Challenge:** Harmonization of MODIS and VIIRS Hot Spots · NASA Space Apps 2026
- **Team:** COSMICBRO's — Lincoln Serrao · Shaikh Mohammed Basil · Mohammed Mubeen Kamalsha · Mohammed Zaidan Contractor
- _Visual: clean title card, map of Northern India in background_

---

### Slide 2 — The Problem: Three Satellites Disagreeing
- **Continuous overlap, contradictory signals:** Between 2016 and 2026, Terra MODIS, Aqua MODIS, and Suomi-NPP VIIRS observed Northern India simultaneously, yet report vastly different fire counts for the exact same districts and months.
- **Why they disagree:**
  - Different overpass times (Terra ~10:30 AM morning vs. Aqua ~1:30 PM afternoon vs. VIIRS afternoon).
  - Spatial resolution mismatch: VIIRS (375 m) detects smaller, cooler agricultural fires that 1 km MODIS pixels miss entirely.
  - Monsoon cloud masking creates severe, unequal blind spots (July–September).
- **The Core Question:** *"Which one is true?"* Raw counts mislead farmers, environmental monitors, and state policy.
- _Visual: R1's multi-sensor time-series figure showing Terra vs Aqua vs VIIRS raw counts diverging over the same Punjab/Haryana districts, captioned "Which satellite do you trust?"_

---

### Slide 3 — Our Approach: The Harmonization Pipeline
- **Unified NASA Earth Engine Ingestion:** Daily MODIS (MOD14A1, MYD14A1) and VIIRS (VNP14A1) data processed across `[R2: __]` Northern India districts (Punjab, Haryana, Uttarakhand) from 2016–2026.
- **The Normalization Equation (Plain Words):**
  $$\text{Burning Activity} = \frac{\text{fire\_pixel\_days}}{\text{clear\_pixel\_days}}$$
  - Counts fire pixels ($\text{FireMask} \ge 8$) divided strictly by cloud-free, clearly seen land pixels ($\text{FireMask} = 5 \text{ or } \ge 7$).
  - Eliminates cloud obscuration bias that falsely makes monsoon months look clean.
- **Harmonization & Calibration:**
  - **Anchor sensor:** Suomi-NPP VIIRS (highest spatial resolution and modern radiometry).
  - Cross-calibrating MODIS series to the VIIRS anchor over their extensive overlapping period.
- **Production Dataset:** Clean `district_monthly.csv` powering an interactive Streamlit intelligence app.
- _Visual: Pipeline flowchart: NASA Earth Engine (3 sensors) ➔ Pixel Cloud Normalization ➔ Anchor Harmonization (VIIRS) ➔ Live App & CSV API_

```
NASA Earth Engine (Daily 2016–2026)
  • Terra MODIS (MOD14A1)  ─┐
  • Aqua MODIS (MYD14A1)   ─┼─► Normalization: fire_pixel_days / clear_pixel_days ─► Harmonize to VIIRS ─► Live App
  • VIIRS S-NPP (VNP14A1)  ─┘                                                        (Anchor Sensor)
```

---

### Slide 4 — Harmonization & Scientific Validation
- **Cross-Sensor Agreement:**
  - VIIRS vs Aqua activity exhibits strong linear correlation: $r = \mathbf{[R2:\ \_\_]}$ ($p = \mathbf{[R2:\ \_\_]}$) across all $\mathbf{[R2:\ \_\_]}$ overlapping district-months.
  - Quantitative scaling confirms VIIRS reads $\mathbf{[R2:\ \_\_\times]}$ higher due to 375 m pixel sensitivity, validating the need for scaling.
- **Double-Cropping Stubble Seasonality Validated:**
  - **Ludhiana (Punjab):** Accurately captures the intense post-monsoon **October–November** paddy stubble burn:
    - Oct–Nov mean activity = $\mathbf{[R2:\ \_\_]}$ vs. annual baseline = $\mathbf{[R2:\ \_\_]}$.
  - Captures the secondary **April–May** wheat-residue clearing ($\mathbf{[R2:\ \_\_]}$).
- **Forest Fire Ecosystem Sanity Check:**
  - **Uttarakhand ($\mathbf{[R2:\ District\ Name]}$):** Accurately distinguishes agricultural burning from Himalayan forest fires, isolating the natural **March–May** spring fire season (activity $\mathbf{[R2:\ \_\_]}$ vs annual $\mathbf{[R2:\ \_\_]}$).
- **Gaps Honesty:**
  - $\mathbf{[R2:\ \_\_]}$ gap rows ($\mathbf{[R2:\ \_\_\%]}$) with missing images or heavy cloud obstruction are transparently hatched/blanked, never disguised as "zero fires".
- _Visual: Trio of validation charts — R2's Plot 1 (Ludhiana Seasonality), Plot 2 (VIIRS vs Aqua Correlation Scatter), and Plot 3 (Uttarakhand Forest Fire Season)_

---

### Slide 5 — The App
- Pick state → district → sensor → see a month × year heatmap.
- Metric cards: current month vs long-term median.
- Blank cells = no data (not zero) — honesty built in.
- CSV download for researchers.
- _Visual: 2–3 screenshots of the live Streamlit app — Ludhiana heatmap, metric cards, map_

---

### Slide 6 — Insights & Use Cases
- **Farmers & extension workers:** Is this harvest season unusually smoky?
- **Air-quality researchers:** A clean, long fire-activity time series to correlate with PM2.5.
- **Policymakers:** Which districts burn most, and is it improving?
- Key insight: _[fill in after R2's real data — e.g. "Ludhiana's Oct–Nov activity has declined X% since 2020" or similar]_
- _Visual: heatmap of a high-burning district highlighting the trend_

---

### Slide 7 — Limitations, Next Steps & Credits
**Limitations**
- Pixel aggregates, not individual fire counts
- GAUL boundaries (not official India boundaries)
- Data ends at latest processed satellite image

**Next steps**
- NOAA-20/21 VIIRS · Official boundaries · Record back to 2003 · Human-activity context panel

**Data credits**
- MOD14A1 v6.1, MYD14A1 v6.1, VNP14A1 v2 — NASA LP DAAC via Google Earth Engine
- GAUL Level 2 — FAO via Google Earth Engine

---

## Screenshots needed (Sunday)
- [ ] App home / district picker (sidebar visible)
- [ ] Ludhiana heatmap with Oct–Nov band visible
- [ ] Metric cards close-up
- [ ] Sensor-agreement chart (from R2's notebook)
- [ ] CSV download in action
- [ ] Map tab with district boundary

---

> **TODO before recording:**
> - [ ] Confirm video ≤ 30 s and subtitle format from submission rules (R4)
> - [ ] Confirm which district shows clearest Oct–Nov peak (R2 — Mohammed Basil)
> - [ ] Get live app URL from R3 (Mohammed Mubeen) for recording
> - [ ] Fill in sensor-agreement correlation value from R2's Plot 2
> - [ ] Fill in Slide 6 insight once real data is available

