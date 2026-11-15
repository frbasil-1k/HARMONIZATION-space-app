# FireLens — Storyboard & Slide Skeleton
> **Status:** DRAFT · R4 owner: Mohammed Zaidan Contractor · Last updated: 2026-11-15
> Numbers below are from the real data (`science/phase1_findings.md`, `science/validation.md`).

---

## 30-Second Demo Storyboard

| Seconds | Screen | Subtitle (spoken / on screen) |
|---------|--------|-------------------------------|
| 0–5 | R1’s figure (`data/figures/ludhiana_sensors.png`): Three satellites disagreeing about the same fires over Northern India (Terra MODIS, Aqua MODIS, Suomi-NPP VIIRS displaying conflicting counts for the same period) | *"Three satellites, three different stories about the same fires. Which one is true?"* |
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
  - Different sensitivity: VIIRS and MODIS detect fires differently, so the same burning gives different counts (we compare them on one 1 km grid).
  - Monsoon cloud masking creates severe, unequal blind spots (July–September).
- **The Core Question:** *"Which one is true?"* Raw counts mislead farmers, environmental monitors, and state policy.
- _Visual: R1's multi-sensor time-series figure showing Terra vs Aqua vs VIIRS raw counts diverging over the same Punjab/Haryana districts, captioned "Which satellite do you trust?"_

---

### Slide 3 — Our Approach: The Harmonization Pipeline
- **Unified NASA Earth Engine Ingestion:** Daily MODIS (MOD14A1, MYD14A1) and VIIRS (VNP14A1) data processed across 49 Northern India districts (Punjab, Haryana, Uttarakhand) from 2016–2026.
- **The Normalization Equation (Plain Words):**
  $$\text{Burning Activity} = \frac{\text{fire\_pixel\_days}}{\text{clear\_pixel\_days}}$$
  - Counts fire pixels ($\text{FireMask} \ge 8$) divided strictly by cloud-free, clearly seen land pixels ($\text{FireMask} = 5 \text{ or } \ge 7$).
  - Eliminates cloud obscuration bias that falsely makes monsoon months look clean.
- **Harmonization & Calibration:**
  - **Anchor sensor:** Suomi-NPP VIIRS: unbroken record over 2016–2026, and the sensor that continues the record.
  - One VIIRS ÷ MODIS ratio per state and sensor, fitted on 2016–2022, then tested blind on 2023–2025.
- **Production Dataset:** `district_monthly.csv` (19,404 rows) and `district_harmonized.csv` powering an interactive Streamlit intelligence app.
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
  - VIIRS vs Aqua activity: **r = 0.913** (p < 1e-16) across 6,419 shared district-months.
  - Leave-one-year-out test (2016–2022) of the scaled MODIS against VIIRS: **r = 0.98 (Aqua), 0.91 (Terra)**, peak-season totals within 4%; MODIS-only reconstruction **r = 0.97, bias 2%**.
  - After the orbit drift (2023–2025) Aqua reads 1.8× VIIRS in the peak, so drifted MODIS is not blended.
  - Fitted ratios: VIIRS ≈ Aqua (0.91–0.97×, both early-afternoon passes) but **1.5–2.4× Terra**, whose morning pass misses afternoon burning. Without scaling, Terra would make every district look half as active.
- **Double-Cropping Stubble Seasonality Validated:**
  - **Ludhiana (Punjab):** Accurately captures the intense post-monsoon **October–November** paddy stubble burn:
    - Oct–Nov harmonized activity = 0.37 % of clear land vs. 0.085 % annual (**4.3×**).
  - Captures the secondary **April–May** wheat-residue burning (0.10 %, 1.5× annual).
- **Forest Fire Ecosystem Sanity Check:**
  - **Uttarakhand (Naini Tal):** a different calendar: the spring **April–May** forest-fire season (0.060 % vs 0.015 % annual, **3.9×**), not the Oct–Nov crop peak.
- **Gaps Honesty:**
  - 196 gap rows (1.0 %: 147 with no images, 49 with under 10 % clear view) are left blank in the calendar and marked × in the anomaly view, never shown as zero.
- _Visual: Trio of validation charts — R2's Plot 1 (Ludhiana Seasonality), Plot 2 (VIIRS vs Aqua Correlation Scatter), and Plot 3 (Uttarakhand Forest Fire Season)_

---

### Slide 5 — The App
- Pick a district (or type a latitude/longitude) and any date range; harmonized series by default, or any single sensor.
- Month × year calendar (activity or hotspot count), yearly view, anomaly vs monthly median, sensor comparison before/after harmonization.
- Metric cards: latest complete month vs its historical median, percentile rank, peak months.
- Blank cells = no data (not zero).
- Draw any box or polygon: its own calendar, anomaly and trend, plus a CSV of the hotspots inside it.
- Research views: seasonal trend (Mann-Kendall + Sen's slope) per district and as a map; sensor-range uncertainty on every value; fire type (cropland / forest / woodland) and static heat sources for 19 districts.
- Downloads: harmonized CSV, per-sensor CSV, individual hotspots CSV, trend table, everything as one ZIP with data dictionary and citation; every chart as PNG.
- _Visual: 2–3 screenshots of the live Streamlit app — Ludhiana heatmap, metric cards, map_

---

### Slide 6 — Insights & Use Cases
- **Farmers & extension workers:** Is this harvest season unusually smoky?
- **Air-quality researchers:** A clean, long fire-activity time series to correlate with PM2.5.
- **Policymakers:** Which districts burn most, and is it improving?
- Key insight: Punjab's Oct–Nov hotspots fell **82 % (Aqua) to 97 % (VIIRS) between 2021 and 2025**. The two sensors disagree on how much, a hint that burning moved later in the day, away from the satellites' overpasses: exactly why one harmonized, validated record matters.
- _Visual: heatmap of a high-burning district highlighting the trend_

---

### Slide 7 — Limitations, Next Steps & Credits
**Limitations**
- Detections (pixel-days), not individual fires
- 2016–2026 (the three-sensor overlap), not yet the early 2000s
- 49 fixed districts; GAUL boundaries (not official India boundaries)
- VIIRS and Aqua diverge after 2023 in Punjab: Aqua's orbit drift to a later overpass, plus later burning; drifted MODIS is no longer blended
- Manual refresh: data ends at the latest processed image

**Next steps**
- Back to 2001/2003 with MODIS · NOAA-20/21 VIIRS · Harmonized values for drawn areas · Official boundaries · Live FIRMS layer

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
> - [x] Confirm which district shows clearest Oct–Nov peak: Ludhiana (4.2×)
> - [ ] Get live app URL from R3 (Mohammed Mubeen) for recording
> - [x] Fill in sensor-agreement correlation value from R2's Plot 2 (r = 0.913)
> - [x] Fill in Slide 6 insight once real data is available

